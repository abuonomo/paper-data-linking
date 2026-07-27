#!/bin/bash

# Script to run multiple self-consistency experiments
# This allows us to measure consistency across multiple runs with temperature=1.0

CONFIG_FILE="$1"
NUM_RUNS="${2:-5}"  # Default to 5 runs if not specified

if [ -z "$CONFIG_FILE" ]; then
    echo "Usage: $0 <config_file> [num_runs]"
    echo "Example: $0 experiments/compare_models/misc/experiment_configs/test_set_2025_11_26/cadence_normalization.yaml 5"
    exit 1
fi

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Config file not found: $CONFIG_FILE"
    exit 1
fi

echo "Running $NUM_RUNS self-consistency experiments with config: $CONFIG_FILE"
echo "=============================================="

# Extract experiment name and call type from config file
EXPERIMENT_NAME=$(grep "^experiment_name:" "$CONFIG_FILE" | awk '{print $2}')
CALL_TYPE=$(grep -A1 "^call_types:" "$CONFIG_FILE" | grep "^  -" | head -1 | sed 's/.*- //')

if [ -z "$EXPERIMENT_NAME" ]; then
    echo "Error: Could not extract experiment_name from config file"
    exit 1
fi

if [ -z "$CALL_TYPE" ]; then
    echo "Error: Could not extract call_type from config file"
    exit 1
fi

# Derive test_set by removing call_type prefix from experiment_name
# e.g., "cadence_normalization_test_set_2025_11_26" -> "test_set_2025_11_26"
TEST_SET="${EXPERIMENT_NAME#${CALL_TYPE}_}"

echo "Experiment name: $EXPERIMENT_NAME"
echo "Call type: $CALL_TYPE"
echo "Test set: $TEST_SET"
echo ""

# Run experiments sequentially
for i in $(seq 1 $NUM_RUNS); do
    echo "Starting run $i/$NUM_RUNS at $(date '+%Y-%m-%d %H:%M:%S')"
    echo "----------------------------------------"

    # Clear previous output directory for this run to force re-run
    OUTPUT_DIR="experiments/compare_models/self_consistency/results/${TEST_SET}/${CALL_TYPE}/run${i}"
    if [ -d "$OUTPUT_DIR" ]; then
        echo "Removing existing output directory: $OUTPUT_DIR"
        rm -rf "$OUTPUT_DIR"
    fi

    # Ensure parent directories exist
    mkdir -p "$(dirname "$OUTPUT_DIR")"

    # Modify config to use run-specific experiment name and output directory
    TMP_CONFIG="/tmp/self_consistency_config_run${i}.yaml"
    sed "s/experiment_name: ${EXPERIMENT_NAME}/experiment_name: run${i}/" "$CONFIG_FILE" > "$TMP_CONFIG"

    # Run the experiment
    python experiments/compare_models/run_parallel_experiment.py \
        --config "$TMP_CONFIG" \
        --output-dir "$OUTPUT_DIR" \
        --skip-credential-check

    EXIT_CODE=$?

    # Clean up temp config
    rm "$TMP_CONFIG"

    if [ $EXIT_CODE -ne 0 ]; then
        echo "Error: Run $i failed with exit code $EXIT_CODE"
        exit $EXIT_CODE
    fi

    echo "Completed run $i/$NUM_RUNS at $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
done

echo "=============================================="
echo "All $NUM_RUNS runs completed successfully!"
echo ""
echo "Output directories:"
for i in $(seq 1 $NUM_RUNS); do
    echo "  - experiments/compare_models/self_consistency/results/${TEST_SET}/${CALL_TYPE}/run${i}"
done
echo ""
echo "To analyze self-consistency, use the self_consistency_experiments.ipynb notebook."
