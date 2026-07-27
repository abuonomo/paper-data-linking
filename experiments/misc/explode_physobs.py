#!/usr/bin/env python3
"""
VSO Metadata Physobs Explosion Script

This script reads the VSO metadata JSONL file and explodes the physobs field
to create separate rows for each space-separated physobs value.

Input: paper_data_linking/data_assets/vso/vso_metadata.jsonl (279 records)
Output: paper_data_linking/data_assets/vso/vso_metadata_exploded.jsonl (~440+ records)

Example transformation:
Input:  {"physobs": "intensity irradiance", "instrument": "EVE", ...}
Output: {"physobs": "intensity", "instrument": "EVE", ...}
        {"physobs": "irradiance", "instrument": "EVE", ...}
"""

import json
import sys
from pathlib import Path


def normalize_physobs(physobs_value: str) -> str:
    """Normalize physobs value by fixing case inconsistencies."""
    # Convert "Intensity" to "intensity" for consistency
    if physobs_value == "Intensity":
        return "intensity"
    return physobs_value


def explode_physobs_record(record: dict) -> list[dict]:
    """
    Explode a single record based on space-separated physobs values.
    
    Args:
        record: Original JSONL record
        
    Returns:
        List of records, one for each physobs component
    """
    physobs_components = record["physobs"].split()
    exploded_records = []
    
    for component in physobs_components:
        # Create a copy of the original record
        new_record = record.copy()
        # Update the physobs field with the single component
        new_record["physobs"] = normalize_physobs(component.strip())
        exploded_records.append(new_record)
    
    return exploded_records


def main():
    # Define file paths
    input_file = Path("paper_data_linking/data_assets/vso/vso_metadata.jsonl")
    output_file = Path("paper_data_linking/data_assets/vso/vso_metadata_exploded.jsonl")
    
    # Check if input file exists
    if not input_file.exists():
        print(f"Error: Input file {input_file} does not exist")
        sys.exit(1)
    
    print(f"Reading from: {input_file}")
    print(f"Writing to: {output_file}")
    
    # Process the JSONL file
    total_input_records = 0
    total_output_records = 0
    space_separated_count = 0
    
    with open(input_file, 'r') as infile, open(output_file, 'w') as outfile:
        for line_num, line in enumerate(infile, 1):
            try:
                # Parse the JSON record
                record = json.loads(line.strip())
                total_input_records += 1
                
                # Check if physobs contains spaces (multiple values)
                if ' ' in record["physobs"]:
                    space_separated_count += 1
                    print(f"Exploding record {line_num}: '{record['physobs']}'")
                
                # Explode the record
                exploded_records = explode_physobs_record(record)
                
                # Write each exploded record to output
                for exploded_record in exploded_records:
                    json.dump(exploded_record, outfile)
                    outfile.write('\n')
                    total_output_records += 1
                    
            except json.JSONDecodeError as e:
                print(f"Error parsing line {line_num}: {e}")
                continue
            except KeyError as e:
                print(f"Error: Missing 'physobs' field in line {line_num}: {e}")
                continue
    
    # Print summary statistics
    print(f"\nProcessing complete!")
    print(f"Input records: {total_input_records}")
    print(f"Output records: {total_output_records}")
    print(f"Records with space-separated physobs: {space_separated_count}")
    print(f"Expansion ratio: {total_output_records / total_input_records:.2f}x")
    
    # Verify the output by analyzing unique physobs values
    print(f"\nAnalyzing exploded data...")
    
    unique_physobs_after = set()
    with open(output_file, 'r') as f:
        for line in f:
            record = json.loads(line.strip())
            unique_physobs_after.add(record["physobs"])
    
    print(f"Unique physobs values after explosion: {len(unique_physobs_after)}")
    print("All unique physobs values:")
    for i, physobs in enumerate(sorted(unique_physobs_after), 1):
        print(f"  {i:2d}. {physobs}")


if __name__ == "__main__":
    main()