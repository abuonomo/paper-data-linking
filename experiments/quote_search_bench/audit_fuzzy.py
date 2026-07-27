#!/usr/bin/env python3
"""Fuzzy-fallback validation loop: fast proxy calibrated by (occasional) vision.

Vision does not scale to the corpus, so it is used here only as an OFFLINE ORACLE
to (a) measure the TRUE precision of the fast rapidfuzz fallback on a bounded
sample and (b) judge whether the distinctive-token guard removes WRONG boxes
(good) or RIGHT ones (recall loss). The production path stays purely algorithmic.

For each fixture quote that the deterministic pass misses, it runs the fuzzy
locate both WITH and WITHOUT the distinctive-token guard and classifies:
  - KEPT     : guard keeps the box (both return it)
  - REJECTED : guard drops a box the unguarded matcher returned  <- the ones to inspect
It renders a boxed crop + records quote/under-box text for each, and merges any
cached human/vision verdicts from gold_labels.json to print a precision tally.

    uv run python experiments/quote_search_bench/audit_fuzzy.py --crops /tmp/fuzzy_audit
    # then label crops in gold_labels.json as {"<key>": "correct"|"wrong"} and re-run
"""

import argparse
import json
import sys
from pathlib import Path

import fitz

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from paper_data_linking.processing.pdf_text_search import PDFTextSearcher, _normalize_text  # noqa: E402

GOLD = Path(__file__).resolve().parent / 'gold_labels.json'


def _crop(doc, regions, out_png):
    p0 = regions[0]['page']
    pr = [r for r in regions if r['page'] == p0]
    page = doc.load_page(p0 - 1)
    for r in pr:
        page.draw_rect(fitz.Rect(r['x0'], r['y0'], r['x1'], r['y1']), color=(1, 0, 0), width=1.2)
    x0 = min(r['x0'] for r in pr); y0 = min(r['y0'] for r in pr)
    x1 = max(r['x1'] for r in pr); y1 = max(r['y1'] for r in pr)
    clip = fitz.Rect(max(0, x0 - 30), max(0, y0 - 25), x1 + 30, y1 + 25)
    page.get_pixmap(clip=clip, dpi=220).save(str(out_png))


def _under(doc, regions):
    parts = []
    for r in regions:
        page = doc.load_page(r['page'] - 1)
        parts.append(page.get_textbox(fitz.Rect(r['x0'], r['y0'], r['x1'], r['y1'])).strip())
    return ' '.join(p for p in parts if p)


def _regions_to_cr(regions):
    cr = []
    for pg, rects in regions.items():
        for r in rects:
            cr.append({'page': pg + 1, 'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1})
    return cr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--index', type=Path,
                    default=REPO_ROOT / 'experiments/quote_search_bench/fixtures/quotes/index.json')
    ap.add_argument('--crops', type=Path, default=Path('/tmp/fuzzy_audit'))
    ap.add_argument('--limit', type=int, default=None)
    args = ap.parse_args()

    index = json.loads(args.index.read_text(encoding='utf-8'))
    if args.limit:
        index = index[:args.limit]
    args.crops.mkdir(parents=True, exist_ok=True)
    for f in args.crops.glob('*.png'):
        f.unlink()
    gold = json.loads(GOLD.read_text()) if GOLD.exists() else {}

    manifest = []
    counts = {'KEPT': 0, 'REJECTED': 0}
    for entry in index:
        quotes = json.loads(Path(entry['quotes_file']).read_text())
        qobjs = [{k: v for k, v in q.items() if k in ('quote', 'instrument', 'parameter')} for q in quotes]
        searcher = PDFTextSearcher(entry['pdf'], fast_index=True)
        det = searcher.find_quotes_original(qobjs, skip_expensive_crosspage=True)
        doc = fitz.open(entry['pdf'])
        for q, dres in zip(quotes, det):
            if dres.get('location'):
                continue  # deterministic already found it; fuzzy not involved
            nq = _normalize_text(q['quote'])
            if not nq:
                continue
            raw = searcher._fuzzy_locate_rapid(nq, apply_distinctive_guard=False)
            if not raw:
                continue
            guarded = searcher._fuzzy_locate_rapid(nq, apply_distinctive_guard=True)
            status = 'KEPT' if guarded else 'REJECTED'
            counts[status] += 1
            cr = _regions_to_cr(raw)
            key = f"{entry.get('bibcode')}|{q['quote'][:80]}"
            png = args.crops / f"{status}_{len(manifest):03d}.png"
            _crop(doc, cr, png)
            manifest.append({
                'key': key, 'status': status, 'png': str(png),
                'quote': q['quote'], 'under': _under(doc, cr),
                'verdict': gold.get(key, '?'),
            })
        doc.close()
        searcher.close()

    (args.crops / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')

    # precision tally from cached verdicts (if any labeled)
    def tally(items):
        labeled = [m for m in items if m['verdict'] in ('correct', 'wrong')]
        good = sum(1 for m in labeled if m['verdict'] == 'correct')
        return good, len(labeled)

    kept = [m for m in manifest if m['status'] == 'KEPT']
    rej = [m for m in manifest if m['status'] == 'REJECTED']
    kg, kn = tally(kept); rg, rn = tally(rej)
    print(f"fuzzy boxes: KEPT={counts['KEPT']}  REJECTED-by-guard={counts['REJECTED']}")
    print(f"crops + manifest -> {args.crops}")
    if kn:
        print(f"  KEPT   labeled precision: {kg}/{kn} = {kg/kn:.2f}")
    if rn:
        print(f"  REJECTED were actually correct (recall lost): {rg}/{rn} = {rg/rn:.2f} "
              f"(want this LOW — means guard removed wrong boxes)")
    if not (kn or rn):
        print("  (no verdicts yet — label gold_labels.json with the crop keys, then re-run)")


if __name__ == '__main__':
    main()
