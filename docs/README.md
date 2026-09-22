# Documentation

## For users and operators

| Document | What it covers |
|---|---|
| [PUBLIC_API.md](PUBLIC_API.md) | The read-only public API: query validated data references by paper, mission, instrument, and time range; bulk CSV export; generated SunPy snippets. No account needed. |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Running a production instance with Docker Compose, image registry, and reverse proxy. |
| [EXTENDING_DATA_SOURCES.md](EXTENDING_DATA_SOURCES.md) | Adding a new data archive: the normalizer, script-generator, and analyzer registry pattern. |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Development setup, environment variables, tests, pull-request process. |
| [vision/](vision/) | Project vision materials and infographic. |

An OpenAPI schema for the public endpoints is served by a running instance at `/builder/schema/` (Swagger UI at `/builder/schema/swagger/`).

## Internal design and experiment notes

Historical notes kept for reference. They describe the state of the system at the time they were written and are not maintained.

| Document | What it covers |
|---|---|
| [internal/llm_call_testing.md](internal/llm_call_testing.md) | Exporting recorded LLM calls to JSONL fixtures and validating them offline. |
| [internal/llm_call_dependency_tracing.md](internal/llm_call_dependency_tracing.md) | Design for span/DAG tracing of LLM calls. |
| [internal/quote_location_search.md](internal/quote_location_search.md) | The quote-location (PDF coordinate) algorithm and its diagnostics. |
| [internal/end_to_end_disagreement_analysis.md](internal/end_to_end_disagreement_analysis.md) | Comparison of two LLM configurations on a 200-paper test set. |
| [internal/test_set_helio_v2_2026_04_06.md](internal/test_set_helio_v2_2026_04_06.md) | Construction of the v2 evaluation set. |
| [internal/helio_non_helio_classification_results.md](internal/helio_non_helio_classification_results.md) | Results of the heliophysics / non-heliophysics paper classifier. |
| [internal/normalization_test_data_export_plan.md](internal/normalization_test_data_export_plan.md) | Plan for exporting normalization test data from production. |
| [internal/patterns_refactor_recommendations.md](internal/patterns_refactor_recommendations.md) | Design and refactoring recommendations. |
| [internal/validation_parser_regex_bug.md](internal/validation_parser_regex_bug.md) | Writeup of a validation-handler regex bug. |
