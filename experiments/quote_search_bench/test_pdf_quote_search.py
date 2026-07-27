#!/usr/bin/env python3
"""
Quick harness to evaluate PDFTextSearcher on synthetic or real PDFs.

Usage:
  python scripts/test_pdf_quote_search.py \
      [--pdf <path>] [--quotes <quotes.json|txt>] [--assume-positive] \
      [--highlight] [--compare] [-v] [--out-json results.json]

If no --pdf is provided, a synthetic PDF is generated in ./sample_quote_test.pdf
covering exact, normalized, hyphenation, ellipsis, and cross-page cases.

Quotes input:
  - If --quotes is omitted, synthetic positives/negatives are used.
  - If --quotes points to a JSON file:
      * Accepts a list of strings, or a list of objects with fields:
        {"quote": str, "expected": bool?, "instrument": str?, "parameter": str?}
  - If --quotes points to a .txt file: one quote per line (blank lines ignored).
    Use --assume-positive to evaluate recall when no expected labels are provided.
"""

import argparse
import time
from pathlib import Path
import fitz
import sys
from pathlib import Path as _Path

# Ensure repo root is on sys.path so `paper_data_linking` can be imported
_REPO_ROOT = _Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from paper_data_linking.processing.pdf_text_search import PDFTextSearcher
from paper_data_linking.processing.pdf_annotator import PDFAnnotator


def create_synthetic_pdf(path: Path) -> None:
    doc = fitz.open()
    # Page 1
    p1 = doc.new_page(width=612, height=792)
    box1 = fitz.Rect(50, 60, 560, 360)
    text1 = (
        "The first observation — as indicated in “Figure 1” — showed a clear trend.\n"
        "This line contains an ellipsis… indicating omitted text.\n"
        "Hyphenation example: spectral-\nresolution can be tricky across line breaks.\n"
        "Another quote with smart quotes: “Smart quotes should match \"straight\" quotes.”\n"
    )
    p1.insert_textbox(box1, text1, fontsize=11, fontname="helv")

    # Put content near the bottom to continue on next page
    box1b = fitz.Rect(50, 620, 560, 760)
    text1b = (
        "Cross-page start: This sentence begins here and will continue to the next page, "
        "forming a quote that spans pages…"
    )
    p1.insert_textbox(box1b, text1b, fontsize=11, fontname="helv")

    # Page 2
    p2 = doc.new_page(width=612, height=792)
    box2 = fitz.Rect(50, 60, 560, 760)
    text2 = (
        "…and here is the continuation that completes the cross-page quote with additional context.\n"
        "We also include regular three dots ... as an ellipsis variant."
    )
    p2.insert_textbox(box2, text2, fontsize=11, fontname="helv")

    doc.save(str(path))
    doc.close()


def highlight_results(pdf_path: Path, results: list, out_path: Path) -> None:
    doc = fitz.open(str(pdf_path))
    for res in results:
        loc = res.get("location")
        if not loc:
            continue
        regions = loc.get("coordinate_regions") or []
        for r in regions:
            page = doc.load_page(r["page"] - 1)
            rect = fitz.Rect(r["x0"], r["y0"], r["x1"], r["y1"])
            try:
                page.add_highlight_annot(rect)
            except Exception:
                pass
    doc.save(str(out_path))
    doc.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, default=None, help="PDF path; if omitted, a synthetic PDF is generated")
    ap.add_argument("--quotes", type=Path, default=None, help="Path to quotes file (json or txt)")
    ap.add_argument("--assume-positive", action="store_true", help="Treat all provided quotes as expected=True (recall focus)")
    ap.add_argument("--highlight", action="store_true", help="Write an annotated copy with highlights")
    ap.add_argument("--compare", action="store_true", help="Compare with existing PDFAnnotator timing")
    ap.add_argument("-v", "--verbose", action="store_true", help="Show per-quote debug info from searcher")
    ap.add_argument("--out-json", type=Path, default=None, help="Write detailed JSON results to this path")
    args = ap.parse_args()

    pdf_path = args.pdf
    if pdf_path is None:
        pdf_path = Path("sample_quote_test.pdf")
        create_synthetic_pdf(pdf_path)
        print(f"Created synthetic PDF at {pdf_path}")

    def load_quotes(quotes_path: Path) -> list:
        if quotes_path.suffix.lower() == ".json":
            import json
            data = json.loads(quotes_path.read_text(encoding="utf-8"))
            quotes_list = []
            if isinstance(data, list):
                for i, item in enumerate(data):
                    if isinstance(item, str):
                        quotes_list.append({
                            "quote": item,
                            "instrument": "TEST",
                            "parameter": f"q{i+1}",
                        })
                    elif isinstance(item, dict) and "quote" in item:
                        q = {
                            "quote": item["quote"],
                            "instrument": item.get("instrument", "TEST"),
                            "parameter": item.get("parameter", f"q{i+1}"),
                        }
                        if "expected" in item:
                            q["expected"] = bool(item["expected"])
                        quotes_list.append(q)
            return quotes_list
        # txt file: one quote per line
        quotes_list = []
        with quotes_path.open("r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                quotes_list.append({
                    "quote": line,
                    "instrument": "TEST",
                    "parameter": f"q{i+1}",
                })
        return quotes_list

    # Choose quotes source
    if args.quotes:
        quotes = load_quotes(args.quotes)
        if args.assume_positive:
            for q in quotes:
                q["expected"] = True
    else:
        quotes = [
            # Positive examples
            {"quote": "first observation — as indicated in \"Figure 1\"", "instrument": "TEST", "parameter": "exact", "expected": True},
            {"quote": "Smart quotes should match \"straight\" quotes.", "instrument": "TEST", "parameter": "smart_quotes", "expected": True},
            {"quote": "Hyphenation example: spectralresolution can be tricky across line breaks.", "instrument": "TEST", "parameter": "hyphen_join", "expected": True},
            {"quote": "This line contains an ellipsis... indicating omitted text.", "instrument": "TEST", "parameter": "ellipsis_three_dots", "expected": True},
            {"quote": "Cross-page start: This sentence begins here … continuation that completes the cross-page quote", "instrument": "TEST", "parameter": "cross_page_gap", "expected": True},
            # Negative/near-miss examples (should not be found)
            {"quote": "first observation - as indicated in 'Figure 2'", "instrument": "TEST", "parameter": "neg_wrong_figure", "expected": False},
            {"quote": "Hyphenation example: spectral resolution is tricky across line breaks.", "instrument": "TEST", "parameter": "neg_variation", "expected": False},
            {"quote": "This line contains an ellipsis indicating included text.", "instrument": "TEST", "parameter": "neg_word_change", "expected": False},
            {"quote": "Clever quotes should match 'straight' quotes.", "instrument": "TEST", "parameter": "neg_synonym", "expected": False},
            {"quote": "completely absent phrase never in document", "instrument": "TEST", "parameter": "neg_absent", "expected": False},
        ]

    # Run new searcher
    t0 = time.time()
    searcher = PDFTextSearcher(str(pdf_path))
    results = searcher.find_quotes(quotes, debug=args.verbose)
    searcher.close()
    t1 = time.time()

    print(f"PDFTextSearcher processed {len(quotes)} quotes in {t1 - t0:.3f}s")
    for r in results[:5]:
        print(f"- {r['parameter']}: {'FOUND' if r.get('location') else 'MISS'}")
    if args.verbose:
        print("\nPer-quote summary:")
        for r in results:
            dbg = r.get('debug') or {}
            print(f"[{r['parameter']}] exp={r.get('expected')} pred={'FOUND' if r.get('location') else 'MISS'} method={dbg.get('method')} attempt={dbg.get('attempt')} cov={dbg.get('coverage_ratio')} len={dbg.get('len_ratio')} ms={dbg.get('timing_ms')} span={dbg.get('span')} reject={dbg.get('reject_reason')}")

    # Evaluate precision/recall on synthetic set
    def normalize_text(s: str) -> str:
        import unicodedata, re
        t = unicodedata.normalize('NFKD', s)
        t = t.replace('\u00ad', '').replace('\u200b', '').replace('\u2009', ' ').replace('\u202f', ' ')
        t = t.replace('−', '-').replace('–', '-').replace('—', '-')
        t = t.replace('‘', "'").replace('’', "'").replace('“', '"').replace('”', '"').replace('…', '...')
        t = re.sub(r"\s+", " ", t)
        return t.strip().lower()

    def parts_in_order(hay: str, quote: str) -> bool:
        import re
        # Support ellipsis as gaps (simple ordered containment of parts)
        parts = [p.strip() for p in re.split(r"\.\.\.|…", quote) if p.strip()]
        if parts and len(parts) > 1:
            cur = 0
            h = normalize_text(hay)
            for p in parts:
                pn = normalize_text(p)
                idx = h.find(pn, cur)
                if idx == -1:
                    return False
                cur = idx + len(pn)
            return True
        # Token-based verification for non-ellipsis quotes
        def toks(s: str):
            return re.findall(r"[0-9A-Za-z]+", normalize_text(s))
        qtok = toks(quote)
        htok = toks(hay)
        if not qtok:
            return False
        cover = 0
        cur = 0
        for qt in qtok:
            try:
                j = htok.index(qt, cur)
                cover += 1
                cur = j + 1
            except ValueError:
                pass
        coverage_ratio = cover / len(qtok)
        len_ratio = (len(' '.join(htok)) / max(1, len(' '.join(qtok))))
        return (coverage_ratio >= 0.8) and (0.6 <= len_ratio <= 1.8)

    def extract_text_for_location(pdf: Path, location: dict) -> str:
        if not location:
            return ''
        doc = fitz.open(str(pdf))
        texts = []
        for r in location.get('coordinate_regions') or []:
            page = doc.load_page(r['page'] - 1)
            rect = fitz.Rect(r['x0'], r['y0'], r['x1'], r['y1'])
            texts.append(page.get_textbox(rect))
        doc.close()
        return ' '.join(texts)

    def eval_results(results: list) -> None:
        tp = fp = fn = tn = 0
        for r in results:
            pred = bool(r.get('location'))
            exp = bool(r.get('expected'))
            if pred:
                extracted = extract_text_for_location(pdf_path, r.get('location'))
                correct = parts_in_order(extracted, r['quote'])
                if exp and correct:
                    tp += 1
                elif exp and not correct:
                    fp += 1  # wrong match on a positive example
                elif not exp:
                    fp += 1
            else:
                if exp:
                    fn += 1
                else:
                    tn += 1
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) else 0.0
        print(f"Precision: {precision:.3f}, Recall: {recall:.3f}, F1: {f1:.3f}  (TP={tp}, FP={fp}, FN={fn}, TN={tn})")

    # Only compute metrics if we have expected labels for all quotes
    if all("expected" in q for q in quotes):
        print("PDFTextSearcher metrics:")
        eval_results(results)

    if args.compare:
        # Use the existing annotator (slower, mutates PDF) for comparison
        annot = PDFAnnotator(str(pdf_path))
        t2 = time.time()
        ann_results = annot.process_quotes([{k: v for k, v in q.items() if k in ('quote','instrument','parameter')} for q in quotes])
        t3 = time.time()
        print(f"PDFAnnotator processed {len(quotes)} quotes in {t3 - t2:.3f}s")
        # Attach expectations back for evaluation if present
        if all("expected" in q for q in quotes):
            for i, r in enumerate(ann_results):
                r['expected'] = quotes[i]['expected']
            print("PDFAnnotator metrics:")
            eval_results(ann_results)

    # Dump JSON results if requested
    if args.out_json:
        import json
        payload = {
            "pdf": str(pdf_path),
            "count": len(results),
            "results": results,
        }
        args.out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote results JSON to {args.out_json}")
        try:
            annot.pdf_document.close()
        except Exception:
            pass

    if args.highlight:
        out_path = pdf_path.with_name(pdf_path.stem + "_annotated.pdf")
        highlight_results(pdf_path, results, out_path)
        print(f"Wrote highlighted results to {out_path}")


if __name__ == "__main__":
    main()
