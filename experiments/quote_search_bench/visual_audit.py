#!/usr/bin/env python3
"""Render located quote boxes onto page images so accuracy can be eyeballed.

Consumes a bench_report.py `--out` JSON (which carries per-quote `location`,
`ok`, `method`, `ambiguous`). For each selected quote it draws the returned
rectangle(s) on the page and writes a PNG, so the automatic round-trip metric
can be calibrated against real eyes.

Selection (default): every FAILURE (predicted but round-trip said wrong) plus a
capped random-free sample of hits. With --compare-out it also renders every
CROSS-METHOD DISAGREEMENT (box present in one method, absent/different page in
the other) — the highest-value cases to inspect.

Usage:
    uv run python experiments/quote_search_bench/visual_audit.py \
        --report /tmp/bench_enrich.json --out-dir /tmp/audit_enrich --max 60
"""

import argparse
import json
from pathlib import Path

import fitz


def _draw(pdf_path: str, location: dict, out_png: Path, label: str):
    doc = fitz.open(pdf_path)
    regions = location.get('coordinate_regions') or []
    pages = sorted({r['page'] for r in regions}) or [location.get('page_number', 1)]
    # render the first page the match touches (cross-page: first page)
    page = doc.load_page(pages[0] - 1)
    for r in regions:
        if r['page'] != pages[0]:
            continue
        rect = fitz.Rect(r['x0'], r['y0'], r['x1'], r['y1'])
        page.draw_rect(rect, color=(1, 0, 0), width=1.5)
    pix = page.get_pixmap(dpi=110)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(out_png))
    doc.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report', type=Path, required=True, help='bench_report.py --out JSON')
    ap.add_argument('--out-dir', type=Path, required=True)
    ap.add_argument('--max', type=int, default=60, help='cap total PNGs rendered')
    ap.add_argument('--sample-hits', type=int, default=15, help='how many correct hits to spot-check')
    args = ap.parse_args()

    payload = json.loads(args.report.read_text(encoding='utf-8'))
    per_pdf = payload.get('per_pdf', [])

    failures, hits = [], []
    for r in per_pdf:
        pdf = r['pdf']
        for i, p in enumerate(r['per']):
            if not p['predicted'] or not p.get('location'):
                continue
            item = (pdf, i, p)
            (hits if p['ok'] else failures).append(item)

    rendered = 0
    manifest = []
    # failures first — these are what you most want to see
    for group, tag, cap in ((failures, 'fail', args.max),
                            (hits, 'hit', args.sample_hits)):
        step = max(1, len(group) // cap) if cap else 1
        for (pdf, i, p) in group[::step]:
            if rendered >= args.max:
                break
            name = f"{tag}_{Path(pdf).stem[:12]}_{i}_{p.get('method') or 'none'}.png"
            out_png = args.out_dir / name
            try:
                _draw(pdf, p['location'], out_png, tag)
            except Exception as e:  # noqa: BLE001
                print(f"skip {name}: {e}")
                continue
            manifest.append({
                'png': str(out_png), 'tag': tag, 'method': p.get('method'),
                'ambiguous': p.get('ambiguous'), 'quote': p['quote'][:160],
            })
            rendered += 1

    (args.out_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f"Rendered {rendered} PNGs -> {args.out_dir} "
          f"({len(failures)} failures, {len(hits)} hits available)")


if __name__ == '__main__':
    main()
