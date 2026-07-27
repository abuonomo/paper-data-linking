"""Tests for StructureValidatorRegistry."""

import pytest

from paper_data_linking.linkers.general.validators.base_validator import (
    BaseStructureValidator,
)
from paper_data_linking.linkers.general.validators.validator_registry import (
    StructureValidatorRegistry,
)


class _DummyValidator(BaseStructureValidator):
    def detect(self, structured, original_markdown):
        return []

    def fix(self, structured, issues, original_markdown):
        return structured


class TestStructureValidatorRegistry:
    def setup_method(self):
        """Save and restore registry state around each test."""
        self._saved = dict(StructureValidatorRegistry._registry)

    def teardown_method(self):
        StructureValidatorRegistry._registry = self._saved

    def test_register_and_get(self):
        @StructureValidatorRegistry.register("test_v1", version="1.0", priority=0)
        class V1(_DummyValidator):
            pass

        assert StructureValidatorRegistry.get("test_v1") is V1

    def test_list_ordered_by_priority(self):
        @StructureValidatorRegistry.register("prio_high", version="1.0", priority=10)
        class VHigh(_DummyValidator):
            pass

        @StructureValidatorRegistry.register("prio_low", version="1.0", priority=0)
        class VLow(_DummyValidator):
            pass

        @StructureValidatorRegistry.register("prio_mid", version="1.0", priority=5)
        class VMid(_DummyValidator):
            pass

        ordered = StructureValidatorRegistry.list_ordered()
        # Filter to just our test validators
        test_names = [n for n in ordered if n.startswith("prio_")]
        assert test_names == ["prio_low", "prio_mid", "prio_high"]

    def test_duplicate_raises(self):
        @StructureValidatorRegistry.register("dup_test", version="1.0", priority=0)
        class V1(_DummyValidator):
            pass

        with pytest.raises(ValueError, match="already registered"):
            @StructureValidatorRegistry.register(
                "dup_test", version="1.0", priority=0
            )
            class V2(_DummyValidator):
                pass

    def test_get_missing_raises(self):
        with pytest.raises(ValueError):
            StructureValidatorRegistry.get("nonexistent_validator_xyz")
