import pytest
import json
from pathlib import Path
from typing import Any, Generator, Tuple
from paper_data_linking.linkers.general.normalizers.normalization_context import (
    NormalizationContext,
    GroundingResult,
)
from paper_data_linking.linkers.general.normalizers.normalization_models import (
    InternalDataCollectionPeriod,
)
from paper_data_linking.config.settings import (
    LLMPipelineConfig,
    LLMCallConfig,
    NormalizationConfig,
    InstrumentGroundingConfig,
)


@pytest.fixture(scope="session")
def data_dir() -> Path:
    """Fixture that provides the test data directory path.

    Session-scoped so the path is calculated only once per test session.
    Points to: tests/data/
    """
    return Path(__file__).parent.parent / "data"


@pytest.fixture(scope="session")
def normalization_test_data_dir(data_dir) -> Path:
    """Fixture that provides the normalization test data directory path.

    Session-scoped for efficiency.
    Points to: tests/data/normalization_test_data/
    """
    return data_dir / "normalization_test_data"


@pytest.fixture
def load_normalization_test_data(normalization_test_data_dir):
    """Fixture that loads normalization test data from JSON files.

    Returns a function that takes a filename and returns the loaded JSON data.
    Files should be in tests/data/normalization_test_data/

    The JSON files contain both structured instrument details AND grounding results,
    representing the complete input state before normalization.
    """

    def _load(file_name: str) -> Any:
        file_path = normalization_test_data_dir / file_name

        if not file_path.exists():
            pytest.fail(f"Test data file not found: {file_path}")

        try:
            with open(file_path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            pytest.fail(f"Failed to parse JSON from {file_path}: {e}")
        except Exception as e:
            pytest.fail(f"Unexpected error reading {file_path}: {e}")

    return _load


@pytest.fixture
def normalization_contexts_from_test_data(load_normalization_test_data):
    """Fixture that converts normalization test data into NormalizationContext objects.

    Returns a function that takes a filename and yields (instrument_name, period_name, context) tuples.

    This mimics how StructuredNormalizer._run_dynamic_normalizers constructs contexts,
    but reads grounding results directly from the test data JSON files.
    """

    def _build_contexts(
        file_name: str,
    ) -> Generator[Tuple[str, str, NormalizationContext], None, None]:
        """Build NormalizationContext objects from normalization test data.

        Args:
            file_name: Name of the JSON file in tests/data/normalization_test_data/

        Yields:
            Tuples of (instrument_name, period_name, NormalizationContext)
        """
        test_data = load_normalization_test_data(file_name)

        for instrument in test_data["instruments"]:
            instrument_name = instrument.get("name", "Unknown")

            # Extract grounding result from JSON (required field)
            grounding_result = instrument.get("grounding_result")
            if not grounding_result:
                pytest.fail(
                    f"Missing grounding_result in test data for instrument: {instrument_name}"
                )

            # Extract required fields from grounding result (mimics _run_dynamic_normalizers)
            data_system = grounding_result.get("data_system")
            if not data_system:
                pytest.fail(
                    f"Missing data_system in grounding result for instrument: {instrument_name}"
                )

            inst_code = grounding_result.get("matched_instrument_code", "unknown")

            # Create safe grounding result with all required fields (mimics lines 75-82 of structured_normalizer.py)
            safe_grounding_result = {
                "matched_instrument_code": grounding_result.get(
                    "matched_instrument_code"
                ),
                "matched_mission_code": grounding_result.get("matched_mission_code"),
                "matched_instrument_name": grounding_result.get(
                    "matched_instrument_name"
                ),
                "matched_mission_name": grounding_result.get("matched_mission_name"),
                "data_system": data_system,
                "reasoning": grounding_result.get("reasoning", ""),
            }

            for period in instrument.get("data_collection_periods", []):
                period_name = period.get("period_name", "Unknown period")

                # Build InternalDataCollectionPeriod from period data
                period_data = InternalDataCollectionPeriod(
                    period_name=period_name,
                    time_range=period.get("time_range"),
                    time_quotes=period.get("time_quotes", []),
                    wavelengths=period.get("wavelengths"),
                    wavelength_quotes=period.get("wavelength_quotes", []),
                    physical_observable=period.get("physical_observable"),
                    physobs_quotes=period.get("physobs_quotes", []),
                    general_quotes=period.get("general_quotes", []),
                    additional_comments=period.get("additional_comments"),
                )

                # Build GroundingResult object (mimics line 85)
                grounding_obj = GroundingResult(**safe_grounding_result)

                # Build NormalizationContext (mimics lines 86-96)
                context = NormalizationContext(
                    period_data=period_data,
                    instrument_code=inst_code,
                    instrument_name=instrument_name,
                    instrument_general_comments=instrument.get("general_comments", ""),
                    data_system=data_system,
                    period_name=period_name,
                    grounding_result=grounding_obj,
                )

                yield (instrument_name, period_name, context)

    return _build_contexts


@pytest.fixture
def llm_pipeline_config() -> LLMPipelineConfig:
    """Fixture that provides a test LLMPipelineConfig.

    This is used for testing normalizers that require LLM configuration.
    Uses the bedrock gpt-oss-120b model suitable for testing.
    """
    return LLMPipelineConfig(
        paper_analysis=LLMCallConfig(
            model="bedrock/converse/openai.gpt-oss-120b-1:0",
            temperature=1.0,
            max_tokens=None,
            aws_region_name="us-west-2"
        ),
        structured_parsing=LLMCallConfig(
            model="bedrock/converse/openai.gpt-oss-120b-1:0",
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
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            wavelength=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            physical_observable=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            detector=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            ),
            cadence=LLMCallConfig(
                model="bedrock/converse/openai.gpt-oss-120b-1:0",
                temperature=1.0,
                max_tokens=None,
                aws_region_name="us-west-2"
            )
        ),
        instrument_grounding=InstrumentGroundingConfig(
            validation=LLMCallConfig(
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
    )