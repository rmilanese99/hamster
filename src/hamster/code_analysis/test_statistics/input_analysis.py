from typing import Dict, List, Optional, Set, Union

from cldk.analysis.java import JavaAnalysis
from cldk.models.java import JCallable
from cldk.models.java.models import JCallSite

from hamster.code_analysis.common import Reachability
from hamster.code_analysis.model.models import (
    AnnotationScope,
    AnnotationTestInput,
    CallSiteTestInput,
    InputType,
)
from hamster.code_analysis.utils.constants import (
    ANNOTATION_INPUT_MAP,
    STRUCTURED_INPUT_MAP,
)


class InputAnalysis:
    def __init__(self, analysis: JavaAnalysis):
        self.analysis = analysis

    def get_input_details(
        self,
        qualified_class_name: str,
        method_signature: str,
        test_utility_classes: List[str] | None = None,
    ) -> List[Union[CallSiteTestInput, AnnotationTestInput]]:
        """
        Retrieves a list of test inputs for the given method and its reachable helper methods.

        Combines call-site-level analysis (matching API calls against known structured input
        libraries) with annotation-level analysis (detecting input-declaring annotations on the
        test method and its enclosing class).

        Args:
            qualified_class_name: The fully qualified name of the class containing the method.
            method_signature: The signature of the method to analyze.
            test_utility_classes: List of test utility classes to consider as helper sources.

        Returns:
            A list of identified test inputs from the method and its helpers.

        Limitations:
            Protobuf generated-class static methods (MyMessage.parseFrom(...)) and
            Spring Data repository calls use app-specific receiver types that cannot
            be matched via library prefix.
        """
        method_details = self.analysis.get_method(
            qualified_class_name, method_signature
        )
        if not method_details:
            return []

        test_inputs: List[Union[CallSiteTestInput, AnnotationTestInput]] = []

        # --- Call-site detection across the method and its reachable helpers ---

        helper_methods: Dict[str, List[str]] = Reachability(
            self.analysis
        ).get_helper_methods(
            qualified_class_name,
            method_signature,
            add_extended_class=True,
            allow_repetition=False,
            test_utility_classes=test_utility_classes or [],
        )

        all_methods = {k: list(v) for k, v in helper_methods.items()}
        all_methods.setdefault(qualified_class_name, []).append(method_signature)

        for class_name in all_methods:
            for method_sig in all_methods[class_name]:
                method = self.analysis.get_method(class_name, method_sig)
                if not method:
                    continue
                test_inputs.extend(
                    self._collect_call_site_inputs(class_name, method_sig, method)
                )

        # --- Annotation detection on the test method and its class ---

        test_inputs.extend(
            self._collect_annotation_inputs(qualified_class_name, method_signature)
        )

        return test_inputs

    def _get_input_type(self, call_site: JCallSite) -> Optional[List[InputType]]:
        input_types: Set[InputType] = set()

        is_ctor = call_site.is_constructor_call
        recv_type = call_site.receiver_type or ""
        recv_expr = call_site.receiver_expr or ""
        callee_sig = call_site.callee_signature or ""
        method_called = call_site.method_name or ""

        for input_type, prefix_maps in STRUCTURED_INPUT_MAP.items():
            for prefix, method_names in prefix_maps.items():
                # Handle malformed constructor calls where signature is missing
                if is_ctor and not callee_sig:
                    if recv_type.startswith(prefix) and any(
                        m.startswith("new ") and m[4:] == recv_type.rsplit(".", 1)[-1]
                        for m in method_names
                    ):
                        input_types.add(input_type)
                    continue

                # Check receiver type or expression for prefix matching
                if recv_type:
                    # Skip if receiver type does not start with the prefix
                    if not recv_type.startswith(prefix):
                        continue
                else:
                    # For static calls without receiver type, check expression against prefix end
                    if prefix.rsplit(".", 1)[-1] != recv_expr:
                        continue

                # Match method names or constructor invocations
                for candidate in method_names:
                    if not is_ctor:
                        if candidate == method_called:
                            input_types.add(input_type)
                            break
                    else:
                        if candidate.startswith("new "):
                            ctor_name = callee_sig.split("(", 1)[0]
                            if candidate[4:] == ctor_name:
                                input_types.add(input_type)
                                break

        return list(input_types) if input_types else None

    def _collect_call_site_inputs(
        self, source_class: str, source_method: str, method_details: JCallable
    ) -> List[CallSiteTestInput]:
        input_details: List[CallSiteTestInput] = []

        # Check call sites for structured input patterns (JSON, XML, SQL, etc.)
        for call_site in method_details.call_sites:
            input_type = self._get_input_type(call_site)
            if input_type:
                input_details.append(
                    CallSiteTestInput(
                        method_name=call_site.method_name,
                        method_signature=call_site.callee_signature,
                        receiver_type=call_site.receiver_type,
                        receiver_expr=call_site.receiver_expr,
                        input_type=input_type,
                        source_class=source_class,
                        source_method=source_method,
                    )
                )

        # Note: Any wrapper classes will be parsed through reachability
        return input_details

    def _collect_annotation_inputs(
        self,
        qualified_class_name: str,
        method_signature: str,
    ) -> List[AnnotationTestInput]:
        """Detect input-declaring annotations on the method and its enclosing class."""
        results: List[AnnotationTestInput] = []

        method_details = self.analysis.get_method(
            qualified_class_name, method_signature
        )
        if not method_details:
            return results

        for annotation in method_details.annotations:
            annotation_name = annotation.split("(")[0]
            input_types = ANNOTATION_INPUT_MAP.get(annotation_name)
            if input_types is not None:
                results.append(
                    AnnotationTestInput(
                        annotation=annotation,
                        annotation_name=annotation_name,
                        scope=AnnotationScope.METHOD,
                        input_type=list(input_types),
                        source_class=qualified_class_name,
                        source_method=method_signature,
                    )
                )

        class_details = self.analysis.get_class(qualified_class_name)
        if class_details:
            for annotation in class_details.annotations or []:
                annotation_name = annotation.split("(")[0]
                input_types = ANNOTATION_INPUT_MAP.get(annotation_name)
                if input_types is not None:
                    results.append(
                        AnnotationTestInput(
                            annotation=annotation,
                            annotation_name=annotation_name,
                            scope=AnnotationScope.CLASS,
                            input_type=list(input_types),
                            source_class=qualified_class_name,
                            source_method=None,
                        )
                    )

        return results
