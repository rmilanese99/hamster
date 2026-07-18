#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hamster.code_analysis.model.models import ProjectAnalysis, TestType


def load_project(model_file: Path) -> ProjectAnalysis | None:
    try:
        with model_file.open("r") as f:
            return ProjectAnalysis.model_validate(json.load(f))
    except Exception as exc:
        print(f"Skipping invalid model {model_file}: {exc}", file=sys.stderr)
        return None


def extract_ui_tests(models_dir: Path) -> dict[str, dict[str, list[str]]]:
    ui_tests_by_project: dict[str, dict[str, list[str]]] = {}

    for project_dir in sorted(p for p in models_dir.iterdir() if p.is_dir()):
        model_file = project_dir / "hamster.json"
        if not model_file.is_file():
            continue

        project_analysis = load_project(model_file)
        if project_analysis is None:
            continue

        ui_tests_by_class: dict[str, list[str]] = {}
        for test_class in project_analysis.test_class_analyses:
            method_signatures = [
                test_method.method_signature
                for test_method in test_class.test_method_analyses
                if test_method.test_type == TestType.UI
            ]
            if method_signatures:
                ui_tests_by_class[test_class.qualified_class_name] = method_signatures

        ui_tests_by_project[project_analysis.dataset_name] = ui_tests_by_class

    return ui_tests_by_project


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract UI test methods from Hamster project models."
    )
    parser.add_argument(
        "models_dir",
        type=Path,
        help="Directory containing one subdirectory per project, each with hamster.json.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory where ui_tests.json will be written.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.models_dir.is_dir():
        raise SystemExit(f"models_dir does not exist or is not a directory: {args.models_dir}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    ui_tests = extract_ui_tests(args.models_dir)

    output_file = args.output_dir / "ui_tests.json"
    with output_file.open("w") as f:
        json.dump(ui_tests, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"Saved UI test mapping to {output_file}")


if __name__ == "__main__":
    main()
