"""Train an experimental helio/non-helio classifier on labeled abstracts.

Training labels (no keyword-classifier positives to avoid circularity):
  Positive: mission-tagged papers + helio-journal papers
  Negative: non-helio-journal papers + zero-keyword papers

Model: TF-IDF (title+abstract) + Logistic Regression
Optimized for high helio recall (>=95%) via threshold tuning.

This is an analyst-facing experiment, not a production pipeline step.

Usage:
    PYTHONPATH=. uv run --extra classify python scripts/train_helio_classifier.py \
        --abstracts data/pipeline-final/abstracts_checkpoint.jsonl \
        --classifications data/pipeline-final/helio_classification.jsonl \
        --sources data/raw/bibcodes/helio_merged.jsonl \
        -o data/pipeline-final/ml_classification.jsonl
"""

import json
import logging
import re
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, precision_recall_curve
from sklearn.model_selection import cross_val_predict, StratifiedKFold

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# --- Label assignment constants ---

MISSION_TAGS = {
    "PSP_FIELDS", "PSP_SWEAP", "SOHO", "Wind", "ACE", "IRIS", "mission_groups",
}

HELIO_JOURNALS = {
    "SoPh", "JGRA", "JGRB", "JGRC", "JGRD", "GeoRL", "AnGeo",
    "SpWea", "JSWSC", "AdSpR", "STP", "EP&S",
}

NON_HELIO_JOURNALS = {
    "Vacuu", "UltSci", "Sentic", "JMatS", "ITMTT", "TDM", "JCrGr",
    "AcMat", "Mate", "PhRvE", "PhRvD", "PhRvC", "NucFu", "NuPhB",
    "JNuM", "JVST", "TSF", "SurSc",
}


def _extract_journal(bibcode: str) -> str:
    journal_part = bibcode[4:].rstrip(".")
    match = re.match(r"^([A-Za-z&.]+)", journal_part)
    return match.group(1).rstrip(".") if match else ""


def build_training_set(abstracts, classifications, source_map):
    """Build high-confidence positive and negative examples.

    Positives: mission-tagged + helio-journal (no keyword-classifier positives).
    Negatives: non-helio-journal + zero-keyword.

    Returns (positives, negatives) as lists of (bibcode, text, label).
    """
    positives = []
    negatives = []

    for bib, info in abstracts.items():
        text = f"{info.get('title', '')} {info.get('abstract', '')}".strip()
        if len(text) < 20:
            continue

        sources = set(source_map.get(bib, []))
        journal = _extract_journal(bib)
        classification = classifications.get(bib, {})

        # --- POSITIVES ---
        if sources & MISSION_TAGS:
            positives.append((bib, text, 1))
            continue

        if journal in HELIO_JOURNALS:
            positives.append((bib, text, 1))
            continue

        # --- NEGATIVES ---
        if journal in NON_HELIO_JOURNALS:
            negatives.append((bib, text, 0))
            continue

        if (classification.get("label") == "non-helio"
                and classification.get("reason") == "no_keywords"):
            negatives.append((bib, text, 0))
            continue

        # Everything else: unlabeled

    return positives, negatives


def find_threshold_for_recall(y_true, y_proba, target_recall=0.95):
    """Find the probability threshold that achieves target helio recall."""
    precision, recall, thresholds = precision_recall_curve(y_true, y_proba)
    # Find the highest threshold where recall >= target
    valid = recall >= target_recall
    if not valid.any():
        logger.warning(f"Cannot achieve {target_recall:.0%} recall, using 0.5")
        return 0.5
    idx = np.where(valid)[0][-1]
    if idx < len(thresholds):
        return float(thresholds[idx])
    return 0.5


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Train helio/non-helio classifier")
    parser.add_argument("--abstracts", type=Path, required=True)
    parser.add_argument("--classifications", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--model-out", type=Path, default=None)
    parser.add_argument("--target-recall", type=float, default=0.95)
    args = parser.parse_args()

    # --- Load data ---
    logger.info("Loading abstracts...")
    abstracts = {}
    with open(args.abstracts) as f:
        for line in f:
            r = json.loads(line)
            abstracts[r["bibcode"]] = r
    logger.info(f"  {len(abstracts):,} abstracts")

    logger.info("Loading keyword classifications...")
    classifications = {}
    with open(args.classifications) as f:
        for line in f:
            r = json.loads(line)
            classifications[r["bibcode"]] = r

    logger.info("Loading source tags...")
    source_map = {}
    with open(args.sources) as f:
        for line in f:
            r = json.loads(line)
            source_map[r["bibcode"]] = r.get("sources", [])

    # --- Build training set ---
    positives, negatives = build_training_set(abstracts, classifications, source_map)
    logger.info(f"Training set: {len(positives):,} positive, {len(negatives):,} negative")

    # Subsample negatives to 2:1 ratio to reduce noise
    rng = np.random.RandomState(42)
    max_neg = len(positives) * 2
    if len(negatives) > max_neg:
        neg_idx = rng.choice(len(negatives), size=max_neg, replace=False)
        negatives = [negatives[i] for i in neg_idx]
        logger.info(f"  Subsampled negatives to {len(negatives):,} (2:1 ratio)")

    labeled = positives + negatives
    logger.info(f"  Final: {len(positives):,} pos + {len(negatives):,} neg = {len(labeled):,}")

    texts = [x[1] for x in labeled]
    labels = np.array([x[2] for x in labeled])

    # --- TF-IDF ---
    logger.info("Fitting TF-IDF...")
    vectorizer = TfidfVectorizer(
        max_features=20_000,
        ngram_range=(1, 2),
        min_df=3,
        max_df=0.95,
        sublinear_tf=True,
    )
    X = vectorizer.fit_transform(texts)
    logger.info(f"  Feature matrix: {X.shape}")

    # --- Cross-validation ---
    logger.info("5-fold cross-validation...")
    clf = LogisticRegression(C=5.0, max_iter=1000, solver="liblinear", class_weight="balanced")
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    y_proba_cv = cross_val_predict(clf, X, labels, cv=cv, method="predict_proba")[:, 1]
    y_pred_default = (y_proba_cv >= 0.5).astype(int)

    print("\n=== Cross-validation (threshold=0.5) ===")
    print(classification_report(labels, y_pred_default, target_names=["non-helio", "helio"]))

    # --- Threshold tuning for target recall ---
    threshold = find_threshold_for_recall(labels, y_proba_cv, target_recall=args.target_recall)
    y_pred_tuned = (y_proba_cv >= threshold).astype(int)

    print(f"=== Tuned threshold={threshold:.3f} (target helio recall={args.target_recall:.0%}) ===")
    print(classification_report(labels, y_pred_tuned, target_names=["non-helio", "helio"]))

    # --- Train final model on all labeled data ---
    logger.info("Training final model...")
    clf.fit(X, labels)

    # Top features
    feature_names = vectorizer.get_feature_names_out()
    coef = clf.coef_[0]

    top_helio = np.argsort(coef)[-20:][::-1]
    top_non = np.argsort(coef)[:20]

    print("Top 20 helio features:")
    for idx in top_helio:
        print(f"  {coef[idx]:+.3f}  {feature_names[idx]}")

    print("\nTop 20 non-helio features:")
    for idx in top_non:
        print(f"  {coef[idx]:+.3f}  {feature_names[idx]}")

    # --- Classify all papers ---
    logger.info(f"\nClassifying all {len(abstracts):,} papers (threshold={threshold:.3f})...")
    all_bibcodes = list(abstracts.keys())
    all_texts = [
        f"{abstracts[b].get('title', '')} {abstracts[b].get('abstract', '')}".strip()
        for b in all_bibcodes
    ]
    X_all = vectorizer.transform(all_texts)
    probas = clf.predict_proba(X_all)[:, 1]

    from collections import Counter
    stats = Counter()

    with open(args.output, "w") as f:
        for bib, prob in zip(all_bibcodes, probas):
            label = "helio" if prob >= threshold else "non-helio"

            if prob >= 0.9 or prob <= 0.1:
                confidence = "high"
            elif prob >= 0.7 or prob <= 0.3:
                confidence = "medium"
            else:
                confidence = "low"

            result = {
                "bibcode": bib,
                "label": label,
                "confidence": confidence,
                "probability": round(float(prob), 4),
                "title": abstracts[bib].get("title", ""),
            }
            f.write(json.dumps(result) + "\n")
            stats[label] += 1

    logger.info(f"\nML classification results:")
    for label, count in stats.most_common():
        logger.info(f"  {label}: {count:,} ({100 * count / len(all_bibcodes):.1f}%)")
    logger.info(f"Written to: {args.output}")

    # --- Save model ---
    if args.model_out:
        import pickle
        with open(args.model_out, "wb") as f:
            pickle.dump({
                "vectorizer": vectorizer,
                "classifier": clf,
                "threshold": threshold,
            }, f)
        logger.info(f"Model saved to: {args.model_out}")


if __name__ == "__main__":
    main()
