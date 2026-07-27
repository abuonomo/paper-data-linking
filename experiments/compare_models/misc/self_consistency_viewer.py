"""
Streamlit app for viewing self-consistency disagreements across multiple runs.

Shows cases where outputs differ across 5 runs with the same prompt at temperature=1.0.

Usage:
    streamlit run experiments/compare_models/self_consistency_viewer.py
"""

import streamlit as st
import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any


def load_jsonl(filepath: Path) -> List[Dict[str, Any]]:
    """Load all records from a JSONL file."""
    records = []
    with open(filepath) as f:
        for line in f:
            records.append(json.loads(line))
    return records


def normalize_response(response: str) -> str:
    """Normalize response text for comparison."""
    return response.strip().lower()


def load_self_consistency_data(base_name: str, base_dir: Path) -> Dict:
    """Load data from multiple runs and identify disagreements."""
    run_dirs = sorted(base_dir.glob(f"{base_name}_run*"))

    if not run_dirs:
        return {'error': f'No run directories found for {base_name}'}

    # Load all runs
    runs_data = []
    for run_dir in run_dirs:
        jsonl_files = list(run_dir.glob("*.jsonl"))
        if not jsonl_files:
            continue

        jsonl_file = jsonl_files[0]
        records = load_jsonl(jsonl_file)
        runs_data.append({
            'dir': run_dir.name,
            'file': jsonl_file.name,
            'records': records
        })

    # Group responses by case ID
    cases_by_id = defaultdict(list)
    for run in runs_data:
        for record in run['records']:
            case_id = record.get('original_id') or record.get('case_index')
            cases_by_id[case_id].append(record)

    # Identify disagreement cases
    disagreement_cases = []
    perfect_consistency_cases = []
    error_cases = []

    for case_id, records in cases_by_id.items():
        # Check for errors
        errors = [r for r in records if 'error' in r]
        if errors:
            error_cases.append({
                'case_id': case_id,
                'records': records,
                'error_count': len(errors)
            })
            continue

        # Extract responses
        responses = []
        for record in records:
            response = record.get('output_content') or record.get('response', '')
            if not response:
                continue
            responses.append(normalize_response(response))

        # Check for disagreements
        unique_responses = set(responses)
        if len(unique_responses) > 1:
            # Count frequency of each response
            response_counts = defaultdict(int)
            for resp in responses:
                response_counts[resp] += 1

            disagreement_cases.append({
                'case_id': case_id,
                'records': records,
                'unique_responses': len(unique_responses),
                'response_counts': dict(response_counts)
            })
        else:
            perfect_consistency_cases.append({
                'case_id': case_id,
                'records': records
            })

    return {
        'runs_data': runs_data,
        'num_runs': len(runs_data),
        'disagreement_cases': disagreement_cases,
        'perfect_consistency_cases': perfect_consistency_cases,
        'error_cases': error_cases,
        'total_cases': len(cases_by_id)
    }


def display_case(case: Dict, num_runs: int):
    """Display a single case with all its runs."""
    records = case['records']

    # Get the first successful record for input details
    first_record = None
    for r in records:
        if 'error' not in r:
            first_record = r
            break

    if not first_record:
        first_record = records[0]

    # Display input
    st.subheader("Input")
    if 'input_messages' in first_record:
        for msg in first_record['input_messages']:
            with st.expander(f"{msg['role'].upper()} message"):
                st.code(msg['content'], language='xml')

    # Display outputs from all runs
    st.subheader(f"Outputs ({len(records)} runs)")

    # Group by output for easier comparison
    outputs_grouped = defaultdict(list)
    for i, record in enumerate(records, 1):
        if 'error' in record:
            output = f"ERROR: {record['error']}"
        else:
            output = record.get('output_content') or record.get('response', 'NO OUTPUT')
        outputs_grouped[output].append(f"Run {i}")

    # Display each unique output with which runs produced it
    for output, runs in outputs_grouped.items():
        run_str = ", ".join(runs)
        st.markdown(f"**{run_str}** ({len(runs)}/{len(records)} runs)")
        if output.startswith("ERROR:"):
            st.error(output)
        else:
            st.code(output, language='text')

            # Show parsed response if available
            for record in records:
                if (record.get('output_content') or record.get('response', '')) == output:
                    if 'parsed_response' in record:
                        with st.expander("Parsed response"):
                            st.json(record['parsed_response'])
                    break
        st.markdown("---")

    # Show metadata
    with st.expander("Metadata"):
        for i, record in enumerate(records, 1):
            st.markdown(f"**Run {i}**")
            metadata = {
                'created_at': record.get('created_at'),
                'duration_ms': record.get('duration_ms'),
                'prompt_tokens': record.get('prompt_tokens'),
                'completion_tokens': record.get('completion_tokens'),
                'model_name': record.get('model_name')
            }
            st.json({k: v for k, v in metadata.items() if v is not None})


def main():
    st.set_page_config(page_title="Self-Consistency Viewer", layout="wide")

    st.title("🔍 Self-Consistency Disagreement Viewer")
    st.markdown("View cases where model outputs differ across multiple runs with same prompt")

    # Configuration
    base_dir = Path("experiments/compare_models/prompt_experiments")

    # Sidebar configuration
    st.sidebar.header("Configuration")

    # Auto-detect available experiments
    all_dirs = [d.name for d in base_dir.iterdir() if d.is_dir()]

    # Find base names (without _runN suffix)
    base_names = set()
    for dirname in all_dirs:
        if '_run' in dirname:
            base_name = dirname.rsplit('_run', 1)[0]
            base_names.add(base_name)

    if not base_names:
        st.error(f"No self-consistency experiments found in {base_dir}")
        st.info("Looking for directories with pattern: *_run1, *_run2, etc.")
        return

    selected_base = st.sidebar.selectbox(
        "Select Experiment",
        sorted(base_names)
    )

    # Load data
    with st.spinner("Loading self-consistency data..."):
        data = load_self_consistency_data(selected_base, base_dir)

    if 'error' in data:
        st.error(data['error'])
        return

    # Display summary statistics
    st.sidebar.markdown("---")
    st.sidebar.subheader("Summary")
    st.sidebar.metric("Number of Runs", data['num_runs'])
    st.sidebar.metric("Total Cases", data['total_cases'])
    st.sidebar.metric("Perfect Consistency", len(data['perfect_consistency_cases']))
    st.sidebar.metric("Disagreements", len(data['disagreement_cases']))
    st.sidebar.metric("API Errors", len(data['error_cases']))

    if data['total_cases'] > 0:
        consistency_pct = len(data['perfect_consistency_cases']) / (data['total_cases'] - len(data['error_cases'])) * 100
        st.sidebar.metric("Consistency Rate", f"{consistency_pct:.1f}%")

    # Main content - tabs for different views
    tab1, tab2, tab3 = st.tabs(["Disagreements", "Error Cases", "Perfect Consistency"])

    with tab1:
        st.header(f"Disagreement Cases ({len(data['disagreement_cases'])})")

        if not data['disagreement_cases']:
            st.success("No disagreements found! All cases have perfect consistency.")
        else:
            # Filter by number of unique responses
            unique_counts = sorted(set(c['unique_responses'] for c in data['disagreement_cases']))
            selected_unique = st.multiselect(
                "Filter by number of unique responses",
                unique_counts,
                default=unique_counts
            )

            filtered_cases = [c for c in data['disagreement_cases'] if c['unique_responses'] in selected_unique]

            st.info(f"Showing {len(filtered_cases)} cases")

            # Case selector
            case_options = {
                f"Case {i+1}: {c['case_id']} ({c['unique_responses']} unique responses)": c
                for i, c in enumerate(filtered_cases)
            }

            if case_options:
                selected_case_name = st.selectbox("Select case to view", list(case_options.keys()))
                selected_case = case_options[selected_case_name]

                st.markdown("---")
                display_case(selected_case, data['num_runs'])

    with tab2:
        st.header(f"Error Cases ({len(data['error_cases'])})")

        if not data['error_cases']:
            st.success("No error cases!")
        else:
            # Case selector
            case_options = {
                f"Case {i+1}: {c['case_id']} ({c['error_count']}/{data['num_runs']} errors)": c
                for i, c in enumerate(data['error_cases'])
            }

            selected_case_name = st.selectbox("Select error case to view", list(case_options.keys()))
            selected_case = case_options[selected_case_name]

            st.markdown("---")
            display_case(selected_case, data['num_runs'])

    with tab3:
        st.header(f"Perfect Consistency ({len(data['perfect_consistency_cases'])})")

        if not data['perfect_consistency_cases']:
            st.warning("No cases with perfect consistency")
        else:
            # Case selector
            case_options = {
                f"Case {i+1}: {c['case_id']}": c
                for i, c in enumerate(data['perfect_consistency_cases'][:100])  # Limit to 100
            }

            if len(data['perfect_consistency_cases']) > 100:
                st.info(f"Showing first 100 of {len(data['perfect_consistency_cases'])} perfect consistency cases")

            selected_case_name = st.selectbox("Select case to view", list(case_options.keys()))
            selected_case = case_options[selected_case_name]

            st.markdown("---")
            display_case(selected_case, data['num_runs'])


if __name__ == '__main__':
    main()
