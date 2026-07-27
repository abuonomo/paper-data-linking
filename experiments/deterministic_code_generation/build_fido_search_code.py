from typing import Dict, List
import json
from pathlib import Path
from paper_data_linking.config.paths import DATA_ASSETS_DIR


def build_fido_search_code(normalized: Dict) -> str:
    """
    Given a normalized output dict, generate Python code that uses SunPy’s Fido.search
    to query each instrument/period.
    """
    lines: List[str] = []
    lines.append("from sunpy.net import Fido, attrs as a")
    lines.append("")

    query_count = 0
    for instrument in normalized.get("instruments", []):
        inst_norm = instrument["name"]["normalized"]
        inst_code = inst_norm.get("matched_instrument_code")
        mission_code = inst_norm.get("matched_mission_code")

        # Skip if grounding failed
        if not inst_code or not mission_code:
            continue

        # Lowercase attribute names in SunPy
        instrument_attr = inst_code.lower()
        source_attr = mission_code.lower()

        for period in instrument.get("data_collection_periods", []):
            time_norm = period["time_range"]["normalized"]
            start = time_norm.get("start_datetime")
            end = time_norm.get("end_datetime")
            # Remove trailing 'Z' for SunPy
            if start and start.endswith("Z"):
                start = start[:-1]
            if end and end.endswith("Z"):
                end = end[:-1]

            phys_norm = period["physical_observable"]["normalized"]
            categories = phys_norm.get("categories", [])
            physobs_attr = categories[0].lower() if categories else None

            query_count += 1
            lines.append(
                f"# Query for {inst_code} on {mission_code}, time {start} to {end}"
                + (f", physobs {physobs_attr}" if physobs_attr else "")
            )

            search_lines = [f"query{query_count} = Fido.search("]
            search_lines.append(f"    a.Instrument.{instrument_attr},")
            search_lines.append(f"    a.Source.{source_attr},")
            search_lines.append(f"    a.Time('{start}', '{end}')")
            if physobs_attr:
                search_lines[-1] += ","
                search_lines.append(f"    a.Physobs.{physobs_attr}")
            search_lines.append(")")

            lines.extend(search_lines)
            lines.append("")

    if query_count == 0:
        lines.append("# No valid instrument/period pairs found in the normalized input.")

    return "\n".join(lines)


if __name__ == "__main__":
    # Read normalized_output.json as input example
    normalized_path = DATA_ASSETS_DIR / "vso" / "examples" / "normalized_output.json"
    if not normalized_path.exists():
        print(f"Error: {normalized_path} not found.")
    else:
        normalized = json.loads(normalized_path.read_text())
        code_str = build_fido_search_code(normalized)
        print(code_str)
