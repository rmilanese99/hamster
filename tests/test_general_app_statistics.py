import time
from pathlib import Path

import pytest
from cldk import CLDK
from cldk.analysis import AnalysisLevel

BASE_DIR = Path(__file__).resolve().parent
PROJECT_PATH_RELATIVE = "resources/spring-petclinic"
ANALYSIS_JSON_PATH_RELATIVE = "output/spring-petclinic"
PROJECT_PATH = str(BASE_DIR / PROJECT_PATH_RELATIVE)
ANALYSIS_JSON_PATH = str(BASE_DIR / ANALYSIS_JSON_PATH_RELATIVE)
DATASET_NAME = "spring-petclinic"


@pytest.fixture(scope="module")
def analysis():
    return CLDK(language="java").analysis(
        project_path=PROJECT_PATH,
        analysis_level=AnalysisLevel.symbol_table,
        analysis_json_path=ANALYSIS_JSON_PATH,
        eager=False,
    )


@pytest.fixture
def time_tracker(request):
    start_time = time.time()
    yield
    duration = time.time() - start_time
    print(f"\nTest {request.node.nodeid} took {duration:.4f} seconds.")
