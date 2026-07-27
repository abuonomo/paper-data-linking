"""
Call type handlers for different LLM tasks.

Handlers are automatically registered on import.
"""
from experiments.compare_models.core.registry import CallTypeRegistry
from experiments.compare_models.handlers.instrument_validation import InstrumentValidationHandler
from experiments.compare_models.handlers.mission_validation import MissionValidationHandler
from experiments.compare_models.handlers.wavelength_normalization import WavelengthNormalizationHandler, WavelengthNormalizationSimpleHandler
from experiments.compare_models.handlers.physobs_normalization import PhysObsNormalizationHandler
from experiments.compare_models.handlers.mission_selection import MissionSelectionHandler
from experiments.compare_models.handlers.instrument_selection import InstrumentSelectionHandler
from experiments.compare_models.handlers.detector_normalization import DetectorNormalizationHandler
from experiments.compare_models.handlers.time_normalization import TimeNormalizationHandler
from experiments.compare_models.handlers.cadence_normalization import CadenceNormalizationHandler
from experiments.compare_models.handlers.mission_identification import MissionIdentificationHandler
from experiments.compare_models.handlers.structure_analysis import StructureAnalysisHandler
from experiments.compare_models.handlers.physobs_normalization_free_text_v2 import PhysObsNormalizationFreeTextV2Handler
from experiments.compare_models.handlers.detector_normalization_free_text_v2 import DetectorNormalizationFreeTextV2Handler
from experiments.compare_models.handlers.cadence_normalization_free_text import CadenceNormalizationFreeTextHandler

# Auto-register handlers
CallTypeRegistry.register(InstrumentValidationHandler())
CallTypeRegistry.register(MissionValidationHandler())
CallTypeRegistry.register(WavelengthNormalizationHandler())
CallTypeRegistry.register(WavelengthNormalizationSimpleHandler())
CallTypeRegistry.register(PhysObsNormalizationHandler())
CallTypeRegistry.register(MissionSelectionHandler())
CallTypeRegistry.register(InstrumentSelectionHandler())
CallTypeRegistry.register(DetectorNormalizationHandler())
CallTypeRegistry.register(TimeNormalizationHandler())
CallTypeRegistry.register(CadenceNormalizationHandler())
CallTypeRegistry.register(MissionIdentificationHandler())
CallTypeRegistry.register(StructureAnalysisHandler())
CallTypeRegistry.register(PhysObsNormalizationFreeTextV2Handler())
CallTypeRegistry.register(DetectorNormalizationFreeTextV2Handler())
CallTypeRegistry.register(CadenceNormalizationFreeTextHandler())

# Export for convenience
__all__ = [
    'InstrumentValidationHandler',
    'MissionValidationHandler',
    'WavelengthNormalizationHandler',
    'WavelengthNormalizationSimpleHandler',
    'PhysObsNormalizationHandler',
    'MissionSelectionHandler',
    'InstrumentSelectionHandler',
    'DetectorNormalizationHandler',
    'TimeNormalizationHandler',
    'CadenceNormalizationHandler',
    'MissionIdentificationHandler',
    'StructureAnalysisHandler',
]
