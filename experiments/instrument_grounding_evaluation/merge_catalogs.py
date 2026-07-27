#!/usr/bin/env python3
"""
Merge VSO and CDAWeb instrument catalogs into a unified catalog with data_system field.

This creates a much larger and more challenging dataset for testing instrument grounding.
"""

import json
import sys
from pathlib import Path
from typing import List, Dict

# Setup path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from paper_data_linking.config.paths import DATA_ASSETS_DIR

def load_catalog(file_path: Path) -> List[Dict]:
    """Load a catalog from JSON file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def add_data_system_field(catalog: List[Dict], data_system: str) -> List[Dict]:
    """Add data_system field to all instruments in catalog."""
    for instrument in catalog:
        instrument['data_system'] = data_system
    return catalog

def merge_catalogs() -> List[Dict]:
    """Merge VSO and CDAWeb catalogs with data_system field."""
    
    # Load VSO catalog
    vso_path = DATA_ASSETS_DIR / "vso" / "enhanced_instrument_catalog.json"
    print(f"Loading VSO catalog from: {vso_path}")
    vso_catalog = load_catalog(vso_path)
    
    # Load CDAWeb catalog  
    cdaweb_path = DATA_ASSETS_DIR / "vso" / "examples" / "cdaweb_instrument_cataologue.json"
    print(f"Loading CDAWeb catalog from: {cdaweb_path}")
    cdaweb_catalog = load_catalog(cdaweb_path)
    
    print(f"VSO instruments: {len(vso_catalog)}")
    print(f"CDAWeb instruments: {len(cdaweb_catalog)}")
    
    # Add data_system field
    vso_catalog = add_data_system_field(vso_catalog, "VSO")
    cdaweb_catalog = add_data_system_field(cdaweb_catalog, "CDAWeb")
    
    # Merge catalogs
    merged_catalog = vso_catalog + cdaweb_catalog
    print(f"Merged catalog size: {len(merged_catalog)}")
    
    return merged_catalog

def save_merged_catalog(catalog: List[Dict], output_path: Path):
    """Save merged catalog to file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    print(f"✅ Merged catalog saved to: {output_path}")

def analyze_merged_catalog(catalog: List[Dict]):
    """Print analysis of the merged catalog."""
    from collections import Counter
    
    print(f"\n📊 MERGED CATALOG ANALYSIS")
    print(f"=" * 50)
    
    # Count by data system
    data_systems = Counter(inst.get('data_system', 'Unknown') for inst in catalog)
    print(f"By data system:")
    for system, count in data_systems.items():
        print(f"  {system}: {count}")
    
    # Count by provider (top 10)
    providers = Counter(inst.get('provider', 'Unknown') for inst in catalog)
    print(f"\nTop 10 providers:")
    for provider, count in providers.most_common(10):
        print(f"  {provider}: {count}")
    
    # Sample instruments from each system
    print(f"\nSample instruments:")
    for system in data_systems.keys():
        sample = next((inst for inst in catalog if inst.get('data_system') == system), None)
        if sample:
            print(f"  {system}: {sample['instrument_code']}/{sample['mission_code']} - {sample['instrument_name']}")

def main():
    print("🔗 Merging VSO and CDAWeb Instrument Catalogs")
    print("=" * 60)
    
    # Merge catalogs
    merged_catalog = merge_catalogs()
    
    # Save to data assets directory
    output_path = DATA_ASSETS_DIR / "vso" / "merged_instrument_catalog.json"
    save_merged_catalog(merged_catalog, output_path)
    
    # Also save to experiments directory for easy access
    experiments_output = Path(__file__).parent / "merged_instrument_catalog.json"
    save_merged_catalog(merged_catalog, experiments_output)
    
    # Analyze the results
    analyze_merged_catalog(merged_catalog)
    
    print(f"\n🎯 Next steps:")
    print(f"1. Generate embeddings: python manage_local_catalog.py regenerate --all")
    print(f"2. Test grounding: python evaluate_grounding_accuracy.py --test-cases debug_failures.jsonl --verbose")

if __name__ == "__main__":
    main()