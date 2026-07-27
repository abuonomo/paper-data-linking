#!/bin/bash
# Run detector_free_text with Bedrock 120B 5 times for self-consistency analysis

set -e

echo "Running detector_free_text self-consistency experiment (5 runs)"
echo "================================================================"
echo ""

for i in {1..5}; do
    echo "Starting run $i/5..."
    python experiments/compare_models/run_parallel_experiment.py \
        --config experiments/compare_models/experiment_configs/detector_free_text_example.yaml \
        --skip-credential-check

    echo "✓ Completed run $i/5"
    echo ""

    # Brief pause between runs
    sleep 2
done

echo "================================================================"
echo "All 5 runs completed!"
echo ""
echo "Results in: experiments/compare_models/prompt_experiments/detector_free_text_bedrock_120b_full/"
