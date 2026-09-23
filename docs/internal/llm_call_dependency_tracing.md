LLM Call Dependency Tracing Plan

- Goal: Represent dependencies between LLM calls and compute steps as a DAG, then visualize as a branching tree on the frontend with minimal code changes.
- Approach: Add a tiny tracing module (spans + context propagation) and lightly instrument key steps and the LLM client. No refactor of business logic required.

**Key Concepts**
- **Span**: A node in the graph representing a meaningful step (e.g., `identify_missions`, `instrument_selection`) or an LLM call (e.g., `llm:mission_selection`). Spans have a name, type, status, timing, and tags. Each span has a parent, forming a DAG.
- **contextvars**: Python’s safe way to carry “current span” and “current trace” across call stacks (and across async tasks) without passing parameters everywhere. When you enter a span, it becomes the current parent for anything inside (including nested spans and LLM calls).
- **DAG**: Parent-child edges form a Directed Acyclic Graph. Sequential steps become a chain; loop iterations (e.g., per-data-system branches in Instrument Grounder) become sibling branches.

**API Surface**
- `start_trace(name, tags={}) -> trace_id`: Open a trace and create the root span context.
- `with span(name, type="step", tags={})`: Create a child span of the current span; on exit, duration and status are finalized.
- `record_llm(call_type, model, usage, cost, status, tags={})`: Convenience called from the LLM client to create an `llm` span under the active span.
- `flush_to_json(path)` / DB adapter: Export nodes/edges after a run.

---

Minimal Tracing Module (pseudocode)

```python
# tracing.py (self-contained, no external deps)
import time, uuid, contextvars
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any

_current_trace_id = contextvars.ContextVar("current_trace_id", default=None)
_current_span_id  = contextvars.ContextVar("current_span_id", default=None)

@dataclass
class SpanNode:
    id: str
    parent_id: Optional[str]
    trace_id: str
    name: str
    type: str               # "step" | "llm"
    status: str = "ok"      # "ok" | "error"
    started_at_ms: int = 0
    duration_ms: int = 0
    tags: Dict[str, Any] = field(default_factory=dict)

class Recorder:
    def __init__(self):
        self.nodes: List[SpanNode] = []

    def add(self, node: SpanNode):
        self.nodes.append(node)

    def flush_to_json(self, path: str):
        import json
        with open(path, "w") as f:
            json.dump({
                "nodes": [n.__dict__ for n in self.nodes],
                "edges": [
                    {"sourceId": n.parent_id, "targetId": n.id}
                    for n in self.nodes if n.parent_id
                ],
            }, f, indent=2)

recorder = Recorder()

def now_ms() -> int:
    return int(time.time() * 1000)

def start_trace(name: str, tags: Dict[str, Any] = {}) -> str:
    trace_id = str(uuid.uuid4())
    root_id = str(uuid.uuid4())
    _current_trace_id.set(trace_id)
    _current_span_id.set(root_id)
    recorder.add(SpanNode(
        id=root_id, parent_id=None, trace_id=trace_id,
        name=name, type="step", started_at_ms=now_ms(), tags=tags
    ))
    return trace_id

class span:
    def __init__(self, name: str, type: str = "step", tags: Dict[str, Any] = {}):
        self.name = name
        self.type = type
        self.tags = tags
        self.node: Optional[SpanNode] = None
        self.token = None

    def __enter__(self):
        parent_id = _current_span_id.get()
        trace_id = _current_trace_id.get()
        if not trace_id:
            # No active trace; act as a no-op context manager
            return self
        self.node = SpanNode(
            id=str(uuid.uuid4()),
            parent_id=parent_id,
            trace_id=trace_id,
            name=self.name,
            type=self.type,
            started_at_ms=now_ms(),
            tags=self.tags.copy(),
        )
        recorder.add(self.node)
        self.token = _current_span_id.set(self.node.id)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.node:
            self.node.duration_ms = now_ms() - self.node.started_at_ms
            if exc_type is not None:
                self.node.status = "error"
                self.node.tags["exception"] = str(exc)
        if self.token is not None:
            _current_span_id.reset(self.token)

def is_active() -> bool:
    return _current_trace_id.get() is not None

def record_llm(call_type: str, model: str, usage: Dict[str, int],
               cost: float, status: str = "ok", tags: Dict[str, Any] = {}):
    # Create an llm span as a child of current span
    with span(name=f"llm:{call_type}", type="llm",
              tags={**tags, "call_type": call_type, "model": model,
                    "usage": usage, "cost_usd": cost, "status": status}):
        pass  # Span timing is recorded; details are in tags
```

Notes on contextvars

- `contextvars` provide request/task-local state. When you enter `with span(...)`, the current span id is set in a `ContextVar`. Any function called inside (including the LLM client) can read the active span without explicitly receiving it as a parameter. This avoids invasive function signature changes and works with async code out-of-the-box.
- If you later parallelize with threads/processes, use `contextvars.copy_context()` or pass `trace_id`/`span_id` explicitly into the worker to retain the parent-child link.

---

LiteLLMClient Hook (example)

```python
# in paper_data_linking/clients/litellm_client.py
from paper_data_linking import tracing  # wherever you place tracing.py

def completion(self, call_type: str, model: str, messages: List[Dict[str, str]], **kwargs):
    start = time.time()
    try:
        response = litellm.completion(model=model, messages=messages, **kwargs)
        duration_ms = int((time.time() - start) * 1000)
        usage = {
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            "total_tokens": response.usage.total_tokens if response.usage else 0,
            "duration_ms": duration_ms,
        }
        cost = self._calculate_cost(response)
        if tracing.is_active():
            tracing.record_llm(
                call_type=call_type,
                model=model,
                usage=usage,
                cost=cost,
                status="ok",
                tags={"provider": model.split("/")[0] if "/" in model else "unknown"}
            )
        return response
    except Exception as e:
        if tracing.is_active():
            tracing.record_llm(
                call_type=call_type,
                model=model,
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                cost=0.0,
                status="error",
                tags={"error": str(e)}
            )
        raise
```

Why this hook?

- It uses the existing `call_type` already present in your client, so it requires no changes to call sites.
- When tracing is active, every LLM call becomes an `llm` span, nested under whichever step span is currently open, preserving dependencies automatically.

---

InstrumentGrounder Instrumentation (example)

Wrap orchestration steps. The LLM client automatically attaches `llm` spans to the currently active step.

```python
# in InstrumentGrounder.ground_instrument(...)
from paper_data_linking.tracing import start_trace, span, recorder

def ground_instrument(self, instrument_entry: dict):
    instrument_name = instrument_entry.get("name", "Unknown")
    trace_id = start_trace("instrument_grounding", {"instrument": instrument_name})

    with span("parallel_grounding", type="step"):
        available_data_systems = self.finder.get_available_data_systems()
        for ds in available_data_systems:
            with span(f"data_system:{ds}", type="step", tags={"data_system": ds}):
                self._ground_instrument_for_data_system(instrument_entry, ds)

    # Optionally, export after the run (or use a DB adapter)
    # recorder.flush_to_json(f"/tmp/trace_{trace_id}.json")
    return self._ground_instrument_parallel(instrument_entry)
```

Bracket the sequential chain inside a data system so dependencies are explicit:

```python
def _ground_instrument_for_data_system(self, instrument_entry: dict, data_system: str):
    with span("identify_missions", tags={"data_system": data_system}):
        candidate_mission_names = self._identify_missions_with_nano_for_data_system(
            instrument_entry, data_system, top_k=10)

    with span("select_final_mission", tags={"n_candidates": len(candidate_mission_names)}):
        selected_missions = self._select_final_mission(instrument_entry, candidate_mission_names)

    with span("filter_catalog", tags={"n_missions": len(selected_missions or [])}):
        filtered_catalog = self._filter_catalog_by_mission_names_for_data_system(selected_missions, data_system)

    with span("select_final_instrument", tags={"n_candidates": len(filtered_catalog or [])}):
        selected_result = self._select_final_instrument(instrument_entry, filtered_catalog)

    with span("validate_entries", tags={"n_selected": len(selected_result or [])}):
        return self._validate_catalogue_entries(instrument_entry, selected_result)
```

Result: Sequential steps form a chain in the DAG; each per-data-system branch becomes a sibling subtree; LLM calls appear under the step that triggered them.

---

Output Schema (for Frontend)

Simple JSON your UI can render as a branching tree:

```json
{
  "nodes": [
    {
      "id": "root",
      "parent_id": null,
      "trace_id": "abc",
      "name": "instrument_grounding",
      "type": "step",
      "status": "ok",
      "started_at_ms": 1736530000000,
      "duration_ms": 820,
      "tags": {"instrument": "AIA"}
    },
    {
      "id": "n1",
      "parent_id": "root",
      "trace_id": "abc",
      "name": "parallel_grounding",
      "type": "step",
      "status": "ok",
      "started_at_ms": 1736530000100,
      "duration_ms": 780,
      "tags": {}
    },
    {
      "id": "n2",
      "parent_id": "n1",
      "trace_id": "abc",
      "name": "data_system:SDO",
      "type": "step",
      "status": "ok",
      "started_at_ms": 1736530000150,
      "duration_ms": 500,
      "tags": {"data_system": "SDO"}
    },
    {
      "id": "n3",
      "parent_id": "n2",
      "trace_id": "abc",
      "name": "identify_missions",
      "type": "step",
      "status": "ok",
      "started_at_ms": 1736530000200,
      "duration_ms": 200,
      "tags": {}
    },
    {
      "id": "n4",
      "parent_id": "n3",
      "trace_id": "abc",
      "name": "llm:mission_identification",
      "type": "llm",
      "status": "ok",
      "started_at_ms": 1736530000250,
      "duration_ms": 180,
      "tags": {
        "call_type": "mission_identification",
        "model": "openai/gpt-4.1-mini",
        "usage": {"total_tokens": 450},
        "cost_usd": 0.0021
      }
    }
  ],
  "edges": [
    {"sourceId": "root", "targetId": "n1"},
    {"sourceId": "n1", "targetId": "n2"},
    {"sourceId": "n2", "targetId": "n3"},
    {"sourceId": "n3", "targetId": "n4"}
  ]
}
```

Frontend Visualization

- Render the root (`instrument_grounding: AIA`) with children:
  - `parallel_grounding`
    - `data_system: SDO` → `identify_missions` → `llm:mission_identification` → …
    - `data_system: SOHO` → …
- Node badges from tags: `call_type`, `model`, `tokens`, `cost`, `status`.
- Layout: left-to-right layered tree to emphasize sequence vs. sibling branches.

---

Why This Design

- Minimal changes: add a small `tracing.py`, a thin hook in `LiteLLMClient`, and a few `with span(...)` blocks in orchestration code.
- Accurate dependencies: sequential steps chain; per-data-system loops appear as independent branches; LLM calls attach under the relevant step.
- Decoupled and future-proof: no coupling to Django; JSON export now, DB adapter later; mirrors OpenTelemetry so you can swap in OTel exporters if you want.

Parallelism Note

- Current per-data-system loop is sequential, but spans still model the logical parallelism as sibling branches.
- If you later parallelize with threads/processes, use `contextvars.copy_context()` or pass `trace_id`/`span_id` explicitly to maintain parent-child links.

Adoption Plan

- Phase 1 (scaffold): Add `tracing.py` with `span`, `start_trace`, `record_llm`, and an in-memory `recorder`. Add a no-op import in `LiteLLMClient` and guard with `is_active()` so behavior is unchanged until a trace is started.
- Phase 2 (instrumentation): Wrap `InstrumentGrounder` root, per-data-system blocks, and sequential steps with `with span(...)`. The LLM client auto-records LLM nodes under the active step.
- Phase 3 (expose graph): Export traces to JSON and have the frontend fetch and render as a branching tree. You can also add a lightweight endpoint to serve the JSON.
- Phase 4 (persist): Optional DB adapter to persist spans/edges and cross-link to your `LLMCall` table (e.g., add `trace_id` and `parent_call_id`).

Future Enhancements

- Error detail: Mark spans `status=error` on exceptions; include exception strings in tags.
- Deterministic IDs: Add a per-trace incremental `span_seq` to simplify UI ordering.
- Sampling: Allow sampling traces to reduce overhead in production.
- Cross-pipeline traces: Apply the same pattern to time normalization, detector normalization, and other pipelines for end-to-end graphs.

