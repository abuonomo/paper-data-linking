#!/usr/bin/env python3
"""
Scan up to N PDFs in the repo and extract a small set of "hard" quotes
per PDF to build a realistic test set (smart quotes, dashes, ellipses,
hyphenation across lines, cross-page gaps).

Outputs per-PDF JSON files under fixtures/quotes/<basename>.quotes.json and
an index at fixtures/quotes/index.json.

Usage:
  python scripts/generate_hard_quotes.py [--limit 10] [--out fixtures/quotes]
         [--glob "api/media/papers/*.pdf"]
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import fitz


def words_from_text(text: str) -> list[str]:
    return re.findall(r"[\w]+", text)


def trim_words(words: list[str], max_words: int) -> str:
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words])


def collect_hard_quotes(pdf_path: Path, max_per_type: int = 3) -> list[dict]:
    doc = fitz.open(str(pdf_path))
    quotes: list[dict] = []
    seen: set[str] = set()

    def add_quote(qtext: str, label: str):
        qt = qtext.strip()
        if len(qt) < 15 or qt in seen:
            return
        quotes.append({
            "quote": qt,
            "instrument": "GEN",
            "parameter": label,
            "expected": True,
        })
        seen.add(qt)

    # 1) Smart quotes / dashes / ellipses from spans
    smart_count = dash_count = ell_count = 0
    for pno in range(len(doc)):
        page = doc.load_page(pno)
        data = page.get_text("dict")
        for block in data.get("blocks", []):
            for line in block.get("lines", []):
                line_text = " ".join(span.get("text", "") for span in line.get("spans", []))
                # Smart quotes
                if smart_count < max_per_type and ("“" in line_text or "”" in line_text or "‘" in line_text or "’" in line_text):
                    add_quote(line_text, f"smart_p{pno+1}")
                    smart_count += 1
                # Dashes
                if dash_count < max_per_type and ("—" in line_text or "–" in line_text or "−" in line_text):
                    add_quote(line_text, f"dash_p{pno+1}")
                    dash_count += 1
                # Ellipses
                if ell_count < max_per_type and ("…" in line_text or "..." in line_text):
                    add_quote(line_text, f"ellipsis_p{pno+1}")
                    ell_count += 1
        if smart_count >= max_per_type and dash_count >= max_per_type and ell_count >= max_per_type:
            break

    # 2) Hyphenation across line breaks
    hyp_count = 0
    for pno in range(len(doc)):
        page = doc.load_page(pno)
        data = page.get_text("dict")
        for block in data.get("blocks", []):
            lines = block.get("lines", [])
            for i in range(len(lines) - 1):
                cur_text = " ".join(span.get("text", "") for span in lines[i].get("spans", []))
                nxt_text = " ".join(span.get("text", "") for span in lines[i+1].get("spans", []))
                if cur_text.rstrip().endswith("-"):
                    # Grab last few words of current and first few of next
                    left = words_from_text(cur_text)
                    right = words_from_text(nxt_text)
                    if left and right:
                        # De-hyphenate join
                        left[-1] = left[-1]  # hyphen removed during tokenization
                        q = f"{' '.join(left[-8:])} {trim_words(right, 8)}"
                        add_quote(q, f"hyphen_join_p{pno+1}")
                        hyp_count += 1
                        if hyp_count >= max_per_type:
                            break
            if hyp_count >= max_per_type:
                break
        if hyp_count >= max_per_type:
            break

    # 3) Cross-page ellipsis quotes: take tail of page p and head of p+1
    cross_count = 0
    for pno in range(len(doc) - 1):
        p1 = doc.load_page(pno).get_text()
        p2 = doc.load_page(pno + 1).get_text()
        tail_words = words_from_text(p1)[-20:]
        head_words = words_from_text(p2)[:20]
        if tail_words and head_words:
            left = trim_words(tail_words, 12)
            right = trim_words(head_words, 12)
            add_quote(f"{left} … {right}", f"cross_page_p{pno+1}")
            cross_count += 1
            if cross_count >= max_per_type:
                break

    doc.close()
    return quotes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10, help="Max number of PDFs to process")
    ap.add_argument("--glob", type=str, default="api/media/papers/*.pdf", help="Glob to find PDFs")
    ap.add_argument("--out", type=Path, default=Path("fixtures/quotes"), help="Output directory for quotes JSON")
    args = ap.parse_args()

    root = Path.cwd()
    pdfs = sorted(root.glob(args.glob))
    if not pdfs:
        # Fallback: search repo
        pdfs = sorted(Path.cwd().rglob("*.pdf"))

    # Prefer non-annotated papers if available
    pdfs = [p for p in pdfs if "annotated_papers" not in str(p)]
    pdfs = pdfs[: args.limit]

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    index = []
    for pdf in pdfs:
        quotes = collect_hard_quotes(pdf)
        out_file = out_dir / (pdf.stem + ".quotes.json")
        out_file.write_text(json.dumps(quotes, indent=2), encoding="utf-8")
        index.append({"pdf": str(pdf), "quotes_file": str(out_file), "count": len(quotes)})
        print(f"Wrote {len(quotes)} quotes for {pdf} -> {out_file}")

    (out_dir / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"Index written to {(out_dir / 'index.json')}")


if __name__ == "__main__":
    main()

