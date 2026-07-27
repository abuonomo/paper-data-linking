LLMCall Fixture Testing

This repository records LLM calls (table `api.vso_query_builder.models.LLMCall`) and can export them to JSONL for offline validation. This document describes how to validate recorded calls per `call_type` using pytest.

- Export fixtures: `python manage.py export_llm_calls --call-type time_normalization --config standard --output experiments/time_model_evaluation/test_standard_time_norm.jsonl`
- Run tests: `pytest -k llm_call` validates any discovered fixtures with registered validators.

Adding a validator
- Implement a validator in `paper_data_linking/testing/validators.py` and register it in the `registry` under the exact `call_type` string stored in `LLMCall.call_type`.
- For simple shape checks, use `make_json_schema_validator(call_type, required_keys)`.
- Place exported fixtures under `experiments/**` or `tests/fixtures/**` with a filename containing the `call_type`.

Time normalization
- The `time_normalization` validator ensures output JSON contains required keys, dates are ISO 8601 Z instants, Unix epoch defaults are never used, and start <= end when both present.

Notes
- The same framework works for other call types (e.g., `wavelength`, `final_grounding`, `validation`). Start with shape checks, then layer domain invariants.
- Validators run offline on recorded outputs; they do not perform live LLM calls.

