"""Configuration for bibcode collection runs."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class StrategyConfig(BaseModel):
    name: str
    type: str  # "keyword" | "bibstem" | "bibgroup" | "arxiv_class"
    params: dict
    enabled: bool = True


class CollectionConfig(BaseModel):
    output_dir: Path = Field(default=Path("data/raw/bibcodes/helio"))
    year_range: tuple[int, int] | None = Field(default=None)
    request_delay: float = Field(default=1.0)
    max_results_per_strategy: int | None = Field(default=None)
    fields: list[str] = Field(default=["bibcode"])
    strategies: list[StrategyConfig]


def load_config(path: Path) -> CollectionConfig:
    with open(path) as f:
        data = yaml.safe_load(f)
    return CollectionConfig(**data)
