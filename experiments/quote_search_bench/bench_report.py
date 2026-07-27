#!/usr/bin/env python3
"""Speed + accuracy report for PDFTextSearcher over the bench fixtures.

Extends run_quote_bench.py with the numbers the optimization work is gated on:

  * found-rate vs round-trip PRECISION (text under the returned box actually
    recovers the quote) — a fast-but-wrong fallback can't hide behind found-rate.
  * per-METHOD breakdown (exact_ci / punctuation_fallback / anchor_gapped /
    fitz_anchor_chain / ...): count, precision, and per-quote timing.
  * index-build vs per-quote (cascade) time split, and per-quote p50/p95.
  * duplicate-occurrence guard: quotes whose normalized text occurs >1x in the
    document are reported separately (round-trip can't disambiguate occurrence).

Reuses the verifier (parts_in_order / extract_text_for_location) from
run_quote_bench so "correct" means the same thing here as there.

Usage:
    uv run python experiments/quote_search_bench/bench_report.py \
        --method original --out /tmp/bench_original.json
    # compare two methods on the same fixtures:
    uv run python experiments/quote_search_bench/bench_report.py \
        --method enrich --compare original
"""

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import fitz

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCH_DIR = Path(__file__).resolve().parent
for _p in (str(REPO_ROOT), str(BENCH_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from paper_data_linking.processing.pdf_text_search import PDFTextSearcher, _normalize_text  # noqa: E402
from run_quote_bench import parts_in_order, extract_text_for_location  # noqa: E402


def _pct(num, den):
    return (num / den) if den else 0.0


def _run_method(searcher, quote_objects, method):
    fn = {
        'original': 'find_quotes_original',
        'ir': 'find_quotes_ir',
        'legacy': 'find_quotes',
        'enrich': 'find_quotes_enrich',
    }[method]
    if not hasattr(searcher, fn):
        raise SystemExit(f"PDFTextSearcher has no method '{fn}' (method={method})")
    return getattr(searcher, fn)(quote_objects, debug=True)


def eval_pdf(pdf_path: Path, quotes_file: Path, method: str) -> dict:
    quotes = json.loads(quotes_file.read_text(encoding='utf-8'))
    quote_objects = [
        {k: v for k, v in q.items() if k in ('quote', 'instrument', 'parameter')}
        for q in quotes
    ]

    t_idx0 = time.perf_counter()
    searcher = PDFTextSearcher(str(pdf_path), fast_index=(method == 'enrich'))
    index_ms = (time.perf_counter() - t_idx0) * 1000.0

    results = _run_method(searcher, quote_objects, method)
    norm_doc = searcher.norm_text_lower
    doc_len = len(norm_doc)
    searcher.close()

    per = []
    for q, res in zip(quotes, results):
        exp = bool(q.get('expected', True))
        loc = res.get('location')
        pred = bool(loc)
        dbg = res.get('debug') or {}
        method_hit = dbg.get('method')  # which stage produced the box (None if miss)
        timing_ms = dbg.get('timing_ms', 0.0)

        ok = False
        if pred:
            extracted = extract_text_for_location(pdf_path, loc)
            ok = parts_in_order(extracted, q['quote'])

        # duplicate-occurrence guard: does the normalized quote appear >1x?
        nq = _normalize_text(q['quote']).lower()
        occ = norm_doc.count(nq) if nq else 0
        ambiguous = occ > 1

        per.append({
            'bibcode': None,
            'quote': q['quote'],
            'parameter': q.get('parameter'),
            'expected': exp,
            'predicted': pred,
            'ok': ok,
            'method': method_hit,
            'timing_ms': timing_ms,
            'ambiguous': ambiguous,
            'occurrences': occ,
            'location': loc,
        })

    return {
        'pdf': str(pdf_path),
        'count': len(quotes),
        'index_ms': round(index_ms, 2),
        'doc_len': doc_len,
        'per': per,
    }


def aggregate(pdf_results, method):
    per_all = [p for r in pdf_results for p in r['per']]
    n = len(per_all)
    found = [p for p in per_all if p['predicted']]
    correct = [p for p in found if p['ok']]
    ambiguous = [p for p in per_all if p['ambiguous']]

    # per-method table
    by_method = defaultdict(lambda: {'n': 0, 'ok': 0, 'timings': []})
    for p in found:
        m = p['method'] or 'unknown'
        by_method[m]['n'] += 1
        by_method[m]['ok'] += 1 if p['ok'] else 0
        by_method[m]['timings'].append(p['timing_ms'])
    # misses (location=None) — their timing is the full cascade cost
    miss_timings = [p['timing_ms'] for p in per_all if not p['predicted']]

    def tstats(ts):
        if not ts:
            return {'p50': 0.0, 'p95': 0.0, 'mean': 0.0, 'max': 0.0}
        s = sorted(ts)
        return {
            'p50': round(statistics.median(s), 2),
            'p95': round(s[min(len(s) - 1, int(0.95 * len(s)))], 2),
            'mean': round(statistics.fmean(s), 2),
            'max': round(max(s), 2),
        }

    all_quote_timings = [p['timing_ms'] for p in per_all]
    index_ms = [r['index_ms'] for r in pdf_results]

    return {
        'method': method,
        'pdfs': len(pdf_results),
        'quotes': n,
        'found': len(found),
        'found_rate': round(_pct(len(found), n), 3),
        'correct': len(correct),
        'precision': round(_pct(len(correct), len(found)), 3),   # of returned boxes, how many right
        'recall': round(_pct(len(correct), n), 3),               # of all quotes, how many correctly located
        'ambiguous': len(ambiguous),
        'per_quote_timing_ms': tstats(all_quote_timings),
        'miss_timing_ms': tstats(miss_timings),
        'index_build_ms': {
            'total': round(sum(index_ms), 1),
            'mean_per_pdf': round(_pct(sum(index_ms), len(index_ms)), 2),
        },
        'cascade_total_ms': round(sum(all_quote_timings), 1),
        'by_method': {
            m: {
                'n': v['n'],
                'precision': round(_pct(v['ok'], v['n']), 3),
                'timing_ms': tstats(v['timings']),
            } for m, v in sorted(by_method.items())
        },
    }


def print_summary(agg):
    print(f"\n=== {agg['method']} : {agg['pdfs']} PDFs / {agg['quotes']} quotes ===")
    print(f"found-rate {agg['found_rate']:.3f} ({agg['found']}/{agg['quotes']})  "
          f"precision {agg['precision']:.3f} ({agg['correct']}/{agg['found']})  "
          f"recall {agg['recall']:.3f}  ambiguous {agg['ambiguous']}")
    it = agg['index_build_ms']
    print(f"index build: {it['total']}ms total, {it['mean_per_pdf']}ms/pdf   "
          f"cascade: {agg['cascade_total_ms']}ms total")
    pq, mt = agg['per_quote_timing_ms'], agg['miss_timing_ms']
    print(f"per-quote ms  p50={pq['p50']} p95={pq['p95']} mean={pq['mean']} max={pq['max']}")
    print(f"miss     ms  p50={mt['p50']} p95={mt['p95']} mean={mt['mean']} max={mt['max']}")
    print("by method (of returned boxes):")
    for m, v in agg['by_method'].items():
        t = v['timing_ms']
        print(f"  {m:28s} n={v['n']:4d}  precision={v['precision']:.3f}  "
              f"ms p50={t['p50']} p95={t['p95']} max={t['max']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--index', type=Path,
                    default=REPO_ROOT / 'experiments/quote_search_bench/fixtures/quotes/index.json')
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--method', choices=['original', 'ir', 'legacy', 'enrich'], default='original')
    ap.add_argument('--compare', choices=['original', 'ir', 'legacy', 'enrich'], default=None,
                    help='Also run this method and diff found-rate/precision/p95')
    ap.add_argument('--out', type=Path, default=None, help='Write full per-quote report JSON')
    args = ap.parse_args()

    index = json.loads(args.index.read_text(encoding='utf-8'))
    if args.limit:
        index = index[:args.limit]

    def run(method):
        results = []
        for entry in index:
            r = eval_pdf(Path(entry['pdf']), Path(entry['quotes_file']), method)
            for p in r['per']:
                p['bibcode'] = entry.get('bibcode')
            results.append(r)
        return results

    print(f"Evaluating {len(index)} PDFs (method={args.method}) ...")
    results = run(args.method)
    agg = aggregate(results, args.method)
    print_summary(agg)

    out_payload = {'primary': agg, 'per_pdf': results}

    if args.compare:
        print(f"\nEvaluating {len(index)} PDFs (method={args.compare}) ...")
        cmp_results = run(args.compare)
        cmp_agg = aggregate(cmp_results, args.compare)
        print_summary(cmp_agg)
        print(f"\n=== DIFF {args.method} vs {args.compare} ===")
        print(f"found-rate {agg['found_rate']:.3f} -> {cmp_agg['found_rate']:.3f}")
        print(f"precision  {agg['precision']:.3f} -> {cmp_agg['precision']:.3f}")
        print(f"recall     {agg['recall']:.3f} -> {cmp_agg['recall']:.3f}")
        print(f"per-quote p95 {agg['per_quote_timing_ms']['p95']} -> "
              f"{cmp_agg['per_quote_timing_ms']['p95']}")
        out_payload['compare'] = cmp_agg

    if args.out:
        args.out.write_text(json.dumps(out_payload, indent=2), encoding='utf-8')
        print(f"\nWrote report -> {args.out}")


if __name__ == '__main__':
    main()
