#!/usr/bin/env python3
"""
Synthesize new instrument grounding test data using OpenAI API.
Uses the merged instrument catalog to generate realistic test cases with proper formatting.
"""

import argparse
import json
import random
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from openai import OpenAI
from pydantic import BaseModel, Field

# Setup path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from paper_data_linking.config.settings import settings

# Models matching the existing test case format
class DataCollectionPeriod(BaseModel):
    """Data collection period matching existing format"""
    time_range: str = Field(description="Time range for the observations")
    wavelengths: Union[str, None] = Field(description="Wavelength range or specific wavelengths observed, or null if not applicable")
    physical_observable: str = Field(description="What physical quantities or phenomena were observed")

class InstrumentEntry(BaseModel):
    """Instrument entry matching existing format"""
    name: str = Field(description="Full name of the instrument or observatory")
    general_comments: str = Field(description="General description of the instrument's role and capabilities")
    data_collection_periods: List[DataCollectionPeriod] = Field(description="Specific observation periods and their details")

class ExpectedResult(BaseModel):
    """Expected result for grounding test cases"""
    instrument_code: Union[str, None] = Field(description="Expected instrument code")
    mission_code: Union[str, None] = Field(description="Expected mission code for single spacecraft")
    mission_codes: Union[List[str], None] = Field(description="Expected mission codes for multi-spacecraft")
    should_match: bool = Field(description="Whether the grounding should succeed")
    ambiguity_type: Union[str, None] = Field(description="Type of ambiguity if applicable")

class TestCase(BaseModel):
    """Test case matching existing format"""
    name: str = Field(description="Unique identifier for the test case")
    category: str = Field(description="Category of the test case")
    instrument_entry: InstrumentEntry = Field(description="The instrument entry to be grounded")
    expected: ExpectedResult = Field(description="Expected grounding result")
    description: str = Field(description="Human-readable description of what this test case evaluates")

class SynthesizedTestCases(BaseModel):
    """Container for synthesized test cases"""
    test_cases: List[TestCase] = Field(description="List of generated test cases")

def load_merged_catalog(catalog_path: Path) -> List[Dict]:
    """Load the merged instrument catalog"""
    with open(catalog_path, 'r') as f:
        return json.load(f)

def load_existing_examples(jsonl_file: Path) -> List[Dict]:
    """Load existing test examples from JSONL file"""
    examples = []
    with open(jsonl_file, 'r') as f:
        for line in f:
            if line.strip():
                examples.append(json.loads(line.strip()))
    return examples

def select_catalog_entries(catalog: List[Dict], mission_code: Optional[str] = None, num_entries: int = 1) -> List[Dict]:
    """Select entries from catalog, optionally filtered by mission"""
    if mission_code:
        filtered = [entry for entry in catalog if entry['mission_code'] == mission_code]
        if not filtered:
            print(f"⚠️ No entries found for mission '{mission_code}', using random selection")
            filtered = catalog
    else:
        filtered = catalog
    
    return random.sample(filtered, min(num_entries, len(filtered)))

def select_random_examples(examples: List[Dict], num_examples: int = 3) -> List[Dict]:
    """Select random examples for few-shot prompting"""
    return random.sample(examples, min(num_examples, len(examples)))

def create_synthesis_prompt(example_cases: List[Dict], catalog_entry: Dict) -> str:
    """Create the system prompt for synthesizing new test cases based on catalog entry"""
    
    # Format examples for the prompt
    examples_text = ""
    for i, example in enumerate(example_cases, 1):
        examples_text += f"\nExample {i}:\n"
        examples_text += f"Name: {example['name']}\n"
        examples_text += f"Category: {example['category']}\n"
        examples_text += f"Instrument Name: {example['instrument_entry']['name']}\n"
        examples_text += f"General Comments: {example['instrument_entry']['general_comments']}\n"
        
        periods = example['instrument_entry'].get('data_collection_periods', [])
        if periods:
            examples_text += f"Data Collection Periods ({len(periods)}):\n"
            for j, period in enumerate(periods, 1):
                examples_text += f"  Period {j}: {period.get('time_range', 'N/A')} | {period.get('wavelengths', 'N/A')} | {period.get('physical_observable', 'N/A')}\n"
        
        examples_text += f"Expected Result: {example['expected']}\n"
        examples_text += f"Description: {example['description']}\n"

    return f"""You are an expert in space science instrumentation and spacecraft missions. Your task is to create realistic test cases for an instrument grounding system that matches instrument descriptions to a catalog of space-based instruments.

Based on the following examples, create NEW and DIVERSE test cases that focus on the specified instrument from the catalog entry below.

EXISTING EXAMPLES:{examples_text}

TARGET CATALOG ENTRY:
- Instrument Code: {catalog_entry['instrument_code']}
- Instrument Name: {catalog_entry['instrument_name']}
- Mission Code: {catalog_entry['mission_code']}
- Mission Name: {catalog_entry['mission_name']}
- Description: {catalog_entry['description']}

INSTRUCTIONS FOR CREATING NEW TEST CASES:

1. **Create diverse scenarios for this specific instrument:**
   - Vary the level of detail in instrument descriptions
   - Create different ambiguity scenarios (clear reference, generic reference, component reference)
   - Use realistic observation periods and scientific contexts
   - Vary the specificity of mission references

2. **Categories to consider:**
   - single_spacecraft: Clear, unambiguous reference to this specific instrument
   - moderately_ambiguous: Generic instrument name that could refer to multiple instruments
   - instrument_component: Reference to a sub-component or alternate name
   - acronym_challenge: Using only the instrument code/acronym

3. **Make it scientifically realistic:**
   - Use appropriate wavelengths/energy ranges for the instrument type
   - Include realistic physical observables for the instrument's capabilities
   - Use authentic-sounding time ranges and observation contexts
   - Reference appropriate scientific phenomena for this instrument type

4. **Expected results should match the catalog entry:**
   - instrument_code: "{catalog_entry['instrument_code']}"
   - mission_code: "{catalog_entry['mission_code']}"
   - should_match: true (for successful cases) or false (for ambiguous/impossible cases)

Create 3 diverse test cases that would be valuable for testing instrument grounding capabilities."""

def synthesize_test_cases(client: OpenAI, examples: List[Dict], catalog_entry: Dict, num_cases: int = 3) -> List[Dict]:
    """Use OpenAI to synthesize new test cases based on examples and catalog entry"""
    
    # Select random examples for few-shot prompting
    selected_examples = select_random_examples(examples, 3)
    
    # Create the synthesis prompt
    system_prompt = create_synthesis_prompt(selected_examples, catalog_entry)
    
    user_prompt = f"Generate {num_cases} new instrument grounding test cases for {catalog_entry['instrument_name']} ({catalog_entry['instrument_code']}) on {catalog_entry['mission_name']}. Make them diverse and realistic."
    
    print(f"🤖 Requesting new test cases from OpenAI...")
    print(f"🎯 Focusing on: {catalog_entry['instrument_name']} ({catalog_entry['instrument_code']}) on {catalog_entry['mission_name']}")
    print(f"📝 Using {len(selected_examples)} examples as few-shot context")
    
    try:
        response = client.beta.chat.completions.parse(
            model="gpt-4o-2024-08-06",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format=SynthesizedTestCases,
            temperature=0.7,
        )
        
        if response.choices[0].message.parsed:
            parsed_response = response.choices[0].message.parsed
            test_cases = parsed_response.test_cases
            print(f"✅ Generated {len(test_cases)} new test cases")
            return [case.model_dump() for case in test_cases]
        else:
            print("❌ Failed to parse structured response")
            return []
            
    except Exception as e:
        print(f"❌ Error generating test cases: {e}")
        return []

def save_test_cases_jsonl(cases: List[Dict], output_file: Path, append_mode: bool = False):
    """Save test cases to JSONL file in the same format as existing examples"""
    mode = 'a' if append_mode else 'w'
    action = "Appended" if append_mode else "Saved"
    
    with open(output_file, mode) as f:
        for case in cases:
            f.write(json.dumps(case) + '\n')
    print(f"💾 {action} {len(cases)} test cases to {output_file}")

def main():
    """Main synthesis workflow"""
    parser = argparse.ArgumentParser(description="Synthesize instrument grounding test data from merged catalog.")
    parser.add_argument(
        "--mission-code",
        type=str,
        default=None,
        help="Optional: specific mission code to focus on (e.g., 'STEREO_A', 'SOHO')"
    )
    parser.add_argument(
        "--num-batches",
        type=int,
        default=2,
        help="Number of batches to generate (default: 2)"
    )
    parser.add_argument(
        "--cases-per-batch",
        type=int,
        default=3,
        help="Number of test cases per batch (default: 3)"
    )
    parser.add_argument(
        "--catalog-entries",
        type=int,
        default=1,
        help="Number of different catalog entries to use (default: 1)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="synthesized_instrument_test_cases.jsonl",
        help="Output JSONL file path (default: synthesized_instrument_test_cases.jsonl)"
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing output file instead of overwriting"
    )
    
    args = parser.parse_args()
    
    print("🧪 INSTRUMENT GROUNDING TEST DATA SYNTHESIS")
    print("=" * 60)
    
    # Setup paths
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    catalog_path = Path("merged_instrument_catalog_improved.json")
    examples_file = Path("comprehensive_instrument_grounding_test_set.jsonl")
    output_file = Path(args.output)
    
    # Load data
    if not catalog_path.exists():
        print(f"❌ Catalog file not found: {catalog_path}")
        return
        
    if not examples_file.exists():
        print(f"❌ Examples file not found: {examples_file}")
        return
    
    catalog = load_merged_catalog(catalog_path)
    examples = load_existing_examples(examples_file)
    
    print(f"📚 Loaded {len(catalog)} catalog entries")
    print(f"📖 Loaded {len(examples)} existing test cases")
    
    # Show output file settings
    if output_file.exists() and not args.append:
        print(f"⚠️  Output file {output_file} exists and will be OVERWRITTEN")
    elif args.append:
        print(f"📝 Will APPEND to output file: {output_file}")
    else:
        print(f"📝 Will create new output file: {output_file}")
    
    # Select catalog entries to work with
    selected_entries = select_catalog_entries(catalog, args.mission_code, args.catalog_entries)
    print(f"🎯 Selected {len(selected_entries)} catalog entries:")
    for entry in selected_entries:
        print(f"  - {entry['instrument_name']} ({entry['instrument_code']}) on {entry['mission_name']}")
    
    # Generate test cases
    all_synthesized_cases = []
    
    for entry_idx, catalog_entry in enumerate(selected_entries, 1):
        print(f"\n🔄 Processing catalog entry {entry_idx}/{len(selected_entries)}: {catalog_entry['instrument_name']}")
        
        for batch in range(args.num_batches):
            print(f"\n  Batch {batch + 1}/{args.num_batches}...")
            batch_cases = synthesize_test_cases(client, examples, catalog_entry, args.cases_per_batch)
            all_synthesized_cases.extend(batch_cases)
    
    if all_synthesized_cases:
        # Save synthesized cases
        save_test_cases_jsonl(all_synthesized_cases, output_file, args.append)
        
        # Print summary
        print(f"\n📊 SYNTHESIS SUMMARY:")
        print(f"  Total synthesized cases: {len(all_synthesized_cases)}")
        print(f"  Catalog entries used: {len(selected_entries)}")
        
        # Show categories
        categories = {}
        for case in all_synthesized_cases:
            cat = case.get('category', 'unknown')
            categories[cat] = categories.get(cat, 0) + 1
        
        print(f"  Categories:")
        for cat, count in categories.items():
            print(f"    {cat}: {count}")
        
        # Show sample case
        if all_synthesized_cases:
            print(f"\n🔍 SAMPLE SYNTHESIZED CASE:")
            sample = all_synthesized_cases[0]
            print(f"  Name: {sample['name']}")
            print(f"  Category: {sample['category']}")
            print(f"  Instrument: {sample['instrument_entry']['name']}")
            print(f"  Expected: {sample['expected']}")
            print(f"  Description: {sample['description']}")
        
        print(f"\n✅ Synthesis complete! Use {output_file} for testing.")
        print(f"💡 You can now run evaluation directly on this file.")
    else:
        print("❌ No test cases were generated")

if __name__ == "__main__":
    main()