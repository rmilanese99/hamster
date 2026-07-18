import re
from typing import Dict, List, Optional, Tuple

from cldk.analysis.java import JavaAnalysis
from cldk.models.java import JCallable

from hamster.code_analysis.common import CommonAnalysis, Reachability
from hamster.code_analysis.model.models import FocalClassInfo, TestingFramework
from hamster.code_analysis.utils.constants import (
    API_TEST_FRAMEWORKS,
    API_TEST_FRAMEWORKS_PREFIXES_INVERT,
    ASSERTIONS_CATEGORY_MAP,
    GETTER_PREFIXES,
    UI_TEST_FRAMEWORKS,
    UI_TEST_FRAMEWORKS_PREFIXES_INVERT,
)

# Regex to match Java identifiers, including fully qualified names (e.g., com.example.User)
_JAVA_IDENT = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*")


class FocalClassMethod:
    def __init__(
        self,
        analysis: JavaAnalysis,
        application_classes: List[str],
    ):
        self.analysis = analysis
        self.common_analysis = CommonAnalysis(self.analysis)
        self.reachability = Reachability(self.analysis)
        self.application_classes = list(application_classes)
        self.assertion_methods = self.__get_assertion_methods()

    @staticmethod
    def __get_assertion_methods() -> List[str]:
        """Collect all known assertion method names across supported frameworks."""
        assertion_methods = set()
        for assertion_type, framework_map in ASSERTIONS_CATEGORY_MAP.items():
            for assertions in framework_map.values():
                assertion_methods.update(assertions)
        return sorted(assertion_methods)

    def is_ui_api_test(
        self,
        method_details: JCallable,
        testing_frameworks: List[TestingFramework],
    ) -> Tuple[bool, bool]:
        """
        Checks if the test method is related to UI and API test by examining
        type references for known framework prefixes.

        Args:
            method_details: The method to analyze
            testing_frameworks: List of testing frameworks detected for the class

        Returns:
            Tuple[bool, bool]: (is_ui_test, is_api_test)
        """
        is_ui_test = False
        is_api_test = False

        # Early exit if no UI/API frameworks are present in the test class
        if not (
            any(framework in testing_frameworks for framework in UI_TEST_FRAMEWORKS)
            or any(framework in testing_frameworks for framework in API_TEST_FRAMEWORKS)
        ):
            return False, False

        # Collect all types referenced in call sites and variable declarations
        all_potential_types: List[str] = []
        for call_site in method_details.call_sites:
            if call_site.receiver_type:
                all_potential_types.append(call_site.receiver_type)
            if call_site.return_type:
                all_potential_types.append(call_site.return_type)

        for variable in method_details.variable_declarations:
            if variable.type:
                all_potential_types.append(variable.type)

        # Check for UI framework type prefixes (Selenium, Selenide, etc.)
        if any(
            type_name.startswith(tuple(UI_TEST_FRAMEWORKS_PREFIXES_INVERT))
            for type_name in all_potential_types
        ):
            is_ui_test = True

        # Check for API framework type prefixes (REST Assured, MockMvc, etc.)
        if any(
            type_name.startswith(tuple(API_TEST_FRAMEWORKS_PREFIXES_INVERT))
            for type_name in all_potential_types
        ):
            is_api_test = True

        return is_ui_test, is_api_test

    def extract_test_scope(
        self,
        test_class_name: str,
        test_method_signature: str,
        setup_methods: Dict[str, List[str]],
    ) -> Tuple[List[FocalClassInfo], bool, bool, bool]:
        """
        Main entry point for focal class identification. Analyzes setup methods first,
        then the test method itself, combining results into validated focal classes.

        Args:
            test_class_name: Fully qualified name of the test class
            test_method_signature: Signature of the test method to analyze
            setup_methods: Map of declaring class to list of setup method signatures

        Returns:
            Tuple[List[FocalClassInfo], bool, bool, bool]: (focal_classes, is_application_class_used,
                is_ui_test, is_api_test)
        """
        is_api_test = False
        is_ui_test = False

        all_focal_methods: dict[
            str, list[str]
        ] = {}  # Maps focal classes to a list of focal methods
        focal_class_model_object: list[FocalClassInfo] = []

        # Step 1: Analyze setup methods (@Before, @BeforeEach, etc.) to find focal classes initialized outside the test method itself.
        setup_application_classes = {}
        if setup_methods:
            for declaring_class, method_signatures in setup_methods.items():
                if not method_signatures:
                    continue

                for setup_method_signature in method_signatures:
                    if not setup_method_signature:
                        continue

                    (
                        setup_focal_classes,
                        focal_methods,
                        _,
                        is_ui_test_m,
                        is_api_test_m,
                    ) = self.__get_focal_class_and_method(
                        declaring_class, setup_method_signature
                    )

                    is_api_test = is_api_test or is_api_test_m
                    is_ui_test = is_ui_test or is_ui_test_m

                    for f_class in focal_methods:
                        if f_class in all_focal_methods:
                            all_focal_methods[f_class].extend(focal_methods[f_class])
                        else:
                            all_focal_methods[f_class] = focal_methods[f_class]

                    for focal_class in setup_focal_classes:
                        setup_application_classes[focal_class] = setup_focal_classes[
                            focal_class
                        ]

        # Step 2: Analyze the test method, passing in setup-discovered classes for context
        (
            focal_classes,
            focal_methods,
            is_application_class_used,
            is_ui_test_m,
            is_api_test_m,
        ) = self.__get_focal_class_and_method(
            test_class_name, test_method_signature, setup_application_classes
        )

        for f_class in focal_methods:
            if f_class in all_focal_methods:
                all_focal_methods[f_class].extend(focal_methods[f_class])
            else:
                all_focal_methods[f_class] = focal_methods[f_class]

        # Step 3: Build deduplicated focal class map and validate methods exist in hierarchy
        focal_class_map: Dict[str, List[str]] = {}
        for var_name in focal_classes:
            focal_class_name = focal_classes[var_name]
            base_focal_class = self._strip_generics(focal_class_name)

            if base_focal_class in focal_class_map:
                continue

            if focal_class_name in all_focal_methods:
                # Validate that methods actually exist in the class or its parents
                final_focal_methods = []
                for f in all_focal_methods[focal_class_name]:
                    if (
                        self.reachability.find_method_in_hierarchy(base_focal_class, f)
                        is not None
                    ):
                        final_focal_methods.append(f)
                focal_class_map[base_focal_class] = final_focal_methods
            else:
                focal_class_map[base_focal_class] = []

        # Step 4: Convert to FocalClassInfo model objects
        for base_focal_class, methods in focal_class_map.items():
            focal_class_model_object.append(
                FocalClassInfo(
                    focal_class=base_focal_class,
                    focal_method_names=list(set(methods)),
                )
            )

        is_api_test = is_api_test or is_api_test_m
        is_ui_test = is_ui_test or is_ui_test_m

        return (
            focal_class_model_object,
            is_application_class_used,
            is_ui_test,
            is_api_test,
        )

    def __get_focal_class_and_method(
        self,
        class_name: str,
        method_signature: str,
        previously_detect_focal_classes: Optional[dict] = None,
    ) -> Tuple[dict, dict, bool, bool, bool]:
        """
        Analyzes a method and its helper methods to extract focal classes and methods.

        Args:
            class_name: Fully qualified name of the class containing the method
            method_signature: Signature of the method to analyze
            previously_detect_focal_classes: Focal classes already detected (e.g., from setup)

        Returns:
            Tuple[dict, dict, bool, bool, bool]: (variable_to_focal_class_map, focal_class_to_methods_map,
                is_application_class_used, is_ui_test, is_api_test)
        """
        is_ui_test = False
        is_api_test = False
        focal_methods = {}

        if previously_detect_focal_classes is None:
            previously_detect_focal_classes = {}

        is_application_class_used = False
        method_details = self.analysis.get_method(class_name, method_signature)

        # Collect all helper methods (private utility methods called by this test)
        helper_methods = self.reachability.get_helper_methods(
            qualified_class_name=class_name,
            method_signature=method_signature,
            add_extended_class=True,
        )

        # Cache framework lookups to avoid repeated analysis
        framework_cache: Dict[str, List[TestingFramework]] = {}

        def get_frameworks_for(class_to_check: str) -> List[TestingFramework]:
            if class_to_check in framework_cache:
                return framework_cache[class_to_check]
            try:
                frameworks = self.common_analysis.get_testing_frameworks_for_class(
                    class_to_check
                )
            except Exception:
                frameworks = []
            framework_cache[class_to_check] = frameworks
            return frameworks

        focal_classes = previously_detect_focal_classes.copy()

        # Process helper methods first to capture focal classes they may initialize
        for helper_class in helper_methods:
            for helper_method_sig in helper_methods[helper_class]:
                helper_method = self.analysis.get_method(
                    helper_class, helper_method_sig
                )
                if helper_method is not None:
                    helper_frameworks = get_frameworks_for(helper_class)
                    is_ui_test_m, is_api_test_m = self.is_ui_api_test(
                        helper_method,
                        helper_frameworks,
                    )
                    is_ui_test = is_ui_test or is_ui_test_m
                    is_api_test = is_api_test or is_api_test_m

                    focal_classes, focal_method_m, is_application_class_used_m = (
                        self.__process_method_for_focal_class(
                            helper_class, helper_method, focal_classes
                        )
                    )

                    for cls in focal_method_m:
                        if cls in focal_methods:
                            focal_methods[cls].extend(focal_method_m[cls])
                        else:
                            focal_methods[cls] = focal_method_m[cls]

                    is_application_class_used = (
                        is_application_class_used or is_application_class_used_m
                    )

        # Process the main method after helpers to inherit their discoveries
        if method_details is not None:
            method_frameworks = get_frameworks_for(class_name)
            is_ui_test_m, is_api_test_m = self.is_ui_api_test(
                method_details,
                method_frameworks,
            )
            is_ui_test = is_ui_test or is_ui_test_m
            is_api_test = is_api_test or is_api_test_m

            focal_classes, focal_method_m, is_application_class_used_m = (
                self.__process_method_for_focal_class(
                    class_name, method_details, focal_classes
                )
            )

            for cls in focal_method_m:
                if cls in focal_methods:
                    focal_methods[cls].extend(focal_method_m[cls])
                else:
                    focal_methods[cls] = focal_method_m[cls]

            is_application_class_used = (
                is_application_class_used or is_application_class_used_m
            )

        return (
            focal_classes,
            focal_methods,
            is_application_class_used,
            is_ui_test,
            is_api_test,
        )

    def __process_method_for_focal_class(
        self, test_class: str, method: JCallable, focal_classes: dict
    ) -> Tuple[dict, dict, bool]:
        """
        Core algorithm for extracting focal classes from a single method. Analyzes
        variable declarations, constructor calls, and method invocations to identify
        which application classes are being tested (vs. used as helpers/producers).

        Args:
            test_class: Fully qualified name of the test class
            method: The method object to analyze
            focal_classes: Previously detected focal classes to build upon

        Returns:
            Tuple[dict, dict, bool]: (variable_to_focal_class_map, focal_class_to_methods_map,
                is_application_class_used)
        """
        variables = focal_classes.copy()
        candidate_assignment_targets = []
        is_application_class_used = False
        all_possible_focal_methods = {}
        focal_methods = {}
        parameter_types = []
        static_types = {}

        # -------------------------------------------------------------------------
        # Phase 1: Collect all variable declarations for type matching
        # -------------------------------------------------------------------------

        # Method-local variable declarations
        for variable in method.variable_declarations:
            candidate_assignment_targets.append([variable.name, variable.type])

        # Class fields (including inherited) for constructor assignment matching
        candidate_assignment_targets.extend(
            self.__get_all_field_declarations(test_class)
        )

        # -------------------------------------------------------------------------
        # Phase 2: Process method parameters as potential focal classes
        # -------------------------------------------------------------------------
        for param in method.parameters:
            types = self.base_types(param.type)
            for type_name in types:
                if type_name and type_name in self.application_classes:
                    is_application_class_used = True
                    variables[param.name] = type_name
                    parameter_types.append([param.name, type_name])

        # -------------------------------------------------------------------------
        # Phase 3: Process local variable declarations
        # Note: Fields are NOT processed here because they often have interface/abstract
        # types while concrete types are assigned via constructor calls below.
        # -------------------------------------------------------------------------
        for variable_declaration in method.variable_declarations:
            types = self.base_types(variable_declaration.type)
            for type_name in types:
                if type_name and type_name in self.application_classes:
                    is_application_class_used = True
                    variables[variable_declaration.name] = type_name
                elif type_name:
                    # Try to match by short name when fully qualified name unavailable
                    for class_name in self.application_classes:
                        if type_name == class_name.split(".")[-1]:
                            variables[variable_declaration.name] = class_name
                            break

        # -------------------------------------------------------------------------
        # Phase 4: Process constructor calls to map variables to concrete types
        # This handles cases like: Parser parser = new GnuParser()
        # -------------------------------------------------------------------------
        for call_site in method.call_sites:
            if call_site.is_constructor_call:
                if (
                    call_site.return_type
                    and call_site.return_type in self.application_classes
                ):
                    is_application_class_used = True
                    all_supertypes = self.reachability.get_all_supertypes(
                        call_site.return_type
                    )

                    for variable in candidate_assignment_targets:
                        # Prefer exact type match
                        if variable[1] == call_site.return_type:
                            variables[variable[0]] = call_site.return_type
                        # Match if variable type is a supertype of constructed type
                        elif variable[1] in all_supertypes:
                            variables[variable[0]] = call_site.return_type
                        # Fall back to short name when fully qualified unavailable
                        elif (not variable[1] or "." not in variable[1]) and variable[
                            1
                        ].split(".")[-1] == call_site.return_type.split(".")[-1]:
                            variables[variable[0]] = call_site.return_type

        # -------------------------------------------------------------------------
        # Phase 5: Process non-constructor call sites
        # -------------------------------------------------------------------------
        for call_site in method.call_sites:
            if not call_site.is_constructor_call:
                types = self.base_types(call_site.receiver_type)

                # 5a: Handle static method calls (e.g., Utils.parse())
                if call_site.is_static_call:
                    for type_name in types:
                        if type_name and type_name in self.application_classes:
                            is_application_class_used = True
                            static_types[type_name.lower()] = type_name

                            # Track variables assigned from static call results
                            decl_param_types = [
                                [vd.initializer, vd.name]
                                for vd in method.variable_declarations
                            ]
                            decl_param_types.extend(parameter_types)

                            for v_decl in decl_param_types:
                                if (
                                    v_decl[0]
                                    and call_site.receiver_expr
                                    and call_site.receiver_expr in v_decl[0]
                                ):
                                    variables[v_decl[1]] = type_name

                # 5b: Track called methods as potential focal methods (excluding getters)
                for type_name in types:
                    if type_name and type_name in self.application_classes:
                        is_application_class_used = True
                        callee_signature = ""

                        if any(
                            call_site.method_name.startswith(getter_method)
                            for getter_method in GETTER_PREFIXES
                        ):
                            # Only include getter-like methods if they don't match field names
                            if not self.__is_getter_method(
                                qualified_class_name=type_name,
                                method_name=call_site.method_name,
                            ):
                                callee_signature = call_site.callee_signature
                        else:
                            callee_signature = call_site.callee_signature

                        if callee_signature != "":
                            if type_name in all_possible_focal_methods:
                                all_possible_focal_methods[type_name].append(
                                    callee_signature
                                )
                            else:
                                all_possible_focal_methods[type_name] = [
                                    callee_signature
                                ]

                # 5c: Match return types to declared variables
                types.extend(self.base_types(call_site.return_type))
                for type_name in types:
                    if type_name and type_name in self.application_classes:
                        is_application_class_used = True
                        for variable in candidate_assignment_targets:
                            if variable[1] == type_name:
                                variables[variable[0]] = type_name
                            elif (
                                not variable[1] or "." not in variable[1]
                            ) and variable[1].split(".")[-1] == type_name.split(".")[
                                -1
                            ]:
                                variables[variable[0]] = type_name

                    # 5d: Handle static nested class receivers
                    receiver_types = self.base_types(call_site.receiver_type)
                    for receiver_type in receiver_types:
                        receiver_class_details = self.analysis.get_class(receiver_type)
                        if (
                            receiver_class_details is not None
                            and receiver_type in self.application_classes
                        ):
                            is_application_class_used = True
                            if (
                                receiver_class_details.modifiers
                                and "static" in receiver_class_details.modifiers
                            ):
                                variables[receiver_type.lower()] = receiver_type

        # -------------------------------------------------------------------------
        # Phase 6: Producer-consumer filtering
        # Remove variables passed as arguments to other application class methods,
        # as these are likely "producers" rather than the focal class under test.
        # -------------------------------------------------------------------------
        accessed_arguments = self.get_arguments(method_details=method)
        for arg in accessed_arguments:
            base_var = self._extract_base_variable(arg)
            if base_var and base_var in variables:
                _ = variables.pop(base_var)

        # -------------------------------------------------------------------------
        # Phase 7: Build focal methods map for remaining focal class candidates
        # -------------------------------------------------------------------------
        for variable in variables:
            if variables[variable] in all_possible_focal_methods:
                if variables[variable] not in focal_methods:
                    focal_methods[variables[variable]] = all_possible_focal_methods[
                        variables[variable]
                    ]

        # Fallback: if all instance variables were filtered out, use static types
        if len(variables) == 0 and len(static_types) > 0:
            for static_type in static_types:
                if static_types[static_type] in all_possible_focal_methods:
                    if static_types[static_type] not in focal_methods:
                        focal_methods[static_types[static_type]] = (
                            all_possible_focal_methods[static_types[static_type]]
                        )
            return static_types, focal_methods, is_application_class_used

        return variables, focal_methods, is_application_class_used

    # -------------------------------------------------------------------------
    # Helper methods for field and type introspection
    # -------------------------------------------------------------------------

    def __get_all_fields(self, qualified_class_name: str) -> List[str]:
        """
        Get all field names from a class and its parents.

        Args:
            qualified_class_name: Fully qualified class name

        Returns:
            List[str]: List of field names including inherited fields
        """
        fields = []
        class_details = self.analysis.get_class(qualified_class_name)

        if class_details is not None:
            for f in class_details.field_declarations:
                for field in f.variables:
                    fields.append(field)

            extends_list = class_details.extends_list or []
            for extend in extends_list:
                fields.extend(self.__get_all_fields(extend))

        return fields

    def __get_all_field_declarations(
        self, qualified_class_name: str
    ) -> List[List[str]]:
        """
        Get all field declarations (name and type) from a class and its parents.

        Args:
            qualified_class_name: Fully qualified class name

        Returns:
            List[List[str]]: List of [field_name, field_type] pairs including inherited fields
        """
        field_declarations = []
        class_details = self.analysis.get_class(qualified_class_name)

        if class_details is not None:
            for declared_var in class_details.field_declarations:
                for variable in declared_var.variables:
                    field_declarations.append([variable, declared_var.type])

            extends_list = class_details.extends_list or []
            for extend in extends_list:
                field_declarations.extend(self.__get_all_field_declarations(extend))

        return field_declarations

    def __is_getter_method(self, qualified_class_name: str, method_name: str) -> bool:
        """
        Checks if method is a simple getter by matching against class field names.
        Used to filter out trivial getters from focal method lists.

        Args:
            qualified_class_name: Fully qualified class name
            method_name: Name of the method to check

        Returns:
            bool: True if method is a getter for a field
        """
        fields = self.__get_all_fields(qualified_class_name)

        for getter_prefix in GETTER_PREFIXES:
            if method_name.startswith(getter_prefix):
                method_name = method_name.replace(getter_prefix, "", 1)

        for field in fields:
            if field.lower() == method_name.lower():
                return True

        return False

    # -------------------------------------------------------------------------
    # Producer-consumer relationship detection
    # -------------------------------------------------------------------------

    def get_arguments(self, method_details: JCallable) -> List[str]:
        """
        Collect arguments that indicate producer-consumer relationships.

        Only considers arguments passed to OTHER application class methods,
        not to loggers, utilities, or non-application classes. This prevents
        incorrectly filtering out focal classes that happen to be logged.

        Args:
            method_details: The method to analyze for argument expressions

        Returns:
            List[str]: List of argument expressions passed to application class methods
        """
        arguments = []

        for call_site in method_details.call_sites:
            if (
                call_site.receiver_type
                and call_site.receiver_type in self.application_classes
            ):
                if call_site.method_name not in self.assertion_methods:
                    arguments.extend(call_site.argument_expr)

        return arguments

    # -------------------------------------------------------------------------
    # Type parsing utilities
    # -------------------------------------------------------------------------

    def base_types(self, type_str: str) -> List[str]:
        """
        Extract all component types from a generic type string.
        E.g., 'Map<String, List<User>>' -> ['Map', 'String', 'List', 'User']

        Uses regex to extract all Java identifiers, which correctly handles
        nested generics without complex state-machine parsing.

        Args:
            type_str: Complex type string potentially with generics

        Returns:
            List[str]: All component types extracted from the string
        """
        if not type_str:
            return []
        return _JAVA_IDENT.findall(type_str)

    @staticmethod
    def _strip_generics(type_str: str) -> str:
        """
        Strip generic type parameters: 'Repository<User>' -> 'Repository'

        Args:
            type_str: Type string potentially with generic parameters

        Returns:
            str: Type string with generic parameters removed
        """
        if not type_str:
            return ""
        idx = type_str.find("<")
        return type_str[:idx] if idx != -1 else type_str

    def _extract_base_variable(self, arg_expr: str) -> str:
        """
        Extract base variable name from expression: 'obj.method()' -> 'obj'

        Args:
            arg_expr: Argument expression string

        Returns:
            str: Base variable name or empty string if not found
        """
        if not arg_expr:
            return ""
        match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)", arg_expr.strip())
        return match.group(1) if match else ""

    @staticmethod
    def node_to_txt(src_code, node):
        """
        Convert AST node to source text.

        Args:
            src_code: Source code string
            node: AST node with start_byte and end_byte attributes

        Returns:
            str: Source text for the node, or None if node is None
        """
        if node is None:
            return None
        return src_code[node.start_byte : node.end_byte].strip()
