#!/bin/bash
# Run mission_selection with Bedrock 120B 5 times for self-consistency analysis

set -e

echo "Running mission_selection self-consistency experiment (5 runs)"
echo "================================================================"
echo ""

for i in {1..5}; do
    echo "Starting run $i/5..."
    python experiments/compare_models/run_parallel_experiment.py \
        --config experiments/compare_models/experiment_configs/mission_selection_self_consistency.yaml \
        --skip-credential-check

    echo "✓ Completed run $i/5"
    echo ""

    # Brief pause between runs
    sleep 2
done

echo "=========================================="
echo "All 5 runs completed!"
echo "=========================================="
echo ""
echo "Results saved in: experiments/compare_models/prompt_experiments/bedrock_120b_mission_selection_full/"
echo ""
echo "To analyze results, run:"
echo "  python experiments/compare_models/visualize_mission_selection.py"
