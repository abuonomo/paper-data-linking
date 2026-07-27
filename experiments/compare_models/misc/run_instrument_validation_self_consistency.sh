#!/bin/bash

MODEL="bedrock/converse/openai.gpt-oss-120b-1:0"
NUM_RUNS="${1:-3}" # Default to 3 runs if not specified

echo "Running $NUM_RUNS self-consistency experiments for instrument validation with model: $MODEL"
echo "=============================================="

for i in $(seq 1 $NUM_RUNS); do
    EXPERIMENT_NAME="validation_consistency_run_${i}"
    OUTPUT_DIR="experiments/compare_models/prompt_experiments/${EXPERIMENT_NAME}"

    echo "Starting run $i/$NUM_RUNS at $(date '+%Y-%m-%d %H:%M:%S')"
    echo "  Experiment Name: $EXPERIMENT_NAME"
    echo "  Output Directory: $OUTPUT_DIR"
    echo "----------------------------------------"

    # Optional: Clear previous output directory for this run to force re-run
    # if [ -d "$OUTPUT_DIR" ]; then
    #     echo "  Removing existing output directory: $OUTPUT_DIR"
    #     rm -rf "$OUTPUT_DIR"
    # fi

    python experiments/compare_models/run_parallel_experiment.py \
        --models "$MODEL" \
        --call-types instrument_validation \
        --experiment-name "$EXPERIMENT_NAME" \
        --skip-credential-check \
        --timeout 1200 # Extend timeout for potentially slower Bedrock calls

    EXIT_CODE=$?

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
    echo "  - experiments/compare_models/prompt_experiments/validation_consistency_run_${i}"
done
echo ""
echo "To analyze self-consistency, compare the .jsonl files across these directories."
