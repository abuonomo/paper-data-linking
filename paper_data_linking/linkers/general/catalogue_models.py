# paper_data_linking/linkers/general/catalogue_models.py

from pydantic import BaseModel, field_validator
from typing import List, Optional, Union


class Mission(BaseModel):
    """
    Simple model for mission data used in instrument grounding.

    Represents a unique mission/observatory with its associated data system.
    """
    mission_code: str
    mission_name: str
    data_system: str
    description: Optional[str] = None

    @field_validator('mission_code', 'mission_name', 'data_system')
    def strings_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Mission fields cannot be empty')
        return v.strip()

    @field_validator('data_system')
    def normalize_data_system(cls, v):
        # Normalize to lowercase for consistency
        normalized = v.strip().lower()

        # Validate against known data systems
        valid_systems = {'vso', 'cdaweb', 'pds'}
        if normalized not in valid_systems:
            # Allow unknown systems but log a warning
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Unknown data_system in Mission: {normalized}. Known systems: {valid_systems}")

        return normalized


class CatalogueEntry(BaseModel):
    """
    Explicit data contract for instrument catalogue entries.

    All finders must produce entries that conform to this schema.
    This ensures consistency and prevents silent defaults that can lead to incorrect results.
    """

    # Core identifying fields
    instrument_code: Optional[str] = None  # None for mission-only matches
    instrument_name: Optional[str] = None  # None for mission-only matches
    mission_code: str
    mission_name: str
    data_system: str  # Required - no silent defaults allowed

    # Additional metadata fields
    description: str = ""  # Can be empty but not null in database

    @field_validator('mission_code')
    def mission_code_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('mission_code cannot be empty')
        return v.strip()

    @field_validator('instrument_code')
    def instrument_code_strip(cls, v):
        return v.strip() if v else None

    @field_validator('data_system')
    def data_system_must_be_valid(cls, v):
        if not v or not v.strip():
            raise ValueError('data_system is required and cannot be empty')

        # Normalize to lowercase for consistency
        normalized = v.strip().lower()

        # Validate against known data systems
        valid_systems = {'vso', 'cdaweb', 'pds'}
        if normalized not in valid_systems:
            # Allow unknown systems but log a warning
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Unknown data_system: {normalized}. Known systems: {valid_systems}")

        return normalized

    @field_validator('instrument_name')
    def instrument_name_strip(cls, v):
        return v.strip() if v else None

    @field_validator('mission_name')
    def mission_name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('mission_name cannot be empty')
        return v.strip()

    @field_validator('description')
    def description_normalize(cls, v):
        # Description should never be None from database, but strip whitespace
        return v.strip() if v else ""

    class Config:
        # Allow extra fields for backwards compatibility, but validate known ones
        extra = 'allow'


class CatalogueValidationError(Exception):
    """Raised when catalogue entries don't conform to the required schema."""
    pass


def validate_catalogue_entries(entries: List[dict]) -> List[CatalogueEntry]:
    """
    Validate a list of raw catalogue entries against the schema.

    Args:
        entries: List of raw dictionary entries from finders

    Returns:
        List of validated CatalogueEntry objects

    Raises:
        CatalogueValidationError: If any entries are invalid
    """
    validated_entries = []
    errors = []

    for i, entry in enumerate(entries):
        try:
            validated_entry = CatalogueEntry(**entry)
            validated_entries.append(validated_entry)
        except Exception as e:
            errors.append(f"Entry {i}: {str(e)}")

    if errors:
        raise CatalogueValidationError(
            f"Found {len(errors)} invalid catalogue entries:\n" +
            "\n".join(errors[:10])  # Show first 10 errors
        )

    return validated_entries


def catalogue_entry_to_dict(entry: CatalogueEntry) -> dict:
    """
    Convert a validated CatalogueEntry back to a dictionary format.

    This is for backwards compatibility with existing code that expects dicts.
    """
    return entry.dict()


def validate_missions(missions: List[dict]) -> List[Mission]:
    """
    Validate a list of raw mission entries against the Mission schema.

    Args:
        missions: List of raw dictionary entries for missions

    Returns:
        List of validated Mission objects

    Raises:
        CatalogueValidationError: If any missions are invalid
    """
    validated_missions = []
    errors = []

    for i, mission_data in enumerate(missions):
        try:
            validated_mission = Mission(**mission_data)
            validated_missions.append(validated_mission)
        except Exception as e:
            errors.append(f"Mission {i}: {str(e)}")

    if errors:
        raise CatalogueValidationError(
            f"Found {len(errors)} invalid mission entries:\n" +
            "\n".join(errors[:10])  # Show first 10 errors
        )

    return validated_missions


def mission_to_dict(mission: Mission) -> dict:
    """
    Convert a validated Mission back to a dictionary format.

    This is for backwards compatibility if needed.
    """
    return mission.dict()