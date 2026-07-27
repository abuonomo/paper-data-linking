#!/bin/bash
# Run physobs_free_text with Bedrock 120B 5 times for self-consistency analysis

set -e

echo "Running physobs_free_text self-consistency experiment (5 runs)"
echo "================================================================"
echo ""

for i in {1..5}; do
    echo "Starting run $i/5..."
    python experiments/compare_models/run_parallel_experiment.py \
        --config experiments/compare_models/experiment_configs/physobs_free_text_example.yaml \
        --skip-credential-check

    echo "✓ Completed run $i/5"
    echo ""

    # Brief pause between runs
    sleep 2
done

echo "================================================================"
echo "All 5 runs completed!"
echo ""
echo "Results in: experiments/compare_models/prompt_experiments/physobs_free_text_bedrock_120b_full/"
echo ""
echo "To analyze self-consistency, run:"
echo "  python experiments/compare_models/analyze_self_consistency.py \\"
echo "    --call-type physobs_free_text \\"
echo "    --experiment-dir experiments/compare_models/prompt_experiments/physobs_free_text_bedrock_120b_full"
