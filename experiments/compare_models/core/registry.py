"""
Registry for call type handlers.

Provides centralized management of handlers for different LLM call types.
"""
from typing import Dict
from experiments.compare_models.core.call_handlers import CallTypeHandler


class CallTypeRegistry:
    """
    Registry for managing call type handlers.

    Handlers register themselves by calling register(), and can be
    retrieved by call_type name using get().
    """

    _handlers: Dict[str, CallTypeHandler] = {}

    @classmethod
    def register(cls, handler: CallTypeHandler) -> None:
        """
        Register a call type handler.

        Args:
            handler: Handler instance to register

        Raises:
            ValueError: If a handler with this call_type name is already registered
        """
        call_type = handler.get_call_type_name()
        # Allow re-registration (last-registered wins) so that both
        # WavelengthNormalizationHandler and WavelengthNormalizationSimpleHandler
        # (which share the same call_type name) can coexist in __init__.py.
        cls._handlers[call_type] = handler

    @classmethod
    def get(cls, call_type: str) -> CallTypeHandler:
        """
        Get handler for a specific call type.

        Args:
            call_type: Name of the call type (e.g., 'instrument_validation')

        Returns:
            Handler instance for this call type

        Raises:
            KeyError: If no handler is registered for this call_type
        """
        if call_type not in cls._handlers:
            available = ', '.join(cls._handlers.keys())
            raise KeyError(
                f"No handler registered for call_type '{call_type}'. "
                f"Available: {available}"
            )
        return cls._handlers[call_type]

    @classmethod
    def get_by_class_name(cls, class_name: str) -> CallTypeHandler:
        """
        Get handler by class name instead of call_type name.

        This is useful when experiment configs specify handler class directly,
        allowing the same handler class to be used for multiple call type variants.

        Args:
            class_name: Name of the handler class (e.g., 'PhysObsNormalizationHandler')

        Returns:
            Handler instance for this class

        Raises:
            KeyError: If no handler with this class name is registered
        """
        for handler in cls._handlers.values():
            if handler.__class__.__name__ == class_name:
                return handler

        # If not found, provide helpful error message
        available_classes = [h.__class__.__name__ for h in cls._handlers.values()]
        raise KeyError(
            f"No handler with class name '{class_name}' is registered. "
            f"Available handler classes: {', '.join(available_classes)}"
        )

    @classmethod
    def list_call_types(cls) -> list[str]:
        """Return list of all registered call type names."""
        return list(cls._handlers.keys())

    @classmethod
    def clear(cls) -> None:
        """Clear all registered handlers (primarily for testing)."""
        cls._handlers.clear()
