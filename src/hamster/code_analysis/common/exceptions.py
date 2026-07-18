class AnalysisException(Exception):
    """Base exception for code analysis errors."""

    pass


class ClassFileNotFoundException(AnalysisException):
    """
    Raised when a Java file for a class cannot be found.
    """

    def __init__(self, qualified_class_name: str):
        self.qualified_class_name = qualified_class_name
        message = f"Java file not found for class: {qualified_class_name}"
        super().__init__(message)


class CompilationUnitNotFoundException(AnalysisException):
    """
    Raised when a compilation unit cannot be found for a file.
    """

    def __init__(self, file_path: str):
        self.file_path = file_path
        message = f"Compilation unit not found for file: {file_path}"
        super().__init__(message)


class ClassNotFoundException(AnalysisException):
    """
    Raised when a Java class cannot be found in the analysis.
    """

    def __init__(self, qualified_class_name: str):
        self.qualified_class_name = qualified_class_name
        message = f"Class not found: {qualified_class_name}"
        super().__init__(message)


class MethodNotFoundException(AnalysisException):
    """
    Raised when a method cannot be found in a Java class.
    """

    def __init__(self, qualified_class_name: str, method_signature: str):
        self.qualified_class_name = qualified_class_name
        self.method_signature = method_signature
        message = (
            f"Method not found: {method_signature} in class {qualified_class_name}"
        )
        super().__init__(message)
