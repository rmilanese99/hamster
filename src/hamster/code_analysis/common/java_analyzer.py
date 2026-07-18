import json
import re
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal, cast, overload

from cldk.analysis.java import JavaAnalysis
from cldk.models.java import JCallable

from hamster.code_analysis.model.models import CallableDetails, TestingFramework
from hamster.code_analysis.utils import constants
from hamster.code_analysis.utils.constants import (
    GETTER_PREFIXES,
    TEST_ANNOTATIONS,
    TEST_DIRS,
)

from .exceptions import (
    ClassFileNotFoundException,
    ClassNotFoundException,
    CompilationUnitNotFoundException,
    MethodNotFoundException,
)


def dataclass_serializer(obj):
    """
    Helper function to serialize dataclass objects.
    If the object is a dataclass instance, it returns the dictionary of its fields.
    If the object is an Enum, it returns the enum value.
    Raises TypeError if the object is neither a dataclass instance nor an Enum.
    """
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    if isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"Type {type(obj)} not serializable")


@dataclass
class ReachabilityConfig:
    allow_repetition: bool = False  # On same level
    only_helpers: bool = False
    add_extended_class: bool = False
    test_utility_classes: list[str] = field(default_factory=list)


class CommonAnalysis:
    """
    Class to encapsulate common code analysis operations on Java code.
    """

    def __init__(self, analysis: JavaAnalysis):
        """
        Initialize with a JavaAnalysis instance.
        """
        self.analysis = analysis

    def get_ncloc(self, declaration: str, body: str) -> int:
        """
        Get the number of non-comment lines.
        Args:
            declaration: The declaration part of the code.
            body: The body part of the code.
        Returns:
            int: Number of non-comment lines.
        """
        code = declaration + body
        code_lines = self.__get_non_comment_lines(code)
        body_lines = self.__get_non_comment_lines(body)
        if (
            body_lines == ["}"]
            or len(body_lines) == 0
            or body_lines == ["{}"]
            or body_lines == ["{", "}"]
        ):
            return 0
        return len(code_lines)

    @staticmethod
    def __get_non_comment_lines(code: str) -> list[str]:
        """
        Helper method to get non-comment lines from a block of code.
        Args:
            code: The code to process.
        Returns:
            List[str]: List of lines with comments removed.
        """
        code_lines = []
        inside_block_comment = False
        lines = code.splitlines()
        for line in lines:
            stripped = line.strip()

            # Handle ongoing block comments
            if inside_block_comment:
                if "*/" in stripped:
                    inside_block_comment = False
                continue

            # Handle block comment start
            if stripped.startswith("/*"):
                inside_block_comment = True
                if "*/" in stripped:  # handle one-line block comments
                    inside_block_comment = False
                continue

            # Remove inline // comments
            no_inline_comment = re.sub(r"//.*", "", line).strip()

            # Skip empty lines after comment removal
            if no_inline_comment == "":
                continue

            code_lines.append(no_inline_comment)

        return code_lines

    def is_mocking_used(
        self,
        test_class_qualified_name: str,
        method_signature: str,
        extend_class_list: list[str] | None = None,
    ) -> int:
        """
        Determine if mocking is used in a method.

        Args:
            test_class_qualified_name: The full name of the test class.
            method_signature: The signature of the method.
            extend_class_list: List of class names to extend the search.

        Returns:
            int: Count of mocking usage.

        Raises:
            ClassNotFoundException: If the test class cannot be found.
        """
        if extend_class_list is None:
            extend_class_list = []

        # Validate that the primary class exists
        if not self.analysis.get_class(test_class_qualified_name):
            raise ClassNotFoundException(test_class_qualified_name)

        count = 0
        extend_class_list.append(test_class_qualified_name)
        method_details = None
        found_class_name = test_class_qualified_name
        # Search for the method in the extended class list (e.g., for inheritance hierarchies)
        for class_name in extend_class_list:
            class_temp = self.analysis.get_class(class_name)
            if class_temp:
                all_methods_in_class = self.analysis.get_methods_in_class(class_name)
                for method in all_methods_in_class:
                    if all_methods_in_class[method].signature == method_signature:
                        found_class_name = class_name
                        method_details = self.analysis.get_method(
                            class_name, method_signature
                        )
        if method_details is None:
            return 0

        # Retrieve class details for the class where the method was found
        # Must be truthy if method_details
        class_details = self.analysis.get_class(found_class_name)

        # Retrieve imports once for efficiency
        # Class must exist for method_details to be truthy
        class_imports = self.get_class_imports(
            qualified_class_name=found_class_name,
            is_add_application_class=False,
        )
        has_mockito = any(
            class_import.startswith("org.mockito") for class_import in class_imports
        )
        has_easymock = any(
            class_import.startswith("org.easymock") for class_import in class_imports
        )

        # Check for mocked fields (e.g., @Mock annotations or MockMvc types)
        accessed_fields = method_details.accessed_fields
        for accessed_field in accessed_fields:
            # Check if the field is declared in the same test class
            if accessed_field.startswith(found_class_name + "."):
                field_name = accessed_field.split(".")[-1]

                # Get all the declared fields
                class_fields = class_details.field_declarations
                # Match by field name
                for class_field in class_fields:
                    is_field_found = False
                    for variable in class_field.variables:
                        if variable == field_name:
                            is_field_found = True
                            break
                    # If match found, then check if @Mock in the annotation or type is MockMvc
                    if is_field_found:
                        # MockMvc for springtest
                        if class_field.type.split(".")[-1] == "MockMvc":
                            count += 1
                        for annotation in class_field.annotations:
                            if annotation.startswith("@Mock"):
                                count += 1

        # Initialize flags for WireMock
        is_wire_mock = False
        # Check class annotations for @WireMockTest
        for annotation in class_details.annotations or []:
            if annotation.startswith("@WireMockTest"):
                is_wire_mock = True
        # Check method annotations for @WireMockTest
        for annotation in method_details.annotations or []:
            if annotation.startswith("@WireMockTest"):
                is_wire_mock = True

        # Single loop over call sites to check for various mocking patterns
        for call_site in method_details.call_sites:
            callee_signature = call_site.callee_signature
            # Handle cases where receiver_type might be None
            receiver_type = call_site.receiver_type or ""
            receiver_last = receiver_type.lower().split(".")[-1]

            # Pattern: MyService service = mock(MyService.class);
            if callee_signature.startswith("mock"):
                count += 1

            # Specific to Mockito: when, thenReturn, verify, given, willReturn
            if has_mockito and (
                callee_signature.startswith("when")
                or callee_signature.startswith("thenReturn")
                or callee_signature.startswith("verify")
                or callee_signature.startswith("given")
                or callee_signature.startswith("willReturn")
            ):
                count += 1

            # Specific to EasyMock: expect, andReturn, replay
            if has_easymock and (
                callee_signature.startswith("expect")
                or callee_signature.startswith("andReturn")
                or callee_signature.startswith("replay")
            ):
                count += 1

            # PowerMock pattern: e.g., PowerMockito.whenNew(MyClass.class)
            if receiver_last.startswith("powermockito"):
                count += 1

            # WireMock pattern: e.g., WireMock wireMock = wmRuntimeInfo.getWireMock();
            if receiver_last.startswith("wiremock"):
                is_wire_mock = True

            # MockServer pattern: e.g., new MockServerClient("127.0.0.1", 1080).when(request())
            if receiver_last.startswith("mockserver"):
                count += 1

        # Add to count if any indicator of WireMock was found
        if is_wire_mock:
            count += 1

        return count

    def get_class_imports(
        self, qualified_class_name: str, is_add_application_class: bool = True
    ) -> list[str]:
        """
        Get the imports for a specific class.

        Args:
            qualified_class_name: The full name of the class.
            is_add_application_class: Flag to determine if application classes should be included.

        Returns:
            List[str]: List of imported class names.

        Raises:
            ClassFileNotFoundException: If the Java file for the class cannot be found.
            CompilationUnitNotFoundException: If the compilation unit cannot be resolved.
        """
        # Get the Java file and compilation unit for the specific class
        java_file = self.analysis.get_java_file(qualified_class_name)

        if not java_file:
            raise ClassFileNotFoundException(qualified_class_name)

        compilation_unit = self.analysis.get_java_compilation_unit(file_path=java_file)

        if not compilation_unit:
            raise CompilationUnitNotFoundException(java_file)

        imports = compilation_unit.imports
        project_root = self.__get_project_root()

        # Filter imports based on flag
        if not is_add_application_class:
            return [imp for imp in imports if not imp.startswith(project_root)]
        return imports

    def get_imports(
        self, is_add_application_class: bool = False
    ) -> dict[tuple[str, ...], list[str]]:
        """
        Get imports from applications.
        Args:
            is_add_application_class: Add application classes flag.
        Returns:
            dict: Dictionary containing imports and related classes.
            key: List of imports, value: List of classes.
        """
        import_details = {}
        compilation_units = self.analysis.get_compilation_units()
        project_root = self.__get_project_root()
        for compilation_unit in compilation_units:
            classes = list(compilation_unit.type_declarations.keys())
            imports = compilation_unit.imports
            filtered_imports = [
                imp
                for imp in imports
                if is_add_application_class or not imp.startswith(project_root)
            ]
            import_details[tuple(filtered_imports)] = classes

        return import_details

    def __get_project_root(self) -> str:
        """
        Get the project root from class names.
        Returns:
            str: The common root of the project.
        """
        classes = list(self.analysis.get_classes().keys())
        split_class_names = [s.split(".") for s in classes]

        if not split_class_names:
            return ""

        # Find the shortest length of the split strings
        min_length = min(len(s) for s in split_class_names)

        project_root = []

        # Iterate through the indices up to min_length to find common prefix
        for i in range(min_length):
            # Get the set of elements at index i
            elements = set(s[i] for s in split_class_names)

            # If all elements are the same at this position, add to common_parts
            if len(elements) == 1:
                project_root.append(elements.pop())
            else:
                break

        # Join back with '.' to return the common prefix
        return ".".join(project_root)

    def is_likely_getter(
        self, qualified_class_name: str, method_signature: str
    ) -> bool:
        """
        Determine if a method is likely a getter based on naming conventions and structure.

        Args:
            qualified_class_name: The full name of the class.
            method_signature: The signature of the method.

        Returns:
            bool: True if the method is likely a getter, False otherwise.
        """
        method_name: str = method_signature.partition("(")[0]
        lower_name: str = method_name.lower()

        class_details = self.analysis.get_class(qualified_class_name)
        if not class_details:
            return False

        method_details = self.analysis.get_method(
            qualified_class_name, method_signature
        )
        if not method_details:
            return False

        # Ensure a field exists in the class to get
        if not class_details.field_declarations:
            return False

        # Getters usually don't have parameters
        if method_details.parameters:
            return False

        # First match prefix
        matched_prefix = None
        for prefix in GETTER_PREFIXES:
            if lower_name.startswith(prefix):
                # Ensure there is something after prefix
                if len(lower_name) > len(prefix):
                    matched_prefix = prefix
                    break

        if not matched_prefix:
            return False

        # Check field match
        suffix_lower = lower_name[len(matched_prefix) :].strip("_")
        lower_field_names = [
            var.lower().strip("_")
            for field in class_details.field_declarations
            for var in field.variables
        ]

        if not lower_field_names or suffix_lower not in lower_field_names:
            return False

        return True

    def is_test_class(
        self, qualified_class_name: str, testing_frameworks: list[TestingFramework]
    ) -> bool:
        """
        Determine if a class is a test class, which is when there exists a test method.
        Args:
            qualified_class_name: The full name of the class.
            testing_frameworks: List of testing frameworks.
        Returns:
            bool: True if the class is a test class, False otherwise.
        """
        return any(
            self.is_test_method(
                method_signature, qualified_class_name, testing_frameworks
            )
            for method_signature in self.analysis.get_methods_in_class(
                qualified_class_name
            )
        )

    def is_test_method(
        self,
        method_signature: str,
        qualified_class_name: str,
        testing_frameworks: list[TestingFramework],
        only_ascii: bool = True,
    ) -> bool:
        """
        Determine if a method is a test method.

        Args:
            method_signature: The signature of the method.
            qualified_class_name: The full name of the class containing the method.
            testing_frameworks: List of testing frameworks.

        Returns:
            bool: True if the method is a test method, False otherwise.
        """
        method_details = self.analysis.get_method(
            qualified_class_name, method_signature
        )

        if not method_details:
            return False

        if only_ascii and not method_details.code.isascii():
            return False

        class_details = self.analysis.get_class(qualified_class_name)

        if not class_details:
            return False

        is_public = "public" in (method_details.modifiers or [])

        # Check for standard test annotations on the method
        has_test_annot = any(
            annot.split("(")[0] in TEST_ANNOTATIONS
            for annot in method_details.annotations or []
        )

        # Check for JUnit3 style test methods
        is_junit3_test = (
            TestingFramework.JUNIT3 in testing_frameworks
            and any(
                ext.endswith("TestCase") for ext in class_details.extends_list or []
            )
            and method_signature.startswith("test")
            and is_public
            and method_details.return_type == "void"
            and len(method_details.parameters or []) == 0
        )

        # Check for TestNG style, including class-level @Test
        is_testng_test = (
            TestingFramework.TESTNG in testing_frameworks
            and any(
                annot.split("(")[0] == "@Test"
                for annot in class_details.annotations or []
            )
            and is_public
        )

        return has_test_annot or is_junit3_test or is_testng_test

    def get_testing_frameworks_for_class(
        self, qualified_class_name: str
    ) -> list[TestingFramework]:
        """
        Get the list of testing frameworks for a class.

        Args:
            qualified_class_name: The full name of the class.

        Returns:
            list[TestingFramework]: List of testing frameworks.

        Raises:
            ClassFileNotFoundException: If the Java file for the class cannot be found.
            CompilationUnitNotFoundException: If the compilation unit cannot be resolved.
        """
        java_file = self.analysis.get_java_file(qualified_class_name)

        if not java_file:
            raise ClassFileNotFoundException(qualified_class_name)

        compilation_unit = self.analysis.get_java_compilation_unit(file_path=java_file)

        if not compilation_unit:
            raise CompilationUnitNotFoundException(java_file)

        testing_frameworks: set[TestingFramework] = set()
        # Check imports against known framework prefixes
        for imp in compilation_unit.imports or []:
            for prefix, name in constants.SORTED_FRAMEWORK_PREFIXES:
                if imp.startswith(prefix):
                    testing_frameworks.add(name)
                    break
        return sorted(testing_frameworks, key=lambda x: len(x.value), reverse=True)

    def get_application_call_details(
        self, method_details: JCallable
    ) -> list[CallableDetails]:
        """
        Get all application calls.
        Args:
            method_details: Details of the method.
        Returns:
            List[CallableDetails]: List of callable details.
        """
        callable_details = []
        for call_site in method_details.call_sites:
            receiver_type = call_site.receiver_type
            if self.analysis.get_class(receiver_type):
                callee_method = self.analysis.get_method(
                    receiver_type, call_site.callee_signature
                )
                callable_details.append(
                    CallableDetails(
                        method_name=call_site.callee_signature,
                        argument_types=call_site.argument_types,
                        receiver_type=receiver_type,
                        method_code=None
                        if callee_method is None
                        else callee_method.code,
                    )
                )

        return callable_details

    def get_library_call_details(
        self, method_details: JCallable
    ) -> list[CallableDetails]:
        """
        Get all library calls.
        Args:
            method_details: Details of the method.
        Returns:
            List[CallableDetails]: List of callable details.
        """
        callable_details = []
        for call_site in method_details.call_sites:
            receiver_type = call_site.receiver_type
            if self.analysis.get_class(receiver_type) is None and receiver_type != "":
                callable_details.append(
                    CallableDetails(
                        method_name=call_site.callee_signature,
                        argument_types=call_site.argument_types,
                        receiver_type=receiver_type,
                        method_code=None,
                    )
                )

        return callable_details

    @staticmethod
    def get_constructor_call_details(
        method_details: JCallable,
    ) -> list[CallableDetails]:
        """
        Get all constructor calls.
        Args:
            method_details: Details of the method.
        Returns:
            List[CallableDetails]: List of constructor call details.
        """
        callable_details = []
        # Check call sites for constructor invocations
        for call_site in method_details.call_sites:
            if "new " in call_site.receiver_expr or call_site.is_constructor_call:
                callable_details.append(
                    CallableDetails(
                        method_name=call_site.callee_signature,
                        argument_types=call_site.argument_types,
                        receiver_type=call_site.receiver_type
                        if call_site.receiver_type != ""
                        else None,
                    )
                )
        # Check variable declarations for constructor initializers
        for variable in method_details.variable_declarations:
            if "new " in variable.initializer:
                callable_details.append(
                    CallableDetails(
                        method_name=variable.type.split(".")[-1]
                        if variable.type != ""
                        else "",
                        argument_types=[],
                        receiver_type=variable.type if variable.type != "" else None,
                    )
                )
        return callable_details

    def categorize_classes(
        self,
    ) -> tuple[dict[str, list[str]], list[str], list[str]]:
        """
        Categorize all classes into test classes, application classes, and test utility classes.

        Test utility classes are classes located in test directories (e.g., src/test/java) that
        do not contain any test methods. These are typically helper classes, fixtures, or
        base classes used by test code.

        Returns:
            Tuple containing:
                - Dict[str, List[str]]: Mapping of test class names to their test method signatures
                - List[str]: Application class names (production code)
                - List[str]: Test utility class names (test helpers without test methods)
        """
        test_classes_methods = {}
        application_classes = []
        test_utility_classes = []

        for q_class in self.analysis.get_classes():
            java_file = self.analysis.get_java_file(q_class)
            if not java_file:
                continue

            is_in_test_dir = any(test_dir in java_file for test_dir in TEST_DIRS)

            testing_frameworks = self.get_testing_frameworks_for_class(q_class)

            if not testing_frameworks:
                # Classes in test directories without testing imports are test utilities
                if is_in_test_dir:
                    test_utility_classes.append(q_class)
                else:
                    application_classes.append(q_class)
                continue

            test_methods = []
            for method_sig in self.analysis.get_methods_in_class(q_class):
                if self.is_test_method(method_sig, q_class, testing_frameworks):
                    test_methods.append(method_sig)

            if test_methods:
                test_classes_methods[q_class] = test_methods
            else:
                # Class has testing framework imports but no test methods
                if is_in_test_dir:
                    test_utility_classes.append(q_class)
                else:
                    application_classes.append(q_class)

        return test_classes_methods, application_classes, test_utility_classes

    @staticmethod
    def print_list_of_pydantic(list_: list) -> None:
        """
        Print a Pydantic list in JSON format.
        Args:
            list_: The list of Pydantic models.
        """
        json_str = json.dumps(
            [item.model_dump(mode="json") for item in list_], indent=4
        )
        print(json_str)

    @staticmethod
    def print_dataclass(obj: Any) -> None:
        """
        Print a dataclass object in JSON format.
        Args:
            obj: The dataclass object.
        """
        json_str = json.dumps(obj, default=dataclass_serializer, indent=4)
        print(json_str)

    @staticmethod
    def package_of(qualified_class_name: str) -> str:
        i = qualified_class_name.rfind(".")
        return qualified_class_name[:i] if i != -1 else ""

    def is_subclass_of(self, sub_class: str, super_class: str) -> bool:
        """
        Check if a class is a subclass of another class.

        Args:
            sub_class: The potential subclass.
            super_class: The potential superclass.

        Returns:
            bool: True if sub_class is a subclass of super_class.
        """
        if not sub_class or not super_class or sub_class == super_class:
            return False

        sub_info = self.analysis.get_class(sub_class)
        if not sub_info:
            return False

        stack = list(sub_info.extends_list or [])
        seen: set[str] = set()

        while stack:
            curr = stack.pop()
            if curr in seen:
                continue
            if curr == super_class:
                return True
            seen.add(curr)

            curr_info = self.analysis.get_class(curr)
            if curr_info:
                stack.extend(curr_info.extends_list or [])

        return False

    def is_accessible_from(
        self,
        owner_class: str,
        method_signature: str,
        *,
        accessor_class: str,
        mode: Literal["public", "same_package", "same_package_or_subclass"] = "public",
    ) -> bool:
        """
        Check if a method is accessible from the given accessor context.

        Args:
            owner_class: The class that owns the method.
            method_signature: The method signature.
            accessor_class: The class trying to access the method.
            mode: The visibility mode.

        Returns:
            bool: True if the method is accessible. Returns False if accessor_class
                  does not exist in the analysis (for non-public modes).

        Raises:
            ClassNotFoundException: If the owner class cannot be found.
            MethodNotFoundException: If the method cannot be found in the owner class.
        """
        class_details = self.analysis.get_class(owner_class)
        if not class_details:
            raise ClassNotFoundException(owner_class)

        method_details = self.analysis.get_method(owner_class, method_signature)
        if not method_details:
            raise MethodNotFoundException(owner_class, method_signature)

        mods = set(method_details.modifiers or [])
        owner_pkg = CommonAnalysis.package_of(owner_class)

        # Public methods and interface/annotation non-private methods are always visible
        if "public" in mods:
            return True
        if class_details.is_interface or class_details.is_annotation_declaration:
            if "private" not in mods:
                return True

        # Implicit public constructor for public class
        if (
            method_details.is_constructor
            and method_details.is_implicit
            and "public" in (class_details.modifiers or [])
        ):
            return True

        # Determined all public accessibility options
        if mode == "public":
            return False

        # For non-public checks, accessor_class must exist in the analysis
        if accessor_class and not self.analysis.get_class(accessor_class):
            return False

        # Determine accessor package
        acc_pkg = CommonAnalysis.package_of(accessor_class) if accessor_class else ""

        # Same package rules
        if owner_pkg == acc_pkg:
            if "private" in mods:
                return False
            return True

        # If different package and not public, it is not accessible
        if mode == "same_package":
            return False

        # Check for subclass inheritance of protected method
        if (
            "protected" in mods
            and accessor_class
            and self.is_subclass_of(accessor_class, owner_class)
        ):
            return True

        return False


class Reachability:
    def __init__(self, analysis: JavaAnalysis):
        self.analysis = analysis
        self._common = CommonAnalysis(analysis)
        self._reachability_cache: dict[tuple[Any, ...], dict[str, list[str]]] = {}
        self._inheritance_cache: dict[tuple[str, tuple[str, ...]], list[str]] = {}

    def get_inheritance_chain(
        self, qualified_class_name: str, filter_by_modifier: list[str] | None = None
    ) -> list[str]:
        """
        Get the list of application classes in the inheritance chain.

        Args:
            qualified_class_name: Qualified class name.
            filter_by_modifier: Optional list of modifiers to filter the classes.

        Returns:
            list[str]: List of class names in the inheritance chain.
        """
        if filter_by_modifier is None:
            filter_by_modifier = []

        cache_key = (qualified_class_name, tuple(filter_by_modifier))
        if cache_key in self._inheritance_cache:
            return self._inheritance_cache[cache_key]

        inheritance_chain: list[str] = []
        extends_list = self.analysis.get_extended_classes(
            qualified_class_name=qualified_class_name
        )
        for extend in extends_list:
            extend_class_details = self.analysis.get_class(qualified_class_name=extend)
            if extend_class_details:
                if len(filter_by_modifier) > 0 and extend_class_details.modifiers:
                    for modifier in extend_class_details.modifiers:
                        if modifier in filter_by_modifier:
                            inheritance_chain.append(extend)
                            inheritance_chain.extend(
                                self.get_inheritance_chain(
                                    qualified_class_name=extend,
                                    filter_by_modifier=filter_by_modifier,
                                )
                            )
                else:
                    inheritance_chain.append(extend)
                    inheritance_chain.extend(
                        self.get_inheritance_chain(
                            qualified_class_name=extend,
                            filter_by_modifier=filter_by_modifier,
                        )
                    )

        self._inheritance_cache[cache_key] = inheritance_chain
        return inheritance_chain

    def get_all_supertypes(self, qualified_class_name: str) -> list[str]:
        """
        Get all supertypes (superclasses and implemented interfaces) of a class.

        This includes both the inheritance chain (extends) and all directly or
        transitively implemented interfaces.

        Args:
            qualified_class_name: Qualified class name.

        Returns:
            list[str]: List of all supertype names (classes and interfaces).
        """
        supertypes: list[str] = []
        visited: set[str] = set()
        queue: list[str] = [qualified_class_name]

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            class_details = self.analysis.get_class(current)
            if not class_details:
                continue

            # Add parent classes
            if class_details.extends_list:
                for parent in class_details.extends_list:
                    if parent not in visited:
                        supertypes.append(parent)
                        queue.append(parent)

            # Add implemented interfaces
            if class_details.implements_list:
                for interface in class_details.implements_list:
                    if interface not in visited:
                        supertypes.append(interface)
                        queue.append(interface)

        return supertypes

    def has_external_inheritance(self, qualified_class_name: str) -> bool:
        """
        Check if a class has any external (non-application) types in its inheritance hierarchy.

        Args:
            qualified_class_name: Qualified class name (must be in the analyzed codebase).

        Returns:
            bool: True if any supertype is external (not in analyzed codebase).
        """
        class_details = self.analysis.get_class(qualified_class_name)
        if class_details is None:
            return False

        visited: set[str] = {qualified_class_name}
        queue: list[str] = []

        queue.extend(class_details.extends_list or [])
        queue.extend(class_details.implements_list or [])

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            parent_details = self.analysis.get_class(current)
            if parent_details is None:
                return True

            queue.extend(parent_details.extends_list or [])
            queue.extend(parent_details.implements_list or [])

        return False

    def find_method_in_hierarchy(
        self, qualified_class_name: str, method_signature: str
    ) -> JCallable | None:
        """
        Find a method by searching the class hierarchy.

        Searches for a method in the following order:
        1. Directly in the specified class
        2. If concrete class: searches parent classes (inheritance chain)
        3. If abstract/interface: searches concrete subclasses

        Handles generic type parameters by stripping them before lookup.

        Args:
            qualified_class_name: The qualified class name (may include generics).
            method_signature: The method signature.

        Returns:
            Optional[JCallable]: The method details if found, None otherwise.
        """
        # Strip generic type parameters for class lookup
        base_class_name = self._strip_generics(qualified_class_name)

        method_details = self.analysis.get_method(base_class_name, method_signature)
        if method_details is not None:
            return method_details

        class_details = self.analysis.get_class(base_class_name)
        if class_details is not None:
            # If a concrete class
            if (
                class_details.modifiers
                and "abstract" not in class_details.modifiers
                and not class_details.is_interface
            ):
                # Check all the inherited methods
                inherited_classes = self.get_inheritance_chain(base_class_name)
                for inherited_class in inherited_classes:
                    inherited_method_details = self.analysis.get_method(
                        inherited_class, method_signature
                    )
                    if inherited_method_details is not None:
                        return inherited_method_details
            else:
                # Check all concrete subclasses in case of a non-concrete class
                concrete_classes = self.get_concrete_subclasses(base_class_name)
                for concrete_class in concrete_classes:
                    concrete_method_details = self.analysis.get_method(
                        concrete_class, method_signature
                    )
                    if concrete_method_details is not None:
                        return concrete_method_details

        return None

    def get_concrete_subclasses(self, qualified_class_name: str) -> list[str]:
        """
        Get all concrete subclasses of a class (for abstract classes or interfaces).

        Args:
            qualified_class_name: The qualified class name.

        Returns:
            list[str]: List of concrete subclass names.
        """
        concrete_classes: list[str] = []
        all_sub_classes = self.analysis.get_sub_classes(
            qualified_class_name=qualified_class_name
        )
        for sub_class in all_sub_classes:
            sub_class_details = all_sub_classes[sub_class]
            if (
                not sub_class_details.is_interface
                and "abstract" not in (sub_class_details.modifiers or [])
                and sub_class != qualified_class_name
            ):
                concrete_classes.append(sub_class)
        return concrete_classes

    def get_helper_methods(
        self,
        qualified_class_name: str,
        method_signature: str,
        depth: int = constants.CONTEXT_SEARCH_DEPTH,
        add_extended_class: bool = False,
        allow_repetition: bool = False,
        only_ascii: bool = True,
        test_utility_classes: list[str] | None = None,
    ) -> dict[str, list[str]]:
        """
        Retrieves the helper methods reachable from the given method within the specified depth.
        Helper methods are non-test methods called by the test method that reside in the test class,
        its inheritance chain, or designated test utility classes.

        Args:
            qualified_class_name: The qualified name of the class containing the method.
            method_signature: The signature of the method to analyze.
            depth: The maximum depth for traversing the call hierarchy.
            add_extended_class: If True, include methods from superclasses of the test class.
            allow_repetition: If True, allow the same method to appear multiple times when called
                at different points in the call graph.
            only_ascii: If True, skip methods with non-ASCII characters in their code.
            test_utility_classes: List of qualified class names that should be considered as valid
                sources of helper methods (in addition to the test class and its inheritance chain).

        Returns:
            dict[str, list[str]]: A map from class names to method signatures of helper methods.

        Raises:
            ClassNotFoundException: If the class cannot be found.
            MethodNotFoundException: If the method cannot be found in the class.
        """
        class_details = self.analysis.get_class(qualified_class_name)
        if not class_details:
            raise ClassNotFoundException(qualified_class_name)

        method_details = self.analysis.get_method(
            qualified_class_name, method_signature
        )
        if not method_details:
            raise MethodNotFoundException(qualified_class_name, method_signature)

        visited: set[tuple[str, str]] = set()
        reachability_config = ReachabilityConfig(
            allow_repetition=allow_repetition,
            add_extended_class=add_extended_class,
            only_helpers=True,
            test_utility_classes=test_utility_classes or [],
        )
        reachability_key = self._get_reachability_key(
            qualified_class_name, method_signature, reachability_config
        )

        if reachability_key in self._reachability_cache:
            reachable_methods_by_class = self._reachability_cache[reachability_key]
        else:
            reachable_methods_by_class: dict[str, list[str]] = (
                self._collect_reachable_methods(
                    qualified_class_name,
                    method_signature,
                    depth,
                    reachability_config,
                    visited,
                )
            )
            self._reachability_cache[reachability_key] = reachable_methods_by_class

        final_reachable_methods: dict[str, list[str]] = {}
        for class_name in reachable_methods_by_class:
            for method_sig in reachable_methods_by_class[class_name]:
                method = self.analysis.get_method(class_name, method_sig)
                if (
                    method
                    and (class_name != qualified_class_name or method != method_details)
                    and (not only_ascii or method.code.isascii())
                ):
                    final_reachable_methods.setdefault(class_name, []).append(
                        method_sig
                    )
        return final_reachable_methods

    def _collect_reachable_methods(
        self,
        qualified_class_name: str,
        method_signature: str,
        depth: int,
        reachability_config: ReachabilityConfig,
        visited: set[tuple[str, str]] | None = None,
    ) -> dict[str, list[str]]:
        """
        Collects reachable methods starting from the given method within a given depth.

        Args:
            qualified_class_name: The qualified name of the class.
            method_signature: The method signature.
            depth: The depth for search in call hierarchy.
            reachability_config: The configurations for reachability computation.
            visited: The set of tuples that have already been visited.

        Returns:
            dict[str, list[str]]: A map from class names to method signatures of reachable methods.
        """
        if depth < 0:
            return {}

        if visited is None:
            visited = set()

        # Normalize constructors
        simple_class_name = qualified_class_name.split(".")[-1]
        if method_signature.startswith(f"{simple_class_name}("):
            method_signature = method_signature.replace(
                f"{simple_class_name}(", "<init>("
            )

        basic_key = (qualified_class_name, method_signature)

        # Check for an existing depth-level duplicate
        if basic_key in visited:
            return {}
        visited.add(basic_key)

        reachability_key = self._get_reachability_key(
            qualified_class_name, method_signature, reachability_config
        )

        # Check if already expanded in cache
        if reachability_key in self._reachability_cache:
            return self._reachability_cache[reachability_key]

        method_details = self.analysis.get_method(
            qualified_class_name, method_signature
        )

        # Check for ensuring valid method
        if not method_details:
            return {}

        # Seed result dictionary with the current method to start
        reachable_methods: dict[str, list[str]] = {
            qualified_class_name: [method_signature]
        }

        # Determine extended classes if needed
        extend_list: list[str] = []
        if reachability_config.add_extended_class:
            class_details = self.analysis.get_class(qualified_class_name)
            extend_list = (
                class_details.extends_list
                if class_details and class_details.extends_list
                else []
            )

        test_utility_set = set(reachability_config.test_utility_classes)

        child_counter: Counter[tuple[str, str]] = Counter()

        # Handle interface-based call sites
        interface_map: dict[str, list[str]] = {}
        for site in method_details.call_sites:
            receiver = site.receiver_type
            receiver_class = self.analysis.get_class(receiver)
            if receiver_class and receiver_class.is_interface:
                processed_sig = site.callee_signature
                interface_map.setdefault(receiver, []).append(processed_sig)

        # For all call sites with interface receiver types, collect the method signature
        for interface, callee_sigs in interface_map.items():
            for concrete_class in self.get_concrete_classes(interface_class=interface):
                # All concrete classes that implement interface
                if (
                    not reachability_config.only_helpers
                    or concrete_class == qualified_class_name
                    or concrete_class in test_utility_set
                ) or concrete_class in extend_list:
                    for callee_sig in callee_sigs:
                        child_counter[(concrete_class, callee_sig)] += 1

        # Handle direct symbol-table callees
        callees = self.analysis.get_callees(
            source_class_name=qualified_class_name,
            source_method_declaration=method_signature,
            using_symbol_table=True,
        ).get("callee_details", [])
        for callee_details in callees:
            callee_class = callee_details["callee_method"].klass
            if (
                not reachability_config.only_helpers
                or callee_class == qualified_class_name
                or callee_class in test_utility_set
            ) or callee_class in extend_list:
                callee_sig = callee_details["callee_method"].method.signature
                num_calls = max(len(callee_details.get("calling_lines", [])), 1)
                # Note: CLDK sometimes returns empty lists for calling_lines; assume if it exists, it occurs at least once
                # CLDK currently has a strange bug with calling_lines returning empty lists...
                # if num_calls == 0:
                #     raise Exception("A called method has no calling lines...")
                child_counter[(callee_class, callee_sig)] += num_calls

        # Now process unique children
        for child_key, num_calls in child_counter.items():
            child_class, child_sig = child_key
            child_reachable_methods = self._collect_reachable_methods(
                child_class, child_sig, depth - 1, reachability_config, visited
            )
            if reachability_config.allow_repetition:
                add_times = num_calls
            else:
                add_times = 1
            for _ in range(add_times):
                for child_c_class, methods_list in child_reachable_methods.items():
                    reachable_methods.setdefault(child_c_class, []).extend(methods_list)

        # This will allow a parent to revisit at the same level
        if reachability_config.allow_repetition:
            visited.remove(basic_key)

        return reachable_methods

    @staticmethod
    def _strip_generics(type_str: str) -> str:
        """Strip generic type parameters from a type string."""
        if not type_str:
            return ""
        idx = type_str.find("<")
        return type_str[:idx] if idx != -1 else type_str

    def get_concrete_classes(self, interface_class: str) -> list[str]:
        """
        Returns a list of concrete classes that implement the given interface class.

        Handles both exact matches and generic interface matches (e.g., searching
        for 'Repository' will match classes implementing 'Repository<User>').

        Args:
            interface_class: The interface class (with or without generic parameters).

        Returns:
            list[str]: List of concrete classes that implement the given interface class.
        """
        all_classes_in_application = self.analysis.get_classes()
        concrete_classes: list[str] = []
        base_interface = self._strip_generics(interface_class)

        for qualified_class, class_details in all_classes_in_application.items():
            if not class_details.is_interface and "abstract" not in (
                class_details.modifiers or []
            ):
                # Check for exact match or base interface match (handling generics)
                for impl in class_details.implements_list or []:
                    if (
                        impl == interface_class
                        or self._strip_generics(impl) == base_interface
                    ):
                        concrete_classes.append(qualified_class)
                        break
        return concrete_classes

    def _get_reachability_key(
        self,
        qualified_class_name: str,
        method_signature: str,
        reachability_config: ReachabilityConfig,
    ) -> tuple[Any, ...]:
        """
        Generates a unique key for the reachability computation based on the input parameters.

        Args:
            qualified_class_name: The qualified name of the class.
            method_signature: The method signature.
            reachability_config: The configurations for reachability computation.

        Returns:
            tuple[Any, ...]: A unique reachability key.
        """
        reachability_key = (
            qualified_class_name,
            method_signature,
            reachability_config.allow_repetition,
            reachability_config.add_extended_class,
            reachability_config.only_helpers,
            tuple(reachability_config.test_utility_classes),
        )
        return reachability_key

    @overload
    def get_visible_class_methods(
        self,
        qualified_class_name: str,
        *,
        visibility_mode: Literal[
            "public", "same_package", "same_package_or_subclass"
        ] = "public",
        include_metadata: Literal[False] = False,
    ) -> dict[str, list[str]]: ...

    @overload
    def get_visible_class_methods(
        self,
        qualified_class_name: str,
        *,
        visibility_mode: Literal[
            "public", "same_package", "same_package_or_subclass"
        ] = "public",
        include_metadata: Literal[True],
    ) -> dict[str, list[dict[str, Any]]]: ...

    def get_visible_class_methods(
        self,
        qualified_class_name: str,
        *,
        visibility_mode: Literal[
            "public", "same_package", "same_package_or_subclass"
        ] = "public",
        include_metadata: bool = False,
    ) -> dict[str, list[str]] | dict[str, list[dict[str, Any]]]:
        """
        Retrieves methods reachable from qualified class along its inheritance graph. Precedence looks at the class itself,
        then superclasses, then interfaces (level-order).

        Args:
            qualified_class_name: The qualified name of the class.
            visibility_mode: The visibility mode. Either "public", "same_package", or "same_package_or_subclass".
            include_metadata: Include metadata in the output.

        Returns:
            dict[str, list[str]] mapping owner (class or interface) -> list of method signatures.

        Raises:
            ClassNotFoundException: If the class cannot be found.
        """
        root_details = self.analysis.get_class(qualified_class_name)
        if not root_details:
            raise ClassNotFoundException(qualified_class_name)

        def _accept(owner: str, method_sig: str) -> bool:
            try:
                return self._common.is_accessible_from(
                    owner,
                    method_sig,
                    accessor_class=qualified_class_name,
                    mode=visibility_mode,
                )
            except (ClassNotFoundException, MethodNotFoundException):
                return False

        def _meta(owner: str, method_sig: str) -> dict[str, Any]:
            method_details = self.analysis.get_method(owner, method_sig)
            mods = list(method_details.modifiers or []) if method_details else []
            visibility = (
                "private"
                if "private" in mods
                else (
                    "public"
                    if "public" in mods
                    else "protected"
                    if "protected" in mods
                    else "package-private"
                )
            )
            return {
                "method_signature": method_sig,
                "declaring_qualified_class_name": owner,
                "modifiers": mods,
                "visibility": visibility,
            }

        result: dict[str, list[str | dict[str, Any]]] = {}
        seen_sigs: set[str] = set()

        def _add_methods(owner: str) -> None:
            for method_sig in self.analysis.get_methods_in_class(owner):
                if method_sig in seen_sigs:
                    continue
                if _accept(owner, method_sig):
                    seen_sigs.add(method_sig)
                    if include_metadata:
                        result.setdefault(owner, []).append(_meta(owner, method_sig))
                    else:
                        result.setdefault(owner, []).append(method_sig)

        # Methods on the class itself
        _add_methods(qualified_class_name)

        # Superclasses in BFS order
        super_queue: deque[str] = deque(root_details.extends_list or [])
        visited_supers: set[str] = set(root_details.extends_list or [])
        super_bfs_order: list[str] = []

        while super_queue:
            sup_cls = super_queue.popleft()
            super_bfs_order.append(sup_cls)
            _add_methods(sup_cls)

            sup_details = self.analysis.get_class(sup_cls)
            if sup_details and sup_details.extends_list:
                for next_sup in sup_details.extends_list:
                    if next_sup not in visited_supers:
                        visited_supers.add(next_sup)
                        super_queue.append(next_sup)

        # Interfaces in BFS order
        iface_queue: deque[str] = deque()
        visited_ifaces: set[str] = set()

        def _enqueue_interfaces(owner: str) -> None:
            owner_details = self.analysis.get_class(owner)
            if owner_details and owner_details.implements_list:
                for iface in owner_details.implements_list:
                    if iface not in visited_ifaces:
                        visited_ifaces.add(iface)
                        iface_queue.append(iface)

        _enqueue_interfaces(qualified_class_name)
        for sup in super_bfs_order:
            _enqueue_interfaces(sup)

        while iface_queue:
            iface = iface_queue.popleft()
            _add_methods(iface)

            iface_details = self.analysis.get_class(iface)
            if iface_details and iface_details.extends_list:
                for parent_iface in iface_details.extends_list:
                    if parent_iface not in visited_ifaces:
                        visited_ifaces.add(parent_iface)
                        iface_queue.append(parent_iface)

        return cast(dict[str, list[str]] | dict[str, list[dict[str, Any]]], result)
