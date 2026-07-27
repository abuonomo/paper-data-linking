#!/usr/bin/env python3
"""Run find_quotes_enrich on a real fixture PDF, highlight the located quotes,
and (optionally) open the result in Skim for a manual quality smoke-test.

Each located quote gets a highlight annotation over every coordinate region,
with the quote text + instrument/parameter + match method attached as the
annotation note (visible on hover/click in Skim). Un-located quotes are listed
in the console so you can see what was missed.

Usage:
    uv run python experiments/quote_search_bench/highlight_pdf.py            # richest fixture
    uv run python experiments/quote_search_bench/highlight_pdf.py --bibcode 2021ApJ...  --open
    uv run python experiments/quote_search_bench/highlight_pdf.py --pdf /path.pdf --quotes-file q.json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import fitz

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from paper_data_linking.processing.pdf_text_search import PDFTextSearcher  # noqa: E402

# distinct highlight colors per match method so quality is visually legible
METHOD_COLORS = {
    'exact_ci': (0.55, 0.9, 0.55),            # green  — most trustworthy
    'punctuation_fallback': (0.6, 0.85, 1.0),  # blue
    'ellipsis_chain': (0.8, 0.7, 1.0),         # purple
    'anchor_gapped': (1.0, 0.85, 0.4),         # orange
    'hyphen_join_variant': (1.0, 0.85, 0.4),
    'word_fragment_join': (1.0, 0.85, 0.4),
    'cross_page_chain': (1.0, 0.75, 0.8),      # pink
    'fuzzy_match': (1.0, 0.6, 0.4),            # red-ish — fuzzy, inspect closely
}


def extract_text_under(doc, location) -> str:
    """Text actually under the returned box(es) — the round-trip evidence."""
    parts = []
    for r in location.get('coordinate_regions') or []:
        page = doc.load_page(r['page'] - 1)
        parts.append(page.get_textbox(fitz.Rect(r['x0'], r['y0'], r['x1'], r['y1'])))
    return ' '.join(t.strip() for t in parts if t.strip())


def pick_default_entry(index):
    return max(index, key=lambda e: e.get('count', 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--index', type=Path,
                    default=REPO_ROOT / 'experiments/quote_search_bench/fixtures/quotes/index.json')
    ap.add_argument('--bibcode', type=str, default=None)
    ap.add_argument('--pdf', type=Path, default=None)
    ap.add_argument('--quotes-file', type=Path, default=None)
    ap.add_argument('--out', type=Path, default=None)
    ap.add_argument('--open', action='store_true', help='open the result in Skim')
    args = ap.parse_args()

    if args.pdf and args.quotes_file:
        pdf_path, quotes_file, bib = args.pdf, args.quotes_file, args.pdf.stem
    else:
        index = json.loads(args.index.read_text(encoding='utf-8'))
        if args.bibcode:
            entry = next(e for e in index if e.get('bibcode') == args.bibcode)
        else:
            entry = pick_default_entry(index)
        pdf_path, quotes_file, bib = Path(entry['pdf']), Path(entry['quotes_file']), entry.get('bibcode')

    quotes = json.loads(quotes_file.read_text(encoding='utf-8'))
    quote_objs = [{k: v for k, v in q.items() if k in ('quote', 'instrument', 'parameter')} for q in quotes]

    searcher = PDFTextSearcher(str(pdf_path), fast_index=True)
    results = searcher.find_quotes_enrich(quote_objs, debug=True)
    searcher.close()

    doc = fitz.open(str(pdf_path))
    found = missed = 0
    method_counts = {}
    legend = []   # numbered located quotes
    misses = []   # quotes with no box
    n = 0
    for res in results:
        loc = res.get('location')
        if not loc:
            missed += 1
            misses.append(res.get('quote', ''))
            continue
        found += 1
        n += 1
        method = (res.get('debug') or {}).get('method') or 'unknown'
        method_counts[method] = method_counts.get(method, 0) + 1
        color = METHOD_COLORS.get(method, (1.0, 1.0, 0.4))
        # text actually under the returned box(es) — the round-trip check the reviewer wants
        under = extract_text_under(doc, loc)
        note = (f"#{n} [{method}] {res.get('instrument','')} / {res.get('parameter','')}\n\n"
                f"QUOTE: {res.get('quote','')}\n\nUNDER BOX: {under}")
        regions = loc.get('coordinate_regions') or []
        for j, r in enumerate(regions):
            page = doc.load_page(r['page'] - 1)
            rect = fitz.Rect(r['x0'], r['y0'], r['x1'], r['y1'])
            annot = page.add_highlight_annot(rect)
            annot.set_colors(stroke=color)
            annot.set_info(content=note)
            annot.update()
            if j == 0:  # number label just left of the first region
                lbl = fitz.Rect(rect.x0 - 16, rect.y0 - 2, rect.x0 - 1, rect.y0 + 11)
                t = page.add_freetext_annot(lbl, f"{n}", fontsize=8,
                                            text_color=(1, 0, 0), fill_color=(1, 1, 0.6))
                t.update()
        legend.append({
            'n': n, 'page': loc.get('page_number'), 'method': method,
            'instrument': res.get('instrument', ''), 'parameter': res.get('parameter', ''),
            'quote': res.get('quote', ''), 'under': under,
        })

    out = args.out or Path(f"/tmp/highlighted_{bib or pdf_path.stem}.pdf")
    doc.save(str(out))
    doc.close()

    # sidecar legend: number -> target quote + text under the box, so the highlights
    # can be verified without hovering every annotation.
    sidecar = out.with_suffix('.legend.txt')
    lines = [f"HIGHLIGHT LEGEND for {out.name}", f"bibcode={bib}  pdf={pdf_path.name}",
             "color: green=exact blue=punctuation purple=ellipsis orange=anchor/hyphen "
             "pink=cross-page red=fuzzy(inspect)",
             "compare QUOTE (what we searched for) vs UNDER-BOX (what the highlight covers)",
             "=" * 80]
    for e in legend:
        lines.append(f"\n#{e['n']}  p{e['page']}  [{e['method']}]  "
                     f"{e['instrument']} / {e['parameter']}")
        lines.append(f"  QUOTE   : {e['quote']}")
        lines.append(f"  UNDERBOX: {e['under']}")
    if misses:
        lines.append("\n" + "=" * 80)
        lines.append(f"MISSED (no highlight): {len(misses)}")
        for q in misses:
            lines.append(f"  - {q}")
    sidecar.write_text("\n".join(lines), encoding='utf-8')

    total = found + missed
    print(f"PDF: {pdf_path.name}  bibcode={bib}")
    print(f"quotes: {total}  located: {found} ({found/total*100:.0f}%)  missed: {missed}")
    print("by method: " + ", ".join(f"{m}={c}" for m, c in sorted(method_counts.items())))
    print(f"\nWrote {out}\nWrote {sidecar}")
    print("In Skim: View > Contents Pane (⌥⌘2) shows all quotes in the Notes list; "
          "each highlight is numbered to match the legend file.")
    if args.open:
        subprocess.run(['open', '-a', 'Skim', str(out)], check=False)
        subprocess.run(['open', '-a', 'TextEdit', str(sidecar)], check=False)


if __name__ == '__main__':
    main()
