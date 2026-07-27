"""
Streamlit app for annotating model disagreements across all call types.

Usage:
    streamlit run experiments/compare_models/disagreement_annotator.py
"""

import streamlit as st
import json
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from experiments.compare_models.handlers import *
from experiments.compare_models.core.registry import CallTypeRegistry

# Configuration
GPT5_DIR = Path("experiments/compare_models/prompt_experiments/full_comparison_20251029")

# Model configurations
MODEL_CONFIGS = {
    'GPT-5 vs GPT-5 Mini': {
        'baseline_pattern': 'gpt-5_',
        'comparison_pattern': 'gpt-5-mini_',
        'baseline_dir': GPT5_DIR,
        'comparison_dir': GPT5_DIR,
        'baseline_name': 'GPT-5',
        'comparison_name': 'GPT-5 Mini'
    },
    'GPT-5 vs GPT-5 Nano': {
        'baseline_pattern': 'gpt-5_',
        'comparison_pattern': 'gpt-5-nano_',
        'baseline_dir': GPT5_DIR,
        'comparison_dir': GPT5_DIR,
        'baseline_name': 'GPT-5',
        'comparison_name': 'GPT-5 Nano'
    },
    'GPT-5 vs Bedrock 120b': {
        'baseline_pattern': 'gpt-5_',
        'comparison_pattern': '120b',
        'baseline_dir': GPT5_DIR,
        'comparison_dir': {
            'time_normalization': Path('experiments/compare_models/prompt_experiments/bedrock_120b_vs_20b_time_norm'),
            'detector_normalization': Path('experiments/compare_models/prompt_experiments/bedrock_120b_vs_20b_detector_norm'),
            'physobs_normalization': Path('experiments/compare_models/prompt_experiments/bedrock_120b_vs_20b_physobs_norm'),
            'instrument_validation': Path('experiments/compare_models/prompt_experiments/bedrock_120b_vs_20b_instrument_validation'),
            'mission_identification': Path('experiments/compare_models/prompt_experiments/bedrock_120b_vs_20b_remaining'),
            'mission_selection': Path('experiments/compare_models/prompt_experiments/bedrock_120b_vs_20b_remaining'),
            'instrument_selection': Path('experiments/compare_models/prompt_experiments/bedrock_120b_vs_20b_remaining'),
            'wavelength_normalization': Path('experiments/compare_models/prompt_experiments/bedrock_120b_vs_20b_remaining'),
            'cadence_normalization': Path('experiments/compare_models/prompt_experiments/bedrock_120b_vs_20b_remaining'),
        },
        'baseline_name': 'GPT-5',
        'comparison_name': 'Bedrock 120b'
    },
    'Bedrock 120b Run 1 vs Run 2 (Self-Consistency)': {
        'baseline_pattern': '120b',
        'comparison_pattern': '120b',
        'baseline_dir': {
            'physobs_normalization': Path('experiments/compare_models/prompt_experiments/bedrock_120b_vs_20b_physobs_norm'),
            'mission_identification': Path('experiments/compare_models/prompt_experiments/bedrock_120b_vs_20b_remaining'),
            'instrument_validation': Path('experiments/compare_models/prompt_experiments/bedrock_120b_vs_20b_instrument_validation'),
        },
        'comparison_dir': Path('experiments/compare_models/prompt_experiments/bedrock_120b_self_consistency'),
        'baseline_name': 'Bedrock 120b (Run 1)',
        'comparison_name': 'Bedrock 120b (Run 2)'
    }
}

ANNOTATIONS_FILE = Path("experiments/compare_models/disagreement_annotations.jsonl")

# Categories for disagreements
DISAGREEMENT_CATEGORIES = [
    "prompt_ambiguity",
    "scientific_ambiguity", 
    "formatting_error",
    "model_capability_difference",
    "context_insufficient",
    "genuine_error",
    "other"
]

CORRECTNESS_OPTIONS = [
    "baseline_correct",
    "comparison_correct",
    "both_correct_different_interpretation",
    "both_wrong",
    "ambiguous_cannot_decide",
    "need_more_context"
]

def load_results_for_call_type(call_type, pattern, directory):
    """Load results for a specific call type from a directory/pattern."""
    # Handle dict directories (for Bedrock split structure)
    if isinstance(directory, dict):
        directory = directory.get(call_type)

    if not directory or not directory.exists():
        return None

    files = list(directory.glob(f"*{pattern}*.jsonl"))

    for file in files:
        with open(file) as f:
            first_line = json.loads(f.readline())
            if first_line['call_type'] == call_type:
                f.seek(0)
                return [json.loads(line) for line in f]

    return None

def find_all_disagreements(model_config_key):
    """Find all disagreements across all call types."""
    config = MODEL_CONFIGS[model_config_key]
    all_disagreements = []

    call_types = CallTypeRegistry.list_call_types()

    for call_type in call_types:
        baseline_results = load_results_for_call_type(
            call_type,
            config['baseline_pattern'],
            config['baseline_dir']
        )
        comparison_results = load_results_for_call_type(
            call_type,
            config['comparison_pattern'],
            config['comparison_dir']
        )

        if not baseline_results or not comparison_results:
            continue

        handler = CallTypeRegistry.get(call_type)

        n_cases = min(len(baseline_results), len(comparison_results))

        for idx in range(n_cases):
            baseline = baseline_results[idx]
            comparison = comparison_results[idx]

            baseline_parsed = baseline.get('parsed_response')
            comparison_parsed = comparison.get('parsed_response')

            compare_result = handler.compare_responses(baseline_parsed, comparison_parsed)

            if not compare_result.agree:
                all_disagreements.append({
                    'call_type': call_type,
                    'case_index': idx,
                    'baseline_result': baseline,
                    'comparison_result': comparison,
                    'comparison': compare_result,
                    'handler': handler,
                    'disagreement_id': f"{model_config_key}_{call_type}_{idx}",
                    'model_config_key': model_config_key
                })

    return all_disagreements

def load_annotations():
    """Load existing annotations."""
    if not ANNOTATIONS_FILE.exists():
        return {}
    
    annotations = {}
    with open(ANNOTATIONS_FILE) as f:
        for line in f:
            data = json.loads(line)
            annotations[data['disagreement_id']] = data
    
    return annotations

def save_annotation(disagreement_id, category, correctness, comment, tags):
    """Save a single annotation."""
    annotation = {
        'disagreement_id': disagreement_id,
        'category': category,
        'correctness': correctness,
        'comment': comment,
        'tags': tags,
        'timestamp': datetime.now().isoformat()
    }
    
    # Append to file
    with open(ANNOTATIONS_FILE, 'a') as f:
        f.write(json.dumps(annotation) + '\n')
    
    return annotation

def format_input_messages(messages):
    """Format input messages for display."""
    formatted_messages = []
    for msg in messages:
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')

        # Detect if content is XML (starts with < or <?xml)
        is_xml = content.strip().startswith('<')
        language = 'xml' if is_xml else 'text'

        formatted_messages.append({
            'role': role,
            'content': content,
            'language': language
        })

    return formatted_messages

def main():
    st.set_page_config(page_title="Disagreement Annotator", layout="wide")

    st.title("🔍 Model Disagreement Annotator")

    # Model selection
    model_config_key = st.selectbox(
        "Select Model Comparison",
        list(MODEL_CONFIGS.keys()),
        key="model_selector"
    )

    config = MODEL_CONFIGS[model_config_key]
    st.markdown(f"**Comparing:** {config['baseline_name']} vs {config['comparison_name']}")

    # Initialize session state
    if 'disagreements' not in st.session_state or st.session_state.get('current_model_config') != model_config_key:
        with st.spinner("Loading disagreements..."):
            st.session_state.disagreements = find_all_disagreements(model_config_key)
            st.session_state.annotations = load_annotations()
            st.session_state.current_index = 0
            st.session_state.current_model_config = model_config_key
    
    disagreements = st.session_state.disagreements
    annotations = st.session_state.annotations
    
    if not disagreements:
        st.error("No disagreements found!")
        return
    
    # Sidebar for navigation and stats
    with st.sidebar:
        st.header("Navigation")
        
        total = len(disagreements)
        annotated = len([d for d in disagreements if d['disagreement_id'] in annotations])
        
        st.metric("Total Disagreements", total)
        st.metric("Annotated", annotated)
        st.metric("Progress", f"{annotated/total*100:.1f}%")
        
        st.divider()
        
        # Filter by call type
        call_types = sorted(set(d['call_type'] for d in disagreements))
        selected_call_type = st.selectbox(
            "Filter by call type",
            ["All"] + call_types
        )
        
        # Filter by annotation status
        annotation_filter = st.radio(
            "Show",
            ["All", "Unannotated", "Annotated"]
        )
        
        st.divider()
        
        # Export annotations
        if st.button("📊 Export Annotations"):
            df = pd.DataFrame([annotations[d['disagreement_id']] 
                             for d in disagreements 
                             if d['disagreement_id'] in annotations])
            st.download_button(
                "Download CSV",
                df.to_csv(index=False),
                "disagreement_annotations.csv",
                "text/csv"
            )
    
    # Filter disagreements
    filtered_disagreements = disagreements
    if selected_call_type != "All":
        filtered_disagreements = [d for d in filtered_disagreements 
                                 if d['call_type'] == selected_call_type]
    
    if annotation_filter == "Unannotated":
        filtered_disagreements = [d for d in filtered_disagreements 
                                 if d['disagreement_id'] not in annotations]
    elif annotation_filter == "Annotated":
        filtered_disagreements = [d for d in filtered_disagreements 
                                 if d['disagreement_id'] in annotations]
    
    if not filtered_disagreements:
        st.warning("No disagreements match the current filters")
        return
    
    # Navigation controls
    col1, col2, col3 = st.columns([1, 3, 1])
    
    with col1:
        if st.button("⬅️ Previous") and st.session_state.current_index > 0:
            st.session_state.current_index -= 1
            st.rerun()
    
    with col2:
        case_num = st.number_input(
            "Case",
            min_value=1,
            max_value=len(filtered_disagreements),
            value=min(st.session_state.current_index + 1, len(filtered_disagreements)),
            key="case_selector"
        )
        st.session_state.current_index = case_num - 1
    
    with col3:
        if st.button("Next ➡️") and st.session_state.current_index < len(filtered_disagreements) - 1:
            st.session_state.current_index += 1
            st.rerun()
    
    # Get current disagreement
    current_idx = st.session_state.current_index
    disagreement = filtered_disagreements[current_idx]
    
    disagreement_id = disagreement['disagreement_id']
    call_type = disagreement['call_type']
    handler = disagreement['handler']
    
    # Display disagreement details
    st.header(f"Case {current_idx + 1}/{len(filtered_disagreements)}: {call_type}")
    
    # Show existing annotation if present
    if disagreement_id in annotations:
        st.success("✅ Already annotated")
        existing = annotations[disagreement_id]
        st.info(f"**Category:** {existing['category']} | **Correctness:** {existing['correctness']}")
        if existing.get('comment'):
            st.info(f"**Comment:** {existing['comment']}")
    
    # Display comparison details
    st.subheader("Comparison Details")
    st.code(disagreement['comparison'].details)
    
    # Show input
    with st.expander("📥 Input Messages", expanded=False):
        formatted_msgs = format_input_messages(disagreement['baseline_result']['input_messages'])
        for msg in formatted_msgs:
            st.markdown(f"**{msg['role'].upper()}:**")
            st.code(msg['content'], language=msg['language'])

    # Side-by-side comparison
    col_baseline, col_comparison = st.columns(2)

    with col_baseline:
        st.subheader(f"🤖 {config['baseline_name']}")
        st.json(disagreement['baseline_result']['parsed_response'])
        st.caption(f"Tokens: {disagreement['baseline_result'].get('total_tokens', 'N/A')} | "
                  f"Cost: ${disagreement['baseline_result'].get('estimated_cost_usd', 0):.4f}")

        with st.expander("Raw output"):
            st.code(disagreement['baseline_result'].get('output_content', ''))

    with col_comparison:
        st.subheader(f"🤖 {config['comparison_name']}")
        st.json(disagreement['comparison_result']['parsed_response'])
        st.caption(f"Tokens: {disagreement['comparison_result'].get('total_tokens', 'N/A')} | "
                  f"Cost: ${disagreement['comparison_result'].get('estimated_cost_usd', 0):.4f}")

        with st.expander("Raw output"):
            st.code(disagreement['comparison_result'].get('output_content', ''))
    
    # Annotation form
    st.divider()
    st.subheader("📝 Annotate This Disagreement")
    
    with st.form(key=f"annotation_form_{disagreement_id}"):
        col1, col2 = st.columns(2)
        
        with col1:
            category = st.selectbox(
                "Disagreement Category",
                DISAGREEMENT_CATEGORIES,
                index=0 if disagreement_id not in annotations 
                      else DISAGREEMENT_CATEGORIES.index(annotations[disagreement_id]['category'])
            )
        
        with col2:
            correctness = st.selectbox(
                "Which is Correct?",
                CORRECTNESS_OPTIONS,
                index=0 if disagreement_id not in annotations
                      else CORRECTNESS_OPTIONS.index(annotations[disagreement_id]['correctness'])
            )
        
        comment = st.text_area(
            "Comment / Notes",
            value=annotations.get(disagreement_id, {}).get('comment', ''),
            height=100
        )
        
        tags = st.text_input(
            "Tags (comma-separated)",
            value=", ".join(annotations.get(disagreement_id, {}).get('tags', []))
        )
        
        col1, col2, col3 = st.columns([1, 1, 2])
        
        with col1:
            submit = st.form_submit_button("💾 Save Annotation", type="primary")
        
        with col2:
            skip = st.form_submit_button("⏭️ Skip")
        
        if submit:
            tag_list = [t.strip() for t in tags.split(',') if t.strip()]
            annotation = save_annotation(disagreement_id, category, correctness, comment, tag_list)
            st.session_state.annotations[disagreement_id] = annotation
            st.success("Annotation saved!")
            
            # Auto-advance to next unannotated
            if st.session_state.current_index < len(filtered_disagreements) - 1:
                st.session_state.current_index += 1
                st.rerun()
        
        if skip:
            if st.session_state.current_index < len(filtered_disagreements) - 1:
                st.session_state.current_index += 1
                st.rerun()

if __name__ == "__main__":
    main()
