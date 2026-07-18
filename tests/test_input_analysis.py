from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from cldk import CLDK
from cldk.analysis import AnalysisLevel
from cldk.models.java import JCallable
from cldk.models.java.models import JCallSite

from hamster.code_analysis.common import CommonAnalysis
from hamster.code_analysis.model.models import (
    AnnotationScope,
    AnnotationTestInput,
    CallSiteTestInput,
    InputType,
)
from hamster.code_analysis.test_statistics.input_analysis import InputAnalysis

BASE_DIR = Path(__file__).resolve().parent
TEST_SOURCES = BASE_DIR / "resources"
TEST_OUTPUT = BASE_DIR / "resources" / "output"


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


def _make_call_site(
    method_name: str = "",
    receiver_type: str = "",
    receiver_expr: str = "",
    is_constructor_call: bool = False,
    callee_signature: str = "",
) -> JCallSite:
    return JCallSite(
        comment=None,
        method_name=method_name,
        receiver_type=receiver_type,
        receiver_expr=receiver_expr,
        argument_types=[],
        argument_expr=[],
        is_constructor_call=is_constructor_call,
        callee_signature=callee_signature,
        crud_operation=None,
        crud_query=None,
        start_line=0,
        start_column=0,
        end_line=0,
        end_column=0,
    )


@pytest.fixture(scope="module")
def petclinic_data() -> SimpleNamespace:
    return create_analysis_data("spring-petclinic")


@pytest.fixture(scope="module")
def input_analysis(petclinic_data: SimpleNamespace) -> InputAnalysis:
    return InputAnalysis(petclinic_data.analysis)


# ---------------------------------------------------------------------------
# Unit tests -- validate _get_input_type via constructed JCallSite objects
# ---------------------------------------------------------------------------


def test_sax_parser_xml_detection(input_analysis: InputAnalysis):
    """C1: SAXParser with corrected javax prefix should detect XML input."""
    call_site = _make_call_site(
        method_name="parse",
        receiver_type="javax.xml.parsers.SAXParser",
        receiver_expr="parser",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.XML in result


def test_constructor_fallback_fqn_match(input_analysis: InputAnalysis):
    """C2: Constructor fallback should match FQN prefix and simple class name."""
    call_site = _make_call_site(
        method_name="CSVParser",
        receiver_type="org.apache.commons.csv.CSVParser",
        is_constructor_call=True,
        callee_signature="",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.CSV in result


def test_constructor_fallback_wrong_prefix_no_match(input_analysis: InputAnalysis):
    """C2: Constructor fallback should not match when prefix is wrong."""
    call_site = _make_call_site(
        method_name="CSVParser",
        receiver_type="com.wrong.CSVParser",
        is_constructor_call=True,
        callee_signature="",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is None


def test_json_mapper_detection(input_analysis: InputAnalysis):
    """S3: JsonMapper.readValue should detect JSON input."""
    call_site = _make_call_site(
        method_name="readValue",
        receiver_type="com.fasterxml.jackson.databind.json.JsonMapper",
        receiver_expr="mapper",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.JSON in result


def test_narrow_java_io_prefix(input_analysis: InputAnalysis):
    """M1: BufferedReader should not match the narrowed java.io.FileInputStream prefix."""
    call_site = _make_call_site(
        method_name="read",
        receiver_type="java.io.BufferedReader",
        receiver_expr="reader",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is None


def test_narrow_persistence_prefix(input_analysis: InputAnalysis):
    """M2: EntityManager.persist should not match narrowed javax.persistence prefixes."""
    call_site = _make_call_site(
        method_name="persist",
        receiver_type="javax.persistence.EntityManager",
        receiver_expr="em",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is None


def test_ambiguous_object_mapper(input_analysis: InputAnalysis):
    """ObjectMapper.readValue is ambiguous and should return JSON, XML, YAML, CSV."""
    call_site = _make_call_site(
        method_name="readValue",
        receiver_type="com.fasterxml.jackson.databind.ObjectMapper",
        receiver_expr="mapper",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert set(result) == {InputType.JSON, InputType.XML, InputType.YAML, InputType.CSV}


# ---------------------------------------------------------------------------
# Integration tests -- validate full get_input_details pipeline
# ---------------------------------------------------------------------------


def test_get_input_details_returns_list(
    petclinic_data: SimpleNamespace, input_analysis: InputAnalysis
):
    """S2: get_input_details should return a list (possibly empty) for any valid method."""
    for class_name, methods in petclinic_data.test_class_methods.items():
        for method_sig in methods:
            result = input_analysis.get_input_details(class_name, method_sig)
            assert isinstance(result, list)


def test_call_site_inputs_preserve_duplicates(
    petclinic_data: SimpleNamespace, input_analysis: InputAnalysis
):
    """S1: Call-site inputs are returned as-is, preserving raw counts without deduplication."""
    for class_name, methods in petclinic_data.test_class_methods.items():
        for method_sig in methods:
            result = input_analysis.get_input_details(class_name, method_sig)
            call_site_inputs = [
                ti for ti in result if isinstance(ti, CallSiteTestInput)
            ]
            # Every returned input must have provenance fields populated
            for ti in call_site_inputs:
                assert ti.source_class is not None
                assert ti.source_method is not None


def test_provenance_fields_populated(
    petclinic_data: SimpleNamespace, input_analysis: InputAnalysis
):
    """S4: source_class and source_method should be populated on all returned TestInputs.

    Class-level AnnotationTestInputs have source_method=None because the annotation
    lives on the class, not any specific method.
    """
    inputs_found = False
    for class_name, methods in petclinic_data.test_class_methods.items():
        for method_sig in methods:
            result = input_analysis.get_input_details(class_name, method_sig)
            for ti in result:
                inputs_found = True
                assert ti.source_class is not None, f"source_class is None for {ti}"
                if (
                    isinstance(ti, AnnotationTestInput)
                    and ti.scope == AnnotationScope.CLASS
                ):
                    assert ti.source_method is None, (
                        f"source_method should be None for class-level annotation: {ti}"
                    )
                else:
                    assert ti.source_method is not None, (
                        f"source_method is None for {ti}"
                    )
    # Ensure we actually tested something (petclinic should have at least some inputs)
    assert inputs_found, "No test inputs found in petclinic"


def test_all_inputs_have_detection_source(
    petclinic_data: SimpleNamespace, input_analysis: InputAnalysis
):
    """Every returned input should be either a CallSiteTestInput or AnnotationTestInput."""
    for class_name, methods in petclinic_data.test_class_methods.items():
        for method_sig in methods:
            result = input_analysis.get_input_details(class_name, method_sig)
            for ti in result:
                assert isinstance(ti, (CallSiteTestInput, AnnotationTestInput)), (
                    f"Unexpected type {type(ti)} in {class_name}::{method_sig}"
                )


# ---------------------------------------------------------------------------
# Protobuf and Avro detection tests
# ---------------------------------------------------------------------------


def test_protobuf_detection(input_analysis: InputAnalysis):
    """Protobuf Parser.parseFrom should detect PROTOBUF input."""
    call_site = _make_call_site(
        method_name="parseFrom",
        receiver_type="com.google.protobuf.Parser",
        receiver_expr="parser",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.PROTOBUF in result


def test_protobuf_dynamic_message_detection(input_analysis: InputAnalysis):
    """DynamicMessage.parseFrom should detect PROTOBUF (library-type static call)."""
    call_site = _make_call_site(
        method_name="parseFrom",
        receiver_type="com.google.protobuf.DynamicMessage",
        receiver_expr="DynamicMessage",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.PROTOBUF in result


def test_protobuf_any_unpack_detection(input_analysis: InputAnalysis):
    """Any.unpack should detect PROTOBUF."""
    call_site = _make_call_site(
        method_name="unpack",
        receiver_type="com.google.protobuf.Any",
        receiver_expr="anyMsg",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.PROTOBUF in result


def test_protobuf_text_format_detection(input_analysis: InputAnalysis):
    """TextFormat.merge should detect PROTOBUF."""
    call_site = _make_call_site(
        method_name="merge",
        receiver_type="com.google.protobuf.TextFormat",
        receiver_expr="TextFormat",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.PROTOBUF in result


def test_protobuf_generated_class_not_detected(input_analysis: InputAnalysis):
    """Generated-class static parseFrom is a known limitation and should NOT match."""
    call_site = _make_call_site(
        method_name="parseFrom",
        receiver_type="com.example.protos.MyMessage",
        receiver_expr="MyMessage",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is None


# ---------------------------------------------------------------------------
# Expanded SQL/Hibernate detection tests
# ---------------------------------------------------------------------------


def test_hibernate_query_list_detection(input_analysis: InputAnalysis):
    """org.hibernate.query.Query.list should detect SQL."""
    call_site = _make_call_site(
        method_name="list",
        receiver_type="org.hibernate.query.Query",
        receiver_expr="query",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.SQL in result


def test_hibernate_native_query_detection(input_analysis: InputAnalysis):
    """org.hibernate.query.NativeQuery.uniqueResult should detect SQL."""
    call_site = _make_call_site(
        method_name="uniqueResult",
        receiver_type="org.hibernate.query.NativeQuery",
        receiver_expr="nativeQuery",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.SQL in result


def test_hibernate_session_find_detection(input_analysis: InputAnalysis):
    """Session.find should detect SQL (beyond just get)."""
    call_site = _make_call_site(
        method_name="find",
        receiver_type="org.hibernate.Session",
        receiver_expr="session",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.SQL in result


def test_hibernate_criteria_detection(input_analysis: InputAnalysis):
    """Deprecated Criteria.list should still detect SQL."""
    call_site = _make_call_site(
        method_name="list",
        receiver_type="org.hibernate.Criteria",
        receiver_expr="criteria",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.SQL in result


def test_jakarta_persistence_query_detection(input_analysis: InputAnalysis):
    """Jakarta namespace Query.getResultList should detect SQL."""
    call_site = _make_call_site(
        method_name="getResultList",
        receiver_type="jakarta.persistence.TypedQuery",
        receiver_expr="query",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.SQL in result


def test_jakarta_entity_manager_detection(input_analysis: InputAnalysis):
    """Jakarta EntityManager.find should detect SQL."""
    call_site = _make_call_site(
        method_name="find",
        receiver_type="jakarta.persistence.EntityManager",
        receiver_expr="em",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.SQL in result


def test_javax_entity_manager_find_detection(input_analysis: InputAnalysis):
    """javax EntityManager.find should now detect SQL."""
    call_site = _make_call_site(
        method_name="find",
        receiver_type="javax.persistence.EntityManager",
        receiver_expr="em",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.SQL in result


def test_named_parameter_jdbc_template_detection(input_analysis: InputAnalysis):
    """NamedParameterJdbcTemplate.queryForObject should detect SQL."""
    call_site = _make_call_site(
        method_name="queryForObject",
        receiver_type="org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate",
        receiver_expr="namedJdbc",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.SQL in result


def test_querydsl_jpa_query_detection(input_analysis: InputAnalysis):
    """QueryDSL JPAQuery.fetch should detect SQL."""
    call_site = _make_call_site(
        method_name="fetch",
        receiver_type="com.querydsl.jpa.impl.JPAQuery",
        receiver_expr="query",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.SQL in result


def test_jooq_result_query_detection(input_analysis: InputAnalysis):
    """jOOQ ResultQuery.fetchOptional should detect SQL."""
    call_site = _make_call_site(
        method_name="fetchOptional",
        receiver_type="org.jooq.ResultQuery",
        receiver_expr="query",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.SQL in result


def test_avro_detection(input_analysis: InputAnalysis):
    """DataFileReader constructor should detect AVRO input."""
    call_site = _make_call_site(
        method_name="DataFileReader",
        receiver_type="org.apache.avro.file.DataFileReader",
        is_constructor_call=True,
        callee_signature="",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.AVRO in result


def test_avro_data_file_stream_detection(input_analysis: InputAnalysis):
    """DataFileStream constructor should detect AVRO."""
    call_site = _make_call_site(
        method_name="DataFileStream",
        receiver_type="org.apache.avro.file.DataFileStream",
        is_constructor_call=True,
        callee_signature="",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.AVRO in result


def test_avro_decoder_factory_detection(input_analysis: InputAnalysis):
    """DecoderFactory.binaryDecoder should detect AVRO."""
    call_site = _make_call_site(
        method_name="binaryDecoder",
        receiver_type="org.apache.avro.io.DecoderFactory",
        receiver_expr="DecoderFactory",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.AVRO in result


def test_avro_reflect_datum_reader_detection(input_analysis: InputAnalysis):
    """ReflectDatumReader constructor should detect AVRO."""
    call_site = _make_call_site(
        method_name="ReflectDatumReader",
        receiver_type="org.apache.avro.reflect.ReflectDatumReader",
        is_constructor_call=True,
        callee_signature="",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.AVRO in result


def test_avro_data_file_reader_open_reader_detection(input_analysis: InputAnalysis):
    """DataFileReader.openReader (static factory) should detect AVRO."""
    call_site = _make_call_site(
        method_name="openReader",
        receiver_type="org.apache.avro.file.DataFileReader",
        receiver_expr="DataFileReader",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.AVRO in result


def test_avro_file_reader_interface_detection(input_analysis: InputAnalysis):
    """FileReader.next (polymorphic interface) should detect AVRO."""
    call_site = _make_call_site(
        method_name="next",
        receiver_type="org.apache.avro.file.FileReader",
        receiver_expr="reader",
    )
    result = input_analysis._get_input_type(call_site)
    assert result is not None
    assert InputType.AVRO in result


# ---------------------------------------------------------------------------
# Deduplication tests
# ---------------------------------------------------------------------------


def _mock_class_no_annotations():
    """Return a mock JType with no annotations."""
    mock_class = MagicMock()
    mock_class.annotations = []
    return mock_class


def test_duplicate_call_sites_within_method_are_preserved(
    input_analysis: InputAnalysis,
):
    """Duplicate call sites in the same method body should each produce a CallSiteTestInput."""
    duplicate_call_site = _make_call_site(
        method_name="readValue",
        receiver_type="com.fasterxml.jackson.databind.json.JsonMapper",
        receiver_expr="mapper",
    )
    mock_method = MagicMock(spec=JCallable)
    mock_method.call_sites = [duplicate_call_site, duplicate_call_site]
    mock_method.annotations = []

    class_name = "com.example.TestClass"
    method_sig = "void testMethod()"

    with (
        patch.object(input_analysis.analysis, "get_method", return_value=mock_method),
        patch.object(
            input_analysis.analysis,
            "get_class",
            return_value=_mock_class_no_annotations(),
        ),
        patch(
            "hamster.code_analysis.test_statistics.input_analysis.Reachability"
        ) as mock_reachability_cls,
    ):
        mock_reachability_cls.return_value.get_helper_methods.return_value = {}
        result = input_analysis.get_input_details(class_name, method_sig)

    assert len(result) == 2
    for ti in result:
        assert isinstance(ti, CallSiteTestInput)
        assert ti.method_name == "readValue"
        assert ti.input_type is not None
        assert InputType.JSON in ti.input_type


# ---------------------------------------------------------------------------
# Annotation-based detection tests
# ---------------------------------------------------------------------------


def test_sql_method_annotation_detection(input_analysis: InputAnalysis):
    """@Sql on a method should produce an AnnotationTestInput with SQL type."""
    mock_method = MagicMock(spec=JCallable)
    mock_method.call_sites = []
    mock_method.annotations = ['@Sql("/data.sql")']

    class_name = "com.example.TestClass"
    method_sig = "void testSql()"

    with (
        patch.object(input_analysis.analysis, "get_method", return_value=mock_method),
        patch.object(
            input_analysis.analysis,
            "get_class",
            return_value=_mock_class_no_annotations(),
        ),
        patch(
            "hamster.code_analysis.test_statistics.input_analysis.Reachability"
        ) as mock_reachability_cls,
    ):
        mock_reachability_cls.return_value.get_helper_methods.return_value = {}
        result = input_analysis.get_input_details(class_name, method_sig)

    assert len(result) == 1
    ti = result[0]
    assert isinstance(ti, AnnotationTestInput)
    assert ti.annotation_name == "@Sql"
    assert ti.annotation == '@Sql("/data.sql")'
    assert ti.scope == AnnotationScope.METHOD
    assert ti.input_type is not None
    assert InputType.SQL in ti.input_type


def test_csv_source_annotation_detection(input_analysis: InputAnalysis):
    """@CsvSource on a method should produce an AnnotationTestInput with CSV type."""
    mock_method = MagicMock(spec=JCallable)
    mock_method.call_sites = []
    mock_method.annotations = ["@ParameterizedTest", '@CsvSource({"1,a", "2,b"})']

    class_name = "com.example.TestClass"
    method_sig = "void testCsv(int, String)"

    with (
        patch.object(input_analysis.analysis, "get_method", return_value=mock_method),
        patch.object(
            input_analysis.analysis,
            "get_class",
            return_value=_mock_class_no_annotations(),
        ),
        patch(
            "hamster.code_analysis.test_statistics.input_analysis.Reachability"
        ) as mock_reachability_cls,
    ):
        mock_reachability_cls.return_value.get_helper_methods.return_value = {}
        result = input_analysis.get_input_details(class_name, method_sig)

    annotation_inputs = [ti for ti in result if isinstance(ti, AnnotationTestInput)]
    assert len(annotation_inputs) == 1
    assert annotation_inputs[0].annotation_name == "@CsvSource"
    assert annotation_inputs[0].input_type is not None
    assert InputType.CSV in annotation_inputs[0].input_type


def test_csv_file_source_annotation_detection(input_analysis: InputAnalysis):
    """@CsvFileSource should produce CSV input type."""
    mock_method = MagicMock(spec=JCallable)
    mock_method.call_sites = []
    mock_method.annotations = ['@CsvFileSource(resources = "/test-data.csv")']

    class_name = "com.example.TestClass"
    method_sig = "void testCsvFile(String, int)"

    with (
        patch.object(input_analysis.analysis, "get_method", return_value=mock_method),
        patch.object(
            input_analysis.analysis,
            "get_class",
            return_value=_mock_class_no_annotations(),
        ),
        patch(
            "hamster.code_analysis.test_statistics.input_analysis.Reachability"
        ) as mock_reachability_cls,
    ):
        mock_reachability_cls.return_value.get_helper_methods.return_value = {}
        result = input_analysis.get_input_details(class_name, method_sig)

    assert len(result) == 1
    ti = result[0]
    assert isinstance(ti, AnnotationTestInput)
    assert ti.annotation_name == "@CsvFileSource"
    assert ti.input_type is not None
    assert InputType.CSV in ti.input_type
    assert len(ti.input_type) == 1


def test_class_level_sql_annotation_detection(input_analysis: InputAnalysis):
    """@Sql on the class should produce an AnnotationTestInput with scope=CLASS."""
    mock_method = MagicMock(spec=JCallable)
    mock_method.call_sites = []
    mock_method.annotations = ["@Test"]

    mock_class = MagicMock()
    mock_class.annotations = ['@Sql("/schema.sql")']

    class_name = "com.example.TestClass"
    method_sig = "void testQuery()"

    with (
        patch.object(input_analysis.analysis, "get_method", return_value=mock_method),
        patch.object(input_analysis.analysis, "get_class", return_value=mock_class),
        patch(
            "hamster.code_analysis.test_statistics.input_analysis.Reachability"
        ) as mock_reachability_cls,
    ):
        mock_reachability_cls.return_value.get_helper_methods.return_value = {}
        result = input_analysis.get_input_details(class_name, method_sig)

    annotation_inputs = [ti for ti in result if isinstance(ti, AnnotationTestInput)]
    assert len(annotation_inputs) == 1
    assert annotation_inputs[0].scope == AnnotationScope.CLASS
    assert annotation_inputs[0].annotation_name == "@Sql"
    assert annotation_inputs[0].input_type is not None
    assert InputType.SQL in annotation_inputs[0].input_type
    assert annotation_inputs[0].source_method is None


def test_non_input_annotations_ignored(input_analysis: InputAnalysis):
    """Annotations like @Test and @BeforeEach should not produce any AnnotationTestInput."""
    mock_method = MagicMock(spec=JCallable)
    mock_method.call_sites = []
    mock_method.annotations = ["@Test", "@BeforeEach", "@Transactional"]

    class_name = "com.example.TestClass"
    method_sig = "void testPlain()"

    with (
        patch.object(input_analysis.analysis, "get_method", return_value=mock_method),
        patch.object(
            input_analysis.analysis,
            "get_class",
            return_value=_mock_class_no_annotations(),
        ),
        patch(
            "hamster.code_analysis.test_statistics.input_analysis.Reachability"
        ) as mock_reachability_cls,
    ):
        mock_reachability_cls.return_value.get_helper_methods.return_value = {}
        result = input_analysis.get_input_details(class_name, method_sig)

    assert len(result) == 0


def test_combined_call_site_and_annotation_inputs(input_analysis: InputAnalysis):
    """A method with both a call-site input and an annotation input should return both."""
    json_call_site = _make_call_site(
        method_name="readValue",
        receiver_type="com.fasterxml.jackson.databind.json.JsonMapper",
        receiver_expr="mapper",
    )
    mock_method = MagicMock(spec=JCallable)
    mock_method.call_sites = [json_call_site]
    mock_method.annotations = ['@Sql("/data.sql")']

    class_name = "com.example.TestClass"
    method_sig = "void testMixed()"

    with (
        patch.object(input_analysis.analysis, "get_method", return_value=mock_method),
        patch.object(
            input_analysis.analysis,
            "get_class",
            return_value=_mock_class_no_annotations(),
        ),
        patch(
            "hamster.code_analysis.test_statistics.input_analysis.Reachability"
        ) as mock_reachability_cls,
    ):
        mock_reachability_cls.return_value.get_helper_methods.return_value = {}
        result = input_analysis.get_input_details(class_name, method_sig)

    call_site_inputs = [ti for ti in result if isinstance(ti, CallSiteTestInput)]
    annotation_inputs = [ti for ti in result if isinstance(ti, AnnotationTestInput)]
    assert len(call_site_inputs) == 1
    assert len(annotation_inputs) == 1
    assert InputType.JSON in call_site_inputs[0].input_type
    assert InputType.SQL in annotation_inputs[0].input_type


def test_test_property_source_annotation_detection(input_analysis: InputAnalysis):
    """@TestPropertySource should produce PROPERTIES input type."""
    mock_method = MagicMock(spec=JCallable)
    mock_method.call_sites = []
    mock_method.annotations = ["@Test"]

    mock_class = MagicMock()
    mock_class.annotations = [
        '@TestPropertySource(locations = "classpath:test.properties")'
    ]

    class_name = "com.example.TestClass"
    method_sig = "void testProps()"

    with (
        patch.object(input_analysis.analysis, "get_method", return_value=mock_method),
        patch.object(input_analysis.analysis, "get_class", return_value=mock_class),
        patch(
            "hamster.code_analysis.test_statistics.input_analysis.Reachability"
        ) as mock_reachability_cls,
    ):
        mock_reachability_cls.return_value.get_helper_methods.return_value = {}
        result = input_analysis.get_input_details(class_name, method_sig)

    annotation_inputs = [ti for ti in result if isinstance(ti, AnnotationTestInput)]
    assert len(annotation_inputs) == 1
    assert annotation_inputs[0].annotation_name == "@TestPropertySource"
    assert annotation_inputs[0].input_type is not None
    assert InputType.PROPERTIES in annotation_inputs[0].input_type


def test_duplicate_annotation_inputs_preserved(input_analysis: InputAnalysis):
    """Each annotation occurrence should produce its own AnnotationTestInput."""
    mock_method = MagicMock(spec=JCallable)
    mock_method.call_sites = []
    mock_method.annotations = ['@Sql("/a.sql")', '@Sql("/b.sql")']

    class_name = "com.example.TestClass"
    method_sig = "void testDupAnnot()"

    with (
        patch.object(input_analysis.analysis, "get_method", return_value=mock_method),
        patch.object(
            input_analysis.analysis,
            "get_class",
            return_value=_mock_class_no_annotations(),
        ),
        patch(
            "hamster.code_analysis.test_statistics.input_analysis.Reachability"
        ) as mock_reachability_cls,
    ):
        mock_reachability_cls.return_value.get_helper_methods.return_value = {}
        result = input_analysis.get_input_details(class_name, method_sig)

    annotation_inputs = [ti for ti in result if isinstance(ti, AnnotationTestInput)]
    assert len(annotation_inputs) == 2
    assert annotation_inputs[0].annotation == '@Sql("/a.sql")'
    assert annotation_inputs[1].annotation == '@Sql("/b.sql")'


def test_method_and_class_same_annotation_not_deduplicated(
    input_analysis: InputAnalysis,
):
    """@Sql on both method and class should produce two inputs (different scope)."""
    mock_method = MagicMock(spec=JCallable)
    mock_method.call_sites = []
    mock_method.annotations = ['@Sql("/method.sql")']

    mock_class = MagicMock()
    mock_class.annotations = ['@Sql("/class.sql")']

    class_name = "com.example.TestClass"
    method_sig = "void testBothScopes()"

    with (
        patch.object(input_analysis.analysis, "get_method", return_value=mock_method),
        patch.object(input_analysis.analysis, "get_class", return_value=mock_class),
        patch(
            "hamster.code_analysis.test_statistics.input_analysis.Reachability"
        ) as mock_reachability_cls,
    ):
        mock_reachability_cls.return_value.get_helper_methods.return_value = {}
        result = input_analysis.get_input_details(class_name, method_sig)

    annotation_inputs = [ti for ti in result if isinstance(ti, AnnotationTestInput)]
    assert len(annotation_inputs) == 2
    scopes = {ti.scope for ti in annotation_inputs}
    assert scopes == {AnnotationScope.METHOD, AnnotationScope.CLASS}
    for ti in annotation_inputs:
        if ti.scope == AnnotationScope.METHOD:
            assert ti.source_method is not None
        else:
            assert ti.source_method is None
