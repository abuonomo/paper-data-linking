# Paper Data Linking — Design Pattern Tightening Recommendations

This document summarizes concrete, low‑risk improvements to tighten existing patterns and introduce better‑suited ones where helpful. It’s organized by concern with file pointers, rationale, and suggested actions.

## 1) Registries & Plugins

- Problem: Inconsistent versioning/lookup semantics across registries.
  - Files: `paper_data_linking/analyzers/registry.py`, `paper_data_linking/linkers/registry.py`, `paper_data_linking/analyzers/script_generator_registry.py`.
  - Action:
    - Unify API to `register(name, version="1.0", ...)`, `get(name, version=None)`, `list(versions=False)`.
    - Store all entries under `key = f"{name}:{version}"`; when `version=None`, select the latest or default.

- Problem: Script generator data source inferred from class name.
  - Files: `paper_data_linking/analyzers/script_generator_base.py`, `paper_data_linking/analyzers/vso_script_generator.py`.
  - Action:
    - Add explicit `data_source: ClassVar[str]` on generator classes; remove name‑based inference.

- Problem: Import‑side effects required for registration; fragile in larger deployments.
  - Action:
    - Option A: Keep decorators but add a “registry bootstrap” module that ensures imports in one place.
    - Option B (scalable): Use Python entry points for plugin discovery (optional long‑term).

## 2) Dependency Injection (DI)

- Problem: Mixed use of globals (`dspy.settings.configure(...)`) and constructor injection.
  - Files: `paper_data_linking/linkers/*/*.py`, `paper_data_linking/config/llm_config.py`.
  - Action:
    - Prefer constructor or factory injection for LM clients and LLM configurations.
    - Move global `dspy.settings.configure(...)` calls to a composition root (CLI/app entrypoint) and pass LMs or configs down.

- Problem: `websocket_callback` passed inconsistently.
  - Action:
    - Define a lightweight `ProgressReporter` protocol (callable[str]) or class; inject consistently via constructors.

## 3) Execution Safety

- Problem: Code execution performed in‑process; security scattered (Bandit checks + warning suppression).
  - Files: `paper_data_linking/evaluation/script_evaluation_tools.py`, `paper_data_linking/analyzers/implementations.py`.
  - Action:
    - Introduce `SafeExecutor` with Strategy:
      - Security policy (Bandit + allowlist of imports/modules),
      - Backend (subprocess default; in‑process only for tests),
      - Timeouts and output capture.
    - API: `execute(snippet: str) -> ExecutionResult {success, stdout, stderr, exception, diagnostics}`.
    - Centralize gevent warning suppression and bandit invocation inside the executor.

- Optional: Cache Bandit results by snippet hash to avoid re‑checks during refinement loops.

## 4) Pipelines

- Problem: `forward(...)` methods implement ad‑hoc multi‑step workflows without a common contract.
  - Files: `linkers/general/paper_analyzer.py`, `linkers/vso/modules/script_generator.py`, `linkers/general/modules/*`.
  - Action:
    - Define `PipelineStep` interface: `run(ctx: PipelineContext) -> PipelineContext`.
    - Define `PipelineContext` DTO (inputs, artifacts, errors, metadata).
    - Compose per use case (PaperAnalyzer = PDFText -> Instruments -> Quotes -> Annotation; VSO generator = Source/Instrument discovery -> Interface -> Codegen -> Validation).

## 5) Results & Models

- Problem: Analyzers return heterogeneous dicts; hard to validate downstream.
  - Files: `analyzers/implementations.py`, `analyzers/base.py`.
  - Action:
    - Introduce Pydantic result models per analyzer (e.g., `QuerySyntaxResult`, `QuerySecurityResult`, `QueryExecutionResult`) inheriting from a common base (`BaseAnalysisResult {ok, errors, analyzer_name, metadata}`).
    - Keep `StructuredInstrumentsOutput` pattern and replicate across analyzers for consistency.

## 6) Configuration

- Problem: Two sources of truth for LLM configuration (pydantic settings + `llm_config.py` globals).
  - Files: `config/settings.py`, `config/llm_config.py`.
  - Action:
    - Create `LMFactory` that builds configured `dspy.LM` instances from `AppSettings.llm_pipeline`.
    - Remove module‑level global LMs; get LMs from the factory at composition time or inject into modules.

- Problem: Env loading inside deep modules (e.g., `load_dotenv` in `direct_paper_analyzer.py`).
  - Action:
    - Load env exactly once in the CLI/app entrypoint; keep domain modules pure.

## 7) Facades / Adapters

- Problem: Callers parse LiteLLM response internals and hidden fields.
  - Files: `clients/litellm_client.py`.
  - Action:
    - Define an `LLMCallRecord` DTO containing: model, provider, tokens, cost, duration, input summary, output summary, kwargs.
    - Return both the raw response and `LLMCallRecord`, or just the record when raw isn’t needed.
    - Map provider errors to domain exceptions (`LLMRateLimitError`, `LLMAuthError`, `LLMTransientError`).

## 8) Prompt Handling

- Problem: Prompt rendering is utility‑style; hard to swap policies.
  - Files: `linkers/general/prompt_loader.py`, `linkers/general/direct_paper_analyzer.py`.
  - Action:
    - Introduce a Prompt Strategy interface: `render(context) -> (system, user)`.
    - Implement strategies per task (paper analysis, structured parsing); inject via DI.

## 9) Data Access & Caching

- Problem: JSON assets read in multiple places without a repository abstraction.
  - Files: `linkers/vso/modules/script_generator.py`, `data_assets/vso/*`.
  - Action:
    - Add `VSORepository` with memoized loads and typed accessors (instruments, sources, interface tables).
    - Surface filtered queries (by source/instrument) and return both data frame and serialized forms as needed.

## 10) Logging & Telemetry

- Problem: Token/cost tracking is pull‑based from `dspy` history; LiteLLM cost handling duplicated.
  - Files: `processing/token_tracker.py`, `clients/litellm_client.py`.
  - Action:
    - Convert to an observer/middleware that wraps LLM calls (both dspy and LiteLLM), recording token and cost per call.
    - Provide a single `TokenUsageReport` aggregated by model and by step; attach to pipeline results.

## 11) Testing & Lifecycle

- Problem: Decorator‑based registration creates global state that bleeds across tests.
  - Files: registries.
  - Action:
    - Provide `unregister(name, version=None)` and/or context manager to snapshot/restore registry state in tests.
    - Add Protocols (PEP 544) for analyzer/generator interfaces to enable fakes without inheritance.

## 12) Quick Wins (Low‑Risk)

- Explicit `data_source` on generators; remove class‑name inference.
- Make `DatasetUsageAnalyzerRegistry.register` idempotent with logging on version collisions.
- Normalize `forward(...)` to accept a single `PipelineContext` and return typed results (adapters can offer convenience overloads).
- Centralize Bandit invocation, timeouts, and optional result caching by snippet hash.

## Suggested Implementation Order (Incremental)

1) Safety & consistency
- Create `SafeExecutor`; refactor execution paths to use it.
- Add explicit `data_source` attributes; adjust the generator base and VSO implementation.

2) DI unification
- Introduce `LMFactory`; remove module‑level LM globals; inject via constructors.
- Standardize `websocket_callback` to a `ProgressReporter` protocol.

3) Results & registries
- Replace analyzer dict outputs with Pydantic result models.
- Unify registry versioning/lookup.

4) Pipelines & repos
- Add `PipelineContext` and a minimal `PipelineStep` interface; adapt two key flows.
- Introduce `VSORepository` for cached interface access.

5) Facade & telemetry
- Return `LLMCallRecord` from `LiteLLMClient` and wire TokenTracker as an observer.

## Notes on Backward Compatibility

- Preserve public method names and return shapes via adapter layers while incrementally migrating internal types.
- Keep registries accepting old `get(name)` signatures; deprecate in logs before switching to versioned lookups.
- Gate new executor backend behind a feature flag/env var for staged rollout.

---

If helpful, I can open small PRs implementing:
- `SafeExecutor` + refactor in `QueryExecutionAnalyzer` and `evaluation/script_evaluation_tools.py`.
- Explicit `data_source` in generator base + VSO generator.
- A minimal `LMFactory` and removal of module‑level LM globals where safe.
