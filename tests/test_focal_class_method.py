from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest
from cldk import CLDK
from cldk.analysis import AnalysisLevel

from hamster.code_analysis.common import CommonAnalysis
from hamster.code_analysis.focal_class_method.focal_class_method import FocalClassMethod
from hamster.code_analysis.model.models import FocalClassInfo

BASE_DIR = Path(__file__).resolve().parent
TEST_SOURCES = BASE_DIR / "resources"
TEST_OUTPUT = BASE_DIR / "output"


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


def get_focal_class_names(classes: List[FocalClassInfo]) -> List[str]:
    return [cls.focal_class for cls in classes]


def get_focal_methods(classes: List[FocalClassInfo]) -> set:
    """Returns set of (focal_class, focal_method) tuples."""
    focal_methods = set()
    for cls in classes:
        for method in cls.focal_method_names:
            focal_methods.add((cls.focal_class, method))
    return focal_methods


def get_focal_methods_for_class(
    classes: List[FocalClassInfo], focal_class: str
) -> List[str]:
    """Returns list of focal methods for a specific focal class."""
    for cls in classes:
        if cls.focal_class == focal_class:
            return cls.focal_method_names
    return []


@pytest.fixture(scope="module")
def petclinic_data() -> SimpleNamespace:
    """Shared fixture for spring-petclinic analysis data."""
    return create_analysis_data("spring-petclinic")


@pytest.fixture(scope="module")
def commons_cli_data() -> SimpleNamespace:
    """Shared fixture for commons-cli analysis data."""
    return create_analysis_data("commons-cli")


def test_validator_focal_class_person(petclinic_data):
    """ValidatorTests should identify Person as focal class via bean validation."""
    qualified_class_name = "org.springframework.samples.petclinic.model.ValidatorTests"
    method_signature = "shouldNotValidateWhenFirstNameEmpty()"

    focal_classes, _, _, _ = FocalClassMethod(
        petclinic_data.analysis,
        petclinic_data.application_classes,
    ).extract_test_scope(
        qualified_class_name,
        method_signature,
        {},
    )

    assert get_focal_class_names(focal_classes) == [
        "org.springframework.samples.petclinic.model.Person",
    ]


def test_vet_serialization_focal_class(petclinic_data):
    """VetTests.testSerialization should identify Vet as focal class."""
    qualified_class_name = "org.springframework.samples.petclinic.vet.VetTests"
    method_signature = "testSerialization()"

    focal_classes, _, _, _ = FocalClassMethod(
        petclinic_data.analysis,
        petclinic_data.application_classes,
    ).extract_test_scope(
        qualified_class_name,
        method_signature,
        {},
    )

    assert get_focal_class_names(focal_classes) == [
        "org.springframework.samples.petclinic.vet.Vet",
    ]


def test_pet_validator_with_setup_method(petclinic_data):
    """PetValidatorTests should identify PetValidator as focal class when setUp() is provided."""
    qualified_class_name = (
        "org.springframework.samples.petclinic.owner.PetValidatorTests"
    )
    method_signature = "testValidate()"

    focal_classes, is_app_used, _, _ = FocalClassMethod(
        petclinic_data.analysis,
        petclinic_data.application_classes,
    ).extract_test_scope(
        qualified_class_name,
        method_signature,
        {qualified_class_name: ["setUp()"]},
    )

    focal_class_names = get_focal_class_names(focal_classes)
    assert (
        "org.springframework.samples.petclinic.owner.PetValidator" in focal_class_names
    )
    assert is_app_used


def test_clinic_service_multiple_focal_classes(petclinic_data):
    """ClinicServiceTests.shouldInsertPetIntoDatabaseAndGenerateId should identify OwnerRepository, Owner, and Pet."""
    qualified_class_name = (
        "org.springframework.samples.petclinic.service.ClinicServiceTests"
    )
    method_signature = "shouldInsertPetIntoDatabaseAndGenerateId()"

    focal_classes, _, _, _ = FocalClassMethod(
        analysis=petclinic_data.analysis,
        application_classes=petclinic_data.application_classes,
    ).extract_test_scope(
        qualified_class_name,
        method_signature,
        {},
    )

    # Pet is focal because assertThat(pet.getId()).isNotNull() asserts on it
    assert set(get_focal_class_names(focal_classes)) == {
        "org.springframework.samples.petclinic.owner.OwnerRepository",
        "org.springframework.samples.petclinic.owner.Owner",
        "org.springframework.samples.petclinic.owner.Pet",
    }


def test_focal_class_gnu_parser_inherited_field(commons_cli_data):
    """GnuParser should NOT be focal when instantiated in setUp but no methods are called."""
    qualified_class_name = "org.apache.commons.cli.GnuParserTest"
    method_signature = "testLongWithUnexpectedArgument1()"
    setup_methods = {qualified_class_name: ["setUp()"]}

    focal_classes, _, _, _ = FocalClassMethod(
        analysis=commons_cli_data.analysis,
        application_classes=commons_cli_data.application_classes,
    ).extract_test_scope(
        qualified_class_name,
        method_signature,
        setup_methods,
    )

    focal_class_names = get_focal_class_names(focal_classes)
    print(f"\nFocal classes found: {focal_class_names}")
    print(f"Focal methods found: {get_focal_methods(focal_classes)}")

    # GnuParser should not be focal since no methods are called and it is not in assertions
    assert "org.apache.commons.cli.GnuParser" not in focal_class_names, (
        f"GnuParser should be filtered out for empty test, but got: {focal_class_names}"
    )


def test_focal_methods_use_inferred_concrete_type(commons_cli_data):
    """Methods called on a variable should be keyed by inferred concrete type, not static type."""
    qualified_class_name = "org.apache.commons.cli.DefaultParserTest"
    method_signature = "testDeprecated()"
    setup_methods = {qualified_class_name: ["setUp()"]}

    focal_classes, _, _, _ = FocalClassMethod(
        analysis=commons_cli_data.analysis,
        application_classes=commons_cli_data.application_classes,
    ).extract_test_scope(
        qualified_class_name,
        method_signature,
        setup_methods,
    )

    focal_class_names = get_focal_class_names(focal_classes)
    assert "org.apache.commons.cli.DefaultParser" in focal_class_names

    # The parse() method should be recorded under DefaultParser (concrete type),
    # not CommandLineParser (static type of the parser variable)
    focal_methods = get_focal_methods_for_class(
        focal_classes, "org.apache.commons.cli.DefaultParser"
    )
    assert (
        "parse(org.apache.commons.cli.Options, java.lang.String[])" in focal_methods
    ), f"Expected parse() to be recorded under DefaultParser, but got: {focal_methods}"


def test_crash_controller_field_initialized_focal_class(petclinic_data):
    """CrashController should be focal class when initialized as a field (final CrashController testee = new CrashController())."""
    qualified_class_name = (
        "org.springframework.samples.petclinic.system.CrashControllerTests"
    )
    method_signature = "testTriggerException()"

    focal_classes, is_app_used, _, _ = FocalClassMethod(
        petclinic_data.analysis,
        petclinic_data.application_classes,
    ).extract_test_scope(
        qualified_class_name,
        method_signature,
        {},
    )

    focal_class_names = get_focal_class_names(focal_classes)
    assert (
        "org.springframework.samples.petclinic.system.CrashController"
        in focal_class_names
    )
    assert is_app_used

    # Verify focal method is detected (triggerException)
    focal_methods = get_focal_methods_for_class(
        focal_classes, "org.springframework.samples.petclinic.system.CrashController"
    )
    assert "triggerException()" in focal_methods


def test_vet_domain_object_focal_methods(petclinic_data):
    """Vet setters (setFirstName, setLastName) should be detected as focal methods in VetTests.testSerialization."""
    qualified_class_name = "org.springframework.samples.petclinic.vet.VetTests"
    method_signature = "testSerialization()"

    focal_classes, _, _, _ = FocalClassMethod(
        petclinic_data.analysis,
        petclinic_data.application_classes,
    ).extract_test_scope(
        qualified_class_name,
        method_signature,
        {},
    )

    focal_class_names = get_focal_class_names(focal_classes)
    assert "org.springframework.samples.petclinic.vet.Vet" in focal_class_names

    focal_methods = get_focal_methods_for_class(
        focal_classes, "org.springframework.samples.petclinic.vet.Vet"
    )
    # Setters should be detected as focal methods (not filtered as getters)
    assert "setFirstName(java.lang.String)" in focal_methods
    assert "setLastName(java.lang.String)" in focal_methods


def test_pet_type_formatter_with_setup_and_mock(petclinic_data):
    """PetTypeFormatter should be focal class with print() as focal method when setup() creates it."""
    qualified_class_name = (
        "org.springframework.samples.petclinic.owner.PetTypeFormatterTests"
    )
    method_signature = "testPrint()"

    focal_classes, is_app_used, _, _ = FocalClassMethod(
        petclinic_data.analysis,
        petclinic_data.application_classes,
    ).extract_test_scope(
        qualified_class_name,
        method_signature,
        {qualified_class_name: ["setup()"]},
    )

    focal_class_names = get_focal_class_names(focal_classes)
    # PetTypeFormatter should be focal class (instantiated in setup)
    assert (
        "org.springframework.samples.petclinic.owner.PetTypeFormatter"
        in focal_class_names
    )
    assert is_app_used

    # Check that the print method is detected
    focal_methods = get_focal_methods_for_class(
        focal_classes, "org.springframework.samples.petclinic.owner.PetTypeFormatter"
    )
    assert (
        "print(org.springframework.samples.petclinic.owner.PetType, java.util.Locale)"
        in focal_methods
    )


def test_clinic_service_should_find_vets_repository_is_focal(petclinic_data):
    """VetRepository should be focal class with findAll() as focal method, not just the returned Vet objects."""
    qualified_class_name = (
        "org.springframework.samples.petclinic.service.ClinicServiceTests"
    )
    method_signature = "shouldFindVets()"

    focal_classes, is_app_used, _, _ = FocalClassMethod(
        petclinic_data.analysis,
        petclinic_data.application_classes,
    ).extract_test_scope(
        qualified_class_name,
        method_signature,
        {},
    )

    focal_class_names = get_focal_class_names(focal_classes)

    # Ground truth: VetRepository is the class under test
    assert (
        "org.springframework.samples.petclinic.vet.VetRepository" in focal_class_names
    ), (
        f"VetRepository should be focal class (test exercises findAll), got: {focal_class_names}"
    )
    assert is_app_used

    # Ground truth: findAll() is the method being tested
    repo_methods = get_focal_methods_for_class(
        focal_classes, "org.springframework.samples.petclinic.vet.VetRepository"
    )
    assert "findAll()" in repo_methods, (
        f"findAll() should be focal method, got: {repo_methods}"
    )


# @pytest.mark.skip(reason="Repository save() method detection not yet implemented")
def test_clinic_service_should_update_owner_repository_save(petclinic_data):
    """OwnerRepository.save() should be detected as focal method since the test verifies persistence of changes."""
    qualified_class_name = (
        "org.springframework.samples.petclinic.service.ClinicServiceTests"
    )
    method_signature = "shouldUpdateOwner()"

    focal_classes, is_app_used, _, _ = FocalClassMethod(
        petclinic_data.analysis,
        petclinic_data.application_classes,
    ).extract_test_scope(
        qualified_class_name,
        method_signature,
        {},
    )

    focal_class_names = get_focal_class_names(focal_classes)

    # Ground truth: OwnerRepository is the class under test
    assert (
        "org.springframework.samples.petclinic.owner.OwnerRepository"
        in focal_class_names
    ), f"OwnerRepository should be focal class, got: {focal_class_names}"
    assert is_app_used

    # Ground truth: Both findById and save are exercised
    repo_methods = get_focal_methods_for_class(
        focal_classes, "org.springframework.samples.petclinic.owner.OwnerRepository"
    )
    assert "findById(java.lang.Integer)" in repo_methods, (
        f"findById() should be focal method, got: {repo_methods}"
    )
    assert "save(T)" in repo_methods, (
        f"save() should be focal method, got: {repo_methods}"
    )


def test_pet_validator_nested_class_inherits_setup(petclinic_data):
    """Nested test class should inherit PetValidator as focal class from parent's setUp()."""
    # CLDK uses dot notation for nested classes
    qualified_class_name = "org.springframework.samples.petclinic.owner.PetValidatorTests.ValidateHasErrors"
    method_signature = "testValidateWithInvalidPetName()"
    parent_class = "org.springframework.samples.petclinic.owner.PetValidatorTests"

    focal_classes, is_app_used, _, _ = FocalClassMethod(
        petclinic_data.analysis,
        petclinic_data.application_classes,
    ).extract_test_scope(
        qualified_class_name,
        method_signature,
        {parent_class: ["setUp()"]},
    )

    focal_class_names = get_focal_class_names(focal_classes)

    # Ground truth: PetValidator is the class under test
    assert (
        "org.springframework.samples.petclinic.owner.PetValidator" in focal_class_names
    ), f"PetValidator should be focal class, got: {focal_class_names}"
    assert is_app_used, "Application class (PetValidator) is used"

    # Ground truth: validate() is the method being tested
    focal_methods = get_focal_methods_for_class(
        focal_classes, "org.springframework.samples.petclinic.owner.PetValidator"
    )
    assert (
        "validate(java.lang.Object, org.springframework.validation.Errors)"
        in focal_methods
    ), f"validate() should be focal method, got: {focal_methods}"


# @pytest.mark.skip(reason="Mocked repository exclusion not yet implemented")
def test_pet_type_formatter_parse_exception_handling(petclinic_data):
    """Mocked OwnerRepository should NOT be focal class; only PetTypeFormatter with parse() should be focal."""
    qualified_class_name = (
        "org.springframework.samples.petclinic.owner.PetTypeFormatterTests"
    )
    method_signature = "shouldThrowParseException()"

    focal_classes, is_app_used, _, _ = FocalClassMethod(
        petclinic_data.analysis,
        petclinic_data.application_classes,
    ).extract_test_scope(
        qualified_class_name,
        method_signature,
        {qualified_class_name: ["setup()"]},
    )

    focal_class_names = get_focal_class_names(focal_classes)

    # Ground truth: PetTypeFormatter is the class under test
    assert (
        "org.springframework.samples.petclinic.owner.PetTypeFormatter"
        in focal_class_names
    ), f"PetTypeFormatter should be focal class, got: {focal_class_names}"

    # Ground truth: Mocked OwnerRepository should NOT be focal class
    assert (
        "org.springframework.samples.petclinic.owner.OwnerRepository"
        not in focal_class_names
    ), f"Mocked OwnerRepository should NOT be focal class, got: {focal_class_names}"

    # Ground truth: parse() is the method being tested
    focal_methods = get_focal_methods_for_class(
        focal_classes, "org.springframework.samples.petclinic.owner.PetTypeFormatter"
    )
    assert "parse(java.lang.String, java.util.Locale)" in focal_methods, (
        f"parse() should be focal method, got: {focal_methods}"
    )


def test_clinic_service_insert_owner_repository_is_focal(petclinic_data):
    """OwnerRepository.save() should be focal method; Owner setters are just test setup."""
    qualified_class_name = (
        "org.springframework.samples.petclinic.service.ClinicServiceTests"
    )
    method_signature = "shouldInsertOwner()"

    focal_classes, is_app_used, _, _ = FocalClassMethod(
        petclinic_data.analysis,
        petclinic_data.application_classes,
    ).extract_test_scope(
        qualified_class_name,
        method_signature,
        {},
    )

    focal_class_names = get_focal_class_names(focal_classes)

    # Ground truth: OwnerRepository is the class under test
    assert (
        "org.springframework.samples.petclinic.owner.OwnerRepository"
        in focal_class_names
    ), (
        f"OwnerRepository should be focal class (test exercises save), got: {focal_class_names}"
    )
    assert is_app_used

    # Ground truth: save() and findByLastNameStartingWith() are exercised
    repo_methods = get_focal_methods_for_class(
        focal_classes, "org.springframework.samples.petclinic.owner.OwnerRepository"
    )
    assert "save(T)" in repo_methods, (
        f"save() should be focal method, got: {repo_methods}"
    )


def test_is_application_class_used_flag(petclinic_data):
    """The is_application_class_used flag should be True when application classes are referenced."""
    # Test with application class usage
    focal_classes, is_app_used, _, _ = FocalClassMethod(
        petclinic_data.analysis,
        petclinic_data.application_classes,
    ).extract_test_scope(
        "org.springframework.samples.petclinic.vet.VetTests",
        "testSerialization()",
        {},
    )
    assert is_app_used, "VetTests uses Vet which is an application class"

    # Test with CrashController (also application class)
    focal_classes, is_app_used, _, _ = FocalClassMethod(
        petclinic_data.analysis,
        petclinic_data.application_classes,
    ).extract_test_scope(
        "org.springframework.samples.petclinic.system.CrashControllerTests",
        "testTriggerException()",
        {},
    )
    assert is_app_used, (
        "CrashControllerTests uses CrashController which is an application class"
    )
