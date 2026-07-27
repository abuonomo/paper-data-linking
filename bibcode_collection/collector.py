"""Main bibcode collection orchestrator."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm

from .ads_client import ADSClient
from .config import CollectionConfig, load_config
from .strategies import (
    arxiv_class_search,
    bibgroup_search,
    bibstem_search,
    keyword_search,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

STRATEGY_BUILDERS = {
    "keyword": keyword_search,
    "bibstem": bibstem_search,
    "bibgroup": bibgroup_search,
    "arxiv_class": arxiv_class_search,
}


def collect(config: CollectionConfig, dry_run: bool = False) -> dict:
    """Run all enabled strategies, save per-strategy results, then merge."""
    client = ADSClient(delay=config.request_delay)
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_bibcodes: set[str] = set()
    run_metadata = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "strategies": {},
    }

    enabled = [s for s in config.strategies if s.enabled]

    for strategy in tqdm(enabled, desc="Strategies"):
        if strategy.type == "library":
            # Library strategy: fetch bibcodes directly from ADS biblib API
            libraries = strategy.params.get("libraries", {})
            all_lib_bibcodes: set[str] = set()

            for lib_name, lib_id in libraries.items():
                if dry_run:
                    count = client.library_count(lib_id)
                    logger.info(f"Strategy '{strategy.name}' / {lib_name}: {count:,} papers  |  library={lib_id}")
                else:
                    lib_bibcodes = client.library_bibcodes(lib_id)
                    logger.info(f"Strategy '{strategy.name}' / {lib_name}: {len(lib_bibcodes):,} bibcodes  |  library={lib_id}")
                    all_lib_bibcodes.update(lib_bibcodes)

                    # Write per-library file for provenance tracking
                    lib_file = output_dir / f"{lib_name}_bibcodes.txt"
                    lib_file.write_text("\n".join(sorted(lib_bibcodes)) + "\n")

            run_metadata["strategies"][strategy.name] = {
                "libraries": {name: lid for name, lid in libraries.items()},
            }

            if not dry_run:
                bibcodes = sorted(all_lib_bibcodes)
                strategy_file = output_dir / f"{strategy.name}_bibcodes.txt"
                strategy_file.write_text("\n".join(bibcodes) + "\n")
                run_metadata["strategies"][strategy.name]["fetched"] = len(bibcodes)
                all_bibcodes.update(bibcodes)

            continue

        builder = STRATEGY_BUILDERS[strategy.type]
        query = builder(**strategy.params, year_range=config.year_range)
        count = client.count(query)

        logger.info(f"Strategy '{strategy.name}': {count:,} results  |  q={query}")

        run_metadata["strategies"][strategy.name] = {
            "query": query,
            "total_in_ads": count,
        }

        if dry_run:
            continue

        docs = client.search(
            query,
            fields=config.fields,
            max_results=config.max_results_per_strategy,
        )
        bibcodes = sorted({doc["bibcode"] for doc in docs})

        strategy_file = output_dir / f"{strategy.name}_bibcodes.txt"
        strategy_file.write_text("\n".join(bibcodes) + "\n")

        run_metadata["strategies"][strategy.name]["fetched"] = len(bibcodes)
        all_bibcodes.update(bibcodes)

    if not dry_run:
        merged_file = output_dir / "all_helio_bibcodes.txt"
        merged_file.write_text("\n".join(sorted(all_bibcodes)) + "\n")
        run_metadata["total_unique"] = len(all_bibcodes)

    metadata_file = output_dir / "collection_metadata.json"
    metadata_file.write_text(json.dumps(run_metadata, indent=2) + "\n")

    return run_metadata


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Collect heliophysics bibcodes from ADS")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent / "configs" / "default.yaml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show counts, don't fetch full results",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    result = collect(config, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
