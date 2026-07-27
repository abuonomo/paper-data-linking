from paper_data_linking.linkers.general.instrument_grounder import InstrumentGrounder
from paper_data_linking.linkers.general.structured_normalizer import StructuredNormalizer
from .clients import DjangoLiteLLMClient
from .finders import DjangoInstrumentFinder

# Singleton instances to avoid re-creation on every call
_instrument_grounder_instance = None
_structured_normalizer_instance = None


def get_instrument_grounder() -> InstrumentGrounder:
    """Factory to get the singleton InstrumentGrounder instance, configured for Django."""
    global _instrument_grounder_instance
    if _instrument_grounder_instance is None:
        finder = DjangoInstrumentFinder()
        _instrument_grounder_instance = InstrumentGrounder(finder=finder)
    return _instrument_grounder_instance


def get_structured_normalizer() -> StructuredNormalizer:
    """Factory to get the singleton StructuredNormalizer, with dependencies injected."""
    global _structured_normalizer_instance
    if _structured_normalizer_instance is None:
        grounder = get_instrument_grounder()
        _structured_normalizer_instance = StructuredNormalizer(instrument_grounder=grounder)
    return _structured_normalizer_instance


def get_django_structured_normalizer(association_callback=None, llm_config=None, phenomena=None) -> StructuredNormalizer:
    """Factory to get StructuredNormalizer with Django LLM client for token tracking."""
    django_client = DjangoLiteLLMClient(association_callback=association_callback)

    if llm_config is None:
        raise ValueError("llm_config is required for get_django_structured_normalizer")

    finder = DjangoInstrumentFinder()
    grounder = InstrumentGrounder(finder=finder, llm_client=django_client, llm_config=llm_config)

    return StructuredNormalizer(
        instrument_grounder=grounder,
        llm_client=django_client,
        llm_config=llm_config,
        phenomena=phenomena,
    )