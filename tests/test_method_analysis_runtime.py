import cProfile
import io
import pstats
import time
from pathlib import Path

import pytest
from cldk import CLDK
from cldk.analysis import AnalysisLevel

from hamster.code_analysis.common import CommonAnalysis, Reachability
from hamster.code_analysis.test_statistics import (
    CallAndAssertionSequenceDetailsInfo,
    InputAnalysis,
    SetupAnalysisInfo,
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
def test_class_data(analysis):
    return CommonAnalysis(analysis).categorize_classes()


@pytest.fixture(scope="module")
def test_class_methods(test_class_data):
    return test_class_data[0]


@pytest.fixture(scope="module")
def application_classes(test_class_data):
    return test_class_data[1]


@pytest.fixture(scope="module")
def input_analysis(analysis):
    return InputAnalysis(analysis)


@pytest.fixture(scope="module")
def setup_analysis(analysis):
    return SetupAnalysisInfo(analysis)


@pytest.fixture(scope="module")
def test_method_analysis(analysis, application_classes):
    return TestMethodAnalysisInfo(analysis, DATASET_NAME, application_classes)


@pytest.fixture(scope="module")
def call_and_assertion_info(analysis):
    return CallAndAssertionSequenceDetailsInfo(analysis, DATASET_NAME)


@pytest.fixture
def profiled_time_tracker(request):
    profiler = cProfile.Profile()
    start_time = time.perf_counter()
    profiler.enable()
    yield
    profiler.disable()
    duration = time.perf_counter() - start_time
    print(f"\nTest {request.node.nodeid} took {duration:.4f} seconds.")

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream).sort_stats("cumulative")
    stats.print_stats(20)
    print("\nProfile stats for this test:\n")
    print(stream.getvalue())


def test_all_get_ncloc(profiled_time_tracker, analysis, test_class_methods):
    common_analysis = CommonAnalysis(analysis)
    for qualified_class_name, methods in test_class_methods.items():
        for method_signature in methods:
            method_details = analysis.get_method(qualified_class_name, method_signature)
            ncloc = common_analysis.get_ncloc(
                method_details.declaration, method_details.code
            )
            assert ncloc > 0


def test_all_get_input_details(
    profiled_time_tracker, input_analysis, test_class_methods
):
    for qualified_class_name, methods in test_class_methods.items():
        for method_signature in methods:
            test_inputs = input_analysis.get_input_details(
                qualified_class_name, method_signature
            )
            assert test_inputs is not None


def test_all_get_helper_methods(profiled_time_tracker, analysis, test_class_methods):
    reachability = Reachability(analysis)
    for qualified_class_name, methods in test_class_methods.items():
        for method_signature in methods:
            helper_methods = reachability.get_helper_methods(
                qualified_class_name,
                method_signature,
                add_extended_class=True,
                allow_repetition=True,
            )
            assert helper_methods is not None


def test_all_is_mocking_used(profiled_time_tracker, analysis, test_class_methods):
    common_analysis = CommonAnalysis(analysis)
    for qualified_class_name, methods in test_class_methods.items():
        for method_signature in methods:
            mock_count = common_analysis.is_mocking_used(
                qualified_class_name, method_signature
            )
            assert isinstance(mock_count, int)


def test_all_get_constructor_call_details(
    profiled_time_tracker, analysis, test_class_methods
):
    common_analysis = CommonAnalysis(analysis)
    for qualified_class_name, methods in test_class_methods.items():
        for method_signature in methods:
            method_details = analysis.get_method(qualified_class_name, method_signature)
            constructor_details = common_analysis.get_constructor_call_details(
                method_details
            )
            assert isinstance(constructor_details, list)


def test_all_get_application_call_details(
    profiled_time_tracker, analysis, test_class_methods
):
    common_analysis = CommonAnalysis(analysis)
    for qualified_class_name, methods in test_class_methods.items():
        for method_signature in methods:
            method_details = analysis.get_method(qualified_class_name, method_signature)
            app_details = common_analysis.get_application_call_details(method_details)
            assert isinstance(app_details, list)


def test_all_get_library_call_details(
    profiled_time_tracker, analysis, test_class_methods
):
    common_analysis = CommonAnalysis(analysis)
    for qualified_class_name, methods in test_class_methods.items():
        for method_signature in methods:
            method_details = analysis.get_method(qualified_class_name, method_signature)
            lib_details = common_analysis.get_library_call_details(method_details)
            assert isinstance(lib_details, list)


def test_all_get_setup_method_details(
    profiled_time_tracker,
    analysis,
    setup_analysis,
    test_class_methods,
):
    common_analysis = CommonAnalysis(analysis)
    for qualified_class_name, methods in test_class_methods.items():
        testing_frameworks = common_analysis.get_testing_frameworks_for_class(
            qualified_class_name
        )
        for method_signature in methods:
            mocked_details = setup_analysis.get_setup_method_details(
                qualified_class_name=qualified_class_name,
                method_signature=method_signature,
                testing_frameworks=testing_frameworks,
                is_test_method=True,
            )
            assert mocked_details is not None


def test_all_get_call_and_assertion_sequence_details_info(
    profiled_time_tracker,
    analysis,
    call_and_assertion_info,
    test_class_methods,
):
    common_analysis = CommonAnalysis(analysis)
    for qualified_class_name, methods in test_class_methods.items():
        testing_frameworks = common_analysis.get_testing_frameworks_for_class(
            qualified_class_name
        )
        for method_signature in methods:
            result = (
                call_and_assertion_info.get_call_and_assertion_sequence_details_info(
                    qualified_class_name=qualified_class_name,
                    method_signature=method_signature,
                    testing_frameworks=testing_frameworks,
                )
            )
            assert result is not None


def test_all_get_test_type_focal_classes(
    profiled_time_tracker,
    analysis,
    setup_analysis,
    test_method_analysis,
    test_class_methods,
):
    common_analysis = CommonAnalysis(analysis)
    for qualified_class_name, methods in test_class_methods.items():
        testing_frameworks = common_analysis.get_testing_frameworks_for_class(
            qualified_class_name
        )
        setup_methods = setup_analysis.get_setup_methods(
            qualified_class_name=qualified_class_name
        )
        for method_signature in methods:
            test_type, focal_classes = test_method_analysis.get_test_type_focal_classes(
                qualified_class_name,
                method_signature,
                setup_methods,
            )
            assert test_type is not None


def test_all_get_test_method_analysis_info(
    profiled_time_tracker,
    analysis,
    setup_analysis,
    test_method_analysis,
    test_class_methods,
):
    common_analysis = CommonAnalysis(analysis)
    for qualified_class_name, methods in test_class_methods.items():
        testing_frameworks = common_analysis.get_testing_frameworks_for_class(
            qualified_class_name
        )
        setup_methods = setup_analysis.get_setup_methods(
            qualified_class_name=qualified_class_name
        )
        for method_signature in methods:
            result = test_method_analysis.get_test_method_analysis_info(
                testing_frameworks,
                qualified_class_name,
                method_signature,
                setup_methods,
            )
            assert result is not None
