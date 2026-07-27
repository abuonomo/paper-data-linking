#!/usr/bin/env python3
"""
Batch runner to evaluate PDFTextSearcher on generated fixtures/quotes.

Reads fixtures/quotes/index.json and for each entry, loads the PDF and its
quotes file, runs the searcher, and prints per-PDF precision/recall/F1 and a
final summary. Outputs a JSON report if --out is provided.
"""

import json
from pathlib import Path
import argparse
import time
import fitz
import sys

# Ensure repo root on path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from paper_data_linking.processing.pdf_text_search import PDFTextSearcher


def normalize_text(s: str) -> str:
    """Enhanced normalization that matches the PDF searcher's normalization"""
    import unicodedata, re
    t = unicodedata.normalize('NFKD', s)
    
    # Mathematical symbols and special characters (matching PDF searcher)
    replacements = {
        # Dashes and hyphens
        "−": "-", "–": "-", "—": "-", "―": "-", "‐": "-",
        # Quotes
        "'": "'", "'": "'", "‚": "'", "‛": "'", "`": "'",
        """: '"', """: '"', "„": '"', "‟": '"',
        # Ellipsis
        "…": "...",
        # Ligatures
        "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
        # Mathematical symbols - normalize to ASCII equivalents
        "·": "*", "∙": "*", "•": "*", "⋅": "*", "×": "*", "⨯": "*",
        "±": "+-", "∓": "-+", "≈": "~=", "≃": "~=", "≅": "~=",
        "≠": "!=", "≤": "<=", "≥": ">=", "≪": "<<", "≫": ">>",
        "∞": "inf", "∂": "d", "∇": "grad", "∆": "delta", "∑": "sum",
        "∏": "prod", "∫": "int", "√": "sqrt", "∝": "prop",
        # Greek letters commonly used in math
        "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon",
        "ζ": "zeta", "η": "eta", "θ": "theta", "ι": "iota", "κ": "kappa",
        "λ": "lambda", "μ": "mu", "µ": "mu", "ν": "nu", "ξ": "xi", "ο": "omicron",
        "π": "pi", "ρ": "rho", "σ": "sigma", "τ": "tau", "υ": "upsilon",
        "φ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega",
        # Special whitespace
        "\u00a0": " ", "\u2003": " ", "\u2002": " ", "\u2004": " ", 
        "\u2005": " ", "\u2006": " ",
    }
    
    for u, a in replacements.items():
        t = t.replace(u, a)
    
    # Remove soft hyphen and zero-widths
    t = t.replace('\u00ad', '').replace('\u200b', '').replace('\u2009', ' ').replace('\u202f', ' ')
    
    # Normalize punctuation that commonly differs in PDFs
    # Remove @ symbols, parentheses, brackets, colons, commas that might be missing/added
    t = re.sub(r'[@()\[\]∈:,.\-;]', ' ', t)
    
    # Handle common word boundary issues (hyphens between words)
    t = re.sub(r'\b(\w+)-(\w+)\b', r'\1 \2', t)  # "odd-s" -> "odd s"
    
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


def parts_in_order(hay: str, quote: str) -> bool:
    import re
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
    # token-based
    def toks(s: str):
        import re
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
    
    # More lenient thresholds for cross-page and mathematical content
    # Detect if this might be cross-page content (has ellipsis parts)
    is_cross_page = len(parts) > 1
    # Detect mathematical content
    has_math = any(char in quote for char in ['=', '+', '-', '*', '/', '(', ')', 'α', 'β', 'λ', 'σ', 'μ'])
    
    if is_cross_page:
        # Cross-page content: very lenient due to extraction challenges
        return (coverage_ratio >= 0.6) and (0.4 <= len_ratio <= 2.5)
    elif has_math:
        # Mathematical content: more lenient due to symbol variations
        return (coverage_ratio >= 0.7) and (0.5 <= len_ratio <= 2.0)
    else:
        # Regular content: standard thresholds
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


def eval_pdf(pdf_path: Path, quotes_file: Path, debug: bool = False, method: str = 'original') -> dict:
    quotes = json.loads(quotes_file.read_text(encoding='utf-8'))
    searcher = PDFTextSearcher(str(pdf_path))
    t0 = time.time()
    
    # Use the specified method
    if method == 'ir':
        results = searcher.find_quotes_ir([
            {k: v for k, v in q.items() if k in ('quote', 'instrument', 'parameter')}
            for q in quotes
        ], debug=debug)
    elif method == 'original':
        results = searcher.find_quotes_original([
            {k: v for k, v in q.items() if k in ('quote', 'instrument', 'parameter')}
            for q in quotes
        ], debug=debug)
    else:  # legacy
        results = searcher.find_quotes([
            {k: v for k, v in q.items() if k in ('quote', 'instrument', 'parameter')}
            for q in quotes
        ], debug=debug)
    
    t1 = time.time()
    searcher.close()

    tp = fp = fn = tn = 0
    per = []
    cat_stats = {}
    for i, res in enumerate(results):
        q = quotes[i]
        exp = bool(q.get('expected', True))
        pred = bool(res.get('location'))
        ok = False
        if pred:
            extracted = extract_text_for_location(pdf_path, res.get('location'))
            ok = parts_in_order(extracted, q['quote'])
        if pred and exp and ok:
            tp += 1
        elif pred and not exp:
            fp += 1
        elif pred and exp and not ok:
            fp += 1
        elif not pred and exp:
            fn += 1
        else:
            tn += 1
        per.append({
            'quote': q['quote'][:100] + ('...' if len(q['quote']) > 100 else ''),
            'expected': exp,
            'predicted': pred,
            'ok': ok,
            'parameter': q.get('parameter')
        })

        # Per-category stats
        param = (q.get('parameter') or '').lower()
        if param.startswith('smart'):
            cat = 'smart'
        elif param.startswith('dash'):
            cat = 'dash'
        elif param.startswith('ellipsis'):
            cat = 'ellipsis'
        elif param.startswith('hyphen'):
            cat = 'hyphen'
        elif param.startswith('cross_page'):
            cat = 'cross_page'
        else:
            cat = 'other'
        c = cat_stats.setdefault(cat, {'total': 0, 'tp': 0, 'fp': 0, 'fn': 0})
        c['total'] += 1
        if pred and exp and ok:
            c['tp'] += 1
        elif pred and exp and not ok:
            c['fp'] += 1
        elif not pred and exp:
            c['fn'] += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) else 0.0
    return {
        'pdf': str(pdf_path),
        'quotes_file': str(quotes_file),
        'count': len(quotes),
        'time_s': round(t1 - t0, 3),
        'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
        'precision': round(precision, 3),
        'recall': round(recall, 3),
        'f1': round(f1, 3),
        'samples': per[:5],
        'categories': cat_stats,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--index', type=Path, default=Path('fixtures/quotes/index.json'))
    ap.add_argument('--limit', type=int, default=10)
    ap.add_argument('--out', type=Path, default=None)
    ap.add_argument('--debug', action='store_true', help='Enable detailed per-quote debug logs')
    ap.add_argument('--debug-dir', type=Path, default=None, help='Directory to write per-PDF debug JSON files')
    ap.add_argument('--method', choices=['legacy', 'ir', 'original'], default='original', help='Method to use: original (d85121c fast method), legacy (current find_quotes), or ir (IR-inspired)')
    args = ap.parse_args()

    index = json.loads(args.index.read_text(encoding='utf-8'))
    index = index[: args.limit]
    results = []
    print(f"Evaluating {len(index)} PDFs from {args.index} ...")
    for entry in index:
        pdf = Path(entry['pdf'])
        qf = Path(entry['quotes_file'])
        res = eval_pdf(pdf, qf, debug=args.debug, method=args.method)
        results.append(res)
        print(f"- {pdf.name}: P={res['precision']:.3f} R={res['recall']:.3f} F1={res['f1']:.3f} in {res['time_s']:.3f}s (n={res['count']})")
        if args.debug_dir:
            args.debug_dir.mkdir(parents=True, exist_ok=True)
            dbg_path = args.debug_dir / (pdf.stem + '.debug.json')
            dbg_path.write_text(json.dumps(res, indent=2), encoding='utf-8')
            print(f"  wrote debug -> {dbg_path}")
    # Summary
    if results:
        avg_p = sum(r['precision'] for r in results) / len(results)
        avg_r = sum(r['recall'] for r in results) / len(results)
        avg_f1 = sum(r['f1'] for r in results) / len(results)
        print(f"Summary: avg P={avg_p:.3f} R={avg_r:.3f} F1={avg_f1:.3f}")
        # Aggregate category stats
        agg = {}
        for r in results:
            for cat, s in r.get('categories', {}).items():
                a = agg.setdefault(cat, {'total': 0, 'tp': 0, 'fp': 0, 'fn': 0})
                a['total'] += s['total']
                a['tp'] += s['tp']
                a['fp'] += s['fp']
                a['fn'] += s['fn']
        if agg:
            print("Category breakdown (micro):")
            for cat, s in sorted(agg.items(), key=lambda kv: kv[0]):
                prec = s['tp'] / (s['tp'] + s['fp']) if (s['tp'] + s['fp']) else 0.0
                rec = s['tp'] / (s['tp'] + s['fn']) if (s['tp'] + s['fn']) else 0.0
                f1c = (2 * prec * rec) / (prec + rec) if (prec + rec) else 0.0
                print(f"  - {cat}: P={prec:.3f} R={rec:.3f} F1={f1c:.3f} (n={s['total']})")
    if args.out:
        args.out.write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(f"Wrote report to {args.out}")


if __name__ == '__main__':
    main()
