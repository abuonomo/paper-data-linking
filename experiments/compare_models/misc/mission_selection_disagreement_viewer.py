"""
Streamlit app for viewing mission_selection self-consistency disagreements.

Usage:
    streamlit run experiments/compare_models/mission_selection_disagreement_viewer.py
"""

import streamlit as st
import json
import sys
from pathlib import Path
from collections import Counter

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

st.set_page_config(page_title="Mission Selection Disagreements", layout="wide")

# Configuration
EXPERIMENT_DIR = Path("experiments/compare_models/prompt_experiments/bedrock_120b_mission_selection_full")


@st.cache_data
def load_all_runs():
    """Load all 5 runs of mission_selection experiment."""
    jsonl_files = sorted(EXPERIMENT_DIR.glob("bedrock_openai.gpt-oss-120b-1_0_*.jsonl"))

    runs_data = []
    for f in jsonl_files:
        with open(f) as file:
            runs_data.append([json.loads(line) for line in file])

    return runs_data


@st.cache_data
def find_disagreements(runs_data):
    """Find all cases with disagreements."""
    n_cases = len(runs_data[0])

    disagreement_cases = []

    for case_idx in range(n_cases):
        # Collect responses from all runs
        case_responses = []
        for run in runs_data:
            case = run[case_idx]
            parsed = case.get('parsed_response')
            if parsed:
                is_ambiguous = parsed.get('is_ambiguous', False)
                if is_ambiguous:
                    response = 'AMBIGUOUS'
                else:
                    mission_indices = parsed.get('mission_indices', [])
                    response = tuple(sorted(mission_indices)) if mission_indices else 'EMPTY'
            else:
                response = 'PARSE_ERROR'
            case_responses.append(response)

        # Check if disagreement
        unique_responses = set(case_responses)
        if len(unique_responses) > 1:
            # Get full case data from first run
            case_data = runs_data[0][case_idx]

            # Categorize disagreement
            if 'PARSE_ERROR' in unique_responses:
                category = "Parse Error"
            elif 'AMBIGUOUS' in unique_responses or 'EMPTY' in unique_responses:
                category = "AMBIGUOUS vs Specific"
            else:
                category = "Different Indices"

            disagreement_cases.append({
                'case_idx': case_idx,
                'responses': case_responses,
                'unique_responses': unique_responses,
                'category': category,
                'case_data': case_data,
                'distribution': dict(Counter(case_responses))
            })

    return disagreement_cases


def format_response(response):
    """Format a response for display."""
    if isinstance(response, tuple):
        return f"[{', '.join(map(str, response))}]"
    return str(response)


def main():
    st.title("Mission Selection Self-Consistency Disagreements")
    st.markdown("### 5-Run Self-Consistency Analysis with Bedrock GPT-OSS 120B")

    # Load data
    with st.spinner("Loading experiment data..."):
        runs_data = load_all_runs()
        disagreements = find_disagreements(runs_data)

    # Summary statistics
    total_cases = len(runs_data[0])
    n_disagreements = len(disagreements)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Cases", total_cases)
    with col2:
        st.metric("Disagreements", n_disagreements)
    with col3:
        st.metric("Agreement Rate", f"{100*(total_cases-n_disagreements)/total_cases:.1f}%")

    # Category breakdown
    st.markdown("---")
    st.subheader("Disagreement Categories")

    category_counts = Counter(d['category'] for d in disagreements)
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("AMBIGUOUS vs Specific", category_counts.get("AMBIGUOUS vs Specific", 0))
    with col2:
        st.metric("Different Indices", category_counts.get("Different Indices", 0))
    with col3:
        st.metric("Parse Errors", category_counts.get("Parse Error", 0))

    # Filter by category
    st.markdown("---")
    category_filter = st.selectbox(
        "Filter by Category",
        ["All"] + list(category_counts.keys())
    )

    if category_filter != "All":
        filtered_disagreements = [d for d in disagreements if d['category'] == category_filter]
    else:
        filtered_disagreements = disagreements

    st.markdown(f"**Showing {len(filtered_disagreements)} cases**")

    # Case selector
    if filtered_disagreements:
        case_indices = [d['case_idx'] for d in filtered_disagreements]
        selected_idx = st.selectbox(
            "Select Case to View",
            range(len(filtered_disagreements)),
            format_func=lambda i: f"Case {filtered_disagreements[i]['case_idx']} ({filtered_disagreements[i]['category']})"
        )

        # Display selected case
        case = filtered_disagreements[selected_idx]

        st.markdown("---")
        st.subheader(f"Case {case['case_idx']}: {case['category']}")

        # Response distribution
        st.markdown("#### Response Distribution Across 5 Runs")
        response_df = []
        for resp, count in case['distribution'].items():
            response_df.append({
                'Response': format_response(resp),
                'Count': count,
                'Percentage': f"{100*count/5:.0f}%"
            })
        st.dataframe(response_df, use_container_width=True)

        # Individual run responses
        st.markdown("#### Individual Run Responses")
        cols = st.columns(5)
        for i, (col, resp) in enumerate(zip(cols, case['responses'])):
            with col:
                st.markdown(f"**Run {i+1}**")
                st.code(format_response(resp))

        # Input prompt
        st.markdown("---")
        st.markdown("#### Input Prompt")

        case_data = case['case_data']
        input_messages = case_data.get('input_messages', [])

        if input_messages:
            # System message
            with st.expander("System Prompt", expanded=False):
                system_msg = input_messages[0].get('content', 'N/A')
                st.text(system_msg)

            # User message
            st.markdown("**User Message:**")
            user_msg = input_messages[-1].get('content', 'N/A')
            st.text_area("", user_msg, height=400, label_visibility="collapsed")

        # Sample outputs from runs
        st.markdown("---")
        st.markdown("#### Sample Model Outputs")

        # Show outputs from first 3 runs
        for i in range(min(3, len(runs_data))):
            run_case = runs_data[i][case['case_idx']]
            output = run_case.get('output_content', 'N/A')
            parsed = run_case.get('parsed_response', {})

            with st.expander(f"Run {i+1} Output: {format_response(case['responses'][i])}", expanded=False):
                st.markdown("**Raw Output:**")
                st.code(output)
                st.markdown("**Parsed:**")
                st.json(parsed)

        # Navigation
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 2, 1])
        with col1:
            if st.button("← Previous Case") and selected_idx > 0:
                st.rerun()
        with col3:
            if st.button("Next Case →") and selected_idx < len(filtered_disagreements) - 1:
                st.rerun()

    else:
        st.info("No disagreements found in selected category.")


if __name__ == "__main__":
    main()
