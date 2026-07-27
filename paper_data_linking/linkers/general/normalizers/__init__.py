# Import normalizers to trigger registry decorators
from .time_range_normalizer import TimeRangeNormalizer
from .wavelength_normalizer import WavelengthNormalizer
from .physobs_normalizer import PhysObsNormalizer
from .quote_normalizer import QuoteNormalizer
from .detector_normalizer import DetectorNormalizer
from .cadence_normalizer import CadenceNormalizer
from .phenomenon_normalizer import PhenomenonNormalizer

# Export the registry for easy access
from .normalizer_registry import NormalizerRegistry

__all__ = [
    "TimeRangeNormalizer",
    "WavelengthNormalizer",
    "PhysObsNormalizer",
    "QuoteNormalizer",
    "DetectorNormalizer",
    "CadenceNormalizer",
    "PhenomenonNormalizer",
    "NormalizerRegistry"
]