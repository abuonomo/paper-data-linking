#!/usr/bin/env python3
"""
Instrument Grounding Accuracy Evaluation

This experiment evaluates how accurately the InstrumentGrounder can match instrument
descriptions to the VSO catalog across various realistic scenarios.

The evaluation reads test cases from a JSONL file and measures:
- Overall accuracy rates
- Performance by category (exact matches, contextual, ambiguous, etc.)
- Timing and throughput metrics
- Error analysis and patterns

Usage:
    python evaluate_grounding_accuracy.py [options]
    
Options:
    --test-cases FILE    Path to JSONL test cases file (default: test_cases.jsonl)
    --limit N           Limit to first N test cases
    --category CAT      Only run tests from specific category
    --save-results FILE Save detailed results to JSON file
    --api-key KEY       OpenAI API key (optional, uses environment)
    --verbose           Detailed output for each test case
    --dry-run           Parse test cases but don't run evaluation
    --use-local         Use local file-based finder instead of Django (default: True)
"""

import os
import sys
import argparse
import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict, Counter

# Setup path for local imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Import the local finder and grounder directly
from paper_data_linking.linkers.general.local_finder import LocalInstrumentFinder
from paper_data_linking.linkers.general.instrument_grounder import InstrumentGrounder

def setup_debug_logging(verbose: bool = False):
    """Configure comprehensive debug logging for the grounding process."""
    log_level = logging.DEBUG if verbose else logging.INFO
    
    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set specific loggers to DEBUG for detailed output
    loggers_to_debug = [
        'paper_data_linking.linkers.general.instrument_grounder',
        '__main__'
    ]
    
    for logger_name in loggers_to_debug:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    
    # Reduce noise from other libraries
    logging.getLogger('openai').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)

def get_local_instrument_grounder() -> InstrumentGrounder:
    """Factory to get InstrumentGrounder with local file-based finder."""
    finder = LocalInstrumentFinder()
    return InstrumentGrounder(finder=finder)


def load_test_cases(file_path: str) -> List[Dict]:
    """Load test cases from JSONL file"""
    test_cases = []
    try:
        with open(file_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    test_case = json.loads(line)
                    test_cases.append(test_case)
                except json.JSONDecodeError as e:
                    print(f"⚠️  Invalid JSON on line {line_num}: {e}")
                    continue
    except FileNotFoundError:
        print(f"❌ Test cases file not found: {file_path}")
        sys.exit(1)
    
    return test_cases


def validate_test_case(test_case: Dict) -> List[str]:
    """Validate test case structure and return list of errors"""
    errors = []
    
    required_fields = ['name', 'category', 'instrument_entry', 'expected']
    for field in required_fields:
        if field not in test_case:
            errors.append(f"Missing required field: {field}")
    
    if 'instrument_entry' in test_case:
        if 'name' not in test_case['instrument_entry']:
            errors.append("instrument_entry missing 'name' field")
    
    if 'expected' in test_case:
        expected = test_case['expected']
        if 'should_match' not in expected:
            errors.append("expected missing 'should_match' field")
        
        should_match = expected.get('should_match', False)
        if should_match:
            if 'instrument_code' not in expected or 'mission_code' not in expected:
                errors.append("should_match=true but missing instrument_code/mission_code")
    
    return errors


def filter_test_cases(test_cases: List[Dict], 
                     category: Optional[str] = None, 
                     limit: Optional[int] = None) -> List[Dict]:
    """Filter test cases by category and/or limit"""
    filtered = test_cases
    
    if category:
        filtered = [tc for tc in filtered if tc.get('category') == category]
        if not filtered:
            available_categories = set(tc.get('category', 'unknown') for tc in test_cases)
            print(f"❌ No test cases found for category '{category}'")
            print(f"Available categories: {', '.join(sorted(available_categories))}")
            sys.exit(1)
    
    if limit:
        filtered = filtered[:limit]
    
    return filtered


def evaluate_result(result, expected: Dict, test_name: str) -> Tuple[bool, str, Dict]:
    """
    Evaluate if grounding result matches expectations.
    Handles both single results (Dict) and multiple results (List[Dict]).
    Returns (is_correct, explanation, details)
    """
    # Handle multi-target results (List[Dict])
    if isinstance(result, list):
        if len(result) == 0:
            # Empty list means no match
            actual_match = False
            details = {
                "actual_match": False,
                "expected_match": expected["should_match"],
                "actual_instrument": None,
                "actual_mission": None,
                "expected_instrument": expected.get("instrument_code"),
                "expected_mission": expected.get("mission_code"),
                "reasoning": "Multiple target search returned no results",
                "multiple_results": True,
                "result_count": 0
            }
        else:
            # Multiple matches found
            actual_match = True
            expected_instrument = expected.get("instrument_code")
            expected_mission = expected.get("mission_code")
            
            # Check if any of the results match the expected
            matching_results = []
            for res in result:
                if (expected_instrument and res.get("matched_instrument_code") == expected_instrument and 
                    expected_mission and res.get("matched_mission_code") == expected_mission):
                    matching_results.append(res)
            
            details = {
                "actual_match": True,
                "expected_match": expected["should_match"],
                "actual_instrument": [r.get("matched_instrument_code") for r in result],
                "actual_mission": [r.get("matched_mission_code") for r in result],
                "expected_instrument": expected_instrument,
                "expected_mission": expected_mission,
                "reasoning": f"Multiple matches found: {len(result)} results",
                "multiple_results": True,
                "result_count": len(result),
                "matching_results": len(matching_results)
            }
            
            # Evaluation logic for multiple results
            expected_match = expected["should_match"]
            if not expected_match:
                return False, f"Expected no match but got {len(result)} matches", details
            elif len(matching_results) > 0:
                return True, f"Correct match found among {len(result)} results", details
            else:
                return False, f"Expected match not found among {len(result)} results", details
    
    # Handle single result (Dict)
    else:
        actual_match = result["matched_instrument_code"] is not None
        expected_match = expected["should_match"]
        
        details = {
            "actual_match": actual_match,
            "expected_match": expected_match,
            "actual_instrument": result.get("matched_instrument_code"),
            "actual_mission": result.get("matched_mission_code"),
            "expected_instrument": expected.get("instrument_code"),
            "expected_mission": expected.get("mission_code"),
            "reasoning": result.get("reasoning", ""),
            "multiple_results": False,
            "result_count": 1 if actual_match else 0
        }
        
        # Check match expectation
        if actual_match != expected_match:
            if expected_match:
                return False, f"Expected match but got none", details
            else:
                return False, f"Expected no match but got {result['matched_instrument_code']}/{result['matched_mission_code']}", details
        
        # If both expected and got a match, check correctness
        if expected_match and actual_match:
            expected_instrument = expected.get("instrument_code")
            expected_mission = expected.get("mission_code")
            
            if expected_instrument and result["matched_instrument_code"] != expected_instrument:
                return False, f"Wrong instrument: expected {expected_instrument}, got {result['matched_instrument_code']}", details
            
            if expected_mission and result["matched_mission_code"] != expected_mission:
                return False, f"Wrong mission: expected {expected_mission}, got {result['matched_mission_code']}", details
            
            return True, f"Correct match: {result['matched_instrument_code']}/{result['matched_mission_code']}", details
        
        # Both expected and got no match
        return True, "Correctly identified as no match", details


def run_evaluation(test_cases: List[Dict], grounder, verbose: bool = False) -> Dict:
    """Run the evaluation on all test cases"""
    results = {
        "summary": {
            "total": 0,
            "correct": 0,
            "incorrect": 0,
            "errors": 0,
            "total_time": 0.0,
            "average_time": 0.0
        },
        "by_category": defaultdict(lambda: {"total": 0, "correct": 0, "incorrect": 0, "errors": 0}),
        "test_results": [],
        "error_patterns": Counter(),
        "performance_stats": {}
    }
    
    print(f"🔬 Running evaluation on {len(test_cases)} test cases...")
    print("=" * 60)
    
    for i, test_case in enumerate(test_cases, 1):
        test_name = test_case["name"]
        category = test_case.get("category", "unknown")
        instrument_entry = test_case["instrument_entry"]
        expected = test_case["expected"]
        
        print(f"[{i:2d}/{len(test_cases)}] {test_name}")
        
        if verbose:
            print(f"  Category: {category}")
            print(f"  Input: {instrument_entry['name']}")
        
        # Run grounding with timing and detailed logging
        if verbose:
            print(f"\n{'='*80}")
            print(f"🧪 DETAILED TEST: {test_name}")
            print(f"   Category: {category}")
            print(f"   Instrument: {instrument_entry.get('name', 'N/A')}")
            print(f"   General comments: {instrument_entry.get('general_comments', 'N/A')}")
            print(f"{'='*80}")
        
        start_time = time.time()
        try:
            grounding_result = grounder.ground_instrument(instrument_entry)
        except Exception as e:
            end_time = time.time()
            elapsed = end_time - start_time
            
            print(f"  ❌ Error during grounding: {e}")
            
            # Record error
            results["summary"]["total"] += 1
            results["summary"]["errors"] += 1
            results["summary"]["total_time"] += elapsed
            results["by_category"][category]["total"] += 1
            results["by_category"][category]["errors"] += 1
            results["error_patterns"][str(type(e).__name__)] += 1
            
            results["test_results"].append({
                "name": test_name,
                "category": category,
                "status": "error",
                "error": str(e),
                "time_seconds": elapsed
            })
            continue
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        # Evaluate correctness
        is_correct, explanation, details = evaluate_result(grounding_result, expected, test_name)
        
        # Record results
        results["summary"]["total"] += 1
        results["summary"]["total_time"] += elapsed
        results["by_category"][category]["total"] += 1
        
        test_result = {
            "name": test_name,
            "category": category,
            "status": "correct" if is_correct else "incorrect",
            "explanation": explanation,
            "time_seconds": elapsed,
            "details": details,
            "grounding_result": grounding_result,
            "expected": expected
        }
        
        if is_correct:
            results["summary"]["correct"] += 1
            results["by_category"][category]["correct"] += 1
            print(f"  ✅ {explanation} ({elapsed:.2f}s)")
        else:
            results["summary"]["incorrect"] += 1
            results["by_category"][category]["incorrect"] += 1
            print(f"  ❌ {explanation} ({elapsed:.2f}s)")
            
            if verbose and grounding_result.get("reasoning"):
                print(f"    LLM reasoning: {grounding_result['reasoning'][:100]}...")
        
        results["test_results"].append(test_result)
    
    # Calculate summary statistics
    total = results["summary"]["total"]
    if total > 0:
        results["summary"]["average_time"] = results["summary"]["total_time"] / total
        results["summary"]["accuracy"] = results["summary"]["correct"] / total * 100
        results["summary"]["error_rate"] = results["summary"]["errors"] / total * 100
    
    return results


def print_summary(results: Dict):
    """Print evaluation summary"""
    summary = results["summary"]
    
    print(f"\n{'='*60}")
    print(f"INSTRUMENT GROUNDING EVALUATION RESULTS")
    print(f"{'='*60}")
    
    print(f"Overall Performance:")
    print(f"  Total test cases: {summary['total']}")
    print(f"  Correct: {summary['correct']} ({summary.get('accuracy', 0):.1f}%)")
    print(f"  Incorrect: {summary['incorrect']}")
    print(f"  Errors: {summary['errors']} ({summary.get('error_rate', 0):.1f}%)")
    
    print(f"\nTiming:")
    print(f"  Total time: {summary['total_time']:.2f}s")
    print(f"  Average per case: {summary['average_time']:.2f}s")
    if summary['total_time'] > 0:
        print(f"  Throughput: {summary['total']/summary['total_time']:.1f} cases/second")
    
    print(f"\nBy Category:")
    for category, stats in results["by_category"].items():
        total_cat = stats["total"]
        if total_cat > 0:
            accuracy = stats["correct"] / total_cat * 100
            print(f"  {category:20s}: {stats['correct']:2d}/{total_cat:2d} correct ({accuracy:5.1f}%)")
    
    # Error patterns
    if results["error_patterns"]:
        print(f"\nError Patterns:")
        for error_type, count in results["error_patterns"].most_common():
            print(f"  {error_type}: {count}")
    
    # Performance assessment
    accuracy = summary.get('accuracy', 0)
    if accuracy >= 90:
        print(f"\n🎉 Excellent performance! The grounder is working very well.")
    elif accuracy >= 75:
        print(f"\n✅ Good performance, but there's room for improvement:")
        print(f"   - Review failed cases for patterns")
        print(f"   - Consider fine-tuning prompts or thresholds")
    else:
        print(f"\n⚠️  Performance below expectations. Consider:")
        print(f"   - Reviewing embedding similarity approach")
        print(f"   - Improving LLM prompt engineering")
        print(f"   - Adding more contextual clues")


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate InstrumentGrounder accuracy",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--test-cases", 
        default="test_cases.jsonl",
        help="Path to JSONL test cases file (default: test_cases.jsonl)"
    )
    parser.add_argument(
        "--limit", 
        type=int,
        help="Limit to first N test cases"
    )
    parser.add_argument(
        "--category",
        help="Only run tests from specific category"
    )
    parser.add_argument(
        "--save-results",
        help="Save detailed results to JSON file"
    )
    parser.add_argument(
        "--api-key",
        help="OpenAI API key (optional, uses environment)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Detailed output for each test case"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true", 
        help="Parse test cases but don't run evaluation"
    )
    
    args = parser.parse_args()
    
    # Resolve test cases file path
    test_cases_path = Path(args.test_cases)
    if not test_cases_path.is_absolute():
        test_cases_path = Path(__file__).parent / test_cases_path
    
    # Load and validate test cases
    print(f"📁 Loading test cases from: {test_cases_path}")
    test_cases = load_test_cases(str(test_cases_path))
    print(f"📋 Loaded {len(test_cases)} test cases")
    
    # Validate test cases
    invalid_cases = []
    for i, test_case in enumerate(test_cases):
        errors = validate_test_case(test_case)
        if errors:
            invalid_cases.append((i, test_case.get('name', f'case_{i}'), errors))
    
    if invalid_cases:
        print(f"❌ Found {len(invalid_cases)} invalid test cases:")
        for i, name, errors in invalid_cases:
            print(f"  {name}: {', '.join(errors)}")
        return 1
    
    # Filter test cases
    test_cases = filter_test_cases(test_cases, args.category, args.limit)
    print(f"🎯 Running {len(test_cases)} test cases")
    
    if args.category:
        print(f"📂 Category filter: {args.category}")
    
    # Show categories
    categories = Counter(tc.get('category', 'unknown') for tc in test_cases)
    print(f"📊 Categories: {dict(categories)}")
    
    if args.dry_run:
        print("🏃 Dry run - test cases loaded successfully")
        return 0
    
    # Setup environment
    # if not DJANGO_AVAILABLE:
    #     print("❌ Django not available. Please ensure database is configured.")
    #     return 1

    if args.api_key:
        os.environ["OPENAI_API_KEY"] = args.api_key
    
    # Setup logging first
    setup_debug_logging(args.verbose)
    
    # Initialize grounder
    try:
        grounder = get_local_instrument_grounder()
        print("✅ Using local file-based instrument finder")
    except Exception as e:
        print(f"❌ Failed to initialize grounder: {e}")
        return 1
    
    # Run evaluation
    results = run_evaluation(test_cases, grounder, args.verbose)
    
    # Print summary
    print_summary(results)
    
    # Save results if requested
    if args.save_results:
        results["metadata"] = {
            "test_cases_file": str(test_cases_path),
            "total_cases_in_file": len(load_test_cases(str(test_cases_path))),
            "cases_run": len(test_cases),
            "category_filter": args.category,
            "limit": args.limit,
            "timestamp": time.time()
        }
        
        with open(args.save_results, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\n💾 Results saved to: {args.save_results}")
    
    # Return exit code based on performance
    accuracy = results["summary"].get("accuracy", 0)
    if accuracy < 50:
        return 2  # Poor performance
    elif accuracy < 75:
        return 1  # Below expectations
    else:
        return 0  # Good performance


if __name__ == "__main__":
    sys.exit(main())