#!/bin/bash
set -e
TAG=test_set_helio_v2_2026_04_06
OUT=inputs/test_set
mkdir -p "$OUT"
for ct in instrument_validation wavelength_normalization physobs_normalization \
          mission_selection instrument_selection detector_normalization \
          time_normalization cadence_normalization mission_identification; do
    uv run python api/manage.py export_llm_calls \
        --call-type "$ct" --require-render-context \
        --paper-tags "$TAG" --output "$OUT/${ct}_${TAG}.jsonl"
    echo "$ct: $(wc -l < $OUT/${ct}_${TAG}.jsonl)"
done
