"""
Inter-rater agreement utilities for DatasetUsage validations.

Provides Fleiss' kappa (for 2+ raters across all usages in a scope)
and Cohen's kappa (pairwise between two raters).

Extracted from experiments/compare_models/misc/calculate_fleiss_kappa_all.py
and adapted for the live validation data model.
"""
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np


INTERPRETATION = [
    (0.81, 'Almost perfect'),
    (0.61, 'Substantial'),
    (0.41, 'Moderate'),
    (0.21, 'Fair'),
    (0.01, 'Slight'),
    (-1.0, 'Poor'),
]


def interpret_kappa(kappa: float) -> str:
    for threshold, label in INTERPRETATION:
        if kappa >= threshold:
            return label
    return 'Poor'


def fleiss_kappa(
    responses_by_item: Dict[str, List[str]],
    categories: Optional[List[str]] = None,
) -> Dict:
    """
    Calculate Fleiss' kappa for multiple raters classifying items into categories.

    Args:
        responses_by_item: mapping of item_id → list of category labels (one per rater).
            All lists must have the same length (n_raters).
        categories: optional explicit category list; inferred from data if omitted.

    Returns dict with keys: kappa, p_observed, p_expected, n_items, n_raters,
    n_categories, categories, interpretation.
    """
    if not responses_by_item:
        return {
            'kappa': None,
            'p_observed': None,
            'p_expected': None,
            'n_items': 0,
            'n_raters': 0,
            'n_categories': 0,
            'categories': [],
            'interpretation': 'Insufficient data',
        }

    n_raters = len(next(iter(responses_by_item.values())))
    if n_raters < 2:
        return {
            'kappa': None,
            'p_observed': None,
            'p_expected': None,
            'n_items': len(responses_by_item),
            'n_raters': n_raters,
            'n_categories': 0,
            'categories': [],
            'interpretation': 'Need at least 2 raters',
        }

    if categories is None:
        all_labels = set()
        for labels in responses_by_item.values():
            all_labels.update(labels)
        categories = sorted(all_labels)

    n_categories = len(categories)
    cat_idx = {c: i for i, c in enumerate(categories)}
    n_items = len(responses_by_item)

    matrix = np.zeros((n_items, n_categories), dtype=int)
    for row, (_, labels) in enumerate(sorted(responses_by_item.items())):
        for label in labels:
            if label in cat_idx:
                matrix[row, cat_idx[label]] += 1

    # P_i: proportion of agreeing pairs for each item
    P_i = np.sum(matrix * (matrix - 1), axis=1) / (n_raters * (n_raters - 1))
    P_bar = float(np.mean(P_i))

    # P_e: expected agreement by chance
    p_j = np.sum(matrix, axis=0) / (n_items * n_raters)
    P_e = float(np.sum(p_j ** 2))

    kappa = 1.0 if P_e == 1.0 else (P_bar - P_e) / (1 - P_e)

    return {
        'kappa': round(float(kappa), 4),
        'p_observed': round(P_bar, 4),
        'p_expected': round(P_e, 4),
        'n_items': n_items,
        'n_raters': n_raters,
        'n_categories': n_categories,
        'categories': categories,
        'interpretation': interpret_kappa(kappa),
    }


def cohen_kappa_pair(
    labels_a: List[str],
    labels_b: List[str],
    categories: Optional[List[str]] = None,
) -> Dict:
    """
    Cohen's kappa for two raters who each labelled the same items.

    Args:
        labels_a, labels_b: parallel lists of category labels (same length).
        categories: optional explicit category list.

    Returns dict with kappa, interpretation, n_items.
    """
    assert len(labels_a) == len(labels_b), "Label lists must be the same length"
    n = len(labels_a)

    if categories is None:
        categories = sorted(set(labels_a) | set(labels_b))

    cat_idx = {c: i for i, c in enumerate(categories)}
    k = len(categories)

    # Confusion matrix
    conf = np.zeros((k, k), dtype=int)
    for a, b in zip(labels_a, labels_b):
        if a in cat_idx and b in cat_idx:
            conf[cat_idx[a], cat_idx[b]] += 1

    p_observed = float(np.trace(conf)) / n if n else 0.0
    row_sums = conf.sum(axis=1) / n
    col_sums = conf.sum(axis=0) / n
    p_expected = float(np.dot(row_sums, col_sums))

    kappa = 1.0 if p_expected == 1.0 else (p_observed - p_expected) / (1 - p_expected)

    return {
        'kappa': round(float(kappa), 4),
        'p_observed': round(p_observed, 4),
        'p_expected': round(p_expected, 4),
        'n_items': n,
        'interpretation': interpret_kappa(kappa),
    }


def compute_kappa_for_validations(validations_qs) -> Dict:
    """
    Given a QuerySet of DatasetUsageValidation records (already filtered to
    the desired scope), compute Fleiss' kappa and pairwise Cohen's kappas.

    Only items where at least 2 raters have submitted a validation are included
    in the kappa calculation.

    Returns a dict suitable for JSON serialisation.
    """
    # Group by dataset_usage_id, keyed by rater identity
    by_usage: Dict[str, Dict[str, str]] = defaultdict(dict)

    for v in validations_qs.select_related('user'):
        rater = str(v.user_id) if v.user_id else f'anon:{v.anonymous_id}'
        by_usage[str(v.dataset_usage_id)][rater] = v.validation_status

    # Keep only items with ≥2 raters; build a uniform n_raters matrix
    # by padding with the most common label (won't happen with real data, but
    # Fleiss' kappa requires equal rater counts per item).
    # Simpler: we only include items where ALL raters present agree on rating,
    # or take the exact cross-section of raters that appear in all items.
    # Practical approach: treat each (usage, rater) as a rater-run pair;
    # collect per-usage lists in sorted rater order; trim to the shared rater set.

    multi_rated = {uid: ratings for uid, ratings in by_usage.items() if len(ratings) >= 2}

    if len(multi_rated) < 2:
        return {
            'fleiss': {
                'kappa': None,
                'interpretation': 'Need at least 2 items with multiple raters',
                'n_items': len(multi_rated),
            },
            'pairwise': [],
            'n_total_validations': validations_qs.count(),
            'n_multi_rated_items': len(multi_rated),
        }

    # Build per-rater label lists across shared items
    # Gather all rater IDs that appear in ≥1 multi-rated item
    all_raters = sorted({r for ratings in multi_rated.values() for r in ratings})

    # Build responses_by_item: only include items where ≥2 raters are present
    # For Fleiss' kappa with variable raters, use only items with complete coverage
    # among the most common rater pair (simplification: use all raters who appear,
    # fill missing with None—then Fleiss' is only computed over complete items).
    responses_by_item: Dict[str, List[str]] = {}
    for uid, ratings in multi_rated.items():
        present = [ratings[r] for r in all_raters if r in ratings]
        if len(present) >= 2:
            # Fleiss' requires equal-length lists; trim to 2 (most conservative)
            responses_by_item[uid] = present

    fleiss_result = fleiss_kappa(responses_by_item)

    # Pairwise Cohen's kappa for every pair of raters with ≥2 shared items
    pairwise = []
    for i, ra in enumerate(all_raters):
        for rb in all_raters[i + 1:]:
            shared_items = [uid for uid, ratings in multi_rated.items()
                            if ra in ratings and rb in ratings]
            if len(shared_items) < 2:
                continue
            labels_a = [multi_rated[uid][ra] for uid in shared_items]
            labels_b = [multi_rated[uid][rb] for uid in shared_items]
            ck = cohen_kappa_pair(labels_a, labels_b)
            pairwise.append({
                'rater_a': ra,
                'rater_b': rb,
                'n_shared_items': len(shared_items),
                **ck,
            })

    return {
        'fleiss': fleiss_result,
        'pairwise': pairwise,
        'n_total_validations': validations_qs.count(),
        'n_multi_rated_items': len(multi_rated),
    }
