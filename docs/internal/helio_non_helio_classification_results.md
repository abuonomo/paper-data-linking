# Helio vs Non-Helio Classification Results

This note records the current results from the experimental helio/non-helio
filtering workflow in [`scripts/classify_helio.py`](../scripts/classify_helio.py)
and [`scripts/train_helio_classifier.py`](../scripts/train_helio_classifier.py).

## Inputs

- Abstract corpus: `90,632` papers from `data/pipeline-final/abstracts_checkpoint.jsonl`
- Rule-based labels: `data/pipeline-final/helio_classification.jsonl`
- Source provenance: `data/raw/bibcodes/helio_merged.jsonl`

## Training set

The ML script builds a high-confidence labeled set using heuristics:

- Positive: mission-tagged papers and helio-journal papers
- Negative: non-helio-journal papers and papers with no helio keywords

Observed counts from the current run:

- Positive examples: `11,238`
- Negative examples before downsampling: `32,648`
- Negative examples after downsampling: `22,476`
- Final labeled training set: `33,714`

## Cross-validation metrics

5-fold cross-validation on the labeled set:

```text
non-helio: precision 0.98, recall 0.98, f1 0.98
helio:     precision 0.95, recall 0.95, f1 0.95
accuracy:  0.97
```

The tuned threshold for the target helio recall of `95%` landed at `0.499`,
effectively the same as the default `0.5`.

## Full-corpus predictions

Predictions over all `90,632` abstracts:

- `61,748` non-helio (`68.1%`)
- `28,884` helio (`31.9%`)

Confidence breakdown:

- High confidence: `67,464`
- Medium confidence: `15,368`
- Low confidence: `7,800`

Per-label confidence:

- Helio, high confidence: `20,962`
- Helio, medium confidence: `4,612`
- Helio, low confidence: `3,310`
- Non-helio, high confidence: `46,502`
- Non-helio, medium confidence: `10,756`
- Non-helio, low confidence: `4,490`

## How many are "fully helio"?

There is no gold-standard label set here, so "fully helio" has to be treated
as an estimate rather than a measured fact.

Useful working numbers:

- Conservative estimate of clearly helio papers: about `20,962`
  This is the `helio + high confidence` bucket.
- Broader estimate of likely helio papers: about `28,884`
  This is the full set predicted as helio by the current model.

For planning purposes, a reasonable interpretation is:

- Around `21k` papers look clearly heliophysics-related.
- Another `~7.9k` papers (`28,884 - 20,962`) are helio according to the model
  but are not high-confidence and should be treated as review candidates.

## Caveats

- The training labels are heuristic, not hand-labeled gold data.
- Cross-validation scores are therefore optimistic with respect to real-world
  filtering quality.
- Some learned features look sensible (`solar`, `coronal`, `magnetosphere`),
  but a few look suspicious or dataset-specific (`climate`, `radar`).
- This workflow is suitable for triage and narrowing the corpus, not for
  irreversible filtering without at least some manual review.

## Artifacts from the latest run

- Predictions: `/tmp/helio_ml_classification_smoketest.jsonl`
- Model: `/tmp/helio_model_smoketest.pkl`
