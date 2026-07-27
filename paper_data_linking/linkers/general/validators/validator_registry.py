from dataclasses import dataclass
from typing import Dict, List, Type

from .base_validator import BaseStructureValidator


@dataclass
class ValidatorInfo:
    """Metadata for a registered validator."""

    class_ref: Type[BaseStructureValidator]
    version: str = "1.0"
    description: str = ""
    priority: int = 0  # Lower runs first


class StructureValidatorRegistry:
    """Registry for structure-level validators."""

    _registry: Dict[str, ValidatorInfo] = {}

    @classmethod
    def register(cls, name: str, version: str = "1.0", priority: int = 0):
        def wrapper(validator_class: Type[BaseStructureValidator]):
            if name in cls._registry:
                existing = cls._registry[name].class_ref
                raise ValueError(
                    f"Validator '{name}' already registered by "
                    f"{existing.__module__}.{existing.__name__}"
                )
            cls._registry[name] = ValidatorInfo(
                class_ref=validator_class,
                version=version,
                description=validator_class.__doc__ or "",
                priority=priority,
            )
            return validator_class

        return wrapper

    @classmethod
    def get(cls, name: str) -> Type[BaseStructureValidator]:
        if name not in cls._registry:
            raise ValueError(f"Validator '{name}' not found")
        return cls._registry[name].class_ref

    @classmethod
    def list_ordered(cls) -> List[str]:
        """Return validator names ordered by priority (lowest first)."""
        return sorted(
            cls._registry.keys(), key=lambda n: cls._registry[n].priority
        )

    @classmethod
    def all(cls) -> Dict[str, ValidatorInfo]:
        return dict(cls._registry)
