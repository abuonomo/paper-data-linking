#!/usr/bin/env bash
#
# Run comprehensive model comparison experiment across all call types.
#
# This script runs all 10 call types (excluding paper_analysis) with 4 models:
# - openai/gpt-5
# - openai/gpt-5-mini
# - openai/gpt-5-nano
# - bedrock/openai.gpt-oss-120b-1:0
#
# Estimated cost: ~$76
# Estimated time: ~6 hours (sequential execution)

set -e  # Exit on error

# Configuration
MODELS="openai/gpt-5-nano openai/gpt-5-mini openai/gpt-5 bedrock/openai.gpt-oss-120b-1:0"
EXPERIMENT_NAME="full_comparison_$(date +%Y%m%d)"
MAX_CASES=100  # Limit to 100 cases per call type
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "========================================================================"
echo "COMPREHENSIVE MODEL COMPARISON EXPERIMENT"
echo "========================================================================"
echo "Experiment name: $EXPERIMENT_NAME"
echo "Models: $MODELS"
echo "Max cases per call type: $MAX_CASES"
echo "Start time: $(date)"
echo ""
echo "Estimated cost: ~\$19 (capped at 100 cases)"
echo "Estimated time: ~2 hours"
echo "========================================================================"
echo ""

# Define call types and their configurations
declare -A CALL_TYPES=(
    ["mission_identification"]="paper_data_linking/linkers/general/prompts/mission_identification/system.xml"
    ["time_normalization"]="paper_data_linking/linkers/general/prompts/time_normalization/system.xml"
    ["mission_selection"]="paper_data_linking/linkers/general/prompts/mission_selection/system.xml"
    ["instrument_selection"]="paper_data_linking/linkers/general/prompts/instrument_selection/system.xml"
    ["instrument_validation"]="paper_data_linking/linkers/general/prompts/validation/system.xml"
    ["wavelength_normalization"]="paper_data_linking/linkers/general/prompts/wavelength_normalization/system.xml"
    ["physobs_normalization"]="paper_data_linking/linkers/general/prompts/physobs_normalization/system.xml"
    ["cadence_normalization"]="paper_data_linking/linkers/general/prompts/cadence_normalization/system.xml"
    ["detector_normalization"]="paper_data_linking/linkers/general/prompts/detector_normalization/system.xml"
    ["structure_analysis"]="paper_data_linking/linkers/general/prompts/structured_parsing/system.xml"
)

# Counter for progress tracking
TOTAL_CALL_TYPES=${#CALL_TYPES[@]}
CURRENT=0

# Run each call type
for call_type in "${!CALL_TYPES[@]}"; do
    CURRENT=$((CURRENT + 1))
    prompt_path="${CALL_TYPES[$call_type]}"
    input_file="inputs/test_set/${call_type}.jsonl"

    echo ""
    echo "========================================================================"
    echo "[$CURRENT/$TOTAL_CALL_TYPES] Running: $call_type"
    echo "========================================================================"
    echo "Input: $input_file"
    echo "Prompt: $prompt_path"
    echo "Time: $(date)"
    echo ""

    # Check if input file exists
    if [ ! -f "$BASE_DIR/$input_file" ]; then
        echo "ERROR: Input file not found: $input_file"
        echo "Skipping $call_type"
        continue
    fi

    # Check if prompt file exists
    if [ ! -f "$BASE_DIR/$prompt_path" ]; then
        echo "ERROR: Prompt file not found: $prompt_path"
        echo "Skipping $call_type"
        continue
    fi

    # Run the experiment
    python "$BASE_DIR/experiments/compare_models/run_prompt_experiment.py" \
        --call-type "$call_type" \
        --input "$input_file" \
        --system-prompt "$prompt_path" \
        --models $MODELS \
        --experiment-name "$EXPERIMENT_NAME" \
        --temperature 1.0 \
        --max-cases $MAX_CASES

    echo ""
    echo "Completed: $call_type"
    echo "Progress: $CURRENT/$TOTAL_CALL_TYPES call types"
    echo ""
done

echo ""
echo "========================================================================"
echo "EXPERIMENT COMPLETE"
echo "========================================================================"
echo "Experiment name: $EXPERIMENT_NAME"
echo "End time: $(date)"
echo "Results directory: experiments/compare_models/prompt_experiments/$EXPERIMENT_NAME"
echo ""
echo "Next steps:"
echo "1. Open analyze_experiment_results.ipynb"
echo "2. Load results from: experiments/compare_models/prompt_experiments/$EXPERIMENT_NAME"
echo "3. Analyze model performance across all call types"
echo "========================================================================"
