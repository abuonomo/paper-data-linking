# Runbook: Helio v2 Self-Consistency Experiment

This runbook documents how the self-consistency / substitution experiment for
`test_set_helio_v2_2026_04_06` is executed. The experiment compares GPT-5.4
(OpenAI) against GPT-OSS-120B (AWS Bedrock) across 10 LLM call types, measuring
intra-model and cross-model agreement via Fleiss' / Cohen's κ.

Results are used in the technical report at [docs/technical_report/paper.tex](../../../docs/technical_report/paper.tex).

---

## Test set

- **Tag**: `test_set_helio_v2_2026_04_06`
- **Papers**: 200 heliophysics papers (stratified sample across SOHO, Wind, IRIS, PSP, ACE, and a keyword-filtered general helio stratum)
- **Creation docs**: [docs/test_set_helio_v2_2026_04_06.md](../../../docs/test_set_helio_v2_2026_04_06.md)
- **Creation script**: [scripts/queries/create_helio_test_set_v2.py](../../../scripts/queries/create_helio_test_set_v2.py)

## Call types (10)

`instrument_validation`, `wavelength_normalization`, `physobs_normalization`,
`mission_selection`, `instrument_selection`, `detector_normalization`,
`time_normalization`, `cadence_normalization`, `mission_identification`,
`mission_validation`.

## Models

| Key | Model | Provider |
|---|---|---|
| `standard-gpt54` | `openai/gpt-5.4` | OpenAI Batch API |
| `bedrock-120b-high` | `bedrock/converse/openai.gpt-oss-120b-1:0` | AWS Bedrock Batch (except `time_normalization`; see below) |

Both run with `temperature=1.0` and `reasoning_effort=high`, 5 runs per case.

## Sample variants

Each call type has two 100-case samples that are merged at analysis time for
N≈200 substantive cases per call type:

| Variant | Seed | How cases are chosen |
|---|---|---|
| `sampled_100_seed42` | 42 | Uniform random sample of production LLM calls for that call type |
| `substantive_100_seed43` | 43 | Sampled from the subset where production returned a non-null answer, excluding IDs already in the seed=42 sample |

Both sample files live at [inputs/test_set/](../../../inputs/test_set/) and follow the naming convention:
```
{call_type}_test_set_helio_v2_2026_04_06_{variant}.jsonl
```

The substantive variant exists because uniform random sampling gave tiny
post-filter N for call types with many null answers (e.g., cadence dropped to
N=19 of 100 after filtering). The top-up sample restores statistical power
without requiring a new test set.

---

## Environment setup

### Python environment

```bash
uv sync
```

### AWS credentials for Bedrock

**Critical:** Bedrock batch submission requires the `bedrock-admin` SSO profile,
not the default `bedrock` profile. The default profile lacks `iam:PassRole`
on `pdl-bedrock-batch-role`.

```bash
# First time / when SSO session expires
aws sso login --profile bedrock-admin

# Refresh .env with bedrock-admin creds (overrides default 'bedrock' profile)
AWS_PROFILE=bedrock-admin ./scripts/refresh-aws-credentials.sh
```

The `AWS_BEDROCK_INVOKE_ROLE_ARN` line in `.env` should stay **commented out**
for local submission — that assume-role path is for prod EC2, not local SSO.

### OpenAI credentials

`.env` must contain `OPENAI_API_KEY`. All submission scripts load `.env` via
`dotenv.load_dotenv('.env')`.

### Running scripts with `.env` loaded

Most scripts here expect environment variables in the process environment.
The cleanest pattern:

```bash
VIRTUAL_ENV= .venv/bin/python -c "
from dotenv import load_dotenv; load_dotenv('.env')
import os, subprocess, sys
sys.exit(subprocess.run(
    ['.venv/bin/python', 'path/to/script.py', '--args'],
    env=os.environ.copy()
).returncode)
"
```

`VIRTUAL_ENV=` unsets a stray venv pointer that `uv` sometimes injects.

---

## Step-by-step procedure

### 1. Create a substantive-filtered sample (only needed when adding a new variant)

For each call type with high null rates, sample from the substantive pool
(excluding IDs already in the existing sample):

```bash
# One-off for a single call type:
.venv/bin/python scripts/sample_substantive_jsonl.py \
    inputs/test_set/cadence_normalization_test_set_helio_v2_2026_04_06.jsonl \
    inputs/test_set/cadence_normalization_test_set_helio_v2_2026_04_06_substantive_100_seed43.jsonl \
    100 43 \
    --exclude inputs/test_set/cadence_normalization_test_set_helio_v2_2026_04_06_sampled_100_seed42.jsonl

# All 10 call types at once — see the inline script in git history for the
# 2026-04-16 generation (loops over CALL_TYPES and invokes the above pattern).
```

The sampler reads `output_content` from each production LLM call record, parses
it via the call-type's handler, and keeps only cases where the parsed answer
is non-null (and not `UNKNOWN` / `not_applicable` / empty list, etc.).

### 2. Submit OpenAI batches

```bash
VIRTUAL_ENV= .venv/bin/python -c "
from dotenv import load_dotenv; load_dotenv('.env')
import os, subprocess, sys
sys.exit(subprocess.run([
    '.venv/bin/python',
    'experiments/compare_models/self_consistency/submit_helio_v2_batches.py',
    '--sample-variant', 'substantive_100_seed43',
    '--confirm',
], env=os.environ.copy()).returncode)
"
```

- `--sample-variant` selects which input file (and manifest key) to use.
  Default is `sampled_100_seed42` (the original random variant).
- `--confirm` is required if total estimated cost exceeds the $50 safety limit.
- Skips `time_normalization × bedrock` (handled separately; see below).
- Skips any `(call_type, model, variant)` already submitted to avoid double-charging.

Manifest: [batches/test_set_helio_v2_2026_04_06/_manifest.jsonl](batches/test_set_helio_v2_2026_04_06/_manifest.jsonl).

### 3. Submit Bedrock batches

**First time** (or when SSO session expires): refresh creds with
`AWS_PROFILE=bedrock-admin` (see setup section).

```bash
VIRTUAL_ENV= .venv/bin/python -c "
from dotenv import load_dotenv; load_dotenv('.env')
import os, subprocess, sys
sys.exit(subprocess.run([
    '.venv/bin/python',
    'experiments/compare_models/self_consistency/submit_helio_v2_bedrock.py',
    '--sample-variant', 'substantive_100_seed43',
], env=os.environ.copy()).returncode)
"
```

Bedrock has its own submission script because litellm v1.70.4 (pinned in this
repo) does not support the Bedrock batch API. The script uses
[paper_data_linking/clients/batch_client.py](../../../paper_data_linking/clients/batch_client.py)
which drives boto3 directly: S3 upload of JSONL, then
`bedrock.create_model_invocation_job`.

Bedrock jobs appear in the same `_manifest.jsonl` as OpenAI jobs, tagged with
`model_key: bedrock-120b-high`.

### 4. Run Bedrock `time_normalization` LIVE (schema-forced path)

**Why special:** `time_normalization` is the only call type whose handler
returns a non-None `get_response_format()` (Pydantic schema
`NormalizedTimeRange`). On the live path, litellm translates
`response_format=<Pydantic>` into a Bedrock `toolConfig` tool-use call, which
forces the model to emit exact schema fields. The Bedrock batch API does NOT
apply this translation — it passes `modelInput` through verbatim, so batched
`time_normalization` outputs diverge from prod (different field names, markdown
fences). κ measured on batched outputs is artificially low (~0.52 vs the live
~0.82).

Fix: for Bedrock × time_normalization only, run live instead of batched:

```bash
VIRTUAL_ENV= .venv/bin/python -c "
from dotenv import load_dotenv; load_dotenv('.env')
import os, subprocess, sys
sys.exit(subprocess.run([
    '.venv/bin/python',
    'experiments/compare_models/self_consistency/rerun_bedrock_time_normalization_live.py',
    '--sample-variant', 'substantive_100_seed43',
], env=os.environ.copy()).returncode)
"
```

500 live calls, concurrency 20, takes ~5 minutes. Results flow into the same
`results/test_set_helio_v2_2026_04_06/bedrock_converse_openai_gpt-oss-120b-1_0/time_normalization/run{1..5}/`
directory as the batch results.

`submit_helio_v2_batches.py` and `submit_helio_v2_bedrock.py` both explicitly
**skip** `time_normalization × bedrock` and print a reminder to use this script.

### 5. Retrieve completed batches

Idempotent — safe to re-run repeatedly as batches complete:

```bash
VIRTUAL_ENV= .venv/bin/python -c "
from dotenv import load_dotenv; load_dotenv('.env')
import os, subprocess, sys
sys.exit(subprocess.run([
    '.venv/bin/python',
    'experiments/compare_models/self_consistency/retrieve_helio_v2_batches.py',
], env=os.environ.copy()).returncode)
"
```

Polls each batch's status, retrieves completed ones into
[results/test_set_helio_v2_2026_04_06/](results/test_set_helio_v2_2026_04_06/),
and stamps each manifest entry with `retrieved_at`.

Directory layout for raw results:
```
results/
  test_set_helio_v2_2026_04_06/
    openai_gpt-5_4/
      <call_type>/
        run{1..5}/
          *.jsonl      # per-run, per-batch JSONLs
    bedrock_converse_openai_gpt-oss-120b-1_0/
      <call_type>/
        run{1..5}/
          *.jsonl
```

Multiple sample variants drop into the **same** run directories — each JSONL
file has a distinct timestamp (and variant suffix for the live rerun), and the
analyzer keys on `case_id` so records from different variants are merged
automatically.

### 6. Generate the self-consistency report

```bash
VIRTUAL_ENV= .venv/bin/python \
    experiments/compare_models/self_consistency/analyze_helio_v2_report.py
```

Writes [test_set_helio_v2_2026_04_06_self_consistency_report.md](../test_set_helio_v2_2026_04_06_self_consistency_report.md)
with per-call-type Fleiss' κ, parse rate, perfect-consistency rate, and
substantive-only numbers. N in the report reflects the merged (all variants)
substantive case count.

### 7. Regenerate the primary figure

```bash
VIRTUAL_ENV= .venv/bin/python \
    experiments/compare_models/self_consistency/plot_substitution_bars.py
```

Grouped bar chart with 95% bootstrap CIs (percentile method, 2000 resamples).
Writes `test_set_helio_v2_2026_04_06_substitution_bars.{png,pdf}` in the
`experiments/compare_models/` parent directory.

### 8. Copy figure + update the paper

```bash
cp experiments/compare_models/test_set_helio_v2_2026_04_06_substitution_bars.pdf \
   docs/technical_report/figures/substitution_bars.pdf
cp experiments/compare_models/test_set_helio_v2_2026_04_06_substitution_bars.png \
   docs/technical_report/figures/substitution_bars.png

# Update Table 1 in paper.tex with new κ values + CIs from the report, then:
cd docs/technical_report && ./build.sh
```

The table values (point estimates + CIs) can be dumped programmatically with
a small Python snippet that calls `plot_substitution_decision_kappa.compute()`
for each call type.

---

## Budget notes

Each (call type × model × 5 runs × 100 cases) batch is 500 LLM calls.

Per-round cost (observed, 2026-04):
- OpenAI GPT-5.4: ~$30 for 10 batches (5,000 calls)
- Bedrock GPT-OSS-120B: ~$3 for 9 batches (4,500 calls)
- Bedrock live `time_normalization`: <$1 for 500 calls

Total per 100-case-per-call-type round: ~$35.

---

## Gotchas

1. **SSO profile matters**: `bedrock` vs `bedrock-admin`. Wrong profile gives
   `iam:PassRole` denied. See environment setup section.

2. **litellm Bedrock batch not supported**: Must use `submit_helio_v2_bedrock.py`,
   not `submit_helio_v2_batches.py`, for Bedrock. The batch script would fail
   with `LiteLLM doesn't support bedrock for 'create_file'`.

3. **`time_normalization × bedrock` needs live submission**: schema enforcement
   is a litellm live-path feature that the Bedrock batch API does not apply.
   Both batch scripts are hard-coded to skip this combination.

4. **Manifest has historical failure entries**: The `already_submitted` checks
   skip only non-failed entries, so prior failed attempts (wrong creds, etc.)
   harmlessly stay in the manifest and get retried on the next run.

5. **AWS session tokens expire**: SSO sessions last ~8 hours. Refresh with
   `AWS_PROFILE=bedrock-admin ./scripts/refresh-aws-credentials.sh` before
   re-running retrieve_* if you see token-expired errors.

6. **Sample variant in output paths**: The submission scripts now stamp the
   variant name into batch filenames and (for the live rerun) result filenames,
   so you can tell which run produced which file. Manifest entries carry a
   `sample_variant` field; legacy entries without it are treated as
   `sampled_100_seed42`.

7. **Multi-file loading**: The analysis and plotting scripts (`analyze_helio_v2_report.py`,
   `plot_substitution_decision_kappa.py`) read ALL `.jsonl` files per run directory.
   This was a bug prior to 2026-04-17 (only the first file was read). If results
   look like they ignore a sample variant, check that the loading code iterates
   over all files, not just `jsonl_files[0]`.

8. **GPT-5.4 batch partial failures**: OpenAI batches for GPT-5.4 show 5–16%
   failure rate (all HTTP 500 server errors — OpenAI-side, not content policy or
   context limit). Failures are **not fully random**: certain cases are more
   failure-prone than others (weakly correlated with prompt length), and
   mission_selection was hit hardest (16% vs ~5-8% for others). The
   `substantive_100_seed43` round was affected; the original `sampled_100_seed42`
   round was 100% clean — likely due to different server load conditions. The
   analysis scripts handle this via the `len(resps) == n_runs` filter — cases
   missing a run are simply excluded. Practical impact: N drops ~10-15% from the
   theoretical max of 200, landing at N≈170+ for most call types. To check error
   details for a batch: `client.batches.retrieve(batch_id)` shows `request_counts`
   and `error_file_id`; the error file contains per-request 500 responses.

9. **`.env` loading**: The submission/retrieval scripts read API keys from
   environment variables, NOT directly from `.env`. The recommended invocation
   pattern uses `dotenv.load_dotenv('.env')` in a wrapper (see Step 2). If you
   run scripts directly without loading `.env`, they'll fail with missing credentials.

10. **`VIRTUAL_ENV=` prefix**: When running via `.venv/bin/python`, unset
    `VIRTUAL_ENV` to avoid `uv` warnings about mismatched environments.
    Pattern: `VIRTUAL_ENV= .venv/bin/python script.py`.

---

## Future work: unified orchestrator

The current procedure requires 8 manual steps across multiple scripts. A future
`run_experiment.py` should consolidate into two phases:

```
# Phase 1: sample + submit
uv run python run_experiment.py submit \
    --test-set test_set_helio_v2_2026_04_06 \
    --config-a standard-gpt54 --config-b bedrock-120b-high

# Phase 2: retrieve + analyze + plot
uv run python run_experiment.py analyze \
    --test-set test_set_helio_v2_2026_04_06 \
    --config-a standard-gpt54 --config-b bedrock-120b-high
```

Design notes for the orchestrator:
- For call types whose handler returns a non-None `get_response_format()` (currently
  only `time_normalization`), the Bedrock batch API cannot apply litellm's
  `response_format → tool_use` translation. Rather than special-casing these,
  the orchestrator should use the **live-with-concurrency path** (async litellm
  calls, concurrency ~20) for any `(call_type, model)` pair where `response_format`
  is set. This eliminates the need for `rerun_bedrock_time_normalization_live.py`
  as a separate script.
- Alternatively, upgrading litellm past v1.70.4 may add native Bedrock batch
  support that handles `response_format` correctly. Check litellm changelog before
  building the workaround.
- The orchestrator should auto-detect which provider each model uses (OpenAI batch
  vs Bedrock batch vs live) rather than requiring separate submission scripts.

---

## Appendix: round history

| Date | Sample variant | Notes |
|---|---|---|
| 2026-04 (pre-paper) | `sampled_100_seed42` | Original random sample, N varied by null rate (cadence N=19, etc.) |
| 2026-04-16 | `substantive_100_seed43` | Top-up from substantive-only pool. Targets N≈200 post-merge for call types with high null rates. |
| 2026-04-17 | (merged analysis) | Retrieved all batches. Fixed multi-file loading bug in `analyze_helio_v2_report.py` and `plot_substitution_decision_kappa.py` (`jsonl_files[0]` → loop over all). Some GPT-5.4 batches had ~5% failure rate (physobs 24/500, time 31/500, wavelength 27/500). Cadence N=19→90, detector N=74→171, wavelength N=56→131. Regenerated figure + updated paper table. |
