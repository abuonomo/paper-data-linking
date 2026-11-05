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
    # Time-window validity of self-hosted Gemma (all stages) vs gpt-oss: a review of
    # the claims where the two configs DISAGREE on the eval set and val2026 has no
    # verdict (shared claims cannot change the comparison).
    "window2026": ValidationCampaign(
        slug="window2026",
        configs=["vllm-gemma4@e2e2", "bedrock-120b-mixed-v5@s1"],
        set_tag="window2026:set",
        tag_prefix="window2026:",
        reviewers=["abuonomo"],
        overlap_tag="window2026:overlap",
        calibration_tag="window2026:calibration",
        calibration_size=0,
        claim_scoped=True,
        # Frozen from sample_window_claims --seed 20261105 (50 claims, 33 papers; the sample
        # key lives in pdl-paper/validation/window2026_sample_key.json). All claims come
        # from the first config: every disagreement claim of @s1 already carries a val2026
        # verdict, which the analysis carries over. Not blind to config. @s1 rows must not
        # be re-judged here: verdicts are per (usage, user), so that would overwrite val2026.
        started_at="2026-11-05T13:59:07Z",
        claim_usage_ids=[
            "b42c6b44-9696-44cf-9211-ba93a130fc98",
            "a40df7e0-5715-4c77-83ba-abaab52ad149",
            "d1cc33b3-f7d5-499d-afba-8a8321bb6623",
            "fb44fa7f-cf8c-4071-ae7a-76dd3976c1a2",
            "77678084-28a8-4967-ac9b-1007d9c59e16",
            "afd35b1e-569f-4dfa-a516-fb563ef904d5",
            "717dfa10-0bae-476f-9ab2-62ff47aab46b",
            "dd078822-25e2-4523-a8c0-004fba774d4c",
            "88578eb4-5776-4b1d-b8a7-0f40253c64db",
            "fae0b2cb-9fda-4d36-bb2d-2ee9c9a17094",
            "a1be25ea-fdb7-47bb-b702-263d4711906a",
            "0dbf22a0-2d84-4847-bddb-b99b2fd1324a",
            "daf41508-2f66-4303-9693-474941a04751",
            "aa37424c-fbbe-4d97-8bc9-8e3580b69469",
            "79ad87ff-07a0-41aa-ba9b-df7db96b5980",
            "053d7dc9-734f-4ad0-b6a0-de79b8f995e7",
            "17a60e65-1b0f-4d99-a128-d5ec74ce8ce3",
            "83be37e1-a31b-4012-80fe-5da7d8cdcf95",
            "0f575386-046c-4d1f-9693-29dd2db6e350",
            "a1f08d6c-0c18-4a39-aa53-44eba0148f02",
            "61399980-9450-4293-9a14-37389bb8f446",
            "b2691b77-3ae5-4e9d-80ce-7323225ea4e2",
            "37fd5853-0f35-4cdb-a4c0-4674694d9126",
            "af8bdbc3-632a-4b58-a8aa-27db991c60e6",
            "1357a9d8-2a10-4ab9-b0ba-3f31a3baf926",
            "f4ba0541-22d5-40ea-b20b-961ad1753e37",
            "33f8eeef-f3c9-4b96-9921-1402e96a57b1",
            "1de8e6f6-b7eb-4ac4-ad28-20ade15be05e",
            "0dd3a2e7-9a25-4c2b-9ef4-456c19ff8041",
            "9ecb5b74-fa2e-4485-bb7e-24c405ffc37a",
            "72e2d40e-89c0-4e82-895f-a6ae85fd2a88",
            "6d3004fb-1aaa-4f11-87f4-1adbaead2f04",
            "fd98ae73-2aca-4255-9232-1fdab324f845",
            "35374971-723c-4785-858d-490f2303cbec",
            "b98b0c71-4cce-4384-8926-d16ac1cd24eb",
            "f28b284c-cbf6-46fd-8d7e-8719583d7856",
            "29e57a65-9d34-4f44-a1e2-bff6b092dcab",
            "eeab5207-054a-4200-aa79-f9e719119101",
            "3303a3f8-bc62-4f15-8d8b-52f33cf68de9",
            "a87e27fb-6230-4104-a872-80b951aa709f",
            "b07d6aaa-b7b8-4f85-9745-16067114aea8",
            "372e33ca-2fdb-44c7-8140-249989978bb0",
            "7cd86cb5-50d6-4935-bc3f-249a3be16b88",
            "954d47ba-bf9b-4234-897e-739a82208a1b",
            "cfe80ceb-32d3-46ca-b8d6-8072a262c63e",
            "3da7bce1-a22d-46e8-b170-3d34b5330dda",
            "2074e934-5b55-41b6-b925-182e9378aa36",
            "273f784c-0875-4ba4-af3f-1f2e68c72ac3",
            "7d943703-3484-43cf-9e94-68c52bd9a4a5",
            "adff25d2-8b5c-403a-81e9-13d9282928ae",
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