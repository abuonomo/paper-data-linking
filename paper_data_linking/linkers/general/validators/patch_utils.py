import re
from typing import Any, List, Union

from paper_data_linking.linkers.general.schemas.structured_instruments import (
    StructuredInstrumentDetails,
)


def apply_patch(
    model: StructuredInstrumentDetails, field_path: str, new_value: Any
) -> None:
    """
    Apply a single patch to a StructuredInstrumentDetails model in place.

    Supports paths like:
        instruments[0].data_collection_periods[1].time_range
    """
    parts = _parse_path(field_path)
    obj: Any = model
    for part in parts[:-1]:
        obj = _resolve(obj, part)

    final = parts[-1]
    if isinstance(final, int):
        obj[final] = new_value
    else:
        setattr(obj, final, new_value)


def _parse_path(path: str) -> List[Union[str, int]]:
    """Parse 'instruments[0].data_collection_periods[1].time_range' into tokens."""
    tokens: List[Union[str, int]] = []
    for segment in path.split("."):
        m = re.match(r"^(\w+)\[(\d+)\]$", segment)
        if m:
            tokens.append(m.group(1))
            tokens.append(int(m.group(2)))
        else:
            tokens.append(segment)
    return tokens


def _resolve(obj: Any, token: Union[str, int]) -> Any:
    if isinstance(token, int):
        return obj[token]
    return getattr(obj, token)
