#!/usr/bin/env python3
"""
Local Catalog Management CLI

This script allows you to easily modify instrument descriptions in the local
catalog and regenerate embeddings without going through Django.

Usage:
    python manage_local_catalog.py [command] [options]

Commands:
    list                      List all instruments
    search PATTERN           Search instruments by name/code/description
    update CODE MISSION DESC Update instrument description
    regenerate               Regenerate embeddings (selective or all)
    stats                    Show catalog statistics
    
Examples:
    python manage_local_catalog.py list
    python manage_local_catalog.py search SECCHI
    python manage_local_catalog.py update SECCHI STEREO_A "New description with COR1 coronagraph component"
    python manage_local_catalog.py regenerate --instrument SECCHI STEREO_A
    python manage_local_catalog.py regenerate --instrument SECCHI STEREO_A --instrument COSTEP SOHO
    python manage_local_catalog.py regenerate --all
"""

import os
import sys
import argparse
import json
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional
import re

# Setup path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from paper_data_linking.config.paths import DATA_ASSETS_DIR
from paper_data_linking.config.settings import get_llm_configuration

INSTRUMENT_EMBEDDINGS_MODEL = get_llm_configuration("standard").embeddings.model
from openai import OpenAI

def load_catalog() -> List[Dict]:
    """Load the local instrument catalog."""
    # Try merged catalog first, fall back to original
    merged_path = DATA_ASSETS_DIR / "vso" / "merged_instrument_catalog.json"
    original_path = DATA_ASSETS_DIR / "vso" / "enhanced_instrument_catalog.json"
    
    if merged_path.exists():
        catalog_path = merged_path
        catalog_type = "merged"
    elif original_path.exists():
        catalog_path = original_path
        catalog_type = "original"
    else:
        raise FileNotFoundError(f"No catalog found at {merged_path} or {original_path}")
    
    with open(catalog_path, 'r', encoding='utf-8') as f:
        catalog = json.load(f)
    
    print(f"📚 Loaded {catalog_type} catalog: {len(catalog)} instruments")
    return catalog

def save_catalog(catalog: List[Dict]) -> None:
    """Save the catalog back to file."""
    # Save to the same type we loaded (merged or original)
    merged_path = DATA_ASSETS_DIR / "vso" / "merged_instrument_catalog.json"
    original_path = DATA_ASSETS_DIR / "vso" / "enhanced_instrument_catalog.json"
    
    if merged_path.exists():
        catalog_path = merged_path
    else:
        catalog_path = original_path
        
    with open(catalog_path, 'w', encoding='utf-8') as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    print(f"✅ Catalog saved to {catalog_path}")

def find_instrument(catalog: List[Dict], instrument_code: str, mission_code: str) -> Optional[int]:
    """Find instrument index by codes."""
    for i, inst in enumerate(catalog):
        if (inst.get("instrument_code") == instrument_code and 
            inst.get("mission_code") == mission_code):
            return i
    return None

def list_instruments(catalog: List[Dict], limit: Optional[int] = None) -> None:
    """List all instruments with basic info."""
    print(f"📋 Found {len(catalog)} instruments:")
    print("-" * 80)
    
    items = catalog[:limit] if limit else catalog
    for i, inst in enumerate(items):
        code = inst.get("instrument_code", "N/A")
        mission = inst.get("mission_code", "N/A")
        name = inst.get("instrument_name", "N/A")
        desc = inst.get("description", "")[:60] + "..." if len(inst.get("description", "")) > 60 else inst.get("description", "")
        
        print(f"{i+1:3d}. {code:8s}/{mission:10s} - {name}")
        if desc:
            print(f"     {desc}")
        print()

def search_instruments(catalog: List[Dict], pattern: str) -> List[Dict]:
    """Search instruments by pattern in name, code, or description."""
    pattern_lower = pattern.lower()
    matches = []
    
    for inst in catalog:
        searchable = [
            inst.get("instrument_code", ""),
            inst.get("mission_code", ""),
            inst.get("instrument_name", ""),
            inst.get("description", "")
        ]
        
        if any(pattern_lower in field.lower() for field in searchable):
            matches.append(inst)
    
    return matches

def update_description(catalog: List[Dict], instrument_code: str, mission_code: str, new_description: str) -> bool:
    """Update instrument description."""
    index = find_instrument(catalog, instrument_code, mission_code)
    if index is None:
        print(f"❌ Instrument {instrument_code}/{mission_code} not found")
        return False
    
    old_desc = catalog[index].get("description", "")
    catalog[index]["description"] = new_description
    
    print(f"✅ Updated {instrument_code}/{mission_code}")
    print(f"Old: {old_desc[:100]}...")
    print(f"New: {new_description[:100]}...")
    
    return True

def load_existing_embeddings() -> Optional[np.ndarray]:
    """Load existing embeddings if they exist."""
    embeddings_path = DATA_ASSETS_DIR / "vso" / "instrument_embeddings.npy"
    if embeddings_path.exists():
        return np.load(embeddings_path)
    return None

def generate_embeddings_selective(catalog: List[Dict], api_key: str, 
                                instrument_indices: Optional[List[int]] = None) -> np.ndarray:
    """Generate embeddings for all or selected instruments."""
    client = OpenAI(api_key=api_key)
    
    # Load existing embeddings if doing selective update
    existing_embeddings = None
    if instrument_indices is not None:
        existing_embeddings = load_existing_embeddings()
        if existing_embeddings is None:
            print("⚠️  No existing embeddings found, generating all embeddings...")
            instrument_indices = None
    
    if instrument_indices is None:
        # Generate all embeddings
        descriptions = [inst.get("description", "") for inst in catalog]
        print(f"🔄 Generating embeddings for ALL {len(descriptions)} instruments...")
        
        embeddings = []
        batch_size = 50
        for i in range(0, len(descriptions), batch_size):
            batch = descriptions[i:i+batch_size]
            print(f"  Processing batch {i//batch_size + 1}/{(len(descriptions) + batch_size - 1)//batch_size}")
            
            try:
                response = client.embeddings.create(
                    input=batch,
                    model=INSTRUMENT_EMBEDDINGS_MODEL
                )
                
                batch_embeddings = [data.embedding for data in response.data]
                embeddings.extend(batch_embeddings)
                
            except Exception as e:
                print(f"❌ Failed to generate embeddings for batch {i//batch_size + 1}: {e}")
                return None
        
        return np.array(embeddings)
    
    else:
        # Generate embeddings for selected instruments only
        descriptions_to_generate = []
        instruments_to_update = []
        
        for idx in instrument_indices:
            if 0 <= idx < len(catalog):
                descriptions_to_generate.append(catalog[idx].get("description", ""))
                instruments_to_update.append(idx)
        
        print(f"🔄 Generating embeddings for {len(descriptions_to_generate)} selected instruments...")
        
        try:
            response = client.embeddings.create(
                input=descriptions_to_generate,
                model=INSTRUMENT_EMBEDDINGS_MODEL
            )
            
            new_embeddings = [data.embedding for data in response.data]
            
            # Update existing embeddings array
            updated_embeddings = existing_embeddings.copy()
            for i, idx in enumerate(instruments_to_update):
                updated_embeddings[idx] = new_embeddings[i]
                inst = catalog[idx]
                print(f"  ✅ Updated {inst.get('instrument_code', 'N/A')}/{inst.get('mission_code', 'N/A')}")
            
            return updated_embeddings
            
        except Exception as e:
            print(f"❌ Failed to generate embeddings: {e}")
            return None

def save_embeddings(embeddings: np.ndarray) -> None:
    """Save embeddings to file."""
    embeddings_path = DATA_ASSETS_DIR / "vso" / "instrument_embeddings.npy"
    np.save(embeddings_path, embeddings)
    print(f"✅ Embeddings saved to {embeddings_path}")

def show_stats(catalog: List[Dict]) -> None:
    """Show catalog statistics."""
    total = len(catalog)
    missions = set(inst.get("mission_code", "N/A") for inst in catalog)
    has_description = sum(1 for inst in catalog if inst.get("description"))
    
    print(f"📊 Catalog Statistics:")
    print(f"  Total instruments: {total}")
    print(f"  Unique missions: {len(missions)}")
    print(f"  With descriptions: {has_description} ({has_description/total*100:.1f}%)")
    print(f"  Without descriptions: {total - has_description}")
    
    # Top missions by instrument count
    from collections import Counter
    mission_counts = Counter(inst.get("mission_code", "N/A") for inst in catalog)
    print(f"\n🚀 Top 10 missions by instrument count:")
    for mission, count in mission_counts.most_common(10):
        print(f"  {mission:15s}: {count:3d}")

def main():
    parser = argparse.ArgumentParser(description="Manage local instrument catalog")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List instruments')
    list_parser.add_argument('--limit', type=int, help='Limit number of results')
    
    # Search command
    search_parser = subparsers.add_parser('search', help='Search instruments')
    search_parser.add_argument('pattern', help='Search pattern')
    
    # Update command
    update_parser = subparsers.add_parser('update', help='Update instrument description')
    update_parser.add_argument('instrument_code', help='Instrument code')
    update_parser.add_argument('mission_code', help='Mission code')
    update_parser.add_argument('description', help='New description')
    
    # Regenerate command
    regen_parser = subparsers.add_parser('regenerate', help='Regenerate embeddings')
    regen_parser.add_argument('--api-key', help='OpenAI API key (or set OPENAI_API_KEY env var)')
    regen_parser.add_argument('--all', action='store_true', help='Regenerate ALL embeddings (default: only recently modified)')
    regen_parser.add_argument('--instrument', nargs=2, metavar=('CODE', 'MISSION'), 
                            action='append', help='Regenerate specific instrument (can be used multiple times)')
    
    # Stats command
    subparsers.add_parser('stats', help='Show catalog statistics')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    try:
        catalog = load_catalog()
        
        if args.command == 'list':
            list_instruments(catalog, args.limit)
            
        elif args.command == 'search':
            matches = search_instruments(catalog, args.pattern)
            print(f"🔍 Found {len(matches)} matches for '{args.pattern}':")
            print("-" * 80)
            for match in matches:
                code = match.get("instrument_code", "N/A")
                mission = match.get("mission_code", "N/A")
                name = match.get("instrument_name", "N/A")
                desc = match.get("description", "")
                print(f"{code}/{mission} - {name}")
                if desc:
                    print(f"  {desc[:100]}...")
                print()
                
        elif args.command == 'update':
            if update_description(catalog, args.instrument_code, args.mission_code, args.description):
                save_catalog(catalog)
                print("⚠️  Don't forget to regenerate embeddings with 'regenerate' command")
                
        elif args.command == 'regenerate':
            api_key = args.api_key or os.environ.get('OPENAI_API_KEY')
            if not api_key:
                print("❌ OpenAI API key required. Use --api-key or set OPENAI_API_KEY environment variable")
                return 1
            
            instrument_indices = None
            
            # Handle specific instruments
            if args.instrument:
                instrument_indices = []
                for inst_code, mission_code in args.instrument:
                    idx = find_instrument(catalog, inst_code, mission_code)
                    if idx is not None:
                        instrument_indices.append(idx)
                        print(f"📍 Will regenerate: {inst_code}/{mission_code}")
                    else:
                        print(f"⚠️  Instrument not found: {inst_code}/{mission_code}")
                
                if not instrument_indices:
                    print("❌ No valid instruments specified")
                    return 1
            
            # Handle --all flag or default behavior
            if args.all:
                print("🔄 Regenerating ALL embeddings...")
                instrument_indices = None
            elif instrument_indices is None:
                print("ℹ️  Use --all to regenerate all embeddings, or --instrument CODE MISSION for specific ones")
                print("ℹ️  For now, regenerating all embeddings...")
                instrument_indices = None
                
            embeddings = generate_embeddings_selective(catalog, api_key, instrument_indices)
            if embeddings is not None:
                save_embeddings(embeddings)
            else:
                print("❌ Failed to generate embeddings")
                return 1
                
        elif args.command == 'stats':
            show_stats(catalog)
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())