#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import List

from experiments.compare_models.core.client import call_model


def replay_models(
    call_type: str,
    input_file: str,
    models: List[str],
    out_dir: str,
    temperature: float = 1.0,
    timeout_sec: float | None = None,
    max_retries: int | None = None,
):
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')

    # Open writers per model lazily
    writers = {}

    with open(input_file, 'r', encoding='utf-8') as fh:
        for line_idx, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                print(f"Skipping invalid JSON at line {line_idx}")
                continue

            messages = row.get('input_messages') or []
            if not messages:
                # Support baseline where system/user saved separately
                sys_msg = row.get('system')
                usr_msg = row.get('user')
                if sys_msg and usr_msg:
                    messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": usr_msg}]
                else:
                    print(f"No input_messages at line {line_idx}; skipping")
                    continue

            for model in models:
                try:
                    print(f"Processing line {line_idx} with {model} ...")
                    extra_kwargs = {}
                    # Note: Removed structured output enforcement for instrument_validation
                    # The validation prompt expects plain text format with "VALIDATION ANALYSIS:" structure
                    # if call_type == 'instrument_validation':
                    #     # Encourage structured outputs compatible with ValidationResult
                    #     try:
                    #         from paper_data_linking.linkers.general.validation_models import ValidationResult
                    #         extra_kwargs['response_format'] = ValidationResult
                    #     except Exception:
                    #         # If unavailable, proceed without response_format
                    #         pass
                    resp = call_model(
                        model,
                        messages,
                        temperature=temperature,
                        timeout=timeout_sec,
                        max_retries=max_retries,
                        **extra_kwargs,
                    )
                    result = {
                        'model_name': model,
                        'created_at': datetime.now().isoformat(),
                        'call_type': call_type,
                        'provider': resp['provider'],
                        'prompt_tokens': resp['tokens_used']['prompt_tokens'],
                        'completion_tokens': resp['tokens_used']['completion_tokens'],
                        'total_tokens': resp['tokens_used']['total_tokens'],
                        'estimated_cost_usd': resp['cost_estimate'],
                        'duration_ms': resp['response_time_ms'],
                        'input_messages': messages,
                        'output_content': resp['content'],
                        'source_line': line_idx,
                    }

                    key = model.replace('/', '_')
                    if key not in writers:
                        writers[key] = open(out_path / f"{key}_{ts}.jsonl", 'w', encoding='utf-8')
                    writers[key].write(json.dumps(result) + '\n')
                except Exception as e:
                    print(f"Error calling {model} on line {line_idx}: {e}")

    for f in writers.values():
        try:
            f.close()
        except Exception:
            pass


def parse_output_json(s: str):
    if not s:
        return None
    s = s.strip()
    if s.startswith('```'):
        s = s.strip('`').strip()
        if s.startswith('json'):
            s = s[4:].strip()
    try:
        return json.loads(s)
    except Exception:
        return None


def compare_time(baseline: str, others: List[str], results_dir: str):
    # Load baseline by source line
    base = {}
    with open(baseline, 'r', encoding='utf-8') as fh:
        for line in fh:
            row = json.loads(line)
            src = row.get('source_line')
            obj = parse_output_json(row.get('output_content', '')) or {}
            base[src] = {
                'start': obj.get('start_datetime'),
                'end': obj.get('end_datetime'),
                'precision': obj.get('precision'),
            }

    def trunc(dt: str | None, p: str | None) -> str | None:
        if not dt or not p:
            return dt
        n = {'year':4, 'month':7, 'day':10, 'hour':13, 'minute':16, 'second':19}.get(p)
        return dt[:n] if n else dt

    rows = []
    for other in others:
        model = Path(other).name.split('_')[0]
        with open(other, 'r', encoding='utf-8') as fh:
            for line in fh:
                row = json.loads(line)
                src = row.get('source_line')
                obj = parse_output_json(row.get('output_content', '')) or {}
                b = base.get(src)
                if not b:
                    continue
                # Compare with coarser precision
                bp = b.get('precision')
                mp = obj.get('precision')
                order = {'year':1,'month':2,'day':3,'hour':4,'minute':5,'second':6}
                if order.get(bp, 0) <= order.get(mp, 0):
                    use_p = bp
                else:
                    use_p = mp
                bstart = trunc(b.get('start'), use_p)
                bend = trunc(b.get('end'), use_p)
                mstart = trunc(obj.get('start_datetime'), use_p)
                mend = trunc(obj.get('end_datetime'), use_p)
                start_match = bstart == mstart
                end_match = bend == mend
                rows.append({
                    'model': model,
                    'source_line': src,
                    'start_match': start_match,
                    'end_match': end_match,
                    'both_match': start_match and end_match,
                    'baseline_precision': bp,
                    'model_precision': mp,
                })

    # Write summary json
    outp = Path(results_dir)
    outp.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    with open(outp / f'summary_time_{ts}.json', 'w', encoding='utf-8') as fh:
        json.dump(rows, fh, indent=2)
    # Print short summary
    by_model = {}
    for r in rows:
        d = by_model.setdefault(r['model'], {'n':0,'ok':0})
        d['n'] += 1
        d['ok'] += 1 if r['both_match'] else 0
    for m, s in by_model.items():
        acc = (s['ok']/s['n']*100) if s['n'] else 0.0
        print(f"{m}: {s['ok']}/{s['n']} ({acc:.1f}%)")


def main():
    ap = argparse.ArgumentParser(description='Replay prompts across models and compare outputs')
    ap.add_argument('--call-type', required=True, help='LLMCall.call_type to tag outputs with')
    ap.add_argument('--input', help='Input JSONL with input_messages (exported from DB)')
    ap.add_argument('--models', nargs='+', help='Models to call (e.g., openai/gpt-5 openai/gpt-5-mini)')
    ap.add_argument('--out', default='experiments/compare_models/data', help='Directory to write outputs')
    ap.add_argument('--temperature', type=float, default=1.0)
    ap.add_argument('--timeout-sec', type=float, default=None, help='Per-call timeout in seconds')
    ap.add_argument('--max-retries', type=int, default=None, help='LiteLLM max_retries for each call')
    ap.add_argument('--compare', action='store_true', help='Run comparison summary for supported call_types')
    ap.add_argument('--baseline', help='Baseline JSONL file (one of the outputs)')
    ap.add_argument('--others', nargs='*', help='Other JSONL files to compare to baseline')
    ap.add_argument('--results', default='experiments/compare_models/results', help='Directory to write comparison results')

    args = ap.parse_args()

    if args.compare:
        if args.call_type == 'time_normalization':
            if not args.baseline or not args.others:
                raise SystemExit('--baseline and --others are required for time comparison')
            compare_time(args.baseline, args.others, args.results)
            return
        elif args.call_type == 'instrument_validation':
            if args.baseline:
                # Baseline + others -> classification metrics
                if not args.others:
                    raise SystemExit('Provide --others for validation comparison with baseline')
                compare_instrument_validation_with_baseline(args.baseline, args.others, args.results)
                return
            else:
                # No baseline -> presence + distribution summary
                files = []
                if args.others:
                    files.extend(args.others)
                if not files:
                    raise SystemExit('Provide --others for validation summary (no baseline)')
                compare_instrument_validation(files, args.results)
                return
        else:
            raise SystemExit(f'No comparator implemented for call_type={args.call_type}')

    if not args.input or not args.models:
        raise SystemExit('--input and --models are required for replay')

    replay_models(
        args.call_type,
        args.input,
        args.models,
        args.out,
        temperature=args.temperature,
        timeout_sec=args.timeout_sec,
        max_retries=args.max_retries,
    )


# ---- additional comparators ----

import re


def extract_decision_from_json(text: str) -> str | None:
    obj = parse_output_json(text)
    if not isinstance(obj, dict):
        return None
    decision = obj.get('decision')
    if isinstance(decision, str):
        d = decision.lower()
        if d in {'valid', 'invalid'}:
            return d
    return None


def extract_conclusion_suffix(text: str) -> str | None:
    if not text:
        return None
    s = text.strip()
    if s.startswith('```'):
        lines = [ln for ln in s.splitlines() if not ln.strip().startswith('```')]
        s = '\n'.join(lines).strip()
    m = re.search(r'CONCLUSION:\s*(VALID|INVALID)\s*$', s, flags=re.IGNORECASE)
    return m.group(1).lower() if m else None


def compare_instrument_validation(files: list[str], results_dir: str):
    rows = []
    for path in files:
        with open(path, 'r', encoding='utf-8') as fh:
            for line in fh:
                row = json.loads(line)
                model = row.get('model_name') or 'unknown'
                text = row.get('output_content') or ''
                decision = extract_decision_from_json(text) or extract_conclusion_suffix(text)
                rows.append({'model': model, 'ok': decision in {'valid', 'invalid'}, 'decision': decision})

    # Summarize per model
    summary = {}
    for r in rows:
        s = summary.setdefault(r['model'], {'n': 0, 'ok': 0, 'valid': 0, 'invalid': 0})
        s['n'] += 1
        s['ok'] += 1 if r['ok'] else 0
        if r['decision'] == 'valid':
            s['valid'] += 1
        elif r['decision'] == 'invalid':
            s['invalid'] += 1

    outp = Path(results_dir)
    outp.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    with open(outp / f'summary_instrument_validation_{ts}.json', 'w', encoding='utf-8') as fh:
        json.dump({'by_model': summary}, fh, indent=2)

    for m, s in summary.items():
        rate = (s['ok'] / s['n'] * 100) if s['n'] else 0.0
        print(f"{m}: decision-present {s['ok']}/{s['n']} ({rate:.1f}%), valid={s['valid']}, invalid={s['invalid']}")


def compare_instrument_validation_with_baseline(baseline: str, others: list[str], results_dir: str):
    # Build baseline map: index (1-based) or source_line -> decision
    base = {}
    with open(baseline, 'r', encoding='utf-8') as fh:
        for idx, line in enumerate(fh, 1):
            row = json.loads(line)
            src = row.get('source_line') or idx
            text = row.get('output_content') or ''
            decision = extract_decision_from_json(text) or extract_conclusion_suffix(text)
            if decision in {'valid', 'invalid'}:
                base[src] = decision

    def metrics(tp, fp, fn, tn):
        total = tp + fp + fn + tn
        acc = (tp + tn) / total if total else 0.0
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) else 0.0
        return {
            'accuracy': acc,
            'precision': prec,
            'recall': rec,
            'f1': f1,
            'support': total,
        }

    results = {}
    for path in others:
        model = Path(path).name.split('_')[0]
        tp = fp = fn = tn = 0
        compared = 0
        present = 0
        with open(path, 'r', encoding='utf-8') as fh:
            for idx, line in enumerate(fh, 1):
                row = json.loads(line)
                src = row.get('source_line') or idx
                if src not in base:
                    continue
                base_dec = base[src]
                text = row.get('output_content') or ''
                dec = extract_decision_from_json(text) or extract_conclusion_suffix(text)
                if dec not in {'valid', 'invalid'}:
                    compared += 1
                    continue
                present += 1
                compared += 1
                if base_dec == 'valid' and dec == 'valid':
                    tp += 1
                elif base_dec == 'valid' and dec == 'invalid':
                    fn += 1
                elif base_dec == 'invalid' and dec == 'valid':
                    fp += 1
                elif base_dec == 'invalid' and dec == 'invalid':
                    tn += 1
        results[model] = {
            'counts': {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn, 'present': present, 'compared': compared},
            'metrics': metrics(tp, fp, fn, tn),
        }

    outp = Path(results_dir)
    outp.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_file = outp / f'summary_instrument_validation_vs_baseline_{ts}.json'
    with open(out_file, 'w', encoding='utf-8') as fh:
        json.dump({'baseline': Path(baseline).name, 'results': results}, fh, indent=2)

    for model, res in results.items():
        c = res['counts']
        m = res['metrics']
        print(
            f"{model}: present {c['present']}/{c['compared']} | "
            f"acc={m['accuracy']:.3f} prec={m['precision']:.3f} rec={m['recall']:.3f} f1={m['f1']:.3f} "
            f"tp={c['tp']} fp={c['fp']} fn={c['fn']} tn={c['tn']}"
        )


if __name__ == '__main__':
    main()
