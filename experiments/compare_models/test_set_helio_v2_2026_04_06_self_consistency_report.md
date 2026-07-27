# Self-Consistency Analysis: test_set_helio_v2_2026_04_06

**Test set**: `test_set_helio_v2_2026_04_06` (200 heliophysics papers)

**Runs per case**: 5 (temperature=1.0, reasoning_effort=high)

**Sample size**: 100 cases per call type (seed=42)

**Models analyzed**: bedrock_converse_openai_gpt-oss-120b-1_0, openai_gpt-5_4


## Summary Table

| Call Type | bedrock_converse_openai_gpt-oss-120b-1_0 κ | bedrock_converse_openai_gpt-oss-120b-1_0 perfect% | openai_gpt-5_4 κ | openai_gpt-5_4 perfect% | N |
|---|---|---|---|---|---|
| cadence_normalization | 0.942 | 91.0% | 0.974 | 96.6% | 177 |
| detector_normalization | 0.896 | 82.5% | 0.960 | 92.5% | 200 |
| instrument_selection | 0.941 | 89.0% | 0.985 | 97.5% | 200 |
| instrument_validation | 0.924 | 95.0% | 0.965 | 97.5% | 200 |
| mission_identification | 0.914 | 85.0% | 0.315 | 12.5% | 200 |
| mission_selection | 0.887 | 87.0% | 0.965 | 95.1% | 143 |
| mission_validation | 0.932 | 97.0% | 0.856 | 89.8% | 176 |
| physobs_normalization | 0.933 | 89.5% | 0.924 | 88.2% | 178 |
| time_normalization | 0.892 | 80.5% | 0.902 | 83.1% | 172 |
| wavelength_normalization | 0.975 | 95.0% | 0.966 | 93.7% | 175 |

## Substantive-Only View

Same metric, but cases where every run returned the model's null/refusal answer (e.g. `UNKNOWN`, `uncertain`, `not_applicable`, empty cadence list, null time range) are dropped. This strips out degenerate agreement on refusal so the kappa reflects only cases where the model actually tried to answer.

*Note*: `instrument_validation`, `mission_validation`, `mission_selection`, and `instrument_selection` have no natural null answer, so their numbers are identical to the main table.

| Call Type | bedrock_converse_openai_gpt-oss-120b-1_0 κ (sub) | bedrock_converse_openai_gpt-oss-120b-1_0 perfect% (sub) | bedrock_converse_openai_gpt-oss-120b-1_0 null% | openai_gpt-5_4 κ (sub) | openai_gpt-5_4 perfect% (sub) | openai_gpt-5_4 null% | N sub |
|---|---|---|---|---|---|---|---|
| cadence_normalization | 0.916 | 83.9% | 46.6% | 0.959 | 93.2% | 50.3% | 88 |
| detector_normalization | 0.879 | 79.0% | 24.8% | 0.952 | 90.6% | 24.0% | 160 |
| instrument_selection | 0.941 | 89.0% | 0.0% | 0.985 | 97.5% | 0.0% | 200 |
| instrument_validation | 0.924 | 95.0% | 0.0% | 0.965 | 97.5% | 0.0% | 200 |
| mission_identification | 0.889 | 79.9% | 27.0% | 0.254 | 3.3% | 13.9% | 181 |
| mission_selection | 0.887 | 87.0% | 0.0% | 0.965 | 95.1% | 0.0% | 143 |
| mission_validation | 0.932 | 97.0% | 0.0% | 0.856 | 89.8% | 0.0% | 176 |
| physobs_normalization | 0.928 | 88.9% | 8.4% | 0.917 | 87.3% | 13.3% | 165 |
| time_normalization | 0.894 | 80.9% | 3.4% | 0.921 | 84.9% | 3.6% | 166 |
| wavelength_normalization | 0.970 | 93.6% | 22.9% | 0.956 | 91.3% | 28.5% | 126 |

## Reliability Hotspots

### bedrock_converse_openai_gpt-oss-120b-1_0

**Lowest kappa (least self-consistent)**:

- `mission_selection`: κ=0.887, parse_rate=100.0%, perfect=87.0%
- `time_normalization`: κ=0.892, parse_rate=99.5%, perfect=80.5%
- `detector_normalization`: κ=0.896, parse_rate=100.0%, perfect=82.5%

**Lowest parse rate**:

- `time_normalization`: parse_rate=99.5%, κ=0.892
- `cadence_normalization`: parse_rate=100.0%, κ=0.942
- `detector_normalization`: parse_rate=100.0%, κ=0.896

### openai_gpt-5_4

**Lowest kappa (least self-consistent)**:

- `mission_identification`: κ=0.315, parse_rate=100.0%, perfect=12.5%
- `mission_validation`: κ=0.856, parse_rate=100.0%, perfect=89.8%
- `time_normalization`: κ=0.902, parse_rate=100.0%, perfect=83.1%

**Lowest parse rate**:

- `cadence_normalization`: parse_rate=100.0%, κ=0.974
- `detector_normalization`: parse_rate=100.0%, κ=0.960
- `instrument_selection`: parse_rate=100.0%, κ=0.985

## Realized Cost & Tokens (from retrieved results)

| Model | Total cost (USD) | Total tokens |
|---|---|---|
| bedrock_converse_openai_gpt-oss-120b-1_0 | $0.00 | 22,997,870 |
| openai_gpt-5_4 | $0.00 | 21,621,799 |

## Deviations from Plan

- **Bedrock configuration dropped**: The `bedrock-120b-high` side of the A/B comparison could not be submitted because `litellm.acreate_file()` does not support the `bedrock` provider. Bedrock batch inference uses a different API (S3 + `create_model_invocation_job`) that litellm has not implemented. All 9 Bedrock batch submissions failed at the upload step; only `standard-gpt54` (openai/gpt-5.4) results are available. The side-by-side comparison the plan called for is therefore not possible from this run.
- **`reasoning_effort` fix**: `prepare_batch_file` was patched to forward `reasoning_effort` in the per-request body (previously silently dropped). All batches ran with `reasoning_effort=high`.
- **Registry fix**: `CallTypeRegistry.register()` was made idempotent (last-registered wins) so that `WavelengthNormalizationHandler` and `WavelengthNormalizationSimpleHandler`, which share the same `call_type_name`, can coexist in `handlers/__init__.py`. Without this, `batch_runner.py` could not be imported at all.
- **Added 10th call type**: `mission_validation` was added at user request (not in the original plan) since it had 2970 calls in the test set.
- **Sandbox filesystem write corruption**: intermittent contiguous null-byte blocks in large batch JSONL files (~8MB). Worked around with a fallback cost estimate in the driver; batches uploaded to OpenAI were healthy (OpenAI would have rejected corrupt JSONL).

## Per-Call-Type Detail

### cadence_normalization

**bedrock_converse_openai_gpt-oss-120b-1_0**:
- Fleiss' kappa: `0.9420`
- Parse rate: `100.00%`
- Perfect consistency: `91.0%`
- Complete cases: 200/200
- Total cost: $0.0000
- Total tokens: 1,863,701

**openai_gpt-5_4**:
- Fleiss' kappa: `0.9738`
- Parse rate: `100.00%`
- Perfect consistency: `96.6%`
- Complete cases: 177/200
- Total cost: $0.0000
- Total tokens: 1,441,505

### detector_normalization

**bedrock_converse_openai_gpt-oss-120b-1_0**:
- Fleiss' kappa: `0.8961`
- Parse rate: `100.00%`
- Perfect consistency: `82.5%`
- Complete cases: 200/200
- Total cost: $0.0000
- Total tokens: 1,342,114

**openai_gpt-5_4**:
- Fleiss' kappa: `0.9603`
- Parse rate: `100.00%`
- Perfect consistency: `92.5%`
- Complete cases: 200/200
- Total cost: $0.0000
- Total tokens: 1,031,491

### instrument_selection

**bedrock_converse_openai_gpt-oss-120b-1_0**:
- Fleiss' kappa: `0.9411`
- Parse rate: `100.00%`
- Perfect consistency: `89.0%`
- Complete cases: 200/200
- Total cost: $0.0000
- Total tokens: 2,213,550

**openai_gpt-5_4**:
- Fleiss' kappa: `0.9849`
- Parse rate: `100.00%`
- Perfect consistency: `97.5%`
- Complete cases: 200/200
- Total cost: $0.0000
- Total tokens: 1,873,790

### instrument_validation

**bedrock_converse_openai_gpt-oss-120b-1_0**:
- Fleiss' kappa: `0.9237`
- Parse rate: `100.00%`
- Perfect consistency: `95.0%`
- Complete cases: 200/200
- Total cost: $0.0000
- Total tokens: 3,118,260

**openai_gpt-5_4**:
- Fleiss' kappa: `0.9650`
- Parse rate: `100.00%`
- Perfect consistency: `97.5%`
- Complete cases: 200/200
- Total cost: $0.0000
- Total tokens: 2,593,041

### mission_identification

**bedrock_converse_openai_gpt-oss-120b-1_0**:
- Fleiss' kappa: `0.9135`
- Parse rate: `100.00%`
- Perfect consistency: `85.0%`
- Complete cases: 200/200
- Total cost: $0.0000
- Total tokens: 6,519,501

**openai_gpt-5_4**:
- Fleiss' kappa: `0.3147`
- Parse rate: `100.00%`
- Perfect consistency: `12.5%`
- Complete cases: 200/200
- Total cost: $0.0000
- Total tokens: 8,193,234

### mission_selection

**bedrock_converse_openai_gpt-oss-120b-1_0**:
- Fleiss' kappa: `0.8870`
- Parse rate: `100.00%`
- Perfect consistency: `87.0%`
- Complete cases: 200/200
- Total cost: $0.0000
- Total tokens: 2,154,724

**openai_gpt-5_4**:
- Fleiss' kappa: `0.9647`
- Parse rate: `100.00%`
- Perfect consistency: `95.1%`
- Complete cases: 143/200
- Total cost: $0.0000
- Total tokens: 1,634,321

### mission_validation

**bedrock_converse_openai_gpt-oss-120b-1_0**:
- Fleiss' kappa: `0.9317`
- Parse rate: `100.00%`
- Perfect consistency: `97.0%`
- Complete cases: 200/200
- Total cost: $0.0000
- Total tokens: 2,260,769

**openai_gpt-5_4**:
- Fleiss' kappa: `0.8562`
- Parse rate: `100.00%`
- Perfect consistency: `89.8%`
- Complete cases: 176/200
- Total cost: $0.0000
- Total tokens: 1,960,453

### physobs_normalization

**bedrock_converse_openai_gpt-oss-120b-1_0**:
- Fleiss' kappa: `0.9331`
- Parse rate: `100.00%`
- Perfect consistency: `89.5%`
- Complete cases: 200/200
- Total cost: $0.0000
- Total tokens: 1,303,583

**openai_gpt-5_4**:
- Fleiss' kappa: `0.9245`
- Parse rate: `100.00%`
- Perfect consistency: `88.2%`
- Complete cases: 178/200
- Total cost: $0.0000
- Total tokens: 930,831

### time_normalization

**bedrock_converse_openai_gpt-oss-120b-1_0**:
- Fleiss' kappa: `0.8923`
- Parse rate: `99.50%`
- Perfect consistency: `80.5%`
- Complete cases: 200/200
- Total cost: $0.0000
- Total tokens: 987,209

**openai_gpt-5_4**:
- Fleiss' kappa: `0.9022`
- Parse rate: `100.00%`
- Perfect consistency: `83.1%`
- Complete cases: 172/200
- Total cost: $0.0000
- Total tokens: 981,561

### wavelength_normalization

**bedrock_converse_openai_gpt-oss-120b-1_0**:
- Fleiss' kappa: `0.9755`
- Parse rate: `100.00%`
- Perfect consistency: `95.0%`
- Complete cases: 200/200
- Total cost: $0.0000
- Total tokens: 1,234,459

**openai_gpt-5_4**:
- Fleiss' kappa: `0.9661`
- Parse rate: `100.00%`
- Perfect consistency: `93.7%`
- Complete cases: 175/200
- Total cost: $0.0000
- Total tokens: 981,572
