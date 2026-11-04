# ./config/settings.py
from pathlib import Path
from typing import Optional, Literal

from pydantic import BaseModel, field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Define the project root directory.
# This is needed for pydantic_settings to locate the .env file correctly if it's specified relative to the root.
PROJECT_ROOT_DIR = Path(__file__).resolve().parent.parent


class LLMCallConfig(BaseModel):
    """Base configuration for an LLM call"""
    model: str
    temperature: float = Field(ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None)
    aws_region_name: Optional[str] = Field(default=None, description="AWS region for Bedrock models")
    reasoning_effort: Optional[str] = Field(default=None, description="Reasoning effort level: 'low', 'medium', 'high'")
    extra_body: Optional[dict] = Field(default=None, description="Extra request-body fields for OpenAI-compatible servers (e.g. vLLM chat_template_kwargs)")

    @field_validator('max_tokens')
    @classmethod
    def validate_max_tokens(cls, v):
        if v is not None and v <= 0:
            raise ValueError('max_tokens must be positive when specified')
        return v
    
    def to_kwargs(self, **additional_kwargs) -> dict:
        """Convert config to LiteLLM kwargs, excluding None values and model."""
        kwargs = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }
        
        # Add optional parameters only if they're not None
        if self.aws_region_name is not None:
            kwargs["aws_region_name"] = self.aws_region_name
        if self.reasoning_effort is not None:
            kwargs["reasoning_effort"] = self.reasoning_effort
        if self.extra_body is not None:
            kwargs["extra_body"] = self.extra_body

        # Add any additional kwargs passed in
        kwargs.update(additional_kwargs)
        
        return kwargs


class NormalizationConfig(BaseModel):
    """Configuration for normalization pipeline calls - all fields are required."""
    time_range: LLMCallConfig
    wavelength: LLMCallConfig
    physical_observable: LLMCallConfig
    detector: LLMCallConfig
    cadence: LLMCallConfig


class InstrumentGroundingConfig(BaseModel):
    """Configuration for instrument grounding pipeline calls"""
    similarity_filter: LLMCallConfig = Field(default_factory=lambda: LLMCallConfig(
        model="openai/gpt-5-mini",
        temperature=1.0,
        max_tokens=None
    ))
    exact_match: LLMCallConfig = Field(default_factory=lambda: LLMCallConfig(
        model="openai/gpt-5",
        temperature=1.0,
        max_tokens=None
    ))
    exact_match_fallback: LLMCallConfig = Field(default_factory=lambda: LLMCallConfig(
        model="openai/gpt-5",
        temperature=1.0,
        max_tokens=None
    ))
    substring_filter: LLMCallConfig = Field(default_factory=lambda: LLMCallConfig(
        model="openai/gpt-5",
        temperature=1.0,
        max_tokens=None
    ))
    reranking: LLMCallConfig = Field(default_factory=lambda: LLMCallConfig(
        model="openai/gpt-5-mini",
        temperature=1.0,
        max_tokens=None
    ))
    final_grounding: LLMCallConfig = Field(default_factory=lambda: LLMCallConfig(
        model="openai/gpt-5",
        temperature=1.0,
        max_tokens=None
    ))
    validation: LLMCallConfig = Field(default_factory=lambda: LLMCallConfig(
        model="openai/gpt-5",
        temperature=1.0,
        max_tokens=None
    ))
    validation_retry: LLMCallConfig = Field(default_factory=lambda: LLMCallConfig(
        model="openai/gpt-5",
        temperature=1.0,
        max_tokens=None
    ))
    mission_validation: Optional[LLMCallConfig] = None  # Falls back to validation if not set


class LLMPipelineConfig(BaseModel):
    """Top-level LLM pipeline configuration - all fields are required and must be explicitly configured."""
    paper_analysis: LLMCallConfig
    structured_parsing: LLMCallConfig
    embeddings: LLMCallConfig
    normalization: NormalizationConfig
    instrument_grounding: InstrumentGroundingConfig
    structure_validation: LLMCallConfig


class AppSettings(BaseSettings):
    # --- Environment & API Keys ---
    OPENAI_API_KEY: str = Field(..., description="API key for OpenAI services.")
    ADS_TOKEN: str = Field(..., description="Token for ADS services.")
    CHROMEDRIVER_PATH: Optional[Path] = Field(default=None, description="Path to Chromedriver executable.")
    
    # --- Text Processing Limits ---
    MAX_TEXT_LENGTH: int = Field(default=500_000, gt=0, description="Maximum text length for LLM processing (characters)")
    TEXT_LENGTH_WARNING_THRESHOLD: int = Field(default=200_000, gt=0, description="Text length warning threshold (characters)")

    # --- Logging Configuration ---
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO", description="Logging level.")

    # --- Pydantic Settings Configuration ---
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT_DIR.parent / ".env",  # Load .env file from project root
        env_file_encoding='utf-8',
        extra='ignore',  # Ignore extra variables in .env or environment
        case_sensitive=False # Environment variable names are typically case-insensitive
    )

    # --- Custom Validators (Example) ---
    @field_validator("CHROMEDRIVER_PATH")
    @classmethod
    def check_chromedriver_path_exists(cls, v: Optional[Path]) -> Optional[Path]:
        if v and not v.exists():
            # You could log a warning instead of raising an error if it's acceptable for it not to exist initially
            raise ValueError(f"CHROMEDRIVER_PATH specified but not found at: {v}")
        return v

# --- Multi-Configuration LLM Support ---
LLM_CONFIGURATIONS = {
    "standard": LLMPipelineConfig(
        paper_analysis=LLMCallConfig(
            model="openai/gpt-5",
            temperature=1.0,
            max_tokens=None,
            reasoning_effort="high"  # OK - doesn't use structured outputs
        ),
        structured_parsing=LLMCallConfig(
            model="openai/gpt-5",
            temperature=1.0,
            max_tokens=None
        ),
        embeddings=LLMCallConfig(
            model="openai/text-embedding-3-small",
            temperature=1.0,
            max_tokens=1
        ),
        normalization=NormalizationConfig(
            time_range=LLMCallConfig(
                model="openai/gpt-5",
                temperature=1.0,
                max_tokens=None
            ),
            wavelength=LLMCallConfig(
                model="openai/gpt-5",
                temperature=1.0,
                max_tokens=None
            ),
            physical_observable=LLMCallConfig(
                model="openai/gpt-5",
                temperature=1.0,
                max_tokens=None
            ),
            detector=LLMCallConfig(
                model="openai/gpt-5",
                temperature=1.0,
                max_tokens=None
            ),
            cadence=LLMCallConfig(
                model="openai/gpt-5",
                temperature=1.0,
                max_tokens=None
            )
        ),
        instrument_grounding=InstrumentGroundingConfig(
            similarity_filter=LLMCallConfig(
                model="openai/gpt-5-mini",
                temperature=1.0,
                max_tokens=None
            ),
            exact_match=LLMCallConfig(
                model="openai/gpt-5",
                temperature=1.0,
                max_tokens=None
            ),
            exact_match_fallback=LLMCallConfig(
                model="openai/gpt-5",
                temperature=1.0,
                max_tokens=None
            ),
            substring_filter=LLMCallConfig(
                model="openai/gpt-5",
                temperature=1.0,
                max_tokens=None
            ),
            reranking=LLMCallConfig(
                model="openai/gpt-5-mini",
                temperature=1.0,
                max_tokens=None
            ),
            final_grounding=LLMCallConfig(
                model="openai/gpt-5",
                temperature=1.0,
                max_tokens=None
            ),
            validation=LLMCallConfig(
                model="openai/gpt-5",
                temperature=1.0,
                max_tokens=None
            ),
            validation_retry=LLMCallConfig(
                model="openai/gpt-5",
                temperature=1.0,
                max_tokens=None
            )
        ),
        structure_validation=LLMCallConfig(
            model="openai/gpt-5-mini",
            temperature=1.0,
            max_tokens=None
        )
    ),
    "budget": LLMPipelineConfig(
        paper_analysis=LLMCallConfig(
            model="openai/gpt-5-mini",
            temperature=1.0,
            max_tokens=None
        ),
        structured_parsing=LLMCallConfig(
            model="openai/gpt-5-mini",
            temperature=1.0,
            max_tokens=None
        ),
        embeddings=LLMCallConfig(
            model="openai/text-embedding-3-small",
            temperature=1.0,
            max_tokens=1
        ),
        normalization=NormalizationConfig(
            time_range=LLMCallConfig(
                model="openai/gpt-5-mini",
                temperature=1.0,
                max_tokens=None
            ),
            wavelength=LLMCallConfig(
                model="openai/gpt-5-mini",
                temperature=1.0,
                max_tokens=None
            ),
            physical_observable=LLMCallConfig(
                model="openai/gpt-5-mini",
                temperature=1.0,
                max_tokens=None
            ),
            detector=LLMCallConfig(
                model="openai/gpt-5-mini",
                temperature=1.0,
                max_tokens=None
            ),
            cadence=LLMCallConfig(
                model="openai/gpt-5-mini",
                temperature=1.0,
                max_tokens=None
            )
        ),
        instrument_grounding=InstrumentGroundingConfig(
            similarity_filter=LLMCallConfig(
                model="openai/gpt-5-mini",
                temperature=1.0,
                max_tokens=None
            ),
            exact_match=LLMCallConfig(
                model="openai/gpt-5-mini",
                temperature=1.0,
                max_tokens=None
            ),
            exact_match_fallback=LLMCallConfig(
                model="openai/gpt-5-mini",
                temperature=1.0,
                max_tokens=None
            ),
            substring_filter=LLMCallConfig(
                model="openai/gpt-5-mini",
                temperature=1.0,
                max_tokens=None
            ),
            reranking=LLMCallConfig(
                model="openai/gpt-5-mini",
                temperature=1.0,
                max_tokens=None
            ),
            final_grounding=LLMCallConfig(
                model="openai/gpt-5-mini",
                temperature=1.0,
                max_tokens=None
            ),
            validation=LLMCallConfig(
                model="openai/gpt-5-mini",
                temperature=1.0,
                max_tokens=None
            ),
            validation_retry=LLMCallConfig(
                model="openai/gpt-5-mini",
                temperature=1.0,
                max_tokens=None
            )
        ),
        structure_validation=LLMCallConfig(
            model="openai/gpt-5-mini",
            temperature=1.0,
            max_tokens=None
        )
    ),
    "super-budget": LLMPipelineConfig(
        paper_analysis=LLMCallConfig(
            model="openai/gpt-5-nano",
            temperature=1.0,
            max_tokens=None
        ),
        structured_parsing=LLMCallConfig(
            model="openai/gpt-5-nano",
            temperature=1.0,
            max_tokens=None
        ),
        embeddings=LLMCallConfig(
            model="openai/text-embedding-3-small",
            temperature=1.0,
            max_tokens=1
        ),
        normalization=NormalizationConfig(
            time_range=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            wavelength=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            physical_observable=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            detector=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            cadence=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            )
        ),
        instrument_grounding=InstrumentGroundingConfig(
            similarity_filter=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            exact_match=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            exact_match_fallback=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            substring_filter=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            reranking=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            final_grounding=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            validation=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            validation_retry=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            )
        ),
        structure_validation=LLMCallConfig(
            model="openai/gpt-5-nano",
            temperature=1.0,
            max_tokens=None
        )
    ),
    "hybrid": LLMPipelineConfig(
        paper_analysis=LLMCallConfig(
            model="openai/gpt-5",
            temperature=1.0,
            max_tokens=None
        ),
        structured_parsing=LLMCallConfig(
            model="openai/gpt-5-nano",
            temperature=1.0,
            max_tokens=None
        ),
        embeddings=LLMCallConfig(
            model="openai/text-embedding-3-small",
            temperature=1.0,
            max_tokens=1
        ),
        normalization=NormalizationConfig(
            time_range=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            wavelength=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            physical_observable=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            detector=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            cadence=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            )
        ),
        instrument_grounding=InstrumentGroundingConfig(
            similarity_filter=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            exact_match=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            exact_match_fallback=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            substring_filter=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            reranking=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            final_grounding=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            validation=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            ),
            validation_retry=LLMCallConfig(
                model="openai/gpt-5-nano",
                temperature=1.0,
                max_tokens=None
            )
        ),
        structure_validation=LLMCallConfig(
            model="openai/gpt-5-nano",
            temperature=1.0,
            max_tokens=None
        )
    ),
    "bedrock-test": LLMPipelineConfig(
        paper_analysis=LLMCallConfig(
            model="bedrock/converse/openai.gpt-oss-120b-1:0",
            temperature=1.0,
            max_tokens=None,
            aws_region_name="us-west-2",
            reasoning_effort="high"  # OK - doesn't use structured outputs
        ),
        structured_parsing=LLMCallConfig(
            model="bedrock/converse/openai.gpt-oss-120b-1:0",
            temperature=1.0,
            max_tokens=None,
            aws_region_name="us-west-2",
            reasoning_effort="low"  # Reduce reasoning tokens to prevent hitting length limit before JSON completes
        ),
        embeddings=LLMCallConfig(
            model="openai/text-embedding-3-small",  # Keep OpenAI for embeddings
            temperature=1.0,
            max_tokens=1
        ),
        normalization=NormalizationConfig(
            time_range=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2",
                reasoning_effort="low"  # Reduce reasoning tokens for faster, more focused normalization
            ),
            wavelength=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2",
                reasoning_effort="low"  # Reduce reasoning tokens for faster, more focused normalization
            ),
            physical_observable=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2",
                reasoning_effort="low"  # Reduce reasoning tokens for faster, more focused normalization
            ),
            detector=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2",
                reasoning_effort="low"  # Reduce reasoning tokens for faster, more focused normalization
            ),
            cadence=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2",
                reasoning_effort="low"  # Reduce reasoning tokens for faster, more focused normalization
            )
        ),
        instrument_grounding=InstrumentGroundingConfig(
            similarity_filter=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-20b-1:0",  # Use smaller model for simpler tasks
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            exact_match=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            exact_match_fallback=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            substring_filter=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            reranking=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-20b-1:0",  # Use smaller model for simpler tasks
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            final_grounding=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            validation=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",  # Use larger model for complex validation
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
                # No reasoning_effort - conflicts with response_format
            ),
            validation_retry=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",  # Use larger model for complex validation
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
                # No reasoning_effort - conflicts with response_format
            )
        ),
        structure_validation=LLMCallConfig(
            model="bedrock/converse/openai.gpt-oss-20b-1:0",
            temperature=1.0,
            max_tokens=None,
            aws_region_name="us-west-2"
        )
    ),
    "bedrock-gpt-oss-120b": LLMPipelineConfig(
        paper_analysis=LLMCallConfig(
            model="bedrock/converse/openai.gpt-oss-120b-1:0",
            temperature=1.0,
            max_tokens=None,
            aws_region_name="us-west-2",
            reasoning_effort="high"
        ),
        structured_parsing=LLMCallConfig(
            model="bedrock/converse/openai.gpt-oss-120b-1:0",
            temperature=1.0,
            max_tokens=None,
            aws_region_name="us-west-2",
            reasoning_effort="low"
        ),
        embeddings=LLMCallConfig(
            model="openai/text-embedding-3-small",
            temperature=1.0,
            max_tokens=1
        ),
        normalization=NormalizationConfig(
            time_range=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2",
                reasoning_effort="low"
            ),
            wavelength=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2",
                reasoning_effort="low"
            ),
            physical_observable=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2",
                reasoning_effort="low"
            ),
            detector=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2",
                reasoning_effort="low"
            ),
            cadence=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2",
                reasoning_effort="low"
            )
        ),
        instrument_grounding=InstrumentGroundingConfig(
            similarity_filter=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            exact_match=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            exact_match_fallback=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            substring_filter=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            reranking=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            final_grounding=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            validation=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            validation_retry=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            )
        ),
        structure_validation=LLMCallConfig(
            model="bedrock/converse/openai.gpt-oss-120b-1:0",
            temperature=1.0,
            max_tokens=None,
            aws_region_name="us-west-2"
        )
    ),
    "bedrock-nemotron-120b": LLMPipelineConfig(
        paper_analysis=LLMCallConfig(
            model="bedrock/converse/nvidia.nemotron-super-3-120b",
            temperature=1.0,
            max_tokens=None,
            aws_region_name="us-west-2"
        ),
        structured_parsing=LLMCallConfig(
            model="bedrock/converse/nvidia.nemotron-super-3-120b",
            temperature=1.0,
            max_tokens=None,
            aws_region_name="us-west-2"
        ),
        embeddings=LLMCallConfig(
            model="openai/text-embedding-3-small",
            temperature=1.0,
            max_tokens=1
        ),
        normalization=NormalizationConfig(
            time_range=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            wavelength=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            physical_observable=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            detector=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            cadence=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            )
        ),
        instrument_grounding=InstrumentGroundingConfig(
            similarity_filter=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            exact_match=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            exact_match_fallback=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            substring_filter=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            reranking=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            final_grounding=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            validation=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            validation_retry=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            )
        ),
        structure_validation=LLMCallConfig(
            model="bedrock/converse/nvidia.nemotron-super-3-120b",
            temperature=1.0,
            max_tokens=None,
            aws_region_name="us-west-2"
        )
    ),
    "standard-gpt54": LLMPipelineConfig(
        paper_analysis=LLMCallConfig(
            model="openai/gpt-5.4",
            temperature=1.0,
            max_tokens=None,
            reasoning_effort="high"
        ),
        structured_parsing=LLMCallConfig(
            model="openai/gpt-5.4",
            temperature=1.0,
            max_tokens=None,
            reasoning_effort="high"
        ),
        embeddings=LLMCallConfig(
            model="openai/text-embedding-3-small",
            temperature=1.0,
            max_tokens=1
        ),
        normalization=NormalizationConfig(
            time_range=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            wavelength=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            physical_observable=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            detector=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            cadence=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            )
        ),
        instrument_grounding=InstrumentGroundingConfig(
            similarity_filter=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            exact_match=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            exact_match_fallback=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            substring_filter=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            reranking=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            final_grounding=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            validation=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            validation_retry=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            mission_validation=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            )
        ),
        structure_validation=LLMCallConfig(
            model="openai/gpt-5.4",
            temperature=1.0,
            max_tokens=None,
            reasoning_effort="high"
        )
    ),
    # gpt-5.5 config: mirrors standard-gpt54 (gpt-5.5 for ALL calls, no mini,
    # reasoning_effort=high). For the larger prod test on test_set_helio_v3,
    # compared head-to-head against bedrock-120b-high (gpt-oss-120b).
    "standard-gpt55": LLMPipelineConfig(
        paper_analysis=LLMCallConfig(
            model="openai/gpt-5.5",
            temperature=1.0,
            max_tokens=None,
            reasoning_effort="high"
        ),
        structured_parsing=LLMCallConfig(
            model="openai/gpt-5.5",
            temperature=1.0,
            max_tokens=None,
            reasoning_effort="high"
        ),
        embeddings=LLMCallConfig(
            model="openai/text-embedding-3-small",
            temperature=1.0,
            max_tokens=1
        ),
        normalization=NormalizationConfig(
            time_range=LLMCallConfig(
                model="openai/gpt-5.5",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            wavelength=LLMCallConfig(
                model="openai/gpt-5.5",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            physical_observable=LLMCallConfig(
                model="openai/gpt-5.5",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            detector=LLMCallConfig(
                model="openai/gpt-5.5",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            cadence=LLMCallConfig(
                model="openai/gpt-5.5",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            )
        ),
        instrument_grounding=InstrumentGroundingConfig(
            similarity_filter=LLMCallConfig(
                model="openai/gpt-5.5",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            exact_match=LLMCallConfig(
                model="openai/gpt-5.5",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            exact_match_fallback=LLMCallConfig(
                model="openai/gpt-5.5",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            substring_filter=LLMCallConfig(
                model="openai/gpt-5.5",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            reranking=LLMCallConfig(
                model="openai/gpt-5.5",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            final_grounding=LLMCallConfig(
                model="openai/gpt-5.5",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            validation=LLMCallConfig(
                model="openai/gpt-5.5",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            validation_retry=LLMCallConfig(
                model="openai/gpt-5.5",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            mission_validation=LLMCallConfig(
                model="openai/gpt-5.5",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            )
        ),
        structure_validation=LLMCallConfig(
            model="openai/gpt-5.5",
            temperature=1.0,
            max_tokens=None,
            reasoning_effort="high"
        )
    ),
    # v2 configs: identical models, new config name to allow re-running
    # test_set_helio_v2 papers with updated prompts (mission_validation
    # family-variant rule, mission_identification shortcode format).
    # Copies structured_instruments_details from v1 analyses and re-runs
    # from normalization/grounding onward.
    "standard-gpt54-v2": LLMPipelineConfig(
        paper_analysis=LLMCallConfig(
            model="openai/gpt-5.4",
            temperature=1.0,
            max_tokens=None,
            reasoning_effort="high"
        ),
        structured_parsing=LLMCallConfig(
            model="openai/gpt-5.4",
            temperature=1.0,
            max_tokens=None,
            reasoning_effort="high"
        ),
        embeddings=LLMCallConfig(
            model="openai/text-embedding-3-small",
            temperature=1.0,
            max_tokens=1
        ),
        normalization=NormalizationConfig(
            time_range=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            wavelength=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            physical_observable=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            detector=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            cadence=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            )
        ),
        instrument_grounding=InstrumentGroundingConfig(
            similarity_filter=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            exact_match=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            exact_match_fallback=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            substring_filter=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            reranking=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            final_grounding=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            validation=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            validation_retry=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            mission_validation=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            )
        ),
        structure_validation=LLMCallConfig(
            model="openai/gpt-5.4",
            temperature=1.0,
            max_tokens=None,
            reasoning_effort="high"
        )
    ),
    "bedrock-120b-high": LLMPipelineConfig(
        paper_analysis=LLMCallConfig(
            model="bedrock/converse/openai.gpt-oss-120b-1:0",
            temperature=1.0,
            max_tokens=30000,
            aws_region_name="us-west-2",
            reasoning_effort="high"
        ),
        structured_parsing=LLMCallConfig(
            model="bedrock/converse/openai.gpt-oss-120b-1:0",
            temperature=1.0,
            max_tokens=30000,
            aws_region_name="us-west-2",
            reasoning_effort="high"
        ),
        embeddings=LLMCallConfig(
            model="openai/text-embedding-3-small",
            temperature=1.0,
            max_tokens=1
        ),
        normalization=NormalizationConfig(
            time_range=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            wavelength=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            physical_observable=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            detector=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            cadence=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            )
        ),
        instrument_grounding=InstrumentGroundingConfig(
            similarity_filter=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            exact_match=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            exact_match_fallback=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            substring_filter=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            reranking=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            final_grounding=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            validation=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            validation_retry=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            mission_validation=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            )
        ),
        structure_validation=LLMCallConfig(
            model="bedrock/converse/openai.gpt-oss-120b-1:0",
            temperature=1.0,
            max_tokens=30000,
            aws_region_name="us-west-2",
            reasoning_effort="high"
        )
    ),
    "standard-gpt54-v3": LLMPipelineConfig(
        paper_analysis=LLMCallConfig(
            model="openai/gpt-5.4",
            temperature=1.0,
            max_tokens=None,
            reasoning_effort="high"
        ),
        structured_parsing=LLMCallConfig(
            model="openai/gpt-5.4",
            temperature=1.0,
            max_tokens=None,
            reasoning_effort="high"
        ),
        embeddings=LLMCallConfig(
            model="openai/text-embedding-3-small",
            temperature=1.0,
            max_tokens=1
        ),
        normalization=NormalizationConfig(
            time_range=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            wavelength=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            physical_observable=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            detector=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            cadence=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            )
        ),
        instrument_grounding=InstrumentGroundingConfig(
            similarity_filter=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            exact_match=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            exact_match_fallback=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            substring_filter=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            reranking=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            final_grounding=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            validation=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            validation_retry=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            ),
            mission_validation=LLMCallConfig(
                model="openai/gpt-5.4",
                temperature=1.0,
                max_tokens=None,
                reasoning_effort="high"
            )
        ),
        structure_validation=LLMCallConfig(
            model="openai/gpt-5.4",
            temperature=1.0,
            max_tokens=None,
            reasoning_effort="high"
        )
    ),
    "bedrock-120b-high-v2": LLMPipelineConfig(
        paper_analysis=LLMCallConfig(
            model="bedrock/converse/openai.gpt-oss-120b-1:0",
            temperature=1.0,
            max_tokens=30000,
            aws_region_name="us-west-2",
            reasoning_effort="high"
        ),
        structured_parsing=LLMCallConfig(
            model="bedrock/converse/openai.gpt-oss-120b-1:0",
            temperature=1.0,
            max_tokens=30000,
            aws_region_name="us-west-2",
            reasoning_effort="high"
        ),
        embeddings=LLMCallConfig(
            model="openai/text-embedding-3-small",
            temperature=1.0,
            max_tokens=1
        ),
        normalization=NormalizationConfig(
            time_range=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            wavelength=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            physical_observable=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            detector=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            cadence=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            )
        ),
        instrument_grounding=InstrumentGroundingConfig(
            similarity_filter=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            exact_match=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            exact_match_fallback=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            substring_filter=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            reranking=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            final_grounding=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            validation=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            validation_retry=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            mission_validation=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            )
        ),
        structure_validation=LLMCallConfig(
            model="bedrock/converse/openai.gpt-oss-120b-1:0",
            temperature=1.0,
            max_tokens=30000,
            aws_region_name="us-west-2",
            reasoning_effort="high"
        )
    ),
    "bedrock-120b-high-v3": LLMPipelineConfig(
        paper_analysis=LLMCallConfig(
            model="bedrock/converse/openai.gpt-oss-120b-1:0",
            temperature=1.0,
            max_tokens=30000,
            aws_region_name="us-west-2",
            reasoning_effort="high"
        ),
        structured_parsing=LLMCallConfig(
            model="bedrock/converse/openai.gpt-oss-120b-1:0",
            temperature=1.0,
            max_tokens=30000,
            aws_region_name="us-west-2",
            reasoning_effort="high"
        ),
        embeddings=LLMCallConfig(
            model="openai/text-embedding-3-small",
            temperature=1.0,
            max_tokens=1
        ),
        normalization=NormalizationConfig(
            time_range=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            wavelength=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            physical_observable=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            detector=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            cadence=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            )
        ),
        instrument_grounding=InstrumentGroundingConfig(
            similarity_filter=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            exact_match=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            exact_match_fallback=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            substring_filter=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            reranking=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            final_grounding=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            validation=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            validation_retry=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            mission_validation=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            )
        ),
        structure_validation=LLMCallConfig(
            model="bedrock/converse/openai.gpt-oss-120b-1:0",
            temperature=1.0,
            max_tokens=30000,
            aws_region_name="us-west-2",
            reasoning_effort="high"
        )
    ),
    "bedrock-nemotron-high": LLMPipelineConfig(
        paper_analysis=LLMCallConfig(
            model="bedrock/converse/nvidia.nemotron-super-3-120b",
            temperature=1.0,
            max_tokens=30000,
            aws_region_name="us-west-2",
            reasoning_effort="high"
        ),
        structured_parsing=LLMCallConfig(
            model="bedrock/converse/nvidia.nemotron-super-3-120b",
            temperature=1.0,
            max_tokens=30000,
            aws_region_name="us-west-2",
            reasoning_effort="high"
        ),
        embeddings=LLMCallConfig(
            model="openai/text-embedding-3-small",
            temperature=1.0,
            max_tokens=1
        ),
        normalization=NormalizationConfig(
            time_range=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            wavelength=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            physical_observable=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            detector=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            cadence=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            )
        ),
        instrument_grounding=InstrumentGroundingConfig(
            similarity_filter=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            exact_match=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            exact_match_fallback=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            substring_filter=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            reranking=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            final_grounding=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            validation=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            validation_retry=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            ),
            mission_validation=LLMCallConfig(
                model="bedrock/converse/nvidia.nemotron-super-3-120b",
                temperature=1.0,
                max_tokens=30000,
                aws_region_name="us-west-2",
                reasoning_effort="high"
            )
        ),
        structure_validation=LLMCallConfig(
            model="bedrock/converse/nvidia.nemotron-super-3-120b",
            temperature=1.0,
            max_tokens=30000,
            aws_region_name="us-west-2",
            reasoning_effort="high"
        )
    ),
    "bedrock-qwen3-235b": LLMPipelineConfig(
        paper_analysis=LLMCallConfig(
            model="bedrock/converse/qwen.qwen3-235b-a22b-2507-v1:0",
            temperature=1.0,
            max_tokens=None,
            aws_region_name="us-west-2"
        ),
        structured_parsing=LLMCallConfig(
            model="bedrock/converse/qwen.qwen3-235b-a22b-2507-v1:0",
            temperature=1.0,
            max_tokens=None,
            aws_region_name="us-west-2"
        ),
        embeddings=LLMCallConfig(
            model="openai/text-embedding-3-small",
            temperature=1.0,
            max_tokens=1
        ),
        normalization=NormalizationConfig(
            time_range=LLMCallConfig(
                model="bedrock/converse/qwen.qwen3-235b-a22b-2507-v1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            wavelength=LLMCallConfig(
                model="bedrock/converse/qwen.qwen3-235b-a22b-2507-v1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            physical_observable=LLMCallConfig(
                model="bedrock/converse/qwen.qwen3-235b-a22b-2507-v1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            detector=LLMCallConfig(
                model="bedrock/converse/qwen.qwen3-235b-a22b-2507-v1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            cadence=LLMCallConfig(
                model="bedrock/converse/qwen.qwen3-235b-a22b-2507-v1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            )
        ),
        instrument_grounding=InstrumentGroundingConfig(
            similarity_filter=LLMCallConfig(
                model="bedrock/converse/qwen.qwen3-235b-a22b-2507-v1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            exact_match=LLMCallConfig(
                model="bedrock/converse/qwen.qwen3-235b-a22b-2507-v1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            exact_match_fallback=LLMCallConfig(
                model="bedrock/converse/qwen.qwen3-235b-a22b-2507-v1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            substring_filter=LLMCallConfig(
                model="bedrock/converse/qwen.qwen3-235b-a22b-2507-v1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            reranking=LLMCallConfig(
                model="bedrock/converse/qwen.qwen3-235b-a22b-2507-v1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            final_grounding=LLMCallConfig(
                model="bedrock/converse/qwen.qwen3-235b-a22b-2507-v1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            validation=LLMCallConfig(
                model="bedrock/converse/qwen.qwen3-235b-a22b-2507-v1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            validation_retry=LLMCallConfig(
                model="bedrock/converse/qwen.qwen3-235b-a22b-2507-v1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            )
        ),
        structure_validation=LLMCallConfig(
            model="bedrock/converse/qwen.qwen3-235b-a22b-2507-v1:0",
            temperature=1.0,
            max_tokens=None,
            aws_region_name="us-west-2"
        )
    )
}

# v4 eval configs: identical models to their base configs, fresh names so the
# test_set_helio_v3 eval re-runs the full pipeline (with the new step-1 rules)
# instead of silently reusing prior standard-gpt54 / bedrock-120b-high analyses.
LLM_CONFIGURATIONS["standard-gpt54-v4"] = LLM_CONFIGURATIONS["standard-gpt54"].model_copy(deep=True)
LLM_CONFIGURATIONS["bedrock-120b-high-v4"] = LLM_CONFIGURATIONS["bedrock-120b-high"].model_copy(deep=True)

# v5 eval configs: fresh names for the clean re-run of the test_set_helio_v3 eval
# AFTER the three fixes (MR #171 mission_selection generic-series, #172 SWEAP
# catalog aliases, #173 step-1 availability-period rule). Preserves the v4 run as
# the before baseline so the post-fix agreement can be measured (not just projected).
LLM_CONFIGURATIONS["standard-gpt54-v5"] = LLM_CONFIGURATIONS["standard-gpt54"].model_copy(deep=True)
LLM_CONFIGURATIONS["bedrock-120b-high-v5"] = LLM_CONFIGURATIONS["bedrock-120b-high"].model_copy(deep=True)

# Mixed-effort deployment candidate (2026-07-02). The per-call effort sweep (v3)
# found 6 downstream stages substitute at LOW effort, 3 need MEDIUM
# (time_normalization, physical_observable, mission_selection), and 0 need HIGH.
# This config is bedrock-120b-high-v5 with stages the sweep actually MEASURED set
# to their sweep-recommended effort (LOW or MEDIUM), and every stage the sweep did
# NOT cover held at HIGH (conservative: only proven-safe stages are cheapened, so
# an end-to-end regression can be attributed to a measured stage). Compare
# cross/intra set-Jaccard against bedrock-120b-high-v5 (reasoning_effort sweep).
#
# Config-slot names are legacy misnomers; sweep call-type -> slot mapping:
#   mission_selection            -> instrument_grounding.exact_match
#   mission_identification        -> instrument_grounding.similarity_filter
#   instrument_selection          -> instrument_grounding.exact_match_fallback
#   instrument_validation         -> instrument_grounding.validation
# NOT covered by the sweep (held HIGH): paper_analysis, structured_parsing,
#   structure_validation, substring_filter (instrument_multiple_selection),
#   reranking, final_grounding, validation_retry.
_mixed = LLM_CONFIGURATIONS["bedrock-120b-high-v5"].model_copy(deep=True)
# normalization: MEDIUM for time_range + physical_observable (measured: need
# medium); LOW for wavelength/detector/cadence (measured: substitute at low).
_mixed.normalization.time_range.reasoning_effort = "medium"
_mixed.normalization.physical_observable.reasoning_effort = "medium"
_mixed.normalization.wavelength.reasoning_effort = "low"
_mixed.normalization.detector.reasoning_effort = "low"
_mixed.normalization.cadence.reasoning_effort = "low"
# instrument_grounding: only the four measured slots move off HIGH.
_mixed.instrument_grounding.exact_match.reasoning_effort = "medium"       # mission_selection
_mixed.instrument_grounding.similarity_filter.reasoning_effort = "low"    # mission_identification
_mixed.instrument_grounding.exact_match_fallback.reasoning_effort = "low" # instrument_selection
_mixed.instrument_grounding.validation.reasoning_effort = "low"           # instrument_validation
if _mixed.instrument_grounding.mission_validation is not None:
    _mixed.instrument_grounding.mission_validation.reasoning_effort = "low"
# Everything else (paper_analysis, structured_parsing, structure_validation,
# substring_filter, reranking, final_grounding, validation_retry) stays HIGH,
# inherited unchanged from bedrock-120b-high-v5.
LLM_CONFIGURATIONS["bedrock-120b-mixed-v5"] = _mixed
del _mixed


def _with_uniform_effort(config: "LLMPipelineConfig", effort: str) -> "LLMPipelineConfig":
    """Deep-copy a pipeline config with EVERY stage's reasoning_effort set to
    ``effort``. Used to build uniform-effort arms for the end-to-end effort
    comparison (now meaningful: effort genuinely reaches every downstream call)."""
    copied = config.model_copy(deep=True)

    def _apply(obj):
        if isinstance(obj, LLMCallConfig):
            obj.reasoning_effort = effort
            return
        if hasattr(obj, "model_fields"):
            for field in type(obj).model_fields:
                _apply(getattr(obj, field))

    _apply(copied)
    return copied


# Uniform-effort arms of the v5 eval config, for the real end-to-end effort
# comparison (high already exists as bedrock-120b-high-v5).
LLM_CONFIGURATIONS["bedrock-120b-med-v5"] = _with_uniform_effort(
    LLM_CONFIGURATIONS["bedrock-120b-high-v5"], "medium")
LLM_CONFIGURATIONS["bedrock-120b-low-v5"] = _with_uniform_effort(
    LLM_CONFIGURATIONS["bedrock-120b-high-v5"], "low")

# (bedrock-120b-mixed-v5 — the per-stage mixed-effort config — is defined above;
# it merged to main independently and the branch's verbatim port was dropped in
# favor of the canonical definition.)


def _on_model(config: "LLMPipelineConfig", template: "LLMCallConfig") -> "LLMPipelineConfig":
    """Deep-copy a pipeline config with every LLM stage (all but embeddings) replaced
    by ``template``. Used for single-model configs served from one endpoint."""
    copied = config.model_copy(deep=True)

    def _apply(obj):
        for field in type(obj).model_fields:
            value = getattr(obj, field)
            if isinstance(value, LLMCallConfig):
                setattr(obj, field, template.model_copy(deep=True))
            elif hasattr(value, "model_fields"):
                _apply(value)

    _apply(copied)
    copied.embeddings = config.embeddings.model_copy(deep=True)
    return copied


# Self-hosted Gemma 4 26B-A4B on vLLM (the SciX/ADS L40S candidate), every stage incl.
# downstream. litellm's hosted_vllm provider reads HOSTED_VLLM_API_BASE / HOSTED_VLLM_API_KEY
# from the environment. Thinking is switched on through the chat template (Gemma ignores
# reasoning_effort). Embeddings stay on OpenAI.
LLM_CONFIGURATIONS["vllm-gemma4"] = _on_model(
    LLM_CONFIGURATIONS["bedrock-120b-high-v5"],
    LLMCallConfig(
        model="hosted_vllm/google/gemma-4-26B-A4B-it",
        temperature=1.0,
        max_tokens=16000,
        extra_body={"chat_template_kwargs": {"enable_thinking": True}},
    ),
)


def get_llm_configuration(name: str) -> LLMPipelineConfig:
    """Get LLM configuration by name with strict validation.

    A trailing run-replicate suffix ("@N") is stripped before lookup so the same
    base config can be run multiple times over the same papers for self-consistency
    experiments. Each "@N" is a distinct PaperAnalysis.configuration_name (so it does
    not collide with the (paper, configuration_name) unique constraint) yet resolves
    to identical settings. E.g. "bedrock-120b-high-v5@2" -> "bedrock-120b-high-v5".
    """
    base = name.split("@", 1)[0]
    if base not in LLM_CONFIGURATIONS:
        available = list(LLM_CONFIGURATIONS.keys())
        raise ValueError(f"Unknown configuration: {name}. Available: {available}")
    return LLM_CONFIGURATIONS[base]


def list_available_configurations() -> list[str]:
    """List all available LLM configuration names"""
    return list(LLM_CONFIGURATIONS.keys())


# ---------------------------------------------------------------------------
# Manual validation campaigns
# ---------------------------------------------------------------------------

class ValidationCampaign(BaseModel):
    """A manual validation campaign: blinded human review of the deduplicated
    claim union of two configurations over a tagged paper set.

    Single source of truth for the campaign API views, the tagging/sampling
    management commands, and the analysis scripts.
    """
    slug: str
    # The two PaperAnalysis.configuration_name values whose DatasetUsages form
    # the claim union under review.
    configs: list[str]
    # Paper tag identifying the canonical paper set.
    set_tag: str
    # Reviewer assignment tags: per-reviewer bulk tags are f"{tag_prefix}{username}".
    tag_prefix: str
    # Usernames of the campaign reviewers (authenticated users). Only these
    # users may access the campaign endpoints.
    reviewers: list[str]
    overlap_tag: str
    calibration_tag: str
    calibration_size: int = 25
    # ISO datetime the campaign officially started (frozen when prod tagging is
    # done). The analysis only counts reviewer validations created after this.
    started_at: str | None = None
    # Representative DatasetUsage ids of the calibration claims, frozen from the
    # sample_calibration_claims command output. Both reviewers must judge all of
    # these before the bulk/overlap sections unlock.
    calibration_usage_ids: list[str] = []
    # Claim-scoped campaigns review a frozen sample of claims instead of every
    # claim on the tagged papers: only DatasetUsages listed in claim_usage_ids
    # participate (an empty list means nothing does, so tagging papers before the
    # sample is frozen exposes no claims). Frozen from sample_window_claims.
    claim_scoped: bool = False
    claim_usage_ids: list[str] = []


VALIDATION_CAMPAIGNS: dict[str, ValidationCampaign] = {
    "val2026": ValidationCampaign(
        slug="val2026",
        configs=["bedrock-120b-mixed-v5@s1", "standard-gpt54-v5"],
        set_tag="test_set_helio_v3_2026_06_18",
        tag_prefix="val2026:",
        reviewers=["abuonomo", "ascharnikow"],
        overlap_tag="val2026:overlap",
        calibration_tag="val2026:calibration",
        calibration_size=25,
        # Campaign start: reviewer validations before this are not counted by
        # the analysis. Frozen at prod tagging/sampling (seed 20260817).
        started_at="2026-08-17T16:00:00Z",
        # Frozen from sample_calibration_claims --seed 20260817 (the checked-in
        # list lives in pdl-paper/validation/val2026_calibration_claims.json).
        calibration_usage_ids=[
            "251ed876-85a6-44ed-ae6e-afd55e8d6709",
            "b270fbf0-570f-41bd-a7bc-f67430016e8d",
            "1d243c95-2092-442e-83a5-50e66e72b79b",
            "d463bec1-e26c-46b2-8d9a-ad6f2f101adf",
            "fe0709d1-2b3e-481a-8e2e-683834c17dad",
            "5d3bd50c-a165-4c29-9210-a599fe35f881",
            "e7dd46d0-92c0-407d-87e6-f752d5e1eb8c",
            "333c3609-75d6-4ba8-8d5e-cc6b47698434",
            "cdf39fce-2cad-4dc8-a2e8-f4d523d6e340",
            "acea81bb-0829-4263-9324-7a80135b3a5f",
            "b00acb35-cd1c-469c-95da-0470635000d6",
            "467f46c2-eec3-4295-a179-f007bbb0083c",
            "21d50f10-f19a-41b1-8ebb-997bdc07320d",
            "c1812b78-8979-4248-b0b6-7e086aaca0eb",
            "3b1b64dc-2cf2-49f3-99d3-38d5ceb6b87e",
            "11a2209f-304d-4b58-b659-5cf12a913ebe",
            "44393a0c-06ca-4eb6-9eb2-6e7c2c4a5c42",
            "7f312209-1e88-4120-a301-ea57b832ea70",
            "d11b29f4-eeb1-4f43-a825-97a247930cd4",
            "167af771-5e21-4303-b4df-b043358e6ca4",
            "1c5778a0-5b73-4ae3-88f7-99051f0dee8e",
            "902ed5ac-c8b5-4dec-8c28-9e1031fd4158",
            "755d5250-ad06-4f10-a647-673cbee16916",
            "5a817ab5-48b5-435c-9e3f-7ec28d81802e",
            "420c1ccf-c4f0-4cbb-a7e5-a0916f48e085",
        ],
    ),
    # Time-window validity of self-hosted Gemma (all stages) vs gpt-oss: a blinded
    # review of the claims where the two configs DISAGREE on the eval set and
    # val2026 has no verdict (shared claims cannot change the comparison).
    "window2026": ValidationCampaign(
        slug="window2026",
        configs=["vllm-gemma4@e2e2", "bedrock-120b-mixed-v5@mx2"],
        set_tag="window2026:set",
        tag_prefix="window2026:",
        reviewers=["abuonomo"],
        overlap_tag="window2026:overlap",
        calibration_tag="window2026:calibration",
        calibration_size=0,
        claim_scoped=True,
        # Frozen from sample_window_claims --seed 20261104 (100 claims, 54 papers; the
        # unblinding key lives in pdl-paper/validation/window2026_sample_key.json).
        started_at="2026-11-04T15:57:03Z",
        claim_usage_ids=[
            "b5b151f0-78ea-459d-9107-a1823266cbcc",
            "9ecb5b74-fa2e-4485-bb7e-24c405ffc37a",
            "c65850bf-6673-4986-a12e-66812e4fc1f0",
            "73482369-676d-48fa-95bb-87b1cde93771",
            "3e3fc881-a9d1-4fd1-a020-c756de2cb236",
            "62196d34-3e8d-45b7-94b1-47e27d862855",
            "5c6ccf0f-8825-4ab5-8e76-ea0b365cb304",
            "1901c9c1-e436-4e18-b00e-8d44d6ebae1c",
            "b976ab1a-db37-4ce3-adeb-8efeb009a5b4",
            "3fb1f51b-e80e-47a1-81bf-35f8fb4e70d3",
            "7880f0ef-4229-4b2f-a8f7-36362a26ef0f",
            "daabe5fa-0fb2-453a-b73b-127d6bfcb0e3",
            "364ce587-e684-42ec-ae14-cbf064791fbb",
            "2b1acb6d-757c-4c3b-9bd8-dce0c18236e0",
            "1f385332-314e-4b90-b843-39f70f418070",
            "e5fa48ca-dfc2-4c33-bf5d-1f9b53014cf6",
            "3015e851-dde2-4585-95d4-97664b615818",
            "294a91b9-f19b-453c-a28e-84f849689766",
            "11a8664e-3108-4212-bcec-2834d8d0c3ea",
            "2622aed8-63d4-4279-8a3e-6d09f20b9d77",
            "14ebf59b-be67-4071-a81a-ae0701ec8913",
            "139ec678-76af-47d6-a268-66be6e1286fe",
            "9d225f55-e071-46c6-9488-3ba991c87c3c",
            "33d4a6a5-f445-4eda-8e56-dbc5249f0b86",
            "c67e5376-08cb-4f3c-9bc9-40ee450b9ff9",
            "f0b73434-fb12-4973-9e62-ea8b77a5ed85",
            "ad7bab6c-ea3b-41db-98ce-76d5bc6e23df",
            "ed750e5e-482f-442c-b700-10c918f056ad",
            "6801c25b-56b6-4286-8ade-894a2d9e0680",
            "b2fe6bf6-569d-4884-8de5-456d4ca67ac0",
            "1881712b-33b3-4dfb-9f68-0a900ad61217",
            "57378c00-22f7-4522-8f3b-f84bdcb56356",
            "435a3a3a-be70-45ef-9e43-b6d4d4bfb5dc",
            "c133aaa8-1499-49ce-b3ce-876c88ddfd11",
            "e942f6e7-a993-49db-97fd-836fc12c7ccb",
            "3581c519-e884-4428-8cb0-54418d94778d",
            "0393f26d-b7b4-473e-8fe4-d936f4ecaf64",
            "e7285967-c15b-463f-ab9f-8ec5ecf8fe58",
            "cff93920-b05e-4af3-bd44-960c7e4bffd7",
            "b04c9696-02bc-4eb4-ad09-e89604fa2c4f",
            "0b172ec6-21e1-473d-b6f6-6bf034a01bd7",
            "a1e603e6-7d52-4886-8e8d-19fd3f164789",
            "a1f08d6c-0c18-4a39-aa53-44eba0148f02",
            "c57c0c90-05aa-439b-80e0-e6faaf96fb6f",
            "6bc49e65-3512-45da-b9e2-89836ef7ae15",
            "72e2d40e-89c0-4e82-895f-a6ae85fd2a88",
            "5616cf32-0386-478f-a54f-5c6fc08e1272",
            "a5552e20-24ef-4eea-87f8-30d3eac37967",
            "e3bcb7ac-2570-4c2c-b4d6-b6635076356b",
            "965e6601-2062-4d90-96d3-84f02b58dcb4",
            "da9a06cb-4df1-440a-97c5-2a0f8c25f36c",
            "bd14fdda-5143-4c0c-b850-4f956c452e09",
            "35374971-723c-4785-858d-490f2303cbec",
            "160992d5-69bf-4250-8827-43bf241a1eb1",
            "a9525395-9ee7-49ef-a862-e71246ad4492",
            "ff248035-3655-48bd-a050-dad4760ae44f",
            "06a6d47d-ac2d-495d-ae3f-392699287d9e",
            "71f6b03d-9e71-4c9b-aed0-876202d3b85d",
            "3d751c9f-3fe8-4604-b1be-769f2ea695e9",
            "76935829-8dde-473e-ab1d-f656b647a9dd",
            "1e08bc93-57c9-4c22-8722-5648338d8ed8",
            "accaf665-c9d7-470f-9358-62559de3eefc",
            "8bda321f-4044-4074-9837-47178d141cb5",
            "76cb6dd4-540d-44e7-925f-e0bf2f79d933",
            "a1541c9e-a954-4e08-809a-5d58c38be9d5",
            "7ae73b97-ce32-4331-96ff-a384737b29e0",
            "810bfc2e-210d-4dce-ae15-4aa36b98b668",
            "bdcd2692-0d47-4eee-a759-554ad2e44de2",
            "ba75a7ee-a12e-4e23-8af8-43791ad86acb",
            "f28b284c-cbf6-46fd-8d7e-8719583d7856",
            "f9cf4084-281f-414a-8982-d77bed1bbab9",
            "66294e26-f6ee-402b-8dc7-345f9a6ff70f",
            "aa053cf4-9cfe-455a-8c02-a210c41fc9a7",
            "c4377a93-b051-486b-a3b2-7083e97ba30a",
            "1b307369-85f4-4add-a637-d6e9e6736062",
            "07ae7ba9-19d3-4896-b8d0-3db18f748c6d",
            "c476e26b-86f9-48a7-918d-db01d3ce32e2",
            "b2691b77-3ae5-4e9d-80ce-7323225ea4e2",
            "658f00aa-326c-4f09-b7c3-545875aa4040",
            "6b5aa4a0-dea4-4d1b-983e-2326ce73e691",
            "1c625355-5125-4fa1-b013-7380e5890c1f",
            "b2f78115-6dc3-472f-857b-bcce0ad8abd6",
            "7b920a9d-832c-46ec-889f-822428385a5a",
            "6c3c80a0-05e6-4b74-9d1c-6160968b69e6",
            "53ff60fa-ce72-44cf-b9b8-0b28007bd762",
            "27970960-aff3-4836-957c-e3a805c1dd4d",
            "a1be25ea-fdb7-47bb-b702-263d4711906a",
            "bf9f0e0c-56c7-49bd-aaa0-2f77f7f854b1",
            "100d3463-7497-4198-a510-7f4e9e6444b5",
            "83be37e1-a31b-4012-80fe-5da7d8cdcf95",
            "8e4a6ce1-fd11-4572-ae9f-46054d40be59",
            "13fd7766-bacf-4c0f-8afc-1135682c76fc",
            "1d4f55cb-f305-4c05-acae-3ccc8c3a4a3c",
            "015430cf-8a43-4767-b4f1-9a4f6fc237f0",
            "42ceacd0-c064-4088-aa84-2633f71d2987",
            "a6ca7fba-d218-4b5e-ad43-e619238ac32a",
            "ee64da69-757a-4918-9d92-6a6d44de5108",
            "63ae597c-6ac2-424e-be45-0aa7c68039a8",
            "bc58ccc7-a0e4-40d6-9d2e-0cb196a790d9",
            "d3f4f16f-c8c7-45aa-9f96-29e4ac05aecf",
        ],
    ),
}


def get_validation_campaign(slug: str) -> "ValidationCampaign | None":
    """Look up a validation campaign by slug (None if unknown)."""
    return VALIDATION_CAMPAIGNS.get(slug)


# Instantiate the settings. This will trigger loading from .env/environment and validation.
settings = AppSettings()

# You can still export PROJECT_ROOT_DIR if other modules (like paths.py) need it directly,
# though settings now centrally manages many configurable aspects.