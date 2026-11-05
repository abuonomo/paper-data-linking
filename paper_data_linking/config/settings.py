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
        configs=["vllm-gemma4@e2e2", "bedrock-120b-mixed-v5@s1"],
        set_tag="window2026:set",
        tag_prefix="window2026:",
        reviewers=["abuonomo"],
        overlap_tag="window2026:overlap",
        calibration_tag="window2026:calibration",
        calibration_size=0,
        claim_scoped=True,
        # Frozen from sample_window_claims --seed 20261105 --rejudge (100 claims, 66 papers;
        # the unblinding key lives in pdl-paper/validation/window2026_sample_key.json).
        # @s1, not @mx2: the @mx runs were loaded onto prod without SupportQuotes,
        # which left every gpt-oss claim quote-less and recognisable. @s1's
        # disagreement claims all carry val2026 verdicts, hence --rejudge.
        started_at="2026-11-05T13:06:32Z",
        claim_usage_ids=[
            "34918ca2-31a0-4aa1-ae02-51c5b4fdaf7d",
            "fd73f71f-5648-4ac2-bec5-97c3869303b0",
            "b07d6aaa-b7b8-4f85-9745-16067114aea8",
            "1be3143d-cd25-4f9b-9fd5-28e181b0db93",
            "f15febec-7037-4860-ae7e-339ab264a735",
            "106616a2-f659-4342-bf37-2638ac1c966b",
            "09f7592a-2b08-4d60-b5cb-97131d33bf91",
            "f1ce7e68-be65-4773-88aa-f0a5856eab58",
            "3569c401-bf66-4a85-b443-8a16b94303af",
            "c11863c2-16a4-4a08-b58c-531150124a7b",
            "295f0bdc-21e3-4b32-8f7c-5fb1e0ac51d6",
            "31335b96-0b23-4ed4-986a-d32f7fcff712",
            "adf19638-5c6f-4b52-83a8-3975fb217cbd",
            "93097528-3fb1-4b9a-aeef-049c42dbe93f",
            "b23f9da8-0b18-404f-bbfe-4a25fc126f39",
            "3b192ec9-a425-4f54-8597-1a52d8532ccf",
            "5f62ba94-28af-40d8-a5bb-5d2aa2236b00",
            "951e7584-a420-4dec-bf62-7fbc6b4e40fb",
            "ededbd11-1aa8-4aa2-926b-7ed315f636d5",
            "0dfc7352-79fa-4087-9bbe-0f96d4fb9288",
            "be991093-6498-477f-9e30-69943a365658",
            "d297bde8-58f1-435f-af43-919048b08f70",
            "89659814-3bf0-4ae7-aa28-c7cf1324b550",
            "69d29d6e-109c-4b1f-9b47-09011717a40d",
            "056f3972-cc93-4fd5-bcf0-eb0fd971b503",
            "73b9b5ea-1785-436d-b42b-ee1c2cf0001e",
            "4a25a635-dfea-41c5-ab22-1ffc5ea649ac",
            "f72e0d0f-80ea-4745-8c78-0e4ca4599c79",
            "25ab2b26-04a4-45c1-8a0f-e4f638471bb5",
            "1b1bc49e-abeb-493b-bff8-42ea6e219db5",
            "ed7acae0-557a-4c58-aeef-4c975e0d75b5",
            "92d29e01-ddd6-4190-950f-565f2ed8744b",
            "59350d26-2656-4eac-b5a9-dd554bd8ec26",
            "fa4fe305-99a2-4bbc-a1a4-078e45c7bdf2",
            "3086186d-1ffd-4826-a9e5-4793dd403ffc",
            "5d2a76e4-4993-4840-afb7-f5f5da51d594",
            "17a60e65-1b0f-4d99-a128-d5ec74ce8ce3",
            "3c361a00-7db1-45ba-967e-f88573812fd1",
            "6f2020a6-c1bc-4bf0-8d57-52ea6ad81697",
            "fd036819-5201-4415-915e-f9540999cba1",
            "66c3ac0b-17f6-4197-b39a-288811528855",
            "9902a96f-7f22-4043-bca6-f974efe5ff6a",
            "48e9bc1b-135f-455e-b226-06afaf9b9959",
            "09b5bb62-af62-4566-abcf-31e16108e402",
            "d0637a99-4678-43b1-b6e5-c39002f48d9b",
            "31b3021b-1d92-4523-a588-43985b573723",
            "1e08bc93-57c9-4c22-8722-5648338d8ed8",
            "a1c720b1-0f23-4260-a2ac-4bfec2eeed58",
            "bd38b005-8238-4f6f-98d7-bc1c611ab571",
            "fa0fe056-d837-4adb-a3d7-39e721923068",
            "4ce5aaaf-1a0d-4d9a-9674-821038678dc7",
            "74dbf491-c040-4491-a15e-df2a36871faf",
            "0585ee3d-be10-4016-b733-6af953d2d2d8",
            "78713aec-abe5-43d2-9924-95a0c358cc9b",
            "bdc34e16-dc0e-4628-843e-34324c995911",
            "63ea5556-9065-4c1d-bc74-5dc4d9c4e9d9",
            "042ea550-24c2-4b6d-8bc8-72fc8133a79f",
            "98af05df-e2ed-4d80-9a9e-e0590d951fe7",
            "9607656f-dab0-46e5-b12d-af8d7bc60bb8",
            "eba8645b-9f7e-4762-a038-175e1b83a1ae",
            "bcc596ae-be4e-4413-b56e-516a19db4f26",
            "bd6d9cfc-63b4-4cc7-a864-53f87bb41d69",
            "475b6676-8ef9-46d2-b9d7-6707adef3d57",
            "ca69c94c-ef1e-4957-90ca-fd5b0132be91",
            "9286bc89-095b-4290-a341-e9f1e907bf76",
            "a0d216f1-9ec2-42cd-9c0d-c04f728f256d",
            "7e81d0a2-c6ce-4f9e-87b8-2e5919fd59db",
            "7c0af59f-c920-44e2-974a-51519011bb90",
            "19867fee-398d-47c4-b477-aa42f72e9886",
            "4e731a8b-a75c-4714-98ee-614830c5c69b",
            "aa37424c-fbbe-4d97-8bc9-8e3580b69469",
            "f68d78fe-e144-455a-95b3-ed1b952d6177",
            "af840eda-cfdd-46ae-9d41-f0f55793d41d",
            "fdde48a0-aebe-4313-85ba-2a16914b2e5e",
            "bae2bfab-6eea-4aed-aba0-322cc13050eb",
            "9edf54aa-02bb-4d2c-9846-abb479537c9c",
            "103c159e-f832-40b7-a3d8-f457a27c66f2",
            "56b3cfe2-974c-404f-b1ca-a9e75023d980",
            "3166b956-5c67-426c-a020-5497d881d5ea",
            "4791534c-46ea-4489-89fb-7994a2e6af67",
            "34681b0b-a6bf-486d-99c7-c2d3ab768032",
            "927f4edf-6c1f-4b31-88f7-a5123499e94a",
            "c5a9f25f-8261-4f2a-8990-4ebccf765c11",
            "8c683162-9c6c-4557-b1ce-308718d8bb76",
            "5c043fc6-fdf0-43eb-8230-903f8bb80c9d",
            "56649604-147e-4c9f-99bc-628e4b4e4672",
            "3015e851-dde2-4585-95d4-97664b615818",
            "2c3717c7-2826-4bac-bc50-f34a78c41836",
            "294fe891-69cc-439a-91d3-d4b0aab1ad6f",
            "0a712e12-b033-4209-8413-3e5bf43ff82c",
            "d199dc45-6728-4fb2-b37e-05ad76f55dcd",
            "bfdbd10f-bff4-4299-9cf7-a2b93fbf002f",
            "8a087930-f7a0-4ba5-b56b-a86f37ce996d",
            "23ce6d53-d3a7-4211-8464-7769865732e8",
            "c56686c2-681a-4c44-a07b-f7a1eda41898",
            "7ff9d51c-e7cf-4a68-9c5e-dd7938aca56c",
            "dd078822-25e2-4523-a8c0-004fba774d4c",
            "821e3b9a-dd2d-4e54-8ca0-4f293f707518",
            "3127aab8-2032-44e2-a410-1004c9d7e870",
            "318810ac-f74e-4e8c-904d-d04627c78589",
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