"""One paper, start to finish: step 1 -> structuring -> grounding + normalization.

This is the same sequence the Django tasks run (``analyze_paper_task``,
``analyze_paper_instruments_structure``, ``normalize_structured_instrument_details``)
with the library classes unchanged and the database writes replaced by one JSON line.
The three fields it produces are exactly what ``PaperAnalysis`` stores, so a result
line can be imported and turned into DatasetUsages without calling a model again.
"""

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from paper_data_linking.config.settings import get_llm_configuration
from paper_data_linking.linkers.general.deterministic_structure_analyzer import DeterministicStructureAnalyzer
from paper_data_linking.linkers.general.direct_paper_analyzer import DirectPaperAnalyzer
from paper_data_linking.linkers.general.instrument_grounder import InstrumentGrounder
from paper_data_linking.linkers.general.structured_normalizer import StructuredNormalizer
from paper_data_linking.processing.text_validation import TextValidationError, validate_text_length

from . import __version__
from .client import CallRecorder, EndpointDown, ModelRequestError, Transport, VLLMClient
from .sources import PaperRecord
from .step1_checks import step1_problem
from .store import ShardWriter

logger = logging.getLogger(__name__)

OK, FAILED, ABORTED = "ok", "failed", "aborted"


@dataclass
class Outcome:
    status: str
    bibcode: str
    reason: Optional[str] = None
    stats: Dict[str, Any] = field(default_factory=dict)


def prompts_hash() -> str:
    """Hash of every prompt template, recorded with each result so outputs can be
    tied to the prompt text that produced them."""
    from paper_data_linking.linkers.general import prompt_loader

    digest = hashlib.sha256()
    prompts_dir = Path(prompt_loader.__file__).parent / "prompts"
    for path in sorted(prompts_dir.rglob("*.xml")):
        digest.update(path.relative_to(prompts_dir).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PaperPipeline:
    """Runs papers against one endpoint. Shared by a worker's threads; all per-paper
    state lives in ``run()``."""

    def __init__(
        self,
        config_name: str,
        finder,
        transport: Transport,
        results: ShardWriter,
        step1: ShardWriter,
        failures: ShardWriter,
        calls: Optional[ShardWriter] = None,
        call_log: str = "meta",
        max_step1_attempts: int = 3,
    ):
        self.config_name = config_name
        self.llm_config = get_llm_configuration(config_name)
        self.finder = finder
        self.transport = transport
        self.results, self.step1, self.failures, self.calls = results, step1, failures, calls
        self.call_log = call_log
        self.max_step1_attempts = max_step1_attempts
        # For the last step-1 attempt of a paper whose answers keep coming back empty.
        self.llm_config_no_stop = None
        if self.llm_config.paper_analysis.stop:
            self.llm_config_no_stop = self.llm_config.model_copy(
                update={"paper_analysis": self.llm_config.paper_analysis.model_copy(update={"stop": None})}
            )
        self.versions = {
            "runner": __version__,
            "catalog": getattr(finder, "version", None),
            "prompts": prompts_hash(),
            "model": transport.model_override or self.llm_config.paper_analysis.model,
        }

    def close(self) -> None:
        for writer in (self.results, self.step1, self.failures, self.calls):
            if writer is not None:
                writer.close()

    def run(self, record: PaperRecord) -> Outcome:
        recorder = CallRecorder(record.bibcode, self.calls, self.call_log)
        client = VLLMClient(self.transport, recorder)
        started = time.monotonic()
        try:
            return self._run(record, client, recorder, started)
        except EndpointDown as e:
            logger.warning("Paper %s aborted: %s", record.bibcode, e)
            return Outcome(ABORTED, record.bibcode, str(e), recorder.stats())

    def _fail(self, record: PaperRecord, reason: str, detail: str, recorder: CallRecorder) -> Outcome:
        self.failures.write({
            "bibcode": record.bibcode, "config": self.config_name, "reason": reason, "detail": detail[:2000],
            "stats": recorder.stats(), "failed_at": _now(),
        })
        return Outcome(FAILED, record.bibcode, reason, recorder.stats())

    def _run(self, record: PaperRecord, client: VLLMClient, recorder: CallRecorder, started: float) -> Outcome:
        if not (record.text or "").strip():
            return self._fail(record, "empty_text", "", recorder)
        try:
            validate_text_length(record.text, record.bibcode)
        except TextValidationError as e:
            return self._fail(record, "text_too_long", str(e), recorder)

        instruments_details = record.step1
        step1_attempts = 0
        if instruments_details is None:
            analyzer = DirectPaperAnalyzer(llm_client=client, llm_config=self.llm_config)
            problem = None
            while step1_attempts < self.max_step1_attempts:
                step1_attempts += 1
                if problem == "empty" and step1_attempts == self.max_step1_attempts and self.llm_config_no_stop is not None:
                    # Some papers draw the stop sequence as the first token every time, and
                    # most such answers go on to a normal form. Let the last attempt run
                    # without the stop; one that loops instead is caught by the checks.
                    analyzer = DirectPaperAnalyzer(llm_client=client, llm_config=self.llm_config_no_stop)
                try:
                    answer = analyzer.forward(record.text, None).instruments_details
                except ModelRequestError as e:
                    reason = "context_too_long" if "context length" in str(e).lower() else "step1_request_error"
                    return self._fail(record, reason, str(e), recorder)
                problem = step1_problem(answer, recorder.last["paper_analysis"]["finish_reason"])
                if problem is None:
                    instruments_details = answer
                    break
            if instruments_details is None:
                return self._fail(record, "step1_broken", f"{problem} after {step1_attempts} attempts", recorder)
            self.step1.write({"bibcode": record.bibcode, "config": self.config_name, "instruments_details": instruments_details})

        try:
            structured = DeterministicStructureAnalyzer(llm_client=client, llm_config=self.llm_config).forward(instruments_details)
            if not structured.success:
                return self._fail(record, "structure_error", str(structured.error_message), recorder)
            structured_data = structured.structured_data
        except Exception as e:
            return self._fail(record, "structure_error", f"{type(e).__name__}: {e}", recorder)

        try:
            grounder = InstrumentGrounder(finder=self.finder, llm_client=client, llm_config=self.llm_config)
            normalizer = StructuredNormalizer(instrument_grounder=grounder, llm_client=client, llm_config=self.llm_config)
            # No PDF: quote coordinates are a review-UI concern and are filled in after import.
            normalized = normalizer.forward(structured_data, pdf_path=None)
        except Exception as e:
            return self._fail(record, "normalize_error", f"{type(e).__name__}: {e}", recorder)

        stats = recorder.stats()
        stats["step1_attempts"] = step1_attempts
        stats["seconds"] = round(time.monotonic() - started, 1)
        self.results.write({
            "bibcode": record.bibcode,
            "config": self.config_name,
            "instruments_details": instruments_details,
            "structured_instruments_details": structured_data,
            "normalized_instrument_details": normalized,
            "meta": record.meta,
            "stats": stats,
            "versions": self.versions,
            "finished_at": _now(),
        })
        return Outcome(OK, record.bibcode, None, stats)
