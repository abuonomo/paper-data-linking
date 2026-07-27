#!/usr/bin/env python3
"""
Improved catalog merging with VSO precedence and mission name normalization.

This script:
1. Loads VSO and CDAWeb catalogs
2. Detects and resolves instrument collisions (VSO takes precedence)
3. Normalizes mission names for consistent filtering
4. Creates a unified catalog with proper deduplication
"""

import json
import sys
from pathlib import Path
from typing import List, Dict, Set, Tuple
from collections import defaultdict

# Setup path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from paper_data_linking.config.paths import DATA_ASSETS_DIR

def load_catalog(file_path: Path) -> List[Dict]:
    """Load a catalog from JSON file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def create_mission_name_mapping() -> Dict[str, str]:
    """Create mapping from various mission names to canonical forms."""
    return {
        # SOHO variants -> canonical name
        "SOHO": "Solar and Heliospheric Observatory",
        "Solar and Heliospheric Observatory": "Solar and Heliospheric Observatory",
        
        # STEREO variants -> canonical name  
        "STEREO Mission": "STEREO Mission",
        "Solar TErrestrial RElations Observatory - Ahead": "STEREO Mission",
        "Solar TErrestrial RElations Observatory - Behind": "STEREO Mission",
        
        # SDO variants -> canonical name
        "SDO": "Solar Dynamics Observatory", 
        "Solar Dynamics Observatory": "Solar Dynamics Observatory",
        
        # Parker Solar Probe variants -> canonical name
        "PSP": "Parker Solar Probe",
        "Parker Solar Probe": "Parker Solar Probe",
        
        # Add more mappings as needed
    }

def normalize_mission_name(mission_name: str, mapping: Dict[str, str]) -> str:
    """Normalize a mission name using the mapping."""
    return mapping.get(mission_name, mission_name)

def get_instrument_key(instrument: Dict) -> str:
    """Create a unique key for instrument collision detection."""
    # Use mission + instrument code for collision detection
    mission_code = instrument.get('mission_code', '')
    instrument_code = instrument.get('instrument_code', '')
    
    # Normalize codes for comparison
    if mission_code.startswith('spase://'):
        # Extract the actual mission from CDAWeb format
        mission_code = mission_code.split('/')[-1]
    
    if instrument_code.startswith('spase://'):
        # Extract the actual instrument from CDAWeb format  
        instrument_code = instrument_code.split('/')[-1]
    
    return f"{mission_code}::{instrument_code}".upper()

def detect_collisions(vso_catalog: List[Dict], cdaweb_catalog: List[Dict]) -> Tuple[Set[str], List[Dict], List[Dict]]:
    """
    Detect instrument collisions between catalogs.
    Returns: (collision_keys, vso_no_collisions, cdaweb_no_collisions)
    """
    # Create collision detection sets
    vso_keys = {get_instrument_key(inst): inst for inst in vso_catalog}
    cdaweb_keys = {get_instrument_key(inst): inst for inst in cdaweb_catalog}
    
    # Find collisions
    collision_keys = set(vso_keys.keys()).intersection(set(cdaweb_keys.keys()))
    
    print(f"\n🔄 COLLISION DETECTION")
    print(f"=" * 50)
    print(f"VSO instruments: {len(vso_catalog)}")
    print(f"CDAWeb instruments: {len(cdaweb_catalog)}")
    print(f"Collisions detected: {len(collision_keys)}")
    
    if collision_keys:
        print(f"\nColliding instruments (VSO will take precedence):")
        for key in sorted(collision_keys):
            vso_inst = vso_keys[key]
            cdaweb_inst = cdaweb_keys[key]
            print(f"  • {key}")
            print(f"    VSO: {vso_inst.get('instrument_code')} - {vso_inst.get('instrument_name')}")
            print(f"    CDAWeb: {cdaweb_inst.get('instrument_code')} - {cdaweb_inst.get('instrument_name')}")
    
    # Filter out collisions from CDAWeb (VSO takes precedence)
    cdaweb_no_collisions = [inst for inst in cdaweb_catalog if get_instrument_key(inst) not in collision_keys]
    
    print(f"\nAfter collision resolution:")
    print(f"  VSO instruments (kept): {len(vso_catalog)}")
    print(f"  CDAWeb instruments (non-colliding): {len(cdaweb_no_collisions)}")
    print(f"  Total: {len(vso_catalog) + len(cdaweb_no_collisions)}")
    
    return collision_keys, vso_catalog, cdaweb_no_collisions

def normalize_catalog_mission_names(catalog: List[Dict], mapping: Dict[str, str]) -> List[Dict]:
    """Normalize mission names in a catalog using the mapping."""
    for instrument in catalog:
        original_name = instrument.get('mission_name', '')
        normalized_name = normalize_mission_name(original_name, mapping)
        if normalized_name != original_name:
            print(f"  Normalized: '{original_name}' -> '{normalized_name}'")
        instrument['mission_name'] = normalized_name
    return catalog

def add_data_system_field(catalog: List[Dict], data_system: str) -> List[Dict]:
    """Add data_system field to all instruments in catalog."""
    for instrument in catalog:
        instrument['data_system'] = data_system
    return catalog

def merge_catalogs_improved() -> List[Dict]:
    """
    Merge VSO and CDAWeb catalogs with collision detection and mission name normalization.
    """
    
    # Load catalogs
    vso_path = DATA_ASSETS_DIR / "vso" / "enhanced_instrument_catalog.json"
    cdaweb_path = DATA_ASSETS_DIR / "vso" / "examples" / "cdaweb_instrument_cataologue.json"
    
    print(f"Loading VSO catalog from: {vso_path}")
    vso_catalog = load_catalog(vso_path)
    
    print(f"Loading CDAWeb catalog from: {cdaweb_path}")
    cdaweb_catalog = load_catalog(cdaweb_path)
    
    # Create mission name mapping
    mission_mapping = create_mission_name_mapping()
    
    # Normalize mission names BEFORE collision detection
    print(f"\n📝 MISSION NAME NORMALIZATION")
    print(f"=" * 50)
    print(f"VSO normalizations:")
    vso_catalog = normalize_catalog_mission_names(vso_catalog, mission_mapping)
    
    print(f"\nCDAWeb normalizations:")
    cdaweb_catalog = normalize_catalog_mission_names(cdaweb_catalog, mission_mapping)
    
    # Detect and resolve collisions (VSO precedence)
    collision_keys, vso_final, cdaweb_final = detect_collisions(vso_catalog, cdaweb_catalog)
    
    # Add data system fields
    vso_final = add_data_system_field(vso_final, "VSO")
    cdaweb_final = add_data_system_field(cdaweb_final, "CDAWeb")
    
    # Merge the non-colliding catalogs
    merged_catalog = vso_final + cdaweb_final
    
    print(f"\n✅ MERGE COMPLETE")
    print(f"=" * 50)
    print(f"Final merged catalog size: {len(merged_catalog)}")
    print(f"  VSO instruments: {len(vso_final)}")
    print(f"  CDAWeb instruments: {len(cdaweb_final)}")
    print(f"  Collisions resolved: {len(collision_keys)} (VSO precedence)")
    
    return merged_catalog

def analyze_merged_catalog(catalog: List[Dict]):
    """Print detailed analysis of the merged catalog."""
    from collections import Counter
    
    print(f"\n📊 MERGED CATALOG ANALYSIS")
    print(f"=" * 50)
    
    # Count by data system
    data_systems = Counter(inst.get('data_system', 'Unknown') for inst in catalog)
    print(f"By data system:")
    for system, count in data_systems.items():
        print(f"  {system}: {count}")
    
    # Count by normalized mission (top 15)
    missions = Counter(inst.get('mission_name', 'Unknown') for inst in catalog)
    print(f"\nTop 15 missions by instrument count:")
    for mission, count in missions.most_common(15):
        print(f"  {count:3d} instruments - {mission}")
    
    # Show mission name mappings that were applied
    print(f"\nSample mission names after normalization:")
    unique_missions = set(inst.get('mission_name', 'Unknown') for inst in catalog)
    for mission in sorted(list(unique_missions))[:10]:
        print(f"  • {mission}")
    
    # Test key missions for filtering
    print(f"\nKey missions for testing:")
    key_missions = ["Solar and Heliospheric Observatory", "STEREO Mission", "Solar Dynamics Observatory", "Parker Solar Probe"]
    for mission in key_missions:
        count = sum(1 for inst in catalog if inst.get('mission_name') == mission)
        print(f"  {count:3d} instruments - {mission}")

def save_merged_catalog(catalog: List[Dict], output_path: Path):
    """Save merged catalog to file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    print(f"✅ Merged catalog saved to: {output_path}")

def main():
    print("🔗 IMPROVED CATALOG MERGING WITH VSO PRECEDENCE")
    print("=" * 70)
    
    # Merge catalogs with improvements
    merged_catalog = merge_catalogs_improved()
    
    # Save to data assets directory (this is what the grounder uses)
    output_path = DATA_ASSETS_DIR / "vso" / "merged_instrument_catalog.json"
    save_merged_catalog(merged_catalog, output_path)
    
    # Also save to experiments directory for reference
    experiments_output = Path(__file__).parent / "merged_instrument_catalog_improved.json"
    save_merged_catalog(merged_catalog, experiments_output)
    
    # Analyze the results
    analyze_merged_catalog(merged_catalog)
    
    print(f"\n🎯 NEXT STEPS:")
    print(f"1. Regenerate embeddings: cd experiments/instrument_grounding_evaluation && python manage_local_catalog.py regenerate --all")
    print(f"2. Test EIT case: python evaluate_grounding_accuracy.py --test-cases debug_failed_cases.jsonl --limit 1 --verbose")
    print(f"3. Run full test: python evaluate_grounding_accuracy.py --test-cases debug_failed_cases.jsonl --verbose")

if __name__ == "__main__":
    main()