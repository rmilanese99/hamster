import time
from pathlib import Path

import pytest
from cldk import CLDK
from cldk.analysis import AnalysisLevel

from hamster.code_analysis.common import CommonAnalysis
from hamster.code_analysis.test_statistics import (
    SetupAnalysisInfo,
    TestClassAnalysisInfo,
    TestMethodAnalysisInfo,
)

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


@pytest.fixture(scope="module")
def common_analysis(analysis):
    return CommonAnalysis(analysis)


@pytest.fixture(scope="module")
def test_class_data(common_analysis):
    return common_analysis.categorize_classes()


@pytest.fixture(scope="module")
def test_class_methods(test_class_data):
    return test_class_data[0]


@pytest.fixture(scope="module")
def application_classes(test_class_data):
    return test_class_data[1]


@pytest.fixture(scope="module")
def test_class_analysis(analysis, application_classes):
    return TestClassAnalysisInfo(analysis, DATASET_NAME, application_classes)


@pytest.fixture(scope="module")
def setup_analysis(analysis):
    return SetupAnalysisInfo(analysis)


@pytest.fixture(scope="module")
def test_method_analysis(analysis, application_classes):
    return TestMethodAnalysisInfo(analysis, DATASET_NAME, application_classes)


@pytest.fixture
def time_tracker(request):
    start_time = time.time()
    yield
    duration = time.time() - start_time
    print(f"\nTest {request.node.nodeid} took {duration:.4f} seconds.")


def test_all_get_testing_frameworks_for_class(
    time_tracker, common_analysis, test_class_methods
):
    for qualified_class_name in test_class_methods:
        testing_frameworks = common_analysis.get_testing_frameworks_for_class(
            qualified_class_name=qualified_class_name
        )
        assert isinstance(testing_frameworks, list)


def test_all_get_setup_analyses_info(
    time_tracker,
    test_class_analysis,
    test_class_methods,
):
    for qualified_class_name in test_class_methods:
        setup_analyses = test_class_analysis.get_setup_analysis_info(
            test_class_qualified_name=qualified_class_name
        )
        assert isinstance(setup_analyses, list)


def test_all_get_teardown_analyses_info(
    time_tracker,
    test_class_analysis,
    test_class_methods,
):
    for qualified_class_name in test_class_methods:
        teardown_analyses = test_class_analysis.get_teardown_analysis_info(
            test_class_qualified_name=qualified_class_name
        )
        assert isinstance(teardown_analyses, list)


def test_all_is_tests_order_dependent(
    time_tracker,
    test_class_analysis,
    test_class_methods,
):
    for qualified_class_name in test_class_methods:
        is_order_dependent = test_class_analysis._is_test_order_dependent(
            test_class_qualified_name=qualified_class_name
        )
        assert isinstance(is_order_dependent, bool)


def test_all_is_bdd(time_tracker, common_analysis, test_class_methods):
    for qualified_class_name in test_class_methods:
        testing_frameworks = common_analysis.get_testing_frameworks_for_class(
            qualified_class_name=qualified_class_name
        )
        is_bdd = TestClassAnalysisInfo._is_bdd(testing_frameworks=testing_frameworks)
        assert isinstance(is_bdd, bool)


def test_all_get_setup_methods(time_tracker, setup_analysis, test_class_methods):
    for qualified_class_name in test_class_methods:
        setup_methods = setup_analysis.get_setup_methods(
            qualified_class_name=qualified_class_name,
        )
        assert isinstance(setup_methods, dict)


def test_all_get_test_method_analysis_info(
    time_tracker,
    common_analysis,
    setup_analysis,
    test_method_analysis,
    test_class_methods,
):
    for qualified_class_name in test_class_methods:
        testing_frameworks = common_analysis.get_testing_frameworks_for_class(
            qualified_class_name=qualified_class_name
        )
        setup_methods = setup_analysis.get_setup_methods(
            qualified_class_name=qualified_class_name,
        )
        for method_signature in test_class_methods[qualified_class_name]:
            result = test_method_analysis.get_test_method_analysis_info(
                testing_frameworks=testing_frameworks,
                qualified_class_name=qualified_class_name,
                method_signature=method_signature,
                setup_methods=setup_methods,
            )
            assert result is not None


def test_all_get_test_class_analysis(
    time_tracker,
    test_class_analysis,
    test_class_methods,
):
    for qualified_class_name in test_class_methods:
        test_methods = test_class_methods[qualified_class_name]
        result = test_class_analysis.get_test_class_analysis(
            qualified_class_name=qualified_class_name,
            test_methods=test_methods,
        )
        assert result is not None
