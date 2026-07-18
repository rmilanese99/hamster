#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("RAY_ENABLE_UV_RUN_RUNTIME_ENV", "0")
os.environ.setdefault("RAY_ACCEL_ENV_VAR_OVERRIDE_ON_ZERO", "0")

import ray
from cldk import CLDK
from cldk.analysis import AnalysisLevel
from cldk.analysis.java import JavaAnalysis
from cldk.models.java import JCompilationUnit


UI_TESTING_FRAMEWORK_IMPORT_PREFIXES: dict[str, tuple[str, ...]] = {
    "selenium": (
        "org.openqa.selenium.",
        "com.thoughtworks.selenium.",
    ),
    "selenide": ("com.codeborne.selenide.",),
    "playwright": ("com.microsoft.playwright.",),
    "appium": ("io.appium.java_client.",),
    "selendroid": ("io.selendroid.",),
    "espresso": (
        "androidx.test.espresso.",
        "android.support.test.espresso.",
    ),
    "ui-automator": (
        "androidx.test.uiautomator.",
        "android.support.test.uiautomator.",
        "com.android.uiautomator.",
    ),
    "android-compose-ui-test": ("androidx.compose.ui.test.",),
    "robotium": ("com.robotium.solo.",),
    "testfx": ("org.testfx.",),
}

UI_TESTING_FRAMEWORK_PREFIXES: tuple[str, ...] = tuple(
    prefix
    for prefixes in UI_TESTING_FRAMEWORK_IMPORT_PREFIXES.values()
    for prefix in prefixes
)


def has_ui_testing_import(compilation_unit: JCompilationUnit) -> bool:
    return any(
        import_name.startswith(UI_TESTING_FRAMEWORK_PREFIXES)
        for import_name in compilation_unit.imports
    )


def load_java_analysis(project_analysis_dir: Path) -> JavaAnalysis:
    return CLDK(language="java").analysis(
        project_path="",
        analysis_level=AnalysisLevel.symbol_table,
        analysis_json_path=str(project_analysis_dir),
        eager=False,
    )


def project_uses_ui_testing_framework(project_analysis_dir: Path) -> bool:
    analysis = load_java_analysis(project_analysis_dir)
    return any(
        has_ui_testing_import(compilation_unit)
        for compilation_unit in analysis.get_compilation_units()
    )


@ray.remote
def identify_ui_test_repo(project_analysis_dir_str: str) -> tuple[str | None, str | None]:
    project_analysis_dir = Path(project_analysis_dir_str)
    try:
        if project_uses_ui_testing_framework(project_analysis_dir):
            return project_analysis_dir.name, None
    except Exception as exc:
        analysis_file = project_analysis_dir / "analysis.json"
        return None, f"Skipping invalid analysis {analysis_file}: {exc}"
    return None, None


def extract_ui_test_repos(analysis_dir: Path) -> list[str]:
    project_dirs = sorted(
        p
        for p in analysis_dir.iterdir()
        if p.is_dir() and (p / "analysis.json").is_file()
    )
    if not project_dirs:
        return []

    ray_was_initialized = ray.is_initialized()
    if not ray_was_initialized:
        ray.init(
            ignore_reinit_error=True,
            include_dashboard=False,
            logging_level="warning",
            log_to_driver=False,
        )

    result_refs = [
        identify_ui_test_repo.remote(str(project_dir)) for project_dir in project_dirs
    ]
    try:
        results = ray.get(result_refs)
    finally:
        if not ray_was_initialized:
            ray.shutdown()

    ui_test_repos: list[str] = []
    for project_name, error_message in results:
        if error_message:
            print(error_message, file=sys.stderr)
        if project_name:
            ui_test_repos.append(project_name)

    return ui_test_repos


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract project names whose CLDK imports include Java UI testing frameworks."
    )
    parser.add_argument(
        "analysis_dir",
        type=Path,
        help="Directory containing one subdirectory per project, each with analysis.json.",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Directory where ui_test_repos.json will be written.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.analysis_dir.is_dir():
        raise SystemExit(
            f"analysis_dir does not exist or is not a directory: {args.analysis_dir}"
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    ui_test_repos = extract_ui_test_repos(args.analysis_dir)

    output_file = args.output_dir / "ui_test_repos.json"
    with output_file.open("w") as f:
        json.dump(ui_test_repos, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"Saved {len(ui_test_repos)} UI test repos to {output_file}")


if __name__ == "__main__":
    main()
