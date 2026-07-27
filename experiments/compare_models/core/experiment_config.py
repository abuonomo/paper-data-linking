"""
Experiment configuration system for LLM comparison experiments.

Enables running experiments via YAML config files that specify:
- Experiment metadata
- Models to test
- Call types to test
- Call type configurations (prompts, inputs, handlers)
- Execution parameters
"""

from pathlib import Path
from typing import Optional, Dict, List
from pydantic import BaseModel, Field, validator
import yaml


class CallTypeConfig(BaseModel):
    """Configuration for a single call type in an experiment."""

    prompt: Path = Field(description="Path to system prompt XML file")
    input: Path = Field(description="Path to test data JSONL file")
    handler_class: str = Field(description="Handler class name (e.g., 'PhysObsNormalizationHandler')")

    @validator('prompt', 'input')
    def validate_path_exists(cls, v):
        """Validate that paths exist."""
        if not v.exists():
            raise ValueError(f"Path does not exist: {v}")
        return v


class ExperimentConfig(BaseModel):
    """Top-level experiment configuration."""

    experiment_name: str = Field(description="Unique name for this experiment run")
    description: Optional[str] = Field(default="", description="Human-readable description")

    models: List[str] = Field(description="List of model identifiers to test")
    call_types: List[str] = Field(description="List of call type keys to run")

    call_type_configs: Dict[str, CallTypeConfig] = Field(
        description="Call type configurations keyed by call type name"
    )

    max_cases: Optional[int] = Field(default=None, description="Maximum cases per call type")
    max_workers: int = Field(default=4, description="Maximum parallel workers")
    timeout_seconds: int = Field(default=600, description="Timeout per task in seconds")
    output_dir: Path = Field(
        default=Path("experiments/compare_models/prompt_experiments"),
        description="Output directory for experiment results"
    )

    @validator('call_type_configs')
    def validate_call_types_exist(cls, v, values):
        """Validate that all call_types have corresponding configs."""
        call_types = values.get('call_types', [])
        missing = set(call_types) - set(v.keys())
        if missing:
            raise ValueError(f"Call types missing configs: {missing}")
        return v

    class Config:
        """Pydantic config."""
        validate_assignment = True


def load_experiment_config(config_path: Path) -> ExperimentConfig:
    """
    Load and validate experiment configuration from YAML file.

    Args:
        config_path: Path to YAML config file

    Returns:
        Validated ExperimentConfig instance

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
        yaml.YAMLError: If YAML is malformed
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        data = yaml.safe_load(f)

    return ExperimentConfig(**data)


_config_cache: Optional[ExperimentConfig] = None


def get_config(config_path: Optional[Path] = None, reload: bool = False) -> ExperimentConfig:
    """
    Get experiment configuration with caching.

    Args:
        config_path: Path to config file (uses cached if not specified)
        reload: Force reload from disk even if cached

    Returns:
        Validated experiment configuration
    """
    global _config_cache

    if _config_cache is None or reload or config_path is not None:
        if config_path is None:
            raise ValueError("config_path required for initial load")
        _config_cache = load_experiment_config(config_path)

    return _config_cache
