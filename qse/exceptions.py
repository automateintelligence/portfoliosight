"""Project-wide exception types."""

class QuantScenarioError(Exception):
    """Base exception for all engine errors."""


class DataSourceError(QuantScenarioError):
    """Raised when data retrieval or schema checks fail."""


class DistributionFitError(QuantScenarioError):
    """Raised when distribution fitting fails or is implausible."""


class ResourceLimitError(QuantScenarioError):
    """Raised when a run would exceed configured resource limits."""


class PricingError(QuantScenarioError):
    """Raised when option pricing fails or inputs are invalid."""


class EpisodeGenerationError(QuantScenarioError):
    """Raised when candidate episodes cannot be generated."""


class ConfigError(QuantScenarioError):
    """Raised when configuration is missing or malformed."""


class ConfigValidationError(ConfigError):
    """Raised when validation fails for supplied configuration."""


class ConfigConflictError(ConfigError):
    """Raised when incompatible configuration options are provided."""


class SchemaError(QuantScenarioError):
    """Raised when schema validation fails."""


class InsufficientDataError(DataSourceError):
    """Raised when data does not meet minimum sample requirements."""


class TimestampAnomalyError(DataSourceError):
    """Raised when gaps or ordering issues are detected in timestamps."""


class BankruptcyError(QuantScenarioError):
    """Raised when simulated path hits an absorbing boundary (bankruptcy)."""


class DependencyError(QuantScenarioError):
    """Raised when required dependencies are missing or incompatible."""

