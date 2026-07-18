from pathlib import Path
from types import SimpleNamespace

import pytest
from cldk import CLDK
from cldk.analysis import AnalysisLevel

from hamster.code_analysis.common import CommonAnalysis

BASE_DIR = Path(__file__).resolve().parent
TEST_SOURCES = BASE_DIR / "resources"
TEST_OUTPUT = BASE_DIR / "output"


@pytest.fixture(scope="module")
def petclinic_data() -> SimpleNamespace:
    """Shared fixture for spring-petclinic analysis data."""
    dataset_name = "spring-petclinic"
    analysis = CLDK(language="java").analysis(
        project_path=str(TEST_SOURCES / dataset_name),
        analysis_level=AnalysisLevel.symbol_table,
        analysis_json_path=str(TEST_OUTPUT / dataset_name),
        eager=False,
    )

    common_analysis = CommonAnalysis(analysis)
    test_class_methods, application_classes, test_utility_classes = (
        common_analysis.categorize_classes()
    )

    return SimpleNamespace(
        analysis=analysis,
        common_analysis=common_analysis,
        test_class_methods=test_class_methods,
        application_classes=application_classes,
        test_utility_classes=test_utility_classes,
    )


def test_entity_utils_classified_as_test_utility(petclinic_data: SimpleNamespace):
    """EntityUtils (and other test utilities) should be in test_utility_classes, not application_classes."""
    entity_utils = "org.springframework.samples.petclinic.service.EntityUtils"

    assert entity_utils in petclinic_data.test_utility_classes, (
        f"EntityUtils should be classified as test utility, "
        f"but was not found in test_utility_classes: {petclinic_data.test_utility_classes}"
    )

    assert entity_utils not in petclinic_data.application_classes, (
        f"EntityUtils should NOT be in application_classes"
    )
