import re

from cldk.analysis.java import JavaAnalysis
from cldk.models.java import JCallable

from hamster.code_analysis.common import CommonAnalysis, Reachability
from hamster.code_analysis.model.models import FocalClassInfo, TestingFramework
from hamster.code_analysis.utils.constants import (
    API_TEST_FRAMEWORKS,
    API_TEST_FRAMEWORKS_PREFIXES_INVERT,
    ASSERTIONS_CATEGORY_MAP,
    TRANSPARENT_VALUE_WRAPPERS,
    UI_TEST_FRAMEWORKS,
    UI_TEST_FRAMEWORKS_PREFIXES_INVERT,
)

# Regex for matching Java identifiers (including fully qualified names)
_JAVA_IDENT = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*")
_SIMPLE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_THIS_DOT_IDENT = re.compile(r"^this\.([a-zA-Z_][a-zA-Z0-9_]*)$")
_ANNOTATION_RE = re.compile(r"@[\w.]+(?:\([^)]*\))?\s*")


class FocalClassMethod:
    def __init__(
        self,
        analysis: JavaAnalysis,
        application_classes: list[str],
        test_utility_classes: list[str] | None = None,
    ):
        self.analysis: JavaAnalysis = analysis
        self.common_analysis: CommonAnalysis = CommonAnalysis(self.analysis)
        self.reachability: Reachability = Reachability(self.analysis)
        self.application_classes: list[str] = list(application_classes)
        self.test_utility_classes: list[str] = (
            list(test_utility_classes) if test_utility_classes else []
        )
        self._simple_name_index: dict[str, list[str]] = self._build_simple_name_index(
            self.application_classes
        )
        self.assertion_methods: list[str] = self._get_assertion_methods()

    @staticmethod
    def _build_simple_name_index(app_classes: list[str]) -> dict[str, list[str]]:
        """Build reverse lookup from simple class names to their FQNs."""
        idx: dict[str, list[str]] = {}
        for fqn in app_classes:
            simple = fqn.split(".")[-1]
            idx.setdefault(simple, []).append(fqn)
        return idx

    @staticmethod
    def _get_assertion_methods() -> list[str]:
        """Collect all known assertion method names across supported frameworks."""
        assertion_methods = set()
        for _, framework_map in ASSERTIONS_CATEGORY_MAP.items():
            for assertions in framework_map.values():
                assertion_methods.update(assertions)
        return sorted(assertion_methods)

    def extract_test_scope(
        self,
        test_qualified_class_name: str,
        test_method_signature: str,
        setup_methods: dict[str, list[str]],
    ) -> tuple[list[FocalClassInfo], bool, bool, bool]:
        """
        Main entry point for focal class identification.

        Analyzes setup methods first, then the test method, combining results
        into validated focal classes with their associated methods.

        Args:
            test_qualified_class_name: Fully qualified name of the test class
            test_method_signature: Signature of the test method to analyze
            setup_methods: Map of declaring class to list of setup method signatures

        Returns:
            tuple containing:
                - focal_class_infos: Validated focal classes with their methods
                - is_application_class_used: Whether any application class was referenced
                - is_ui_test: Whether UI testing frameworks are used
                - is_api_test: Whether API testing frameworks are used

        Raises:
            ClassNotFoundException: If the test class or any setup classes cannot be found.
            MethodNotFoundException: If the test method or any setup methods cannot be found.
        """
        is_ui_test, is_api_test = False, False
        all_focal_methods: dict[str, list[str]] = {}
        all_assertion_variables: set[str] = set()

        # Step 1: Analyze setup methods to find focal classes instantiated outside the test
        setup_var_to_focal: dict[str, str] = {}
        is_app_used_setup = False
        if setup_methods:
            for declaring_class, method_signatures in setup_methods.items():
                if not method_signatures:
                    continue

                for setup_sig in method_signatures:
                    if not setup_sig:
                        continue

                    (
                        var_to_focal,
                        focal_methods,
                        is_app_used_m,
                        is_ui_m,
                        is_api_m,
                        assertion_vars_m,
                    ) = self._analyze_method_for_focal_info(
                        declaring_class, setup_sig, {}
                    )

                    is_ui_test = is_ui_test or is_ui_m
                    is_api_test = is_api_test or is_api_m
                    is_app_used_setup = is_app_used_setup or is_app_used_m
                    all_assertion_variables.update(assertion_vars_m)

                    for focal_class, methods in focal_methods.items():
                        all_focal_methods.setdefault(focal_class, []).extend(methods)

                    # Accumulate setup focal classes
                    setup_var_to_focal.update(var_to_focal)

        # Step 2: Analyze the test method with setup context
        (
            var_to_focal,
            focal_methods,
            is_app_used,
            is_ui_m,
            is_api_m,
            assertion_vars_m,
        ) = self._analyze_method_for_focal_info(
            test_qualified_class_name, test_method_signature, setup_var_to_focal
        )

        is_ui_test = is_ui_test or is_ui_m
        is_api_test = is_api_test or is_api_m
        all_assertion_variables.update(assertion_vars_m)

        for focal_class, methods in focal_methods.items():
            all_focal_methods.setdefault(focal_class, []).extend(methods)

        # Step 3: Build deduplicated focal class map with validated methods
        focal_class_map: dict[str, list[str]] = {}

        for var_name, focal_class_name in var_to_focal.items():
            base_focal_class = self._extract_base_type(focal_class_name)
            if base_focal_class in focal_class_map:
                continue

            # Validate methods if any were recorded for this focal class
            validated_methods: list[str] = []
            if focal_class_name in all_focal_methods:
                has_external_parent = self.reachability.has_external_inheritance(
                    base_focal_class
                )
                for method in all_focal_methods[focal_class_name]:
                    if self.reachability.find_method_in_hierarchy(
                        base_focal_class, method
                    ):
                        validated_methods.append(method)
                    elif has_external_parent:
                        validated_methods.append(method)

            # Include focal class only if it has validated methods OR appears in assertions
            # (Excludes prior case where focal classes without validated methods were always kept)
            if validated_methods:
                focal_class_map[base_focal_class] = validated_methods
            elif var_name in all_assertion_variables:
                focal_class_map[base_focal_class] = []

        # Step 4: Convert to FocalClassInfo model objects
        focal_class_infos = [
            FocalClassInfo(
                focal_class=base_class, focal_method_names=list(set(methods))
            )
            for base_class, methods in focal_class_map.items()
        ]

        return focal_class_infos, is_app_used or is_app_used_setup, is_ui_test, is_api_test

    def _analyze_method_for_focal_info(
        self,
        qualified_class_name: str,
        method_signature: str,
        inherited_var_to_focal_class: dict[str, str],
    ) -> tuple[dict, dict, bool, bool, bool, set[str]]:
        """
        Analyzes a method and its helper methods to retrieve focal classes and methods.

        Args:
            qualified_class_name: Fully qualified name of the class containing the method
            method_signature: Signature of the method to analyze
            inherited_var_to_focal_class: Focal classes already detected (e.g., from setup)

        Returns:
            tuple containing:
                - var_to_focal_class: Maps variable names to focal class types
                - focal_class_to_methods: Maps focal classes to called methods
                - is_application_class_used: Whether any application class was referenced
                - is_ui_test: Whether UI testing frameworks are used
                - is_api_test: Whether API testing frameworks are used
                - assertion_variables: Variable names that appear in assertion arguments
        """
        is_ui_test, is_api_test = False, False
        all_assertion_variables: set[str] = set()
        all_focal_methods: dict[str, list[str]] = {}
        base_context_vars = inherited_var_to_focal_class.copy()
        is_application_class_used = False

        method_details = self.analysis.get_method(
            qualified_class_name, method_signature
        )

        # Collect helper methods (private utility methods called by this method)
        helper_methods = self.reachability.get_helper_methods(
            qualified_class_name=qualified_class_name,
            method_signature=method_signature,
            add_extended_class=True,
            test_utility_classes=self.test_utility_classes,
        )

        # Pre-collect assertion variables from all methods (helpers + main) with translation
        # This must happen BEFORE processing so producer-consumer filtering has full context
        if method_details:
            all_assertion_variables.update(
                self._collect_assertion_variables(
                    qualified_class_name, method_signature
                )
            )

        for helper_class, helper_sigs in helper_methods.items():
            for helper_sig in helper_sigs:
                helper_vars = self._collect_assertion_variables(
                    helper_class, helper_sig
                )
                all_assertion_variables.update(helper_vars)

                # Translate parameter names back to caller's argument names
                if method_details:
                    translated = self._translate_assertion_variables(
                        method_details, helper_class, helper_sig, helper_vars
                    )
                    all_assertion_variables.update(translated)

        # Cache framework lookups to avoid repeated analysis
        framework_cache: dict[str, list[TestingFramework]] = {}

        def get_frameworks(class_name: str) -> list[TestingFramework]:
            """Will raise exception if class does not exist, but shouldn't be possible"""
            if class_name not in framework_cache:
                framework_cache[class_name] = (
                    self.common_analysis.get_testing_frameworks_for_class(class_name)
                )
            return framework_cache[class_name]

        # Process helper methods first to capture focal classes they initialize
        for helper_class, helper_sigs in helper_methods.items():
            for helper_sig in helper_sigs:
                helper_method = self.analysis.get_method(helper_class, helper_sig)
                if helper_method is None:
                    continue

                is_ui_m, is_api_m = self._is_ui_or_api_test(
                    helper_method, get_frameworks(helper_class)
                )
                is_ui_test = is_ui_test or is_ui_m
                is_api_test = is_api_test or is_api_m

                # Pass isolated copy of base context to prevent helper vars from leaking
                _, focal_methods_m, is_app_used_m = self._extract_method_focal_info(
                    helper_class,
                    helper_sig,
                    base_context_vars.copy(),
                    all_assertion_variables,
                )

                for cls, methods in focal_methods_m.items():
                    all_focal_methods.setdefault(cls, []).extend(methods)

                is_application_class_used = is_application_class_used or is_app_used_m

        # Process main method with clean base context (no helper local vars)
        var_to_focal_class: dict[str, str] = base_context_vars.copy()
        if method_details is not None:
            is_ui_m, is_api_m = self._is_ui_or_api_test(
                method_details, get_frameworks(qualified_class_name)
            )
            is_ui_test = is_ui_test or is_ui_m
            is_api_test = is_api_test or is_api_m

            var_to_focal_class, focal_methods_m, is_app_used_m = (
                self._extract_method_focal_info(
                    qualified_class_name,
                    method_signature,
                    base_context_vars.copy(),
                    all_assertion_variables,
                )
            )

            for cls, methods in focal_methods_m.items():
                all_focal_methods.setdefault(cls, []).extend(methods)

            is_application_class_used = is_application_class_used or is_app_used_m

        return (
            var_to_focal_class,
            all_focal_methods,
            is_application_class_used,
            is_ui_test,
            is_api_test,
            all_assertion_variables,
        )

    def _extract_method_focal_info(
        self,
        qualified_class_name: str,
        method_signature: str,
        inherited_var_to_focal_class: dict[str, str],
        inherited_assertion_variables: set[str],
    ) -> tuple[dict[str, str], dict[str, list[str]], bool]:
        """
        Core algorithm for extracting focal classes from a single method. Analyzes
        variable declarations, constructor calls, and method invocations to identify
        which application classes are being tested (vs. used as helpers/producers).

        Args:
            qualified_class_name: Fully qualified name of the class
            method_signature: The method signature of the object to analyze
            inherited_var_to_focal_class: Previously detected focal classes to build upon
            inherited_assertion_variables: Pre-collected assertion vars from all methods

        Returns:
            tuple containing:
                - var_to_focal_class: Maps variable names (or class names for static) to focal class types
                - focal_class_to_methods: Maps focal classes to list of called methods
                - is_application_class_used: Whether any application class was referenced
        """
        # Maps variable and field names to their inferred concrete focal class types
        # Used to find inferred types when tracking method calls and to determine focal classes in final output
        var_to_focal_class: dict[str, str] = inherited_var_to_focal_class.copy()

        # Maps variable/field names to their declared (static) types.
        # Used to match constructor return types to variables
        declared_var_types: dict[str, str] = {}

        # Focal classes accessed via static method calls (no instance variable).
        # Used as a fallback when no instance variables remain after filtering
        static_focal_classes: list[str] = []

        # Accumulates any method callsed on each focal class
        # Used in Step 7 to populate focal_class_to_methods for classes in var_to_focal_class.
        candidate_focal_methods: dict[str, list[str]] = {}

        # Final output: maps focal classes to their validated called methods.
        focal_class_to_methods: dict[str, list[str]] = {}

        is_application_class_used: bool = False

        method_details: JCallable = self.analysis.get_method(
            qualified_class_name, method_signature
        )

        if method_details is None:
            raise ValueError("Method does not exist...")

        # Collect mocked field names, excluding those shadowed by local variables
        mocked_fields = self._get_mocked_field_names(qualified_class_name)
        local_var_names = {var.name for var in method_details.variable_declarations}
        effective_mocked_fields = mocked_fields - local_var_names

        # Step 1: Collect all variable declarations and field declarations for type matching
        # Fields go first since they can be overriden by vars
        declared_var_types.update(
            self._get_all_field_declarations(qualified_class_name)
        )

        for var in method_details.variable_declarations:
            declared_var_types[var.name] = var.type

        # Normalize types: clean and resolve to FQN when possible
        for name, t in list(declared_var_types.items()):
            outer = self._extract_base_type(t)
            declared_var_types[name] = self._resolve_application_class(outer) or outer

        # Step 2: Consider all method parameters
        for param in method_details.parameters:
            focal_type = self._declared_focal_type(param.type)
            if param.name and focal_type:
                var_to_focal_class[param.name] = focal_type

            # Check for application class use with high-recall type checking
            if self._contains_application_type(param.type):
                is_application_class_used = True

        # Step 3: Process local variable declarations
        for var in method_details.variable_declarations:
            focal_type = self._declared_focal_type(var.type)
            if focal_type:
                var_to_focal_class[var.name] = focal_type

            # Check for application class use with high-recall type checking
            if self._contains_application_type(var.type):
                is_application_class_used = True

        # Step 4: Map variables to concrete types using constructor calls (refinement on 3)
        matched_vars: set[str] = set(var_to_focal_class.keys())

        for call_site in method_details.call_sites:
            if not call_site.is_constructor_call:
                continue

            constructed_raw = self._extract_base_type(call_site.return_type)
            constructed_type = self._resolve_application_class(constructed_raw)
            if not constructed_type:
                continue

            is_application_class_used = True
            constructed_simple = constructed_type.split(".")[-1]
            matched = False

            # Try precise matching via initializer first
            for var in method_details.variable_declarations:
                if var.name in matched_vars or not var.initializer:
                    continue
                if var.initializer.startswith(f"new {constructed_simple}("):
                    var_to_focal_class[var.name] = constructed_type
                    matched_vars.add(var.name)
                    matched = True
                    break

            # Fallback: type-based matching if no initializer match
            if not matched:
                all_supertypes: list[str] = self.reachability.get_all_supertypes(
                    constructed_type
                )

                for var, var_type in declared_var_types.items():
                    if var in matched_vars:
                        continue

                    if (
                        var_type == constructed_type
                        or var_type in all_supertypes
                        or self._types_match_by_short_name(var_type, constructed_type)
                    ):
                        var_to_focal_class[var] = constructed_type
                        matched_vars.add(var)
                        break

        # Step 5: Process non-constructor call sites
        for call_site in method_details.call_sites:
            if call_site.is_constructor_call:
                continue

            receiver_raw = self._extract_base_type(call_site.receiver_type)
            receiver_type = self._resolve_application_class(receiver_raw)
            receiver_expr = call_site.receiver_expr
            recv_name = self._simple_receiver_name(receiver_expr)

            # 5a: Map receiver variables to focal classes (application class receivers only)
            if receiver_type:
                # Skip mocked fields - they are test doubles, not focal classes
                if recv_name and recv_name in effective_mocked_fields:
                    continue

                # Map variable/field to its receiver type
                if recv_name and (
                    recv_name in declared_var_types or recv_name in var_to_focal_class
                ):
                    var_to_focal_class.setdefault(recv_name, receiver_type)
                else:
                    # Track as static focal class for non-variable receivers
                    if receiver_type not in static_focal_classes:
                        static_focal_classes.append(receiver_type)

                # For static calls, link variables initialized from the RESULT type
                if call_site.is_static_call and receiver_expr:
                    produced_raw = self._extract_base_type(call_site.return_type)
                    produced_type = self._resolve_application_class(produced_raw)
                    if produced_type:
                        for var_decl in method_details.variable_declarations:
                            if var_decl.initializer and var_decl.initializer.startswith(
                                f"{receiver_expr}."
                            ):
                                var_to_focal_class.setdefault(
                                    var_decl.name, produced_type
                                )

            # 5b: Track called methods under the inferred concrete type
            if receiver_type:
                # Case 1: Static type is application class - filter getters, use inferred type
                effective_type = (
                    var_to_focal_class.get(recv_name, receiver_type)
                    if recv_name
                    else receiver_type
                )
                # Use effective (concrete) type for getter check to match actual class fields
                if not self.common_analysis.is_likely_getter(
                    effective_type, call_site.callee_signature
                ):
                    sig = call_site.callee_signature
                    if sig:
                        candidate_focal_methods.setdefault(effective_type, []).append(
                            sig
                        )
            elif recv_name and recv_name in var_to_focal_class:
                # Case 2: Static type is external (e.g., CommandLineParser interface), but has inferred application type (e.g., GnuParser)
                inferred_type = var_to_focal_class[recv_name]
                sig = call_site.callee_signature
                if sig:
                    candidate_focal_methods.setdefault(inferred_type, []).append(sig)

            # 5c: Match return types to declared variables (use setdefault to preserve concrete types)
            return_raw = self._extract_base_type(call_site.return_type)
            return_type = self._resolve_application_class(return_raw)
            if return_type:
                for var, var_type in declared_var_types.items():
                    if var_type == return_type:
                        var_to_focal_class.setdefault(var, return_type)
                    elif self._types_match_by_short_name(var_type, return_type):
                        var_to_focal_class.setdefault(var, return_type)

            # Check for application class use with high-recall type checking
            if self._contains_application_type(call_site.receiver_type):
                is_application_class_used = True
            if self._contains_application_type(call_site.return_type):
                is_application_class_used = True

        # Step 6: Producer-consumer filtering
        # Remove variables passed as arguments to application methods, UNLESS they appear in assertions
        # Uses pre-collected assertion vars from all methods (main + helpers with translation)
        producer_arguments: list[str] = self._get_producer_arguments(
            qualified_class_name, method_signature, var_to_focal_class
        )
        for arg in producer_arguments:
            base_arg: str = self._extract_base_variable(arg)
            if base_arg and base_arg in var_to_focal_class:
                if base_arg not in inherited_assertion_variables:
                    var_to_focal_class.pop(base_arg)

        # Step 7: Merge static focal classes into unified candidate pool
        # Static types use class name as both key and value for self-documenting pattern
        for static_type in static_focal_classes:
            if static_type not in var_to_focal_class:
                var_to_focal_class[static_type] = static_type

        # Step 8: Build focal map for all focal class candidates (instance + static)
        for var, var_type in var_to_focal_class.items():
            if (
                var_type in candidate_focal_methods
                and var_type not in focal_class_to_methods
            ):
                focal_class_to_methods[var_type] = candidate_focal_methods[var_type]

        return var_to_focal_class, focal_class_to_methods, is_application_class_used

    def _get_mocked_field_names(
        self,
        qualified_class_name: str,
        mocked_fields: set[str] | None = None,
    ) -> set[str]:
        """
        Get all mocked field names from a class and its parents.
        Checks for @Mock, @MockBean, @Spy, @SpyBean annotations.
        """
        if mocked_fields is None:
            mocked_fields = set()

        class_details = self.analysis.get_class(qualified_class_name)
        if class_details is None:
            return mocked_fields

        # Recurse into parent classes first
        for parent in class_details.extends_list or []:
            self._get_mocked_field_names(parent, mocked_fields)

        # Process fields in current class
        for field in class_details.field_declarations:
            for annotation in field.annotations:
                if annotation.startswith(("@Mock", "@Spy")):
                    mocked_fields.update(field.variables)
                    break

        return mocked_fields

    def _get_all_field_declarations(
        self,
        qualified_class_name: str,
        field_declarations: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """
        Get all field declarations (name and type) from a class and its parents.

        Args:
            qualified_class_name: Fully qualified class name
            field_declarations: Accumulator for recursive calls (internal use)

        Returns:
            dict[str, str]: Maps field_name to field_type, including inherited fields.
                Child class fields shadow parent fields with the same name.
        """
        if field_declarations is None:
            field_declarations = {}

        class_details = self.analysis.get_class(qualified_class_name)

        if class_details is not None:
            extends_list: list[str] = class_details.extends_list or []
            for class_name in extends_list:
                self._get_all_field_declarations(class_name, field_declarations)

            for field in class_details.field_declarations:
                for variable in field.variables:
                    field_declarations[variable] = field.type

        return field_declarations

    def _get_producer_arguments(
        self,
        qualified_class_name: str,
        method_signature: str,
        var_to_focal_class: dict[str, str],
    ) -> list[str]:
        """
        Collects arguments that indicate producer-consumer relationships.
        Only considers arguments passed to other application class methods (to avoid loggers and utilities from filtering focal classes).

        Args:
            qualified_class_name: Fully qualified class name
            method_signature: The method signature of the method whose call sites are to be analyzed

        Return:
            list[str]: List of argument expressions passed to application classes
        """
        method_details = self.analysis.get_method(
            qualified_class_name, method_signature
        )
        if not method_details:
            return []

        arguments: list[str] = []
        for call_site in method_details.call_sites:
            recv_raw = self._extract_base_type(call_site.receiver_type)
            recv_type = self._resolve_application_class(recv_raw)

            # Fall back to inferred type if static type is external
            if not recv_type:
                recv_name = self._simple_receiver_name(call_site.receiver_expr)
                if recv_name and recv_name in var_to_focal_class:
                    recv_type = var_to_focal_class[recv_name]

            if recv_type:
                if call_site.method_name not in self.assertion_methods:
                    arguments.extend(call_site.argument_expr)

        return arguments

    def _collect_assertion_variables(
        self,
        qualified_class_name: str,
        method_signature: str,
    ) -> set[str]:
        """Collect variables appearing in assertion arguments for a single method."""
        assertion_vars: set[str] = set()
        method_details = self.analysis.get_method(
            qualified_class_name, method_signature
        )
        if not method_details:
            return assertion_vars

        for call_site in method_details.call_sites:
            if call_site.method_name in self.assertion_methods:
                for arg in call_site.argument_expr:
                    arg_identifiers = self._collect_all_identifiers(arg)
                    assertion_vars.update(arg_identifiers)

        return assertion_vars

    def _translate_assertion_variables(
        self,
        caller_method_details: JCallable,
        helper_class: str,
        helper_sig: str,
        helper_assertion_vars: set[str],
    ) -> set[str]:
        """Map helper parameter assertion vars back to caller's argument variables."""
        translated: set[str] = set()
        helper_method = self.analysis.get_method(helper_class, helper_sig)
        if not helper_method or not helper_method.parameters:
            return translated

        # Build param_name -> param_index map
        param_indices = {p.name: i for i, p in enumerate(helper_method.parameters)}

        # Find call sites in caller that invoke this helper
        for call_site in caller_method_details.call_sites:
            if call_site.callee_signature != helper_sig:
                continue
            for var in helper_assertion_vars:
                if var in param_indices:
                    idx = param_indices[var]
                    if idx < len(call_site.argument_expr):
                        base = self._extract_base_variable(call_site.argument_expr[idx])
                        if base:
                            translated.add(base)

        return translated

    def _is_ui_or_api_test(
        self,
        method_details: JCallable,
        testing_frameworks: list[TestingFramework],
    ) -> tuple[bool, bool]:
        """
        Determines if a method uses UI or API testing frameworks by examining
        type references for known framework prefixes.

        Args:
            method_details: The method to analyze
            testing_frameworks: Frameworks detected for the containing class

        Returns:
            tuple[bool, bool]: (is_ui_test, is_api_test)
        """
        # Early exit if no UI/API frameworks present in the class
        has_ui_framework = any(fw in testing_frameworks for fw in UI_TEST_FRAMEWORKS)
        has_api_framework = any(fw in testing_frameworks for fw in API_TEST_FRAMEWORKS)
        if not (has_ui_framework or has_api_framework):
            return False, False

        # Collect all type references from parameters, call sites, and variables
        referenced_types: list[str] = []

        # Include parameter types
        for param in method_details.parameters:
            if param.type:
                referenced_types.append(param.type)

        for call_site in method_details.call_sites:
            if call_site.receiver_type:
                referenced_types.append(call_site.receiver_type)
            if call_site.return_type:
                referenced_types.append(call_site.return_type)

        for var in method_details.variable_declarations:
            if var.type:
                referenced_types.append(var.type)

        # Extract all component types to handle generics (e.g., List<WebElement>)
        all_type_components: list[str] = []
        for t in referenced_types:
            all_type_components.extend(self._get_component_types(t))

        # Check for framework type prefixes
        is_ui_test = any(
            t.startswith(tuple(UI_TEST_FRAMEWORKS_PREFIXES_INVERT))
            for t in all_type_components
        )
        is_api_test = any(
            t.startswith(tuple(API_TEST_FRAMEWORKS_PREFIXES_INVERT))
            for t in all_type_components
        )

        return is_ui_test, is_api_test

    @staticmethod
    def _extract_base_type(type_str: str) -> str:
        """
        Remove generics, varargs, and array brackets to get the base type name.
        Preserves package qualifiers (dots).

        Examples:
            'List<User>' -> 'List'
            'String...' -> 'String'
            'int[]' -> 'int'
            'Map<K, V>[]' -> 'Map'
            'java.util.Optional<Owner>' -> 'java.util.Optional'
        """
        if not type_str:
            return ""
        lt = type_str.find("<")
        if lt != -1:
            type_str = type_str[:lt]
        type_str = type_str.replace("...", "")
        type_str = type_str.replace("[]", "")
        return type_str.strip()

    def _resolve_application_class(self, type_str: str) -> str | None:
        """
        Check if type_str matches an application class.
        Handles both FQN and simple name matching.

        Returns the FQN if found, None otherwise.
        Returns None for ambiguous simple names (multiple FQNs) to avoid false positives.
        """
        if not type_str:
            return None

        if type_str in self.application_classes:
            return type_str

        # Simple name match (only if no package qualifier and unambiguous)
        if "." not in type_str:
            matches = self._simple_name_index.get(type_str, [])
            if len(matches) == 1:
                return matches[0]
            return None  # ambiguous or not found

        return None

    @staticmethod
    def _split_top_level_generic_args(type_str: str) -> list[str]:
        """
        Split top-level generic arguments from a type string.

        Examples:
            'Optional<Owner>' -> ['Owner']
            'Map<String, List<User>>' -> ['String', 'List<User>']
            'Function<Input, Output>' -> ['Input', 'Output']
            'List' -> []
        """
        if not type_str:
            return []

        lt = type_str.find("<")
        if lt == -1:
            return []

        args: list[str] = []
        depth = 0
        buf: list[str] = []

        for ch in type_str[lt + 1 :]:
            if ch == "<":
                depth += 1
                buf.append(ch)
            elif ch == ">":
                if depth == 0:
                    s = "".join(buf).strip()
                    if s:
                        args.append(s)
                    break
                depth -= 1
                buf.append(ch)
            elif ch == "," and depth == 0:
                s = "".join(buf).strip()
                if s:
                    args.append(s)
                buf = []
            else:
                buf.append(ch)

        return args

    def _declared_focal_type(self, type_str: str) -> str | None:
        """
        Extract the application class from a type declaration.
        First checks if the outer type is an application class.
        If the outer type is a wrapper, it looks inside the generic args for application classes.
        Returns the FQN of the matched application class, or None if no match.
        """
        if not type_str:
            return None

        # Clean annotations/wildcards from outer declaration (e.g., '@Nonnull Optional<Owner>')
        type_str = self._strip_annotations_and_wildcards(type_str)

        outer = self._extract_base_type(type_str)
        resolved = self._resolve_application_class(outer)
        if resolved:
            return resolved

        # Check if outer type is a transparent wrapper (by short name)
        outer_short = outer.split(".")[-1]
        if outer_short not in TRANSPARENT_VALUE_WRAPPERS:
            return None

        # Look inside the generic arguments
        for arg in self._split_top_level_generic_args(type_str):
            arg = self._strip_annotations_and_wildcards(arg)
            inner = self._declared_focal_type(arg)
            if inner:
                return inner

        return None

    @staticmethod
    def _get_component_types(type_str: str) -> list[str]:
        """
        Extract all component types from a generic type string.
        E.g., 'Map<String, List<User>>' -> ['Map', 'String', 'List', 'User']

        Args:
            type_str: Complex type string potentially with generics

        Returns:
            list[str]: All component types extracted from the string
        """
        if not type_str:
            return []
        return _JAVA_IDENT.findall(type_str)

    @staticmethod
    def _extract_base_variable(arg_expr: str) -> str:
        """
        Extract base variable name from expression.
        Handles: 'obj.method()' -> 'obj', 'this.field' -> 'field', '((Type)var)' -> 'var'

        Args:
            arg_expr: Argument expression string

        Returns:
            str: Base variable name or empty string if not found
        """
        if not arg_expr:
            return ""
        expr = arg_expr.strip()

        # Strip this./super. prefix
        expr = re.sub(r"^(?:this|super)\.", "", expr)

        # Strip cast prefix: ((Type)expr) or (Type)expr
        expr = re.sub(r"^\(+[^)]+\)\s*", "", expr)

        match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)", expr)
        return match.group(1) if match else ""

    @staticmethod
    def _collect_all_identifiers(arg_expr: str) -> set[str]:
        """
        Extract all variable identifiers from an assertion argument expression.
        Filters out Java keywords, 'this', 'super', and method names.

        Args:
            arg_expr: Assertion argument expression

        Returns:
            set[str]: All variable names found in the expression
        """
        if not arg_expr:
            return set()

        java_keywords = {
            "abstract",
            "assert",
            "boolean",
            "break",
            "byte",
            "case",
            "catch",
            "char",
            "class",
            "const",
            "continue",
            "default",
            "do",
            "double",
            "else",
            "enum",
            "extends",
            "final",
            "finally",
            "float",
            "for",
            "goto",
            "if",
            "implements",
            "import",
            "instanceof",
            "int",
            "interface",
            "long",
            "native",
            "new",
            "package",
            "private",
            "protected",
            "public",
            "return",
            "short",
            "static",
            "strictfp",
            "super",
            "switch",
            "synchronized",
            "this",
            "throw",
            "throws",
            "transient",
            "try",
            "void",
            "volatile",
            "while",
            "true",
            "false",
            "null",
        }

        all_tokens = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", arg_expr)

        identifiers = set()
        for token in all_tokens:
            if token in java_keywords:
                continue

            # Skip if followed by '(' (method name, not variable)
            token_pattern = r"\b" + re.escape(token) + r"\s*\("
            if re.search(token_pattern, arg_expr):
                continue

            identifiers.add(token)

        return identifiers

    @staticmethod
    def _types_match_by_short_name(type_a: str, type_b: str) -> bool:
        """
        Check if two types match by short name when FQN unavailable.
        Only matches if at least one type lacks a package qualifier.

        Args:
            type_a: First type string
            type_b: Second type string

        Returns:
            bool: True if types match by short name
        """
        if not type_a or not type_b:
            return False
        if "." in type_a and "." in type_b:
            return False
        return type_a.split(".")[-1] == type_b.split(".")[-1]

    @staticmethod
    def _simple_receiver_name(receiver_expr: str) -> str | None:
        """
        Return a variable/field name if receiver_expr is a simple reference.
        Handles: 'x', 'this.x', 'super.x', '((Type)var)'
        Returns None for complex expressions (method calls, chained access).
        """
        if not receiver_expr:
            return None
        expr = receiver_expr.strip()

        # Handle this.x and super.x
        m = re.match(r"^(?:this|super)\.([a-zA-Z_][a-zA-Z0-9_]*)$", expr)
        if m:
            return m.group(1)

        # Handle casts: ((Type)var) or (Type)var
        m = re.match(r"^\(+[^)]+\)\s*([a-zA-Z_][a-zA-Z0-9_]*)\)?$", expr)
        if m:
            return m.group(1)

        if _SIMPLE_IDENT.match(expr):
            return expr
        return None

    @staticmethod
    def _strip_annotations_and_wildcards(token: str) -> str:
        """
        Clean a generic argument token:
        - Strip annotations: '@Nonnull Owner' -> 'Owner'
        - Handle wildcards: '? extends Owner' -> 'Owner', '? super Owner' -> 'Owner'
        """
        if not token:
            return ""
        t = token.strip()
        t = _ANNOTATION_RE.sub("", t).strip()
        if t.startswith("?"):
            t = t[1:].strip()
            if t.startswith("extends "):
                t = t[len("extends ") :].strip()
            elif t.startswith("super "):
                t = t[len("super ") :].strip()
        return t

    def _is_application_type_name(self, type_name: str) -> bool:
        """
        High-recall check: returns True if type_name matches an application class
        by FQN or by simple name.
        """
        if not type_name:
            return False
        if type_name in self.application_classes:
            return True
        if "." not in type_name and type_name in self._simple_name_index:
            return True
        return False

    def _contains_application_type(self, type_str: str) -> bool:
        """Check if type string mentions any application class (outer or inner)."""
        if not type_str:
            return False
        for tok in self._get_component_types(type_str):
            if self._is_application_type_name(tok):
                return True
        return False
