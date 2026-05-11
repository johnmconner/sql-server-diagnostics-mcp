"""Project-specific exceptions."""


class SqlTshooterError(Exception):
    """Base error for the project."""


class ConfigurationError(SqlTshooterError):
    """Raised when environment configuration is invalid."""


class PreflightError(SqlTshooterError):
    """Raised when startup validation fails."""


class DatabaseExecutionError(SqlTshooterError):
    """Raised when a SQL query cannot be executed safely."""


class ToolExecutionError(SqlTshooterError):
    """Raised when a tool invocation fails."""
