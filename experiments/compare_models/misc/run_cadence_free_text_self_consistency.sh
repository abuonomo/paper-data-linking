#!/bin/bash
# Run cadence_normalization with Bedrock 120B 5 times for self-consistency analysis

set -e

echo "Running cadence_normalization self-consistency experiment (5 runs)"
echo "================================================================"
echo ""

for i in {1..5}; do
    echo "Starting run $i/5..."
    python experiments/compare_models/run_parallel_experiment.py \
        --config experiments/compare_models/experiment_configs/cadence_free_text_self_consistency.yaml \
        --skip-credential-check

    echo "✓ Completed run $i/5"
    echo ""
    sleep 2
done

echo "================================================================"
echo "All 5 runs completed!"
echo "================================================================"
echo ""
echo "To analyze results, run:"
echo "  python experiments/compare_models/visualize_cadence_free_text.py"