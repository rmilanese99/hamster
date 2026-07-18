import subprocess
import traceback
from pathlib import Path

def main():
    script_dir = Path(__file__).resolve().parent
    root = script_dir.parent.parent
    src_dir = root / "hamster" / "src"

    hamster_results = root / "xvdc" / "hamster_results"
    model_dir = hamster_results / "model"
    statistics_dir = hamster_results / "statistics"
    output_format = "json_pdf_figures"

    cmd = [
        "uv", "run",
        "python", "-m", "hamster.cli", "statistics",
        "--hamster-analysis-parent-directory", str(model_dir),
        "--statistics-store-path", str(statistics_dir),
        "--output-format", output_format,
    ]

    print("Attempting to generate statistics...")
    print()

    try:
        subprocess.run(cmd, check=True, cwd=src_dir)
    except subprocess.CalledProcessError as e:
        print(f"Failed... Exit code {e.returncode}")
        print("Python stack trace for CalledProcessError:")
        traceback.print_exc()
    else:
        print(f"Done. Output in {statistics_dir}\n", flush=True)

if __name__ == "__main__":
    main()
