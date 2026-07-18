from pathlib import Path
from types import SimpleNamespace
from typing import List, Set, Tuple

import pytest
from cldk import CLDK
from cldk.analysis import AnalysisLevel

from hamster.code_analysis.common import CommonAnalysis, Reachability
from hamster.code_analysis.model.models import (
    AssertionType,
    CallAndAssertionSequenceDetails,
    ParameterType,
    TestingFramework,
)
from hamster.code_analysis.test_statistics import CallAndAssertionSequenceDetailsInfo
from hamster.code_analysis.test_statistics.call_and_assertion_sequence_details_info import (
    CategorizationParams,
    ExtractMethodChainParams,
    MethodNode,
)

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
    test_class_methods, application_classes, test_utility_classes = (
        common_analysis.categorize_classes()
    )

    return SimpleNamespace(
        analysis=analysis,
        dataset_name=dataset_name,
        test_class_methods=test_class_methods,
        application_classes=application_classes,
        test_utility_classes=test_utility_classes,
    )


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def petclinic_data() -> SimpleNamespace:
    return create_analysis_data("spring-petclinic")


@pytest.fixture(scope="module")
def commons_bsf_data() -> SimpleNamespace:
    return create_analysis_data("commons-bsf")


def _get_sequences(
    data: SimpleNamespace,
    qualified_class_name: str,
    method_signature: str,
) -> List[CallAndAssertionSequenceDetails]:
    info = CallAndAssertionSequenceDetailsInfo(data.analysis, data.dataset_name)
    testing_frameworks = CommonAnalysis(data.analysis).get_testing_frameworks_for_class(
        qualified_class_name=qualified_class_name
    )
    return info.get_call_and_assertion_sequence_details_info(
        qualified_class_name=qualified_class_name,
        method_signature=method_signature,
        testing_frameworks=testing_frameworks,
        test_utility_classes=getattr(data, "test_utility_classes", None),
    )


# ===========================================================================
# PART 1: Real resource-based tests -- spring-petclinic (JUnit5 + AssertJ)
# ===========================================================================


class TestPetclinicSequences:
    """Tests against real spring-petclinic Java test methods."""

    # -- shouldInsertOwner: two call-then-assert phases ----------------------

    def test_should_insert_owner_sequence_count(self, petclinic_data):
        """shouldInsertOwner() has two distinct call-then-assert phases."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.service.ClinicServiceTests",
            "shouldInsertOwner()",
        )
        assert len(seqs) == 2

    def test_should_insert_owner_first_sequence_has_assertions(self, petclinic_data):
        """First sequence contains assertThat wrapper + isNotZero comparison."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.service.ClinicServiceTests",
            "shouldInsertOwner()",
        )
        assert len(seqs[0].assertion_details) == 2

    def test_should_insert_owner_second_sequence_has_assertions(self, petclinic_data):
        """Second sequence contains assertThat wrapper + isEqualTo assertion."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.service.ClinicServiceTests",
            "shouldInsertOwner()",
        )
        assert len(seqs[1].assertion_details) == 2

    # -- shouldFindOwnersByLastName: two assertThat chains -------------------

    def test_should_find_owners_by_last_name(self, petclinic_data):
        """shouldFindOwnersByLastName() has two assertThat groups with a call between them."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.service.ClinicServiceTests",
            "shouldFindOwnersByLastName()",
        )
        assert len(seqs) == 2

    def test_should_find_owners_by_last_name_assertion_types(self, petclinic_data):
        """Both assertion groups use collection-type assertions (hasSize and isEmpty)."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.service.ClinicServiceTests",
            "shouldFindOwnersByLastName()",
        )
        all_assertion_names = [
            a.assertion_name for s in seqs for a in s.assertion_details
        ]
        assert "hasSize" in all_assertion_names and "isEmpty" in all_assertion_names

    # -- shouldFindSingleOwnerWithPet: one block of chained assertThat -------

    def test_should_find_single_owner_with_pet_sequence_count(self, petclinic_data):
        """shouldFindSingleOwnerWithPet() has five sequences: one per assertThat chain."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.service.ClinicServiceTests",
            "shouldFindSingleOwnerWithPet()",
        )
        assert len(seqs) == 5

    def test_should_find_single_owner_assertions_are_wrapped(self, petclinic_data):
        """All assertions in shouldFindSingleOwnerWithPet() should be wrapped (AssertJ assertThat)."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.service.ClinicServiceTests",
            "shouldFindSingleOwnerWithPet()",
        )
        for seq in seqs:
            for ad in seq.assertion_details:
                if ad.assertion_name != "assertThat":
                    assert ad.is_wrapped is True

    # -- testSerialization (VetTests): single sequence with 3 assertions -----

    def test_vet_serialization_sequence_count(self, petclinic_data):
        """testSerialization() has 3 assertThat().isEqualTo() chains yielding 6
        sequences: secondary assertion getters in assertThat arguments (e.g.
        assertThat(vet.getFirstName()).isEqualTo(...)) split each chain into a
        WRAPPER sequence and an equality sequence."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.vet.VetTests",
            "testSerialization()",
        )
        assert len(seqs) == 6

    def test_vet_serialization_assertion_count(self, petclinic_data):
        """testSerialization() should have 3 isEqualTo assertions across all sequences."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.vet.VetTests",
            "testSerialization()",
        )
        is_equal_to_count = sum(
            1
            for s in seqs
            for a in s.assertion_details
            if a.assertion_name == "isEqualTo"
        )
        assert is_equal_to_count == 3

    def test_vet_serialization_has_call_details(self, petclinic_data):
        """testSerialization() first sequence has 7 setup calls (constructor, setters,
        serialize, deserialize, and a secondary assertion getter)."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.vet.VetTests",
            "testSerialization()",
        )
        assert len(seqs[0].call_sequence_details) == 7

    # -- testTriggerException (CrashControllerTests): assertThatExceptionOfType chain

    def test_crash_controller_exception_assertion(self, petclinic_data):
        """testTriggerException() uses assertThatExceptionOfType -- throwable + wrapper."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.system.CrashControllerTests",
            "testTriggerException()",
        )
        assert len(seqs) == 1
        all_types = {
            at for s in seqs for a in s.assertion_details for at in a.assertion_type
        }
        assert AssertionType.THROWABLE in all_types and AssertionType.WRAPPER in all_types
        assert len(seqs[0].assertion_details) == 3
        assert len(seqs[0].call_sequence_details) == 0

    # -- shouldNotValidateWhenFirstNameEmpty (ValidatorTests): multiple assertThat chains

    def test_validator_tests_sequence_structure(self, petclinic_data):
        """shouldNotValidateWhenFirstNameEmpty() has setup calls then assertion block."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.model.ValidatorTests",
            "shouldNotValidateWhenFirstNameEmpty()",
        )
        assert len(seqs) == 3
        total_assertions = sum(len(s.assertion_details) for s in seqs)
        assert total_assertions == 6

    # -- shouldFindAllPetTypes: alternating call-assert pairs -----------------

    def test_should_find_all_pet_types(self, petclinic_data):
        """shouldFindAllPetTypes() has interleaved EntityUtils.getById and assertThat calls."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.service.ClinicServiceTests",
            "shouldFindAllPetTypes()",
        )
        assert len(seqs) == 2

    # -- testPrint (PetTypeFormatterTests): setup, one assertThat().isEqualTo()

    def test_pet_type_formatter_test_print(self, petclinic_data):
        """testPrint() should have one sequence with calls then one equality assertion."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.owner.PetTypeFormatterTests",
            "testPrint()",
        )
        assert len(seqs) == 1
        non_wrapper = [
            a
            for a in seqs[0].assertion_details
            if AssertionType.WRAPPER not in a.assertion_type
        ]
        assert len(non_wrapper) == 1

    # -- shouldThrowParseException: Assertions.assertThrows (JUnit5 throwable)

    def test_should_throw_parse_exception(self, petclinic_data):
        """shouldThrowParseException() uses Assertions.assertThrows -- should be THROWABLE."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.owner.PetTypeFormatterTests",
            "shouldThrowParseException()",
        )
        assert len(seqs) == 2
        assert len(seqs[0].assertion_details) == 1
        assert AssertionType.THROWABLE in seqs[0].assertion_details[0].assertion_type

    # -- testValidate (PetValidatorTests): JUnit5 assertFalse ----------------

    def test_pet_validator_truthiness(self, petclinic_data):
        """testValidate() uses assertFalse -- should be TRUTHINESS."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.owner.PetValidatorTests",
            "testValidate()",
        )
        all_types = {
            at for s in seqs for a in s.assertion_details for at in a.assertion_type
        }
        assert AssertionType.TRUTHINESS in all_types

    # -- shouldAddNewVisitForPet: chained hasSize().allMatch() ---------------

    def test_should_add_new_visit_chained_assertions(self, petclinic_data):
        """shouldAddNewVisitForPet() chains hasSize and allMatch on assertThat."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.service.ClinicServiceTests",
            "shouldAddNewVisitForPet()",
        )
        assert len(seqs) == 3
        all_names = [a.assertion_name for s in seqs for a in s.assertion_details]
        assert "hasSize" in all_names and "allMatch" in all_names

    # -- shouldFindVisitsByPetId: chained hasSize().element().extracting().isNotNull()

    def test_should_find_visits_by_pet_id_chain(self, petclinic_data):
        """shouldFindVisitsByPetId() chains collection and nullness assertions."""
        seqs = _get_sequences(
            petclinic_data,
            "org.springframework.samples.petclinic.service.ClinicServiceTests",
            "shouldFindVisitsByPetId()",
        )
        assert len(seqs) == 3
        all_names = [a.assertion_name for s in seqs for a in s.assertion_details]
        assert "hasSize" in all_names and "isNotNull" in all_names


# ===========================================================================
# PART 2: Real resource-based tests -- commons-bsf (JUnit3)
# ===========================================================================


class TestCommonsBsfSequences:
    """Tests against real commons-bsf Java test methods (JUnit3 assertions)."""

    # -- testCallBeanMethod: multiple try/catch blocks with assertions --------

    def test_call_bean_method_sequence_count(self, commons_bsf_data):
        """testCallBeanMethod() has multiple assertEquals calls separated by try/catch blocks."""
        seqs = _get_sequences(
            commons_bsf_data,
            "org.apache.bsf.util.EngineUtilsTest",
            "testCallBeanMethod()",
        )
        assert len(seqs) == 7

    def test_call_bean_method_has_equality_assertions(self, commons_bsf_data):
        """assertEquals calls should be categorized as EQUALITY."""
        seqs = _get_sequences(
            commons_bsf_data,
            "org.apache.bsf.util.EngineUtilsTest",
            "testCallBeanMethod()",
        )
        all_types = {
            at for s in seqs for a in s.assertion_details for at in a.assertion_type
        }
        assert AssertionType.EQUALITY in all_types and AssertionType.STRING in all_types

    def test_call_bean_method_has_fail_assertion(self, commons_bsf_data):
        """testCallBeanMethod() has exactly 4 fail() calls categorized as THROWABLE."""
        seqs = _get_sequences(
            commons_bsf_data,
            "org.apache.bsf.util.EngineUtilsTest",
            "testCallBeanMethod()",
        )
        fail_count = sum(
            1 for s in seqs for a in s.assertion_details if a.assertion_name == "fail"
        )
        assert fail_count == 4

    # -- testCreateBean: assertEquals and assertNotNull and fail -------------

    def test_create_bean_mixed_assertions(self, commons_bsf_data):
        """testCreateBean() uses assertNotNull + assertEquals + fail."""
        seqs = _get_sequences(
            commons_bsf_data,
            "org.apache.bsf.util.EngineUtilsTest",
            "testCreateBean()",
        )
        assert len(seqs) == 3
        all_names = [a.assertion_name for s in seqs for a in s.assertion_details]
        assert "assertNotNull" in all_names and "assertEquals" in all_names

    def test_create_bean_has_call_details(self, commons_bsf_data):
        """testCreateBean() should have non-assertion callables (EngineUtils.createBean)."""
        seqs = _get_sequences(
            commons_bsf_data,
            "org.apache.bsf.util.EngineUtilsTest",
            "testCreateBean()",
        )
        all_calls = [c.method_name for s in seqs for c in s.call_sequence_details]
        assert len(all_calls) == 3

    # -- testGetTypeSignatureString: two assertEquals in one block -----------

    def test_type_signature_string_sequence(self, commons_bsf_data):
        """testGetTypeSignatureString() has setup calls then 2 assertEquals."""
        seqs = _get_sequences(
            commons_bsf_data,
            "org.apache.bsf.util.EngineUtilsTest",
            "testGetTypeSignatureString()",
        )
        total_assertions = sum(len(s.assertion_details) for s in seqs)
        assert total_assertions == 2

    # -- testRegisterEngine (BSFTest): single assertTrue --------------------

    def test_register_engine(self, commons_bsf_data):
        """testRegisterEngine() has one call and one assertTrue."""
        seqs = _get_sequences(
            commons_bsf_data,
            "org.apache.bsf.BSFTest",
            "testRegisterEngine()",
        )
        assert len(seqs) == 1
        assert len(seqs[0].assertion_details) == 1
        assert AssertionType.TRUTHINESS in seqs[0].assertion_details[0].assertion_type

    # -- testExec (BSFTest): try/catch with fail then assertEquals ----------

    def test_exec_sequence(self, commons_bsf_data):
        """testExec() has try/catch block with potential fail then assertEquals outside."""
        seqs = _get_sequences(
            commons_bsf_data,
            "org.apache.bsf.BSFTest",
            "testExec()",
        )
        assert len(seqs) == 2
        total_assertions = sum(len(s.assertion_details) for s in seqs)
        assert total_assertions == 2

    # -- testUndeclareBean (BSFTest): assertNull ----------------------------

    def test_undeclare_bean_nullness(self, commons_bsf_data):
        """testUndeclareBean() uses assertNull -- should be NULLNESS."""
        seqs = _get_sequences(
            commons_bsf_data,
            "org.apache.bsf.BSFTest",
            "testUndeclareBean()",
        )
        assert len(seqs) == 2
        all_types = {
            at for s in seqs for a in s.assertion_details for at in a.assertion_type
        }
        assert AssertionType.NULLNESS in all_types

    # -- StringUtilsTest: assertTrue with secondary assertion (builtin) ------

    def test_class_name_to_var_name_truthiness(self, commons_bsf_data):
        """testClassNameToVarName() uses assertTrue(expr.equals(...)) pattern."""
        seqs = _get_sequences(
            commons_bsf_data,
            "org.apache.bsf.util.StringUtilsTest",
            "testClassNameToVarName()",
        )
        assert len(seqs) == 3
        all_types = {
            at for s in seqs for a in s.assertion_details for at in a.assertion_type
        }
        assert AssertionType.TRUTHINESS in all_types

    def test_clean_string_multiple_assert_true(self, commons_bsf_data):
        """testCleanString() has 4 assertTrue calls across 4 sequences (one per cleanString+assertEquals pair)."""
        seqs = _get_sequences(
            commons_bsf_data,
            "org.apache.bsf.util.StringUtilsTest",
            "testCleanString()",
        )
        assert len(seqs) == 4
        total_assertions = sum(len(s.assertion_details) for s in seqs)
        assert total_assertions == 4


# ===========================================================================
# PART 3: extract_method_nodes unit tests (Tree-sitter parsing)
# ===========================================================================


class TestExtractMethodNodes:
    """Test the Tree-sitter method node extraction directly."""

    @pytest.fixture()
    def info(self, petclinic_data):
        return CallAndAssertionSequenceDetailsInfo(
            petclinic_data.analysis, petclinic_data.dataset_name
        )

    def _extract(self, info, code: str) -> list:
        params = ExtractMethodChainParams(method_details=None, call_site_mapping={})
        return info.extract_method_nodes(code, params)

    def test_simple_method_call(self, info):
        nodes = self._extract(info, "foo()")
        assert len(nodes) == 1
        assert nodes[0].method_name == "foo"

    def test_chained_method_calls(self, info):
        nodes = self._extract(info, "a.b().c()")
        assert len(nodes) == 1
        tail = nodes[0]
        names = [tail.method_name]
        while tail.child_invocation:
            tail = tail.child_invocation
            names.append(tail.method_name)
        assert "c" in names

    def test_multiple_statements(self, info):
        code = "foo();\nbar();\nbaz();"
        nodes = self._extract(info, code)
        assert len(nodes) == 3

    def test_nested_method_in_arguments(self, info):
        nodes = self._extract(info, "outer(inner())")
        assert len(nodes) == 1
        assert nodes[0].method_name == "outer"
        # inner() is parsed as a nested MethodNode in the first argument
        assert len(nodes[0].arguments) == 1
        inner_chain = nodes[0].arguments[0]
        assert len(inner_chain) == 1
        assert inner_chain[0].method_name == "inner"

    def test_constructor_call(self, info):
        nodes = self._extract(info, "new Foo()")
        assert len(nodes) == 1
        assert "<<CONSTRUCTOR>>" in nodes[0].method_name

    def test_lambda_expression(self, info):
        nodes = self._extract(info, "run(() -> doSomething())")
        assert len(nodes) == 1

    def test_assert_statement(self, info):
        nodes = self._extract(info, "assert x != null")
        assert len(nodes) == 1
        assert nodes[0].method_name == "<<ASSERT_STATEMENT>>"

    def test_method_reference(self, info):
        nodes = self._extract(info, "list.stream().map(Foo::bar)")
        assert len(nodes) == 1

    def test_empty_code(self, info):
        nodes = self._extract(info, "")
        assert len(nodes) == 0

    def test_no_method_calls(self, info):
        nodes = self._extract(info, "int x = 5;")
        assert len(nodes) == 0

    def test_deeply_chained(self, info):
        code = "a().b().c().d().e()"
        nodes = self._extract(info, code)
        assert len(nodes) == 1
        depth = 1
        curr = nodes[0]
        while curr.child_invocation:
            curr = curr.child_invocation
            depth += 1
        assert depth == 5


# ===========================================================================
# PART 4: Assertion type categorization unit tests
# ===========================================================================


class TestAssertionTypeCategorization:
    """Test __get_assertion_types and __pick_category via the public API with mocked CLDK data."""

    @pytest.fixture()
    def info(self, petclinic_data):
        return CallAndAssertionSequenceDetailsInfo(
            petclinic_data.analysis, petclinic_data.dataset_name
        )

    def _get_types(self, info, method_name, frameworks, is_wrapped=False):
        return info._CallAndAssertionSequenceDetailsInfo__get_assertion_types(
            method_name, frameworks, is_wrapped
        )

    def _pick(self, info, node, frameworks, params=None):
        if params is None:
            params = CategorizationParams()
        return info._CallAndAssertionSequenceDetailsInfo__pick_category(
            node, frameworks, params
        )

    # -- JUnit5 assertion type resolution -----------------------------------

    def test_junit5_assert_true(self, info):
        types = self._get_types(info, "assertTrue", [TestingFramework.JUNIT5])
        assert AssertionType.TRUTHINESS in types

    def test_junit5_assert_equals(self, info):
        types = self._get_types(info, "assertEquals", [TestingFramework.JUNIT5])
        assert set(types) == {
            AssertionType.EQUALITY,
            AssertionType.NUMERIC_TOLERANCE,
            AssertionType.STRING,
        }

    def test_junit5_assert_null(self, info):
        types = self._get_types(info, "assertNull", [TestingFramework.JUNIT5])
        assert AssertionType.NULLNESS in types

    def test_junit5_assert_throws(self, info):
        types = self._get_types(info, "assertThrows", [TestingFramework.JUNIT5])
        assert AssertionType.THROWABLE in types

    def test_junit5_assert_timeout(self, info):
        types = self._get_types(info, "assertTimeout", [TestingFramework.JUNIT5])
        assert AssertionType.TIMEOUT in types

    def test_junit5_assert_same(self, info):
        types = self._get_types(info, "assertSame", [TestingFramework.JUNIT5])
        assert AssertionType.IDENTITY in types

    def test_junit5_assert_all(self, info):
        types = self._get_types(info, "assertAll", [TestingFramework.JUNIT5])
        assert AssertionType.GROUPED in types

    def test_junit5_fail(self, info):
        types = self._get_types(info, "fail", [TestingFramework.JUNIT5])
        assert AssertionType.THROWABLE in types

    # -- JUnit3 assertion type resolution -----------------------------------

    def test_junit3_assert_true(self, info):
        types = self._get_types(info, "assertTrue", [TestingFramework.JUNIT3])
        assert AssertionType.TRUTHINESS in types

    def test_junit3_assert_equals(self, info):
        types = self._get_types(info, "assertEquals", [TestingFramework.JUNIT3])
        assert set(types) == {
            AssertionType.EQUALITY,
            AssertionType.NUMERIC_TOLERANCE,
            AssertionType.STRING,
        }

    def test_junit3_fail(self, info):
        types = self._get_types(info, "fail", [TestingFramework.JUNIT3])
        assert AssertionType.THROWABLE in types

    # -- AssertJ wrapped assertions -----------------------------------------

    def test_assertj_assert_that_is_wrapper(self, info):
        types = self._get_types(info, "assertThat", [TestingFramework.ASSERTJ])
        assert AssertionType.WRAPPER in types

    def test_assertj_is_equal_to_unwrapped_ignored(self, info):
        """isEqualTo without wrapping should not be classified."""
        types = self._get_types(
            info, "isEqualTo", [TestingFramework.ASSERTJ], is_wrapped=False
        )
        assert len(types) == 0

    def test_assertj_is_equal_to_wrapped(self, info):
        """isEqualTo with wrapping should be classified as COLLECTION, EQUALITY, and STRING."""
        types = self._get_types(
            info, "isEqualTo", [TestingFramework.ASSERTJ], is_wrapped=True
        )
        assert set(types) == {
            AssertionType.COLLECTION,
            AssertionType.EQUALITY,
            AssertionType.STRING,
        }

    def test_assertj_is_true_wrapped(self, info):
        types = self._get_types(
            info, "isTrue", [TestingFramework.ASSERTJ], is_wrapped=True
        )
        assert AssertionType.TRUTHINESS in types

    def test_assertj_is_null_wrapped(self, info):
        types = self._get_types(
            info, "isNull", [TestingFramework.ASSERTJ], is_wrapped=True
        )
        assert AssertionType.NULLNESS in types

    def test_assertj_has_size_wrapped(self, info):
        types = self._get_types(
            info, "hasSize", [TestingFramework.ASSERTJ], is_wrapped=True
        )
        assert set(types) == {AssertionType.COLLECTION, AssertionType.STRING}

    def test_assertj_thrown_by_wrapper(self, info):
        types = self._get_types(info, "assertThatThrownBy", [TestingFramework.ASSERTJ])
        assert types == [AssertionType.WRAPPER]

    # -- Hamcrest wrapped assertions ----------------------------------------

    def test_hamcrest_assert_that_is_wrapper(self, info):
        types = self._get_types(info, "assertThat", [TestingFramework.HAMCREST])
        assert AssertionType.WRAPPER in types

    def test_hamcrest_equal_to_wrapped(self, info):
        types = self._get_types(
            info, "equalTo", [TestingFramework.HAMCREST], is_wrapped=True
        )
        assert set(types) == {
            AssertionType.COLLECTION,
            AssertionType.EQUALITY,
            AssertionType.STRING,
        }

    # -- Google Truth -------------------------------------------------------

    def test_google_truth_assert_that_wrapper(self, info):
        types = self._get_types(info, "assertThat", [TestingFramework.GOOGLE_TRUTH])
        assert AssertionType.WRAPPER in types

    def test_google_truth_is_equal_to_wrapped(self, info):
        types = self._get_types(
            info, "isEqualTo", [TestingFramework.GOOGLE_TRUTH], is_wrapped=True
        )
        assert set(types) == {AssertionType.EQUALITY, AssertionType.STRING}

    # -- Unrecognized method produces empty categories ----------------------

    def test_unknown_method_no_categories(self, info):
        types = self._get_types(info, "someRandomMethod", [TestingFramework.JUNIT5])
        assert len(types) == 0

    # -- Java assert statement auto-registers JAVA_BUILTIN ------------------

    def test_java_assert_statement(self, info):
        types = self._get_types(info, "<<ASSERT_STATEMENT>>", [])
        assert AssertionType.TRUTHINESS in types

    # -- __pick_category conflict resolution --------------------------------

    def test_pick_category_assert_equals_numeric_tolerance(self, info):
        """assertEquals with >2 args should be NUMERIC_TOLERANCE."""
        node = MethodNode(
            method_name="assertEquals",
            argument_types=[
                ParameterType.NUMBER,
                ParameterType.NUMBER,
                ParameterType.NUMBER,
            ],
        )
        result = self._pick(info, node, [TestingFramework.JUNIT5])
        assert result == [AssertionType.NUMERIC_TOLERANCE]

    def test_pick_category_assert_equals_string_arg(self, info):
        """assertEquals with STRING arguments should resolve to STRING."""
        node = MethodNode(
            method_name="assertEquals",
            argument_types=[ParameterType.STRING, ParameterType.STRING],
        )
        result = self._pick(info, node, [TestingFramework.JUNIT5])
        assert AssertionType.STRING in result

    def test_pick_category_assert_equals_collection_arg(self, info):
        """assertEquals with COLLECTION arguments should resolve to COLLECTION."""
        node = MethodNode(
            method_name="assertEquals",
            argument_types=[ParameterType.COLLECTION, ParameterType.COLLECTION],
        )
        result = self._pick(info, node, [TestingFramework.JUNIT5])
        assert AssertionType.COLLECTION in result

    def test_pick_category_assert_equals_unknown_args(self, info):
        """assertEquals with all UNKNOWN args should return ambiguous set."""
        node = MethodNode(
            method_name="assertEquals",
            argument_types=[ParameterType.UNKNOWN, ParameterType.UNKNOWN],
        )
        result = self._pick(info, node, [TestingFramework.JUNIT5])
        assert AssertionType.STRING in result
        assert AssertionType.COLLECTION in result
        assert AssertionType.EQUALITY in result

    def test_pick_category_assert_equals_custom_args(self, info):
        """assertEquals with CUSTOM type args should resolve to plain EQUALITY."""
        node = MethodNode(
            method_name="assertEquals",
            argument_types=[ParameterType.CUSTOM, ParameterType.CUSTOM],
        )
        result = self._pick(info, node, [TestingFramework.JUNIT5])
        assert result == [AssertionType.EQUALITY]

    def test_pick_category_contains_wrapped_string(self, info):
        """contains() wrapped with STRING subject should be STRING."""
        node = MethodNode(
            method_name="contains",
            argument_types=[ParameterType.STRING],
        )
        params = CategorizationParams(
            assert_param_type=ParameterType.STRING,
            has_parent_assertion=True,
            is_wrapped=True,
        )
        result = self._pick(info, node, [TestingFramework.ASSERTJ], params)
        assert AssertionType.STRING in result

    def test_pick_category_contains_wrapped_collection(self, info):
        """contains() wrapped with COLLECTION subject should be COLLECTION."""
        node = MethodNode(
            method_name="contains",
            argument_types=[ParameterType.CUSTOM],
        )
        params = CategorizationParams(
            assert_param_type=ParameterType.COLLECTION,
            has_parent_assertion=True,
            is_wrapped=True,
        )
        result = self._pick(info, node, [TestingFramework.ASSERTJ], params)
        assert AssertionType.COLLECTION in result

    def test_pick_category_is_equal_to_wrapped_collection_subject(self, info):
        """isEqualTo wrapped with COLLECTION assertThat subject should be COLLECTION."""
        node = MethodNode(
            method_name="isEqualTo",
            argument_types=[ParameterType.UNKNOWN],
        )
        params = CategorizationParams(
            assert_param_type=ParameterType.COLLECTION,
            has_parent_assertion=True,
            is_wrapped=True,
        )
        result = self._pick(info, node, [TestingFramework.ASSERTJ], params)
        assert AssertionType.COLLECTION in result

    def test_pick_category_is_equal_to_wrapped_string_subject(self, info):
        """isEqualTo wrapped with STRING assertThat subject should be STRING."""
        node = MethodNode(
            method_name="isEqualTo",
            argument_types=[ParameterType.UNKNOWN],
        )
        params = CategorizationParams(
            assert_param_type=ParameterType.STRING,
            has_parent_assertion=True,
            is_wrapped=True,
        )
        result = self._pick(info, node, [TestingFramework.ASSERTJ], params)
        assert AssertionType.STRING in result

    def test_pick_category_has_size_no_args_ambiguous(self, info):
        """hasSize() with no args and no wrapping context returns both STRING and COLLECTION."""
        node = MethodNode(method_name="hasSize", argument_types=[])
        params = CategorizationParams(is_wrapped=True)
        result = self._pick(info, node, [TestingFramework.ASSERTJ], params)
        assert set(result) == {AssertionType.STRING, AssertionType.COLLECTION}

    # -- Multiple framework interactions ------------------------------------

    def test_mixed_junit5_assertj(self, info):
        """When both JUnit5 and AssertJ are present, assertThat should be WRAPPER."""
        types = self._get_types(
            info,
            "assertThat",
            [TestingFramework.JUNIT5, TestingFramework.ASSERTJ],
        )
        assert AssertionType.WRAPPER in types

    def test_mixed_junit5_hamcrest(self, info):
        """JUnit4 assertThat with Hamcrest should be WRAPPER."""
        types = self._get_types(
            info,
            "assertThat",
            [TestingFramework.JUNIT4, TestingFramework.HAMCREST],
        )
        assert AssertionType.WRAPPER in types


# ===========================================================================
# PART 5: Sequence building edge cases
# ===========================================================================


class TestSequenceBuildingEdgeCases:
    """Test edge cases in the sequence building logic using mocked CLDK analysis."""

    def test_visited_set_prevents_infinite_recursion(self, petclinic_data):
        """Calling with a method already in visited set returns empty list."""
        info = CallAndAssertionSequenceDetailsInfo(
            petclinic_data.analysis, petclinic_data.dataset_name
        )
        visited: Set[Tuple[str, str]] = {("some.Class", "someMethod()")}
        result = info.get_call_and_assertion_sequence_details_info(
            qualified_class_name="some.Class",
            method_signature="someMethod()",
            testing_frameworks=[TestingFramework.JUNIT5],
            visited=visited,
        )
        assert result == []

    def test_depth_zero_returns_empty(self, petclinic_data):
        """depth=0 should prevent processing and return empty."""
        info = CallAndAssertionSequenceDetailsInfo(
            petclinic_data.analysis, petclinic_data.dataset_name
        )
        result = info.get_call_and_assertion_sequence_details_info(
            qualified_class_name="org.springframework.samples.petclinic.vet.VetTests",
            method_signature="testSerialization()",
            testing_frameworks=[TestingFramework.JUNIT5],
            depth=0,
        )
        assert result == []

    def test_nonexistent_method_returns_empty(self, petclinic_data):
        """A non-existent method should return empty list, not crash."""
        info = CallAndAssertionSequenceDetailsInfo(
            petclinic_data.analysis, petclinic_data.dataset_name
        )
        result = info.get_call_and_assertion_sequence_details_info(
            qualified_class_name="org.springframework.samples.petclinic.vet.VetTests",
            method_signature="nonExistentMethod()",
            testing_frameworks=[TestingFramework.JUNIT5],
        )
        assert result == []

    def test_nonexistent_class_returns_empty(self, petclinic_data):
        """A non-existent class should return empty list, not crash."""
        info = CallAndAssertionSequenceDetailsInfo(
            petclinic_data.analysis, petclinic_data.dataset_name
        )
        result = info.get_call_and_assertion_sequence_details_info(
            qualified_class_name="com.nonexistent.FakeClass",
            method_signature="someMethod()",
            testing_frameworks=[TestingFramework.JUNIT5],
        )
        assert result == []


# ===========================================================================
# PART 6: Numeric tolerance resolution
# ===========================================================================


class TestNumericToleranceResolution:
    """Test the numeric tolerance disambiguation for assertEquals."""

    @pytest.fixture()
    def info(self, petclinic_data):
        return CallAndAssertionSequenceDetailsInfo(
            petclinic_data.analysis, petclinic_data.dataset_name
        )

    def _is_numeric(self, info, method_name, arg_types, frameworks):
        return info._CallAndAssertionSequenceDetailsInfo__is_numeric_tolerance(
            method_name, arg_types, frameworks
        )

    def test_two_args_not_numeric(self, info):
        assert not self._is_numeric(
            info,
            "assertEquals",
            [ParameterType.NUMBER, ParameterType.NUMBER],
            [TestingFramework.JUNIT5],
        )

    def test_three_args_is_numeric(self, info):
        assert self._is_numeric(
            info,
            "assertEquals",
            [ParameterType.NUMBER, ParameterType.NUMBER, ParameterType.NUMBER],
            [TestingFramework.JUNIT5],
        )

    def test_assert_not_equals_three_args(self, info):
        assert self._is_numeric(
            info,
            "assertNotEquals",
            [ParameterType.NUMBER, ParameterType.NUMBER, ParameterType.NUMBER],
            [TestingFramework.JUNIT5],
        )

    def test_non_assert_equals_method(self, info):
        assert not self._is_numeric(
            info,
            "assertNull",
            [ParameterType.NUMBER, ParameterType.NUMBER, ParameterType.NUMBER],
            [TestingFramework.JUNIT5],
        )

    def test_testng_three_args(self, info):
        assert self._is_numeric(
            info,
            "assertEquals",
            [ParameterType.NUMBER, ParameterType.NUMBER, ParameterType.NUMBER],
            [TestingFramework.TESTNG],
        )

    def test_junit3_three_args(self, info):
        assert self._is_numeric(
            info,
            "assertEquals",
            [ParameterType.NUMBER, ParameterType.NUMBER, ParameterType.NUMBER],
            [TestingFramework.JUNIT3],
        )

    def test_no_framework_not_numeric(self, info):
        assert not self._is_numeric(
            info,
            "assertEquals",
            [ParameterType.NUMBER, ParameterType.NUMBER, ParameterType.NUMBER],
            [],
        )


# ===========================================================================
# PART 7: Optional string removal for assertEquals
# ===========================================================================


class TestRemoveOptionalString:
    """Test __remove_optional_string for assertEquals with optional message args."""

    @pytest.fixture()
    def info(self, petclinic_data):
        return CallAndAssertionSequenceDetailsInfo(
            petclinic_data.analysis, petclinic_data.dataset_name
        )

    def _remove(self, info, node, frameworks):
        return info._CallAndAssertionSequenceDetailsInfo__remove_optional_string(
            node, frameworks
        )

    def test_junit34_first_arg_string_stripped(self, info):
        """JUnit3/4 assertEquals with first arg STRING should strip it."""
        node = MethodNode(
            method_name="assertEquals",
            argument_types=[
                ParameterType.STRING,
                ParameterType.NUMBER,
                ParameterType.NUMBER,
            ],
        )
        result = self._remove(info, node, [TestingFramework.JUNIT3])
        assert result == [ParameterType.NUMBER, ParameterType.NUMBER]

    def test_junit5_third_arg_string_stripped(self, info):
        """JUnit5 assertEquals with third arg STRING should truncate."""
        node = MethodNode(
            method_name="assertEquals",
            argument_types=[
                ParameterType.NUMBER,
                ParameterType.NUMBER,
                ParameterType.STRING,
            ],
        )
        result = self._remove(info, node, [TestingFramework.JUNIT5])
        assert result == [ParameterType.NUMBER, ParameterType.NUMBER]

    def test_junit5_fourth_arg_string_with_tolerance(self, info):
        """JUnit5 assertEquals with 4 args where 4th is STRING should truncate to 3."""
        node = MethodNode(
            method_name="assertEquals",
            argument_types=[
                ParameterType.NUMBER,
                ParameterType.NUMBER,
                ParameterType.NUMBER,
                ParameterType.STRING,
            ],
        )
        result = self._remove(info, node, [TestingFramework.JUNIT5])
        assert result == [
            ParameterType.NUMBER,
            ParameterType.NUMBER,
            ParameterType.NUMBER,
        ]

    def test_no_optional_string_unchanged(self, info):
        """If no optional string argument, types are returned unchanged."""
        node = MethodNode(
            method_name="assertEquals",
            argument_types=[ParameterType.NUMBER, ParameterType.NUMBER],
        )
        result = self._remove(info, node, [TestingFramework.JUNIT5])
        assert result == [ParameterType.NUMBER, ParameterType.NUMBER]

    def test_non_assert_equals_unchanged(self, info):
        """Non-assertEquals methods are returned unchanged."""
        node = MethodNode(
            method_name="assertTrue",
            argument_types=[ParameterType.BOOLEAN],
        )
        result = self._remove(info, node, [TestingFramework.JUNIT5])
        assert result == [ParameterType.BOOLEAN]


# ===========================================================================
# PART 8: Builtin assertion complement detection
# ===========================================================================


class TestBuiltinDetection:
    """Test __is_builtin for recognizing Java built-in complementary methods."""

    @pytest.fixture()
    def info(self, petclinic_data):
        return CallAndAssertionSequenceDetailsInfo(
            petclinic_data.analysis, petclinic_data.dataset_name
        )

    def _is_builtin(self, info, name):
        return info._CallAndAssertionSequenceDetailsInfo__is_builtin(name)

    def test_equals_is_builtin(self, info):
        assert self._is_builtin(info, "equals")

    def test_contains_is_builtin(self, info):
        assert self._is_builtin(info, "contains")

    def test_is_empty_is_builtin(self, info):
        assert self._is_builtin(info, "isEmpty")

    def test_size_is_builtin(self, info):
        assert self._is_builtin(info, "size")

    def test_starts_with_is_builtin(self, info):
        assert self._is_builtin(info, "startsWith")

    def test_random_method_not_builtin(self, info):
        assert not self._is_builtin(info, "someRandomMethod")

    def test_assert_true_not_builtin(self, info):
        assert not self._is_builtin(info, "assertTrue")

    def test_is_present_is_builtin(self, info):
        assert self._is_builtin(info, "isPresent")

    def test_get_is_builtin(self, info):
        assert self._is_builtin(info, "get")


# ===========================================================================
# PART 9: Parameter type resolution
# ===========================================================================


class TestParameterTypeResolution:
    """Test __get_param_type_from_tree and __get_param_type_from_raw."""

    @pytest.fixture()
    def info(self, petclinic_data):
        return CallAndAssertionSequenceDetailsInfo(
            petclinic_data.analysis, petclinic_data.dataset_name
        )

    def _from_tree(self, info, tree_type):
        return info._CallAndAssertionSequenceDetailsInfo__get_param_type_from_tree(
            tree_type
        )

    def _from_raw(self, info, raw_type):
        return info._CallAndAssertionSequenceDetailsInfo__get_param_type_from_raw(
            raw_type
        )

    def test_string_literal_tree(self, info):
        assert self._from_tree(info, "string_literal") == ParameterType.STRING

    def test_decimal_integer_literal_tree(self, info):
        assert self._from_tree(info, "decimal_integer_literal") == ParameterType.NUMBER

    def test_boolean_type_tree(self, info):
        assert self._from_tree(info, "boolean_type") == ParameterType.BOOLEAN

    def test_lambda_expression_tree(self, info):
        assert (
            self._from_tree(info, "lambda_expression")
            == ParameterType.LAMBDA_EXPRESSION
        )

    def test_unknown_tree_type(self, info):
        assert self._from_tree(info, "some_unknown_type") == ParameterType.UNKNOWN

    def test_raw_string(self, info):
        result = self._from_raw(info, "String")
        assert result == ParameterType.STRING

    def test_raw_int(self, info):
        result = self._from_raw(info, "int")
        assert result == ParameterType.NUMBER

    def test_raw_boolean(self, info):
        result = self._from_raw(info, "boolean")
        assert result == ParameterType.BOOLEAN

    def test_raw_list_generic(self, info):
        result = self._from_raw(info, "List<String>")
        assert result == ParameterType.COLLECTION

    def test_raw_array(self, info):
        result = self._from_raw(info, "String[]")
        assert result == ParameterType.COLLECTION

    def test_raw_class_literal(self, info):
        result = self._from_raw(info, "Foo.class")
        assert result == ParameterType.CLASS_LITERAL

    def test_raw_empty_string(self, info):
        result = self._from_raw(info, "")
        assert result is None

    def test_raw_none(self, info):
        result = self._from_raw(info, None)
        assert result is None


# ===========================================================================
# PART 10: Test utility helper integration
# ===========================================================================


class TestTestUtilityHelperIntegration:
    """Moved from test_call_assert.py -- tests for helper method lookup in test utility classes."""

    def test_call_assertion_sequence_with_test_utility_helpers(self, commons_bsf_data):
        """
        Test that call/assertion sequences correctly handle helper methods from test utility classes.

        This test verifies the fix for the bug where helper methods from test utility classes
        (like TestBean.getStringValue()) were being looked up in the wrong class (the test class
        instead of the utility class).
        """
        call_and_assertion_info = CallAndAssertionSequenceDetailsInfo(
            commons_bsf_data.analysis, commons_bsf_data.dataset_name
        )

        qualified_class_name = "org.apache.bsf.util.EngineUtilsTest"
        method_signature = "testCallBeanMethod()"

        testing_frameworks = CommonAnalysis(
            commons_bsf_data.analysis
        ).get_testing_frameworks_for_class(qualified_class_name=qualified_class_name)

        # Verify TestBean is identified as a test utility class
        assert "org.apache.bsf.util.TestBean" in commons_bsf_data.test_utility_classes

        result = call_and_assertion_info.get_call_and_assertion_sequence_details_info(
            qualified_class_name=qualified_class_name,
            method_signature=method_signature,
            testing_frameworks=testing_frameworks,
            test_utility_classes=commons_bsf_data.test_utility_classes,
        )

        assert result is not None
        assert len(result) == 7

        # Verify helper-marked calls appear in sequences
        helper_calls = [
            c
            for s in result
            for c in s.call_sequence_details
            if c.is_helper is True
        ]
        helper_names = {c.method_name for c in helper_calls}
        assert "getStringValue" in helper_names
        assert "getNumericValue" in helper_names

    def test_helper_method_class_identification(self, commons_bsf_data):
        """
        Verify that helper methods are correctly identified with their proper class names.

        When a test method calls a helper from a test utility class,
        the helper method lookup should use the correct class (the utility class, not the test class).
        """
        reachability = Reachability(commons_bsf_data.analysis)

        qualified_class_name = "org.apache.bsf.util.EngineUtilsTest"
        method_signature = "testCallBeanMethod()"

        helper_methods = reachability.get_helper_methods(
            qualified_class_name=qualified_class_name,
            method_signature=method_signature,
            depth=1,
            add_extended_class=True,
            allow_repetition=False,
            test_utility_classes=commons_bsf_data.test_utility_classes,
        )

        assert "org.apache.bsf.util.TestBean" in helper_methods
        testbean_helpers = helper_methods["org.apache.bsf.util.TestBean"]
        assert "getStringValue()" in testbean_helpers or any(
            "getStringValue" in h for h in testbean_helpers
        )


# ===========================================================================
# PART 11: Cross-resource consistency
# ===========================================================================


class TestCrossResourceConsistency:
    """Verify structural consistency across different resource projects."""

    def _validate_sequences(self, seqs, qcn, sig):
        """Validate structural invariants across all sequences."""
        for i, seq in enumerate(seqs):
            # Every sequence should have at least calls or assertions
            assert (
                len(seq.call_sequence_details) > 0
                or len(seq.assertion_details) > 0
            ), f"Empty sequence in {qcn}::{sig}"

            # Each callable should have a method name
            for cd in seq.call_sequence_details:
                assert cd.method_name, f"Empty method_name in {qcn}::{sig}"

            # Whether this or the preceding sequence contains a WRAPPER
            has_wrapper_here = any(
                AssertionType.WRAPPER in a.assertion_type
                for a in seq.assertion_details
            )
            prev_has_wrapper = i > 0 and any(
                AssertionType.WRAPPER in a.assertion_type
                for a in seqs[i - 1].assertion_details
            )

            for ad in seq.assertion_details:
                # Each assertion should have a name and non-empty type
                assert ad.assertion_name, (
                    f"Empty assertion_name in {qcn}::{sig}"
                )
                assert len(ad.assertion_type) >= 1, (
                    f"Empty assertion_type in {qcn}::{sig}"
                )

                # Wrapped assertions must appear in a sequence that contains
                # a WRAPPER or immediately follows one (sequence splitting)
                if ad.is_wrapped:
                    assert has_wrapper_here or prev_has_wrapper, (
                        f"is_wrapped=True without WRAPPER in current or "
                        f"preceding sequence in {qcn}::{sig} seq{i}"
                    )

                # WRAPPER-typed assertions should not be marked as wrapped themselves
                if ad.assertion_type == [AssertionType.WRAPPER]:
                    assert ad.is_wrapped is False, (
                        f"WRAPPER assertion has is_wrapped=True in {qcn}::{sig}"
                    )

    def test_petclinic_sequences_have_valid_structure(self, petclinic_data):
        """Every sequence in petclinic should have valid call/assertion details."""
        info = CallAndAssertionSequenceDetailsInfo(
            petclinic_data.analysis, petclinic_data.dataset_name
        )
        for qcn in petclinic_data.test_class_methods:
            frameworks = CommonAnalysis(
                petclinic_data.analysis
            ).get_testing_frameworks_for_class(qualified_class_name=qcn)
            for sig in petclinic_data.test_class_methods[qcn]:
                seqs = info.get_call_and_assertion_sequence_details_info(
                    qualified_class_name=qcn,
                    method_signature=sig,
                    testing_frameworks=frameworks,
                )
                self._validate_sequences(seqs, qcn, sig)

    def test_bsf_sequences_have_valid_structure(self, commons_bsf_data):
        """Every sequence in commons-bsf should have valid structure."""
        info = CallAndAssertionSequenceDetailsInfo(
            commons_bsf_data.analysis, commons_bsf_data.dataset_name
        )
        for qcn in commons_bsf_data.test_class_methods:
            frameworks = CommonAnalysis(
                commons_bsf_data.analysis
            ).get_testing_frameworks_for_class(qualified_class_name=qcn)
            for sig in commons_bsf_data.test_class_methods[qcn]:
                seqs = info.get_call_and_assertion_sequence_details_info(
                    qualified_class_name=qcn,
                    method_signature=sig,
                    testing_frameworks=frameworks,
                    test_utility_classes=commons_bsf_data.test_utility_classes,
                )
                self._validate_sequences(seqs, qcn, sig)
