# Validation-handler regex drops ~6% of Bedrock verdicts

**Severity**: Medium — silently corrupts validation results for a real slice of prod traffic.
**Affects**: `InstrumentValidationHandler`, `MissionValidationHandler` — both live (non-batch) and batch paths.
**Discovered**: self-consistency run on `test_set_helio_v2_2026_04_06` (gpt-oss-120b via Bedrock), 2026-04-14.

## Summary

Both validation handlers regex the model's free-text response for a final
verdict of `valid` or `invalid`. The current regex in
`experiments/compare_models/handlers/instrument_validation.py:34-38` (and the
identical one in `mission_validation.py:37-41`) is:

```python
re.search(
    r'FINAL\s+DECISION:\s*\*?\*?(valid|invalid)\*?\*?',
    response,
    re.IGNORECASE,
)
```

The intent — per the comment block — is to tolerate optional markdown bold
around the verdict (`**valid**`). The regex handles `FINAL DECISION: valid`
and `FINAL DECISION: **valid**` correctly, but it **fails silently** on the
common markdown-bold-around-the-label variant:

```
**FINAL DECISION:** valid
```

In this form the closing `**` is between the colon and the verdict, with a
space before `valid`. The pattern `\s*\*?\*?` after the colon matches `**`
but leaves the following space un-consumed, so `(valid|invalid)` never fires.

`parse_response` then returns `None`, which downstream means:
- the case is treated as **unparseable**, not as a real `valid`/`invalid`
  decision;
- comparison code flags the run as an error case and drops it from the
  comparison pool;
- metrics like parse rate, perfect-consistency %, and Fleiss' kappa are all
  depressed.

## Evidence

On the 500-record self-consistency set for `instrument_validation × bedrock-120b-high`:

| Regex | Parse rate | Fleiss' kappa | Perfect consistency |
|---|---|---|---|
| Current (`FINAL\s+DECISION:\s*\*?\*?(valid\|invalid)\*?\*?`) | 94.2% | 0.669 | 72% |
| Tolerant (`FINAL\s+DECISION[:\*\s]*(valid\|invalid)`) | **100%** | **0.923** | **94%** |

29/500 records hit the failure mode, all on outputs ending in `**FINAL DECISION:** <verdict>`. After the fix every record parses and the kappa jumps 0.25 points — those 29 records were genuinely consistent with the rest of the case's runs, just unparseable by the old regex.

Same pattern reproduces for `mission_validation × bedrock-120b-high`:
parse rate 98.8 → 100%, kappa 0.849 → 0.946, perfect 92 → 98%.

OpenAI (gpt-5.4) results are unaffected in this dataset because that model
never used the `**FINAL DECISION:**` bolded-label form during the run — but
nothing in the prompt forbids it, so a future prompt tweak or model
upgrade could surface the same bug on the OpenAI path too.

### Example falsely-rejected output

```
...
**FINAL DECISION:** valid
```

Current regex: no match → `parse_response` returns `None` → case counted as
parse error.
Tolerant regex: match, `verdict='valid'`.

## Prod impact

These handlers aren't only used in the self-consistency experiment — they're
imported from `paper_data_linking/linkers/general/prompts/validation/` via
the pipeline runners, so **the exact same regex runs on every live
production validation call**. The miss rate on Bedrock traffic appears to be
~6% for `instrument_validation` and ~1% for `mission_validation`. Those are
silently dropped to "unparseable" and either logged as noise or trigger a
retry, depending on the caller.

## Proposed fix

Replace the regex in both handlers with a tolerant form. Minimal diff:

```diff
- r'FINAL\s+DECISION:\s*\*?\*?(valid|invalid)\*?\*?'
+ r'FINAL\s+DECISION[:\*\s]*(valid|invalid)'
```

Files:
- `experiments/compare_models/handlers/instrument_validation.py:34-38`
- `experiments/compare_models/handlers/mission_validation.py:37-41`

The character class `[:\*\s]*` accepts any mix of `:`, `*`, and whitespace
between `FINAL DECISION` and the verdict, which covers every observed
formatting the model produces:

- `FINAL DECISION: valid`
- `FINAL DECISION: **valid**`
- `**FINAL DECISION:** valid`  ← previously broken
- `**FINAL DECISION**: valid`
- `*FINAL DECISION:* valid`
- `FINAL DECISION:\n\n**valid**`

## Suggested unit tests (add to `tests/unit/test_instrument_validation.py`)

```python
@pytest.mark.parametrize("body, expected", [
    ("... FINAL DECISION: valid", "valid"),
    ("... FINAL DECISION: **valid**", "valid"),
    ("... **FINAL DECISION:** valid", "valid"),          # currently broken
    ("... **FINAL DECISION**: valid", "valid"),
    ("... FINAL DECISION:\n\n**invalid**", "invalid"),
    ("... *FINAL DECISION:* invalid", "invalid"),
])
def test_parse_response_verdict_formats(body, expected):
    assert InstrumentValidationHandler().parse_response(body) == expected
```

Add the parallel set for `MissionValidationHandler`.

## Rollout notes

- No migration needed — behavior change is "more calls now parse correctly"
  rather than a schema change.
- Any prior `DatasetUsage` / validation records that were persisted as
  "unparseable" on live calls could be re-parsed from
  `LLMCall.output_content` with a one-off management command if we want to
  clean historical data; not required for the fix itself.
- The self-consistency analyzer
  (`experiments/compare_models/self_consistency/analyze_helio_v2_report.py`)
  currently carries a local workaround with the tolerant regex; once the
  handler is fixed that workaround can be removed.

## Related

Self-consistency report:
`experiments/compare_models/test_set_helio_v2_2026_04_06_self_consistency_report.md`
— "Deviations" section for the measurement-side impact.
