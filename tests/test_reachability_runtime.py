import cProfile
import io
import pstats
import time
from pathlib import Path

import pytest
from cldk import CLDK
from cldk.analysis import AnalysisLevel

from hamster.code_analysis.common import CommonAnalysis, Reachability

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
def interfaces(analysis):
    all_classes = analysis.get_classes()
    return [
        cls_name for cls_name, details in all_classes.items() if details.is_interface
    ]


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


def test_all_get_helper_methods_default(
    profiled_time_tracker, analysis, test_class_methods
):
    reachability = Reachability(analysis)
    for qualified_class_name, methods in test_class_methods.items():
        for method_signature in methods:
            helpers = reachability.get_helper_methods(
                qualified_class_name, method_signature
            )
            assert isinstance(helpers, dict)


def test_all_get_helper_methods_add_extended(
    profiled_time_tracker, analysis, test_class_methods
):
    reachability = Reachability(analysis)
    for qualified_class_name, methods in test_class_methods.items():
        for method_signature in methods:
            helpers = reachability.get_helper_methods(
                qualified_class_name,
                method_signature,
                add_extended_class=True,
            )
            assert isinstance(helpers, dict)


def test_all_get_helper_methods_allow_repetition(
    profiled_time_tracker, analysis, test_class_methods
):
    reachability = Reachability(analysis)
    for qualified_class_name, methods in test_class_methods.items():
        for method_signature in methods:
            helpers = reachability.get_helper_methods(
                qualified_class_name,
                method_signature,
                allow_repetition=True,
            )
            assert isinstance(helpers, dict)


def test_all_get_helper_methods_both(
    profiled_time_tracker, analysis, test_class_methods
):
    reachability = Reachability(analysis)
    for qualified_class_name, methods in test_class_methods.items():
        for method_signature in methods:
            helpers = reachability.get_helper_methods(
                qualified_class_name,
                method_signature,
                add_extended_class=True,
                allow_repetition=True,
            )
            assert isinstance(helpers, dict)


def test_all_get_helper_methods_depth_1(
    profiled_time_tracker, analysis, test_class_methods
):
    reachability = Reachability(analysis)
    for qualified_class_name, methods in test_class_methods.items():
        for method_signature in methods:
            helpers = reachability.get_helper_methods(
                qualified_class_name,
                method_signature,
                depth=1,
                add_extended_class=True,
                allow_repetition=True,
            )
            assert isinstance(helpers, dict)


def test_all_get_helper_methods_depth_2(
    profiled_time_tracker, analysis, test_class_methods
):
    reachability = Reachability(analysis)
    for qualified_class_name, methods in test_class_methods.items():
        for method_signature in methods:
            helpers = reachability.get_helper_methods(
                qualified_class_name,
                method_signature,
                depth=2,
                add_extended_class=True,
                allow_repetition=True,
            )
            assert isinstance(helpers, dict)


def test_all_get_helper_methods_depth_3(
    profiled_time_tracker, analysis, test_class_methods
):
    reachability = Reachability(analysis)
    for qualified_class_name, methods in test_class_methods.items():
        for method_signature in methods:
            helpers = reachability.get_helper_methods(
                qualified_class_name,
                method_signature,
                depth=3,
                add_extended_class=True,
                allow_repetition=True,
            )
            assert isinstance(helpers, dict)


def test_all_get_concrete_classes(profiled_time_tracker, analysis, interfaces):
    reachability = Reachability(analysis)
    for interface in interfaces:
        concretes = reachability.get_concrete_classes(interface)
        assert isinstance(concretes, list)
