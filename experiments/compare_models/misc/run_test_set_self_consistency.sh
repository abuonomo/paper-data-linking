#!/bin/bash

# Run self-consistency experiments on test_set_2025_11_26
# Simply iterates through config files and runs 5 self-consistency runs for each

set -e

NUM_RUNS="${1:-5}"  # Default to 5 runs
CONFIG_DIR="experiments/compare_models/experiment_configs/test_set_2025_11_26"

echo "================================================================"
echo "SELF-CONSISTENCY EXPERIMENTS: test_set_2025_11_26"
echo "================================================================"
echo "Config directory: $CONFIG_DIR"
echo "Number of runs per experiment: $NUM_RUNS"
echo ""

# Find all YAML configs in the directory
CONFIGS=$(find "$CONFIG_DIR" -name "*.yaml" -type f | sort)

if [ -z "$CONFIGS" ]; then
    echo "Error: No config files found in $CONFIG_DIR"
    exit 1
fi

echo "Found configs:"
echo "$CONFIGS" | sed 's/^/  /'
echo ""

# Run each config
for config in $CONFIGS; do
    echo "================================================================"
    echo "Running: $(basename "$config")"
    echo "================================================================"
    echo ""

    # Check if input file exists
    INPUT_FILE=$(grep "^    input:" "$config" | awk '{print $2}')
    if [ -n "$INPUT_FILE" ] && [ ! -f "$INPUT_FILE" ]; then
        echo "⚠️  Skipping $(basename "$config") - input file not found: $INPUT_FILE"
        echo "   Run ./scripts/export_test_set_for_self_consistency.sh first"
        echo ""
        continue
    fi

    # Run self-consistency
    ./experiments/compare_models/run_self_consistency.sh "$config" "$NUM_RUNS"

    if [ $? -ne 0 ]; then
        echo "❌ Error running: $(basename "$config")"
        echo ""
        continue
    fi

    echo "✓ Completed: $(basename "$config")"
    echo ""

    # Extract experiment name and analyze
    EXPERIMENT_NAME=$(grep "^experiment_name:" "$config" | awk '{print $2}')
    if [ -n "$EXPERIMENT_NAME" ]; then
        echo "Analyzing self-consistency for: $EXPERIMENT_NAME"
        python experiments/compare_models/analyze_self_consistency.py "$EXPERIMENT_NAME"
        echo ""
    fi

    echo "================================================================"
    echo ""
done

echo "================================================================"
echo "ALL EXPERIMENTS COMPLETE"
echo "================================================================"
echo ""
echo "Results saved in: experiments/compare_models/prompt_experiments/"
echo ""