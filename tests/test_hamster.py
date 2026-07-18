from pathlib import Path
from types import SimpleNamespace

import pytest
from cldk import CLDK
from cldk.analysis import AnalysisLevel

from hamster.code_analysis.common import CommonAnalysis
from hamster.code_analysis.model.models import (
    MockingFramework,
    ProjectAnalysis,
    TestingFramework,
)
from hamster.code_analysis.test_statistics import (
    ProjectAnalysisInfo,
    SetupAnalysisInfo,
    TestClassAnalysisInfo,
    TestMethodAnalysisInfo,
)

BASE_DIR = Path(__file__).resolve().parent
TEST_SOURCES = BASE_DIR / "resources"
TEST_OUTPUT = BASE_DIR / "output"


def save_project_analysis(dataset_name: str, project_analysis: ProjectAnalysis) -> None:
    output_dir = TEST_OUTPUT / dataset_name
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "hamster.json").open("w") as f:
        f.write(project_analysis.model_dump_json())


def create_analysis_data(dataset_name: str) -> SimpleNamespace:
    analysis = CLDK(language="java").analysis(
        project_path=str(TEST_SOURCES / dataset_name),
        analysis_level=AnalysisLevel.symbol_table,
        analysis_json_path=str(TEST_OUTPUT / dataset_name),
        eager=False,
    )

    common_analysis = CommonAnalysis(analysis)
    test_class_methods, application_classes, _ = common_analysis.categorize_classes()

    return SimpleNamespace(
        analysis=analysis,
        dataset_name=dataset_name,
        test_class_methods=test_class_methods,
        application_classes=application_classes,
    )


@pytest.fixture(scope="module")
def petclinic_data() -> SimpleNamespace:
    """Shared fixture for spring-petclinic analysis data."""
    return create_analysis_data("spring-petclinic")


@pytest.fixture(scope="module")
def commons_cli_data() -> SimpleNamespace:
    """Shared fixture for commons-cli analysis data."""
    return create_analysis_data("commons-cli")


@pytest.fixture(scope="module")
def commons_bsf_data() -> SimpleNamespace:
    """Shared fixture for commons-bsf analysis data."""
    return create_analysis_data("commons-bsf")


def test_hamster_petclinic(petclinic_data):
    project_analysis = ProjectAnalysisInfo(
        analysis=petclinic_data.analysis, dataset_name=petclinic_data.dataset_name
    ).gather_project_analysis_info()
    save_project_analysis(petclinic_data.dataset_name, project_analysis)

    for test_class_analysis in project_analysis.test_class_analyses:
        assert (
            TestingFramework.JUNIT5 in test_class_analysis.testing_frameworks
            or TestingFramework.MOCKITO in test_class_analysis.testing_frameworks
        )
        assert len(test_class_analysis.testing_frameworks) > 0

        if (
            test_class_analysis.qualified_class_name
            == "org.springframework.samples.petclinic.PostgresIntegrationTests"
        ):
            assert (
                TestingFramework.SPRING_TEST in test_class_analysis.testing_frameworks
            )
            assert test_class_analysis.setup_analyses is not None

    assert project_analysis is not None

    # Verify test class and method counts
    assert project_analysis.test_class_count == 18
    assert project_analysis.test_method_count == 58

    # Verify test utility class and method counts
    # Test utility classes: MysqlTestApplication, EntityUtils, CrashControllerIntegrationTests.TestConfiguration, PostgresIntegrationTests.PropertiesLogger
    assert project_analysis.test_utility_class_count == 4
    assert project_analysis.test_utility_method_count == 6


def test_hamster_commons_cli(commons_cli_data):
    project_analysis = ProjectAnalysisInfo(
        analysis=commons_cli_data.analysis, dataset_name=commons_cli_data.dataset_name
    ).gather_project_analysis_info()
    save_project_analysis(commons_cli_data.dataset_name, project_analysis)

    assert project_analysis is not None
    assert len(project_analysis.test_class_analyses) > 0

    # All commons-cli tests use JUnit5
    for test_class_analysis in project_analysis.test_class_analyses:
        assert TestingFramework.JUNIT5 in test_class_analysis.testing_frameworks
        assert len(test_class_analysis.testing_frameworks) > 0

    # Verify specific test class exists and has expected properties
    default_parser_test = next(
        (
            tc
            for tc in project_analysis.test_class_analyses
            if tc.qualified_class_name == "org.apache.commons.cli.DefaultParserTest"
        ),
        None,
    )
    assert default_parser_test is not None
    assert len(default_parser_test.test_method_analyses) > 0


def test_hamster_commons_bsf(commons_bsf_data):
    project_analysis = ProjectAnalysisInfo(
        analysis=commons_bsf_data.analysis, dataset_name=commons_bsf_data.dataset_name
    ).gather_project_analysis_info()
    save_project_analysis(commons_bsf_data.dataset_name, project_analysis)

    assert project_analysis is not None
    assert len(project_analysis.test_class_analyses) > 0

    # All commons-bsf tests use some form of JUnit
    for test_class_analysis in project_analysis.test_class_analyses:
        has_junit = any(
            tf
            in (
                TestingFramework.JUNIT3,
                TestingFramework.JUNIT4,
                TestingFramework.JUNIT5,
            )
            for tf in test_class_analysis.testing_frameworks
        )
        assert has_junit, (
            f"{test_class_analysis.qualified_class_name} has no JUnit framework"
        )
        assert len(test_class_analysis.testing_frameworks) > 0

    # Verify EngineUtilsTest exists and has test methods (uses JUnit3)
    engine_utils_test = next(
        (
            tc
            for tc in project_analysis.test_class_analyses
            if tc.qualified_class_name == "org.apache.bsf.util.EngineUtilsTest"
        ),
        None,
    )
    assert engine_utils_test is not None
    assert TestingFramework.JUNIT3 in engine_utils_test.testing_frameworks
    assert len(engine_utils_test.test_method_analyses) > 0

    # Verify TestBean is identified as a test utility class
    assert project_analysis.test_utility_class_count >= 1


def test_setup_analysis(petclinic_data):
    qualified_class_name = (
        "org.springframework.samples.petclinic.owner.OwnerControllerTests"
    )
    class_analysis = TestClassAnalysisInfo(
        analysis=petclinic_data.analysis,
        dataset_name=petclinic_data.dataset_name,
        application_classes=petclinic_data.application_classes,
    ).get_test_class_analysis(
        qualified_class_name=qualified_class_name,
        test_methods=petclinic_data.test_class_methods[qualified_class_name],
    )
    assert len(class_analysis.setup_analyses) >= 1
    assert (
        MockingFramework.MOCKITO
        in class_analysis.setup_analyses[0].mocking_frameworks_used
    )
    assert (
        MockingFramework.SPRING_TEST
        in class_analysis.setup_analyses[0].mocking_frameworks_used
    )


def test_method_analysis(petclinic_data):
    qualified_class_name = (
        "org.springframework.samples.petclinic.service.ClinicServiceTests"
    )
    method_signature = "shouldInsertOwner()"
    testing_frameworks = CommonAnalysis(
        petclinic_data.analysis
    ).get_testing_frameworks_for_class(qualified_class_name=qualified_class_name)
    setup_methods = SetupAnalysisInfo(petclinic_data.analysis).get_setup_methods(
        qualified_class_name=qualified_class_name,
    )
    method_analysis = TestMethodAnalysisInfo(
        analysis=petclinic_data.analysis,
        dataset_name=petclinic_data.dataset_name,
        application_classes=petclinic_data.application_classes,
    ).get_test_method_analysis_info(
        testing_frameworks=testing_frameworks,
        qualified_class_name=qualified_class_name,
        method_signature=method_signature,
        setup_methods=setup_methods,
    )
    assert method_analysis is not None
    assert len(method_analysis.call_assertion_sequences) == 2
