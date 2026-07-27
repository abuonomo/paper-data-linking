#!/bin/bash

# Export test set data from production for self-consistency experiments
# This script downloads LLM call data from production for the test_set_2025_11_26

set -e

REMOTE_HOST="${REMOTE_HOST:-your-prod-host}"
REMOTE_DIR="${REMOTE_DIR:-/path/to/paper-data-linking}"
TEST_SET_TAG="test_set_2025_11_26"
LOCAL_OUTPUT_DIR="inputs/test_set"

# Ensure local output directory exists
mkdir -p "$LOCAL_OUTPUT_DIR"

echo "================================================================"
echo "EXPORTING TEST SET DATA FOR SELF-CONSISTENCY EXPERIMENTS"
echo "================================================================"
echo "Test set: $TEST_SET_TAG"
echo "Remote host: $REMOTE_HOST"
echo "Local output: $LOCAL_OUTPUT_DIR"
echo ""

# Define call types to export (excluding structure_analysis and paper_analysis)
CALL_TYPES=(
    "instrument_validation"
    "wavelength_normalization"
    "physobs_normalization"
    "mission_selection"
    "instrument_selection"
    "detector_normalization"
    "time_normalization"
    "cadence_normalization"
    "mission_identification"
)

# Export each call type
for call_type in "${CALL_TYPES[@]}"; do
    echo "----------------------------------------"
    echo "Exporting: $call_type"
    echo "----------------------------------------"

    CONTAINER_OUTPUT="/tmp/${call_type}_${TEST_SET_TAG}.jsonl"
    HOST_OUTPUT="${REMOTE_DIR}/exports/${call_type}_${TEST_SET_TAG}.jsonl"
    LOCAL_OUTPUT="${LOCAL_OUTPUT_DIR}/${call_type}_${TEST_SET_TAG}.jsonl"

    # Ensure remote exports directory exists
    ssh "$REMOTE_HOST" "mkdir -p ${REMOTE_DIR}/exports" 2>/dev/null || true

    # Export on remote server (inside container)
    echo "  Running export on remote server..."
    ssh "$REMOTE_HOST" "cd $REMOTE_DIR && docker compose exec -T api python manage.py export_llm_calls \
        --call-type $call_type \
        --require-render-context \
        --paper-tags $TEST_SET_TAG \
        --output $CONTAINER_OUTPUT" 2>&1 | grep -v "^time=" | grep -v "warning" | grep -v "obsolete" || {
        echo "  ⚠️  Export failed or no data found for $call_type"
        continue
    }

    # Copy file from container to host
    echo "  Copying file from container to host..."
    ssh "$REMOTE_HOST" "cd $REMOTE_DIR && docker compose cp api:$CONTAINER_OUTPUT ./exports/" 2>&1 | grep -v "^time=" | grep -v "warning" | grep -v "obsolete" || {
        echo "  ⚠️  Failed to copy file from container"
        continue
    }

    # Check if file was created and has data
    FILE_SIZE=$(ssh "$REMOTE_HOST" "wc -l < $HOST_OUTPUT 2>/dev/null || echo 0")

    if [ "$FILE_SIZE" -eq 0 ]; then
        echo "  ⚠️  No data exported for $call_type (0 lines)"
        ssh "$REMOTE_HOST" "rm -f $HOST_OUTPUT $CONTAINER_OUTPUT" 2>/dev/null || true
        continue
    fi

    # Copy back to local
    echo "  Copying back ($FILE_SIZE cases)..."
    scp "$REMOTE_HOST:$HOST_OUTPUT" "$LOCAL_OUTPUT"

    # Clean up remote files
    ssh "$REMOTE_HOST" "cd $REMOTE_DIR && docker compose exec -T api rm -f $CONTAINER_OUTPUT" 2>/dev/null || true
    ssh "$REMOTE_HOST" "rm -f $HOST_OUTPUT" 2>/dev/null || true

    echo "  ✓ Saved to: $LOCAL_OUTPUT ($FILE_SIZE cases)"
    echo ""
done

echo "================================================================"
echo "EXPORT COMPLETE"
echo "================================================================"
echo ""
echo "Exported files:"
for call_type in "${CALL_TYPES[@]}"; do
    LOCAL_OUTPUT="${LOCAL_OUTPUT_DIR}/${call_type}_${TEST_SET_TAG}.jsonl"
    if [ -f "$LOCAL_OUTPUT" ]; then
        LINES=$(wc -l < "$LOCAL_OUTPUT")
        echo "  ✓ $call_type: $LINES cases"
    else
        echo "  ✗ $call_type: not found"
    fi
done
echo ""
echo "Next steps:"
echo "  1. Review exported files in: $LOCAL_OUTPUT_DIR/"
echo "  2. Run self-consistency experiments with:"
echo "     ./scripts/run_test_set_self_consistency.sh"
echo ""