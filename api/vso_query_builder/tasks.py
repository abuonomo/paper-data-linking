# tasks.py

import dateutil.parser
import logging
import os
import pytz
from celery import shared_task, group, chain, chord
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.postgres.fields.ranges import DateTimeTZRange
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction, connection
from functools import wraps

from paper_data_linking.config import constants, paths
from paper_data_linking.linkers.general.direct_paper_analyzer import DirectPaperAnalyzer
from paper_data_linking.linkers.general.structured_instruments_analyzer import StructuredInstrumentsAnalyzer
from paper_data_linking.linkers.general.deterministic_structure_analyzer import DeterministicStructureAnalyzer
from paper_data_linking.processing.text_extractor import PDFTextExtractor
from paper_data_linking.processing.pdf_annotator import annotate_pdf
from paper_data_linking.processing.text_validation import validate_text_length, TextValidationError
from paper_data_linking.analyzers import DatasetUsageAnalyzerRegistry, DatasetUsageSnippetGenerator, UnsupportedDataSourceError
from paper_data_linking.pipeline_context import current_pipeline_node, current_node_factory
from .ads_service import ADSService
from .clients import DjangoLiteLLMClient
from .factories import get_structured_normalizer, get_django_structured_normalizer
from .models import (
    Paper, PaperAnalysis, SupportQuote,
    DataSource, Observatory, Instrument, DatasetUsage,
    DatasetUsageAnalysis, QuoteCategory, QuoteUsageLink, BatchJob, PipelineNode,
    InstrumentMention, CatalogSource,
    Phenomenon, PhenomenonMention, PhenomenonMentionValidation,
)
from .pipeline import make_node_factory
from .utils.resolver import resolve_observatory
from .utils.storage import read_pdf_bytes
from .quote_categorization import categorize_quote_from_parameter, create_categorized_quote_usage_links
from .signals import create_embedding as _create_embedding_signal

logger = logging.getLogger(__name__)


def close_db_connection(func):
    """Decorator to ensure DB connections are closed after task execution"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            connection.close()
    return wrapper


def _in_corpus_mode_commit() -> bool:
    """True iff we are inside a batch COMMIT replay for a corpus_mode run.
    Gates the storage/latency-lean behaviors (coordinate skip, deferred
    embeddings) so interactive and research runs are untouched."""
    from paper_data_linking.pipeline_context import get_pipeline_mode, current_batch_run_id
    if get_pipeline_mode() != 'commit':
        return False
    run_id = current_batch_run_id.get()
    if not run_id:
        return False
    from .clients import _run_is_corpus_mode
    return _run_is_corpus_mode(str(run_id))


# ----------------------------
# Text Extraction Tasks
# ----------------------------
@shared_task(soft_time_limit=150, time_limit=180)
def extract_paper_text_task(paper_id, allow_ocr=True):
    """Extract text from paper's PDF (runs on the prefork `cpu` queue; a malformed
    PDF or slow OCR is bounded by the soft/hard time_limit).

    allow_ocr=False (bulk/corpus default) skips the slow tesseract fallback — a
    scanned PDF is left without text rather than OCR'd."""
    try:
        paper = Paper.objects.get(id=paper_id)
        if not paper.pdf:
            logger.error(f"No PDF found for paper {paper_id}")
            return False

        extractor = PDFTextExtractor()
        text, used_ocr = extractor.extract_text(read_pdf_bytes(paper.pdf), allow_ocr=allow_ocr)
        if not text:
            logger.warning(
                "No embedded text for paper %s (OCR %s); leaving unextracted",
                paper_id, "disabled" if not allow_ocr else "yielded nothing")
            return False
        paper.full_text = text
        paper.used_ocr = used_ocr
        paper.save(update_fields=['full_text', 'used_ocr'])
        return True

    except Exception as e:
        logger.exception(f"Failed extracting text from PDF {paper_id}")
        return False


# ----------------------------
# Paper Analysis Tasks
# ----------------------------
@shared_task
@close_db_connection
def analyze_paper_task(paper_id, configuration_name):
    """Analyze a single paper with specified LLM configuration"""
    try:
        paper = Paper.objects.get(id=paper_id)
        
        # Validate text length before processing
        if paper.full_text:
            try:
                validate_text_length(paper.full_text, str(paper_id))
                logger.info(f"Text validation passed for paper {paper_id}")
            except TextValidationError as e:
                logger.error(f"Text validation failed for paper {paper_id}: {e}")
                # Create a failed analysis record
                analysis = PaperAnalysis.objects.create(
                    paper=paper,
                    configuration_name=configuration_name,
                    context=[],
                    instruments_details="",
                    annotated_pdf=None,
                    token_usage={},
                    status='failed'
                )
                return {'success': False, 'error': str(e), 'analysis_id': analysis.id}
        
        # Get and validate configuration
        from paper_data_linking.config.settings import get_llm_configuration
        try:
            llm_config = get_llm_configuration(configuration_name)
        except ValueError as e:
            logger.error(f"Invalid configuration '{configuration_name}' for paper {paper_id}: {e}")
            raise

        with transaction.atomic():
            analysis = PaperAnalysis.objects.create(
                paper=paper,
                configuration_name=configuration_name,
                context=[],  # Will be filled after analysis
                instruments_details="",  # Will be filled after analysis
                annotated_pdf=None,
                token_usage={},  # Will be filled after analysis
                status='processing'
            )

            # Define callback to automatically associate LLM calls with this analysis
            def associate_with_analysis(llm_call):
                analysis.llm_calls.add(llm_call)

            # Use Django-aware LLM client with automatic association
            django_client = DjangoLiteLLMClient(association_callback=associate_with_analysis)
            analyzer = DirectPaperAnalyzer(llm_client=django_client, llm_config=llm_config)

            factory = make_node_factory(analysis)
            factory_token = current_node_factory.set(factory)
            try:
                with factory('paper_analysis', 'Paper Analysis'):
                    analysis_data = analyzer.forward(paper.full_text, read_pdf_bytes(paper.pdf))
            finally:
                current_node_factory.reset(factory_token)

            # Update analysis with results
            analysis.context = analysis_data.context
            analysis.instruments_details = analysis_data.instruments_details
            analysis.annotated_pdf = analysis_data.annotated_pdf
            analysis.token_usage = analysis_data.metadata['token_usage']
            analysis.status = 'completed'
            analysis.save()

            # Note: SupportQuote creation has been moved to the structuring phase
            # for more accurate quote-to-usage linking

        return True

    except Exception as e:
        logger.exception(f"Failed analyzing paper {paper_id}")
        PaperAnalysis.objects.filter(paper_id=paper_id).update(status='failed')
        return False


@shared_task
@close_db_connection
def run_paper_analyses(paper_ids, configuration_name='standard'):
    """Run paper analyses for multiple papers with specified configuration"""
    for paper_id in paper_ids:
        analyze_paper_task.delay(paper_id, configuration_name)


@shared_task
@close_db_connection
def analyze_paper_instruments_structure(paper_analysis_id, configuration_name='standard'):
    """
    Analyze and structure the instruments_details field of a PaperAnalysis using OpenAI Structured Outputs.
    """
    try:
        paper_analysis = PaperAnalysis.objects.get(id=paper_analysis_id)

        if not paper_analysis.instruments_details:
            logger.warning(f"No instruments_details found for PaperAnalysis {paper_analysis_id}")
            return {
                "success": False,
                "error": "No instruments_details text to analyze",
                "paper_analysis_id": str(paper_analysis_id)
            }

        # if paper_analysis.structured_instruments_details:
        #     logger.info(f"PaperAnalysis {paper_analysis_id} already has structured instruments details")
        #     return {
        #         "success": True,
        #         "skipped": True,
        #         "reason": "Already processed",
        #         "paper_analysis_id": str(paper_analysis_id)
        #     }

        # Define callback to automatically associate LLM calls with this analysis
        def associate_with_analysis(llm_call):
            paper_analysis.llm_calls.add(llm_call)

        # Use Django-aware LLM client with automatic association
        django_client = DjangoLiteLLMClient(association_callback=associate_with_analysis)
        # Get and validate configuration
        from paper_data_linking.config.settings import get_llm_configuration
        llm_config = get_llm_configuration(configuration_name)

        analyzer = DeterministicStructureAnalyzer(llm_client=django_client, llm_config=llm_config)

        # Look up paper_analysis node from previous task to use as parent
        paper_analysis_node = PipelineNode.objects.filter(
            analysis=paper_analysis, stage='paper_analysis'
        ).first()

        factory = make_node_factory(paper_analysis)
        factory_token = current_node_factory.set(factory)
        parent_token = current_pipeline_node.set(paper_analysis_node.id if paper_analysis_node else None)
        try:
            with factory('structuring', 'Structuring'):
                result = analyzer.forward(paper_analysis.instruments_details)
        finally:
            current_node_factory.reset(factory_token)
            current_pipeline_node.reset(parent_token)

        if result.success:
            paper_analysis.structured_instruments_details = result.structured_data
            paper_analysis.save(update_fields=['structured_instruments_details'])
            logger.info(f"Successfully structured instruments for PaperAnalysis {paper_analysis_id}")

            # Note: SupportQuote creation moved to normalization step to avoid duplication

            return {
                "success": True,
                "paper_analysis_id": str(paper_analysis_id),
                "paper_bibcode": paper_analysis.paper.bibcode,
                "instruments_count": result.metadata.get('instruments_count', 0),
                "total_data_periods": result.metadata.get('total_data_periods', 0),
                "token_usage": result.metadata.get('token_usage', {}),
                "processing_metadata": result.metadata
            }
        else:
            logger.error(
                f"Failed to structure instruments for PaperAnalysis {paper_analysis_id}: {result.error_message}"
            )
            return {
                "success": False,
                "error": result.error_message,
                "paper_analysis_id": str(paper_analysis_id),
                "paper_bibcode": paper_analysis.paper.bibcode
            }

    except PaperAnalysis.DoesNotExist:
        error_msg = f"PaperAnalysis with id {paper_analysis_id} does not exist"
        logger.error(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "paper_analysis_id": str(paper_analysis_id)
        }
    except Exception as e:
        error_msg = f"Unexpected error processing PaperAnalysis {paper_analysis_id}: {str(e)}"
        logger.exception(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "paper_analysis_id": str(paper_analysis_id)
        }


@shared_task
@close_db_connection
def normalize_structured_instrument_details(paper_analysis_id, configuration_name='standard'):
    """
    Given a PaperAnalysis ID, run StructuredNormalizer on its
    `structured_instruments_details` field and save result to JSONField.
    """
    try:
        pa = PaperAnalysis.objects.get(id=paper_analysis_id)

        if not pa.structured_instruments_details:
            return {
                "success": False,
                "error": "No structured_instruments_details found",
                "paper_analysis_id": str(paper_analysis_id)
            }

        # Define callback to automatically associate LLM calls with this analysis
        def associate_with_analysis(llm_call):
            pa.llm_calls.add(llm_call)

        # Get and validate configuration
        from paper_data_linking.config.settings import get_llm_configuration
        llm_config = get_llm_configuration(configuration_name)

        # Load HelioKnow phenomena for the phenomenon normalizer
        from .models import Phenomenon
        phenomena = list(Phenomenon.objects.order_by('id').values('id', 'name', 'iri'))

        # Use Django-aware factory with association callback
        normalizer = get_django_structured_normalizer(
            association_callback=associate_with_analysis,
            llm_config=llm_config,
            phenomena=phenomena,
        )

        # Get PDF bytes if available for quote coordinate extraction.
        # Skipped in collection mode: coordinates only matter at commit (they feed
        # SupportQuotes), never enter any LLM prompt (hash-safe), and the per-replay
        # PDF load + full-text IR search dominates collection-pass runtime.
        # ALSO skipped in corpus-mode commits: coordinates are review-UI-only
        # (quote highlighting); at corpus scale they are enriched on demand for
        # papers a human actually opens, not paid for up front on every paper.
        from paper_data_linking.pipeline_context import get_pipeline_mode
        pdf_bytes = None
        if pa.paper.pdf and get_pipeline_mode() != 'collection' and not _in_corpus_mode_commit():
            pdf_bytes = read_pdf_bytes(pa.paper.pdf)

        # Look up structuring node from previous task to use as parent for instrument nodes
        structuring_node = PipelineNode.objects.filter(analysis=pa, stage='structuring').first()

        factory = make_node_factory(pa)
        factory_token = current_node_factory.set(factory)
        parent_token = current_pipeline_node.set(structuring_node.id if structuring_node else None)
        try:
            normalized_json = normalizer.forward(pa.structured_instruments_details, pdf_path=pdf_bytes)
        finally:
            current_node_factory.reset(factory_token)
            current_pipeline_node.reset(parent_token)

        pa.normalized_instrument_details = normalized_json
        pa.save(update_fields=['normalized_instrument_details'])

        return {
            "success": True,
            "paper_analysis_id": str(paper_analysis_id),
        }

    except PaperAnalysis.DoesNotExist:
        return {
            "success": False,
            "error": f"PaperAnalysis {paper_analysis_id} does not exist",
            "paper_analysis_id": str(paper_analysis_id)
        }
    except Exception as e:
        # Mark any nodes left in 'running' state as 'failed' so re-runs don't leave ghost nodes
        from django.utils import timezone
        try:
            PipelineNode.objects.filter(
                analysis_id=paper_analysis_id, status='running'
            ).update(status='failed', completed_at=timezone.now())
        except Exception:
            pass
        return {
            "success": False,
            "error": str(e),
            "paper_analysis_id": str(paper_analysis_id)
        }


@shared_task
@close_db_connection
def normalize_and_insert_datasetusage(paper_analysis_id):
    """
    1) Run StructuredNormalizer → PaperAnalysis.normalized_instrument_details
    2) Delegate to helper that inserts DatasetUsage rows.
    """
    try:
        # (1) Ensure normalized_instrument_details is populated
        normalize_structured_instrument_details(paper_analysis_id)

        # (2) Fetch the PaperAnalysis and delegate to the helper
        pa = PaperAnalysis.objects.get(id=paper_analysis_id)
        _upsert_dataset_usages_from_normalized(pa)
        # Phenomena are intentional-only (run_phenomena_enrichment); no upsert here.

        return {"success": True, "paper_analysis_id": paper_analysis_id}
    except PaperAnalysis.DoesNotExist:
        return {
            "success": False,
            "error": f"PaperAnalysis {paper_analysis_id} does not exist",
            "paper_analysis_id": paper_analysis_id
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "paper_analysis_id": paper_analysis_id
        }


@shared_task
@close_db_connection
def insert_datasetusages_only(paper_analysis_id: int) -> dict:
    """
    Read the already‐normalized JSON in PaperAnalysis.normalized_instrument_details,
    then call the existing helper to upsert DatasetUsage rows.

    - paper_analysis_id: primary key of the PaperAnalysis that already has normalized_instrument_details.
    """
    try:
        pa = PaperAnalysis.objects.get(id=paper_analysis_id)
    except PaperAnalysis.DoesNotExist:
        return {
            "success": False,
            "error": f"PaperAnalysis {paper_analysis_id} not found or not linked to that prediction"
        }

    if not pa.normalized_instrument_details:
        return {
            "success": False,
            "error": "That PaperAnalysis has no normalized_instrument_details yet."
        }

    # 3) Delegate to your existing helpers
    _upsert_dataset_usages_from_normalized(pa)
    # Phenomena are intentional-only (run_phenomena_enrichment); no upsert here.

    return {
        "success": True,
        "paper_analysis_id": paper_analysis_id,
    }




def _extract_quote_coordinates(location):
    """
    Extract coordinate data from a quote location dict.

    Args:
        location: Dict containing location data from normalized JSON

    Returns:
        Dict with coordinate fields for SupportQuote creation
    """
    if not location:
        return {
            "page_number": 0,
            "y_coord": 0.0,
            "x_coord_start": 0.0,
            "x_coord_end": 0.0,
            "y_coord_start": 0.0,
            "y_coord_end": 0.0,
            "coordinate_regions": []
        }

    return {
        "page_number": location.get("page_number", 0),
        "y_coord": location.get("vertical_middle", 0.0),
        "x_coord_start": location.get("x0", 0.0),
        "x_coord_end": location.get("x1", 0.0),
        "y_coord_start": location.get("y0", 0.0),
        "y_coord_end": location.get("y1", 0.0),
        "coordinate_regions": location.get("coordinate_regions", [])
    }


def _upsert_instrument_mentions_from_normalized(paper_analysis: PaperAnalysis) -> int:
    """
    Create or update InstrumentMention rows from normalized_instrument_details.

    Resolves missions and instruments against the catalog, counts how many
    data_collection_periods have parseable time ranges, and sets match_level
    accordingly. Does NOT create DatasetUsages or SupportQuotes.

    Args:
        paper_analysis: PaperAnalysis instance with normalized_instrument_details

    Returns:
        int: Number of InstrumentMention rows created or updated
    """
    norm_json = paper_analysis.normalized_instrument_details
    if not norm_json or "instruments" not in norm_json:
        return 0

    mentions_upserted = 0

    for inst_entry in norm_json["instruments"]:
        # Issue #169 hardening: tolerate malformed entries — one bad instrument
        # must not abort mention upserts for the rest of the paper.
        name_norm = (inst_entry.get("name") or {}).get("normalized") \
            if isinstance(inst_entry, dict) else None

        if isinstance(name_norm, list) or name_norm is None or not isinstance(name_norm, dict):
            continue  # Malformed — skip

        inst_code = name_norm.get("matched_instrument_code")
        mission_code = name_norm.get("matched_mission_code")
        data_system = name_norm.get("data_system") or ""

        # Resolve DataSource
        ds = None
        if data_system:
            try:
                ds = DataSource.objects.get(slug=data_system)
            except DataSource.DoesNotExist:
                pass

        # Resolve Observatory (mission)
        obs = None
        if ds and mission_code:
            try:
                obs = Observatory.objects.get(datasource=ds, short_name=mission_code)
            except Observatory.DoesNotExist:
                pass

        # Resolve Instrument
        instrument_obj = None
        if inst_code and obs:
            try:
                instrument_obj = Instrument.objects.get(observatory=obs, short_name=inst_code)
            except Instrument.DoesNotExist:
                pass
        elif inst_code and not obs:
            try:
                instrument_obj = Instrument.objects.get(short_name=inst_code, observatory__isnull=False)
            except (Instrument.DoesNotExist, Instrument.MultipleObjectsReturned):
                pass

        # Determine match_level by counting periods with valid time ranges
        if instrument_obj is not None:
            periods = inst_entry.get("data_collection_periods", [])
            periods_total = len(periods)
            periods_resolved = 0
            for period in periods:
                tr_norm = period.get("time_range", {}).get("normalized", {})
                if not tr_norm:
                    continue
                start_iso = tr_norm.get("start_datetime")
                end_iso = tr_norm.get("end_datetime")
                if not start_iso or not end_iso:
                    continue
                try:
                    dateutil.parser.isoparse(start_iso)
                    dateutil.parser.isoparse(end_iso)
                    periods_resolved += 1
                except Exception:
                    continue

            if periods_resolved == 0:
                match_level = InstrumentMention.MATCH_LEVEL_INSTRUMENT_NO_TIME
            elif periods_resolved < periods_total:
                match_level = InstrumentMention.MATCH_LEVEL_PARTIAL
            else:
                match_level = InstrumentMention.MATCH_LEVEL_FULL
        elif obs is not None:
            match_level = InstrumentMention.MATCH_LEVEL_MISSION_ONLY
        else:
            match_level = InstrumentMention.MATCH_LEVEL_UNMATCHED

        # Upsert using FK identity — skip unmatched (no catalog anchor)
        if instrument_obj is not None:
            InstrumentMention.objects.update_or_create(
                paper_analysis=paper_analysis,
                matched_instrument=instrument_obj,
                defaults={
                    'match_level': match_level,
                    # matched_observatory NOT set — derive from matched_instrument.observatory
                },
            )
            mentions_upserted += 1
        elif obs is not None:
            InstrumentMention.objects.update_or_create(
                paper_analysis=paper_analysis,
                matched_observatory=obs,
                matched_instrument=None,
                defaults={
                    'match_level': InstrumentMention.MATCH_LEVEL_MISSION_ONLY,
                },
            )
            mentions_upserted += 1
        # else: unmatched — no catalog anchor, skip

    return mentions_upserted


def _upsert_mission_only_from_llm_calls(paper_analysis) -> int:
    """
    Create mission_only InstrumentMention rows from mission_selection LLM calls.

    Only mission_selection calls (the deliberate second-stage choice) are used.
    mission_identification calls are excluded because they represent an early
    filtering/ranking step, not a deliberate selection.

    Returns count of rows created/updated.
    """
    import re

    def _parse_candidates(text):
        result = {}
        for line in (text or '').strip().splitlines():
            m = re.match(r'^(\d+)\.\s+(\S+)\s+\((.+)\)\s*$', line.strip())
            if m:
                result[int(m.group(1))] = (m.group(2), m.group(3))
        return result

    def _parse_indices(output_content):
        if not output_content or output_content.strip().upper() == 'UNKNOWN':
            return []
        return [int(x) for x in re.findall(r'\b([1-9]\d*)\b', output_content)]

    mission_codes_seen = set()  # dedup across calls for same PA

    # --- Phase A: mission_selection calls (multi-candidate case) ---
    for call in paper_analysis.llm_calls.filter(call_type='mission_selection'):
        candidates = _parse_candidates(
            (call.render_context or {}).get('candidates_text', '')
        )
        for idx in _parse_indices(call.output_content):
            if idx in candidates:
                mission_codes_seen.add(candidates[idx][0])  # mission_code

    # --- Create InstrumentMentions for missions not already resolved ---
    count = 0
    for mission_code in mission_codes_seen:
        try:
            obs = Observatory.objects.get(short_name__iexact=mission_code)
        except Observatory.DoesNotExist:
            logger.warning(f"Observatory not found for mission_code={mission_code!r}")
            continue
        except Observatory.MultipleObjectsReturned:
            # Shouldn't happen given SPASE URI uniqueness, but handle gracefully
            obs = Observatory.objects.filter(short_name__iexact=mission_code).first()

        # Skip if a specific instrument was already resolved for this observatory
        already_resolved = InstrumentMention.objects.filter(
            paper_analysis=paper_analysis,
            matched_instrument__observatory=obs,
        ).exists()
        if already_resolved:
            continue

        _, created = InstrumentMention.objects.update_or_create(
            paper_analysis=paper_analysis,
            matched_observatory=obs,
            matched_instrument=None,
            defaults={'match_level': InstrumentMention.MATCH_LEVEL_MISSION_ONLY},
        )
        if created:
            count += 1

    return count


def _backfill_mission_only_from_input_messages(paper_analysis) -> tuple[int, list[str]]:
    """
    BACKFILL-ONLY. Parse mission_selection LLM call input_messages to recover
    mission assignments for pre-Oct-10 calls where render_context IS NULL.

    Only mission_selection calls are used. mission_identification calls are
    excluded because they represent an early filtering/ranking step, not a
    deliberate selection.

    Returns:
        (count_created, ambiguity_warnings) — warnings list non-empty when an
        Observatory name matched multiple DB rows (ambiguous; skipped).
    """
    import re

    def _parse_input_messages_candidates(input_messages):
        """Extract {1-based-idx: full_name} from XML block in the user message."""
        user_msg = next(
            (m.get('content', '') for m in (input_messages or []) if m.get('role') == 'user'),
            '',
        )
        match = re.search(r'<candidate_missions>(.*?)</candidate_missions>', user_msg, re.DOTALL)
        if not match:
            return {}
        result = {}
        for line in match.group(1).strip().splitlines():
            m = re.match(r'^(\d+)\.\s+(.+)$', line.strip())
            if m:
                result[int(m.group(1))] = m.group(2).strip()
        return result

    def _parse_indices(output_content):
        if not output_content or output_content.strip().upper() == 'UNKNOWN':
            return []
        return [int(x) for x in re.findall(r'\b([1-9]\d*)\b', output_content)]

    # Only process mission_selection calls with null render_context
    null_rc_calls = paper_analysis.llm_calls.filter(
        call_type='mission_selection',
        render_context__isnull=True,
    )

    obs_names_seen = {}  # full_name -> Observatory (dedup across calls)
    warnings = []

    for call in null_rc_calls:
        candidates = _parse_input_messages_candidates(call.input_messages)
        if not candidates:
            continue

        indices = _parse_indices(call.output_content)
        if not indices:
            continue

        for idx in indices:
            full_name = candidates.get(idx)
            if not full_name or full_name in obs_names_seen:
                continue
            try:
                obs = Observatory.objects.get(name=full_name)
                obs_names_seen[full_name] = obs
            except Observatory.DoesNotExist:
                logger.warning(
                    f"Observatory not found for name={full_name!r} "
                    f"(pa_id={paper_analysis.id}, call_id={call.id})"
                )
            except Observatory.MultipleObjectsReturned:
                msg = (
                    f"Ambiguous observatory name {full_name!r}: multiple DB rows "
                    f"(pa_id={paper_analysis.id}, call_id={call.id}) — skipped, manual review needed"
                )
                warnings.append(msg)
                logger.warning(msg)

    count = 0
    for obs in obs_names_seen.values():
        # Skip if a specific instrument was already resolved for this observatory
        already_resolved = InstrumentMention.objects.filter(
            paper_analysis=paper_analysis,
            matched_instrument__observatory=obs,
        ).exists()
        if already_resolved:
            continue

        _, created = InstrumentMention.objects.update_or_create(
            paper_analysis=paper_analysis,
            matched_observatory=obs,
            matched_instrument=None,
            defaults={'match_level': InstrumentMention.MATCH_LEVEL_MISSION_ONLY},
        )
        if created:
            count += 1

    return count, warnings


def _upsert_phenomenon_mentions_from_normalized(paper_analysis: PaperAnalysis) -> int:
    """
    Create PhenomenonMention records from phenomenon normalizer output stored in
    normalized_instrument_details.

    One record per (paper_analysis, phenomenon, instrument_name). All physobs
    SupportQuotes found across every period for that instrument are collected and
    linked via the supporting_quotes M2M so the validation UI can show all of them.
    """
    from .models import Phenomenon, PhenomenonMention

    norm_json = paper_analysis.normalized_instrument_details
    if not norm_json:
        return 0

    phenomenon_by_iri = {p.iri: p for p in Phenomenon.objects.all()}
    seen: set = set()
    created = 0

    for inst_entry in norm_json.get("instruments", []):
        raw_name = inst_entry.get("name", {})
        instrument_name = (raw_name.get("original", "") if isinstance(raw_name, dict) else raw_name).strip()
        normalized_name = raw_name.get("normalized", {}) if isinstance(raw_name, dict) else {}
        matched_instrument_code = normalized_name.get("matched_instrument_code") if normalized_name else None
        matched_mission_code = normalized_name.get("matched_mission_code") if normalized_name else None

        # --- Pass 1: collect all physobs SupportQuotes for this instrument ---
        # Gather those already in the DB (created by the dataset-usage path for grounded instruments).
        # Key by quote text to deduplicate — the dataset-usage path creates one SupportQuote per
        # period per quote, so the same text may appear multiple times with different IDs.
        # No page_number filter: collect all physobs quotes so grounded instruments show quotes
        # even when find_quotes_original found no coordinates during normalization.
        inst_sq_map: dict = {
            sq.quote: sq for sq in SupportQuote.objects.filter(
                paper_analysis=paper_analysis,
                instrument=instrument_name,
                parameter="physobs",
            )
        }

        # For ungrounded instruments, also create SupportQuotes from the quote normalizer
        # output stored per-period in supporting_quotes
        if matched_instrument_code is None:
            for period in inst_entry.get("data_collection_periods", []):
                sq_data = period.get("supporting_quotes") or {}
                physobs_normalized = (sq_data.get("normalized") or {}).get("physobs", [])
                for quote_data in physobs_normalized:
                    if not isinstance(quote_data, dict):
                        continue
                    quote_text = quote_data.get("text", "")
                    if quote_text:
                        coords = _extract_quote_coordinates(quote_data.get("location"))
                        sq, _ = SupportQuote.objects.get_or_create(
                            paper_analysis=paper_analysis,
                            instrument=instrument_name[:100],
                            parameter="physobs",
                            quote=quote_text,
                            defaults={
                                "page_number": coords["page_number"],
                                "y_coord": coords["y_coord"],
                                "x_coord_start": coords["x_coord_start"],
                                "x_coord_end": coords["x_coord_end"],
                                "y_coord_start": coords["y_coord_start"],
                                "y_coord_end": coords["y_coord_end"],
                                "coordinate_regions": coords["coordinate_regions"],
                            }
                        )
                        inst_sq_map[sq.quote] = sq

        # Run IR search on any quotes still missing coordinates — find_quotes_original (run
        # during normalization) only does exact matching and often fails for physobs quotes.
        # Applies to both grounded and ungrounded instruments.
        missing_coords = [sq for sq in inst_sq_map.values() if sq.page_number == 0]
        if missing_coords and paper_analysis.paper.pdf:
            try:
                from paper_data_linking.processing.pdf_text_search import PDFTextSearcher
                from .utils.storage import read_pdf_bytes
                pdf_bytes = read_pdf_bytes(paper_analysis.paper.pdf)
                # Pathological PDFs balloon fitz by GBs (cohort_10k: 1.4GB RSS,
                # cgroup kills). Bound the search: skip oversized PDFs — the
                # coordinate enrichment sweep handles them with its own budget.
                if len(pdf_bytes) > 25 * 1024 * 1024:
                    raise RuntimeError(
                        f"PDF too large for inline IR search ({len(pdf_bytes)} bytes); skipping")
                quote_objects = [
                    {"quote": sq.quote, "instrument": sq.instrument, "parameter": sq.parameter}
                    for sq in missing_coords
                ]
                searcher = PDFTextSearcher(pdf_bytes)
                ir_results = searcher.find_quotes_ir(quote_objects)
                searcher.close()
                for sq, result in zip(missing_coords, ir_results):
                    location = result.get("location")
                    if location:
                        coords = _extract_quote_coordinates(location)
                        sq.page_number = coords["page_number"]
                        sq.y_coord = coords["y_coord"]
                        sq.x_coord_start = coords["x_coord_start"]
                        sq.x_coord_end = coords["x_coord_end"]
                        sq.y_coord_start = coords["y_coord_start"]
                        sq.y_coord_end = coords["y_coord_end"]
                        sq.coordinate_regions = coords["coordinate_regions"]
                        sq.save(update_fields=[
                            "page_number", "y_coord",
                            "x_coord_start", "x_coord_end",
                            "y_coord_start", "y_coord_end",
                            "coordinate_regions",
                        ])
            except Exception as e:
                logger.warning(f"IR quote search failed for instrument '{instrument_name}': {e}")

        all_inst_sqs = list(inst_sq_map.values())
        # Prefer a SupportQuote with real PDF coordinates as the primary FK
        best_sq = next((sq for sq in all_inst_sqs if sq.page_number > 0), None) or (all_inst_sqs[0] if all_inst_sqs else None)

        # --- Pass 2: collect unique phenomena and first physical_observable per phenomenon ---
        inst_phenomena: dict = {}  # iri -> physical_observable text
        for period in inst_entry.get("data_collection_periods", []):
            phenomena_data = (period.get("phenomenon") or {}).get("phenomena", [])
            if not phenomena_data:
                continue
            phys_field = period.get("physical_observable", {})
            if isinstance(phys_field, dict):
                physical_observable = phys_field.get("original", "")
            elif isinstance(phys_field, str):
                physical_observable = phys_field
            else:
                physical_observable = ""
            for ph_data in phenomena_data:
                iri = ph_data.get("iri")
                if iri and iri not in inst_phenomena:
                    inst_phenomena[iri] = physical_observable

        # --- Pass 3: upsert one PhenomenonMention per (instrument, phenomenon) ---
        for iri, physical_observable in inst_phenomena.items():
            phenomenon = phenomenon_by_iri.get(iri)
            if not phenomenon:
                logger.warning(f"_upsert_phenomenon_mentions: unknown IRI '{iri}', skipping")
                continue

            key = (phenomenon.id, instrument_name)
            if key in seen:
                continue
            seen.add(key)

            mention, _ = PhenomenonMention.objects.get_or_create(
                paper_analysis=paper_analysis,
                phenomenon=phenomenon,
                instrument_name=instrument_name,
                defaults={
                    "matched_instrument_code": matched_instrument_code,
                    "matched_mission_code": matched_mission_code,
                    "quote": best_sq.quote if best_sq else "",
                    "supporting_quote": best_sq,
                    "physical_observable": physical_observable,
                    "validation_status": "pending",
                },
            )

            # Link all SupportQuotes to the mention (idempotent M2M add)
            if all_inst_sqs:
                mention.supporting_quotes.add(*all_inst_sqs)

            created += 1

    logger.info(f"_upsert_phenomenon_mentions: {created} PhenomenonMention records for PaperAnalysis {paper_analysis.id}")
    return created


def _upsert_dataset_usages_from_normalized(paper_analysis: PaperAnalysis) -> int:
    """
    Create DatasetUsages AND SupportQuotes from normalized_instrument_details.
    Links quotes directly to DatasetUsages (no string matching).

    This function creates quotes inline during DatasetUsage creation to ensure
    correct linking. Period-level quotes are linked only to their specific
    DatasetUsage, while instrument-level quotes are linked to all DatasetUsages
    for that instrument.

    Args:
        paper_analysis: PaperAnalysis instance with normalized_instrument_details

    Returns:
        int: Number of DatasetUsages created
    """
    norm_json = paper_analysis.normalized_instrument_details
    if not norm_json or "instruments" not in norm_json:
        return 0

    # Always create/update InstrumentMention rows first (mentions-only, no DatasetUsages)
    _upsert_instrument_mentions_from_normalized(paper_analysis)

    dataset_usages_created = 0
    quotes_created = 0
    all_new_quotes = []  # collect for batch embedding

    # Disconnect per-quote embedding signal — we'll batch-embed at the end
    from django.db.models.signals import post_save
    post_save.disconnect(_create_embedding_signal, sender=SupportQuote)

    try:
        for inst_entry in norm_json["instruments"]:
            try:
                name_norm = inst_entry["name"]["normalized"]
                instrument_name = inst_entry["name"]["original"].strip()

                # Handle case where normalized might be a list (multiple matches) or None
                if isinstance(name_norm, list):
                    logger.warning(f"Unexpected list in normalized field for instrument: {instrument_name}")
                    continue
                elif name_norm is None:
                    logger.warning(f"Null normalized field for instrument: {instrument_name}")
                    continue
                elif not isinstance(name_norm, dict):
                    logger.warning(f"Unexpected type {type(name_norm)} in normalized field for instrument: {instrument_name}")
                    continue

                inst_code = name_norm.get("matched_instrument_code")
                mission_code = name_norm.get("matched_mission_code")
                data_system = name_norm.get("data_system")

                # Get the appropriate DataSource for this instrument
                if not data_system:
                    logger.warning(f"No data_system found for instrument: {instrument_name}")
                    continue

                try:
                    ds = DataSource.objects.get(slug=data_system)
                except DataSource.DoesNotExist:
                    logger.error(f"DataSource '{data_system}' not found for instrument: {instrument_name}")
                    continue

                if not inst_code:
                    continue

                # Resolve observatory if mission_code is present
                obs = None
                try:
                    if mission_code:
                        obs = Observatory.objects.get(datasource=ds, short_name=mission_code)

                    instrument_obj = Instrument.objects.get(observatory=obs, short_name=inst_code)
                except ObjectDoesNotExist:
                    logger.error(
                        f"Attempted to use non-canonical instrument during normalized upsert: "
                        f"'{inst_code}' for observatory '{mission_code}'. "
                        f"Skipping for PaperAnalysis ID {paper_analysis.id}."
                    )
                    continue

                # Collect all DatasetUsages for this instrument (for instrument-level quotes)
                instrument_dataset_usages = []

                # Loop every data_collection_period
                for period in inst_entry.get("data_collection_periods", []):
                    tr_norm = period.get("time_range", {}).get("normalized", {})
                    if not tr_norm:
                        continue

                    start_iso = tr_norm.get("start_datetime")
                    end_iso = tr_norm.get("end_datetime")
                    if not start_iso or not end_iso:
                        continue

                    try:
                        start_dt = dateutil.parser.isoparse(start_iso).astimezone(pytz.UTC)
                        end_dt = dateutil.parser.isoparse(end_iso).astimezone(pytz.UTC)
                    except Exception:
                        continue

                    if start_dt > end_dt:
                        # Model-emitted reversed range (issue #169): Postgres rejects a
                        # reversed tstzrange at INSERT, and pre-guard that error aborted
                        # every remaining period/instrument for the paper. Treat it like
                        # an unparseable range: skip just this period.
                        logger.warning(
                            f"Reversed normalized time range for instrument '{instrument_name}' "
                            f"(PaperAnalysis {paper_analysis.id}): {start_iso} > {end_iso}; skipping period."
                        )
                        continue

                    window = DateTimeTZRange(start_dt, end_dt, bounds='[]')

                    # Generic extraction of all normalized fields into extra_params
                    extras = {
                        "resolver_reason": None,
                        "possible_sources": [],
                    }

                    # Process all fields in the period (except metadata and specially handled fields)
                    for field_name, field_data in period.items():
                        if field_name in ["period_name", "additional_comments", "time_range", "supporting_quotes"]:
                            continue  # Skip metadata, time_range (handled above), and supporting_quotes (handled below)

                        # Extract normalized data if it exists
                        if isinstance(field_data, dict) and "normalized" in field_data:
                            normalized_data = field_data.get("normalized")
                            if normalized_data is not None:
                                # Store the entire normalized data for all fields (consistent approach)
                                extras[field_name] = normalized_data

                    if not mission_code:
                        fallbacks = list(
                            Observatory.objects
                                .filter(instrument__short_name=inst_code)
                                .values_list("short_name", flat=True)
                                .distinct()
                        )
                        extras["possible_sources"] = fallbacks

                    dataset_usage, created = DatasetUsage.objects.get_or_create(
                        paper=paper_analysis.paper,
                        instrument=instrument_obj,
                        paper_analysis=paper_analysis,
                        observation_window=window,
                        defaults={
                            "extra_params": extras,
                        }
                    )

                    if created:
                        dataset_usages_created += 1

                    match_node = PipelineNode.objects.filter(
                        analysis=paper_analysis,
                        stage='grounding_match',
                        label=inst_code,
                    ).first()
                    if match_node:
                        match_node.dataset_usages.add(dataset_usage)

                    # Create period-level SupportQuotes and link directly to this DatasetUsage
                    period_quotes_data = period.get("supporting_quotes", {})
                    period_quotes_created = []

                    if isinstance(period_quotes_data, dict) and "normalized" in period_quotes_data:
                        normalized_period_quotes = period_quotes_data["normalized"]

                        # Period quotes are organized by category (time, wavelength, physobs, general)
                        if isinstance(normalized_period_quotes, dict):
                            for category, quote_list in normalized_period_quotes.items():
                                if isinstance(quote_list, list):
                                    for quote_data in quote_list:
                                        if isinstance(quote_data, dict):
                                            quote_text = quote_data.get("text", "")

                                            if quote_text.strip():
                                                coords = _extract_quote_coordinates(quote_data.get("location"))
                                                parameter = category if category in ['time', 'wavelength', 'physobs', 'general'] else 'general'

                                                # get_or_create: this function re-runs on commit
                                                # retries / reconciler re-entries (DatasetUsage is
                                                # get_or_create too) — bare create() duplicated
                                                # every quote per re-entry (observed 30x at scale).
                                                quote, created = SupportQuote.objects.get_or_create(
                                                    paper_analysis=paper_analysis,
                                                    quote=quote_text,
                                                    instrument=instrument_name[:100],
                                                    parameter=parameter[:100],
                                                    defaults={
                                                        "page_number": coords["page_number"],
                                                        "y_coord": coords["y_coord"],
                                                        "x_coord_start": coords["x_coord_start"],
                                                        "x_coord_end": coords["x_coord_end"],
                                                        "y_coord_start": coords["y_coord_start"],
                                                        "y_coord_end": coords["y_coord_end"],
                                                        "coordinate_regions": coords["coordinate_regions"],
                                                    },
                                                )
                                                period_quotes_created.append(quote)
                                                if created or quote.embedding is None:
                                                    all_new_quotes.append(quote)
                                                if created:
                                                    quotes_created += 1

                    # Link period quotes directly to this DatasetUsage
                    if period_quotes_created:
                        dataset_usage.supporting_quotes.add(*period_quotes_created)
                        create_categorized_quote_usage_links(dataset_usage, period_quotes_created)
                        logger.debug(f"Created and linked {len(period_quotes_created)} period quotes to DatasetUsage {dataset_usage.id}")

                    instrument_dataset_usages.append(dataset_usage)

                # Create instrument-level SupportQuotes and link to ALL DatasetUsages for this instrument
                # Only create if we have DatasetUsages to link them to (avoid orphan quotes)
                if not instrument_dataset_usages:
                    continue

                general_quotes_data = inst_entry.get("supporting_quotes", {})
                instrument_quotes_created = []

                if isinstance(general_quotes_data, dict) and "normalized" in general_quotes_data:
                    normalized_quotes = general_quotes_data["normalized"]

                    # Instrument-level quotes are organized by category (e.g., {"general": [...]})
                    # Same structure as period-level quotes
                    if isinstance(normalized_quotes, dict):
                        for category, quote_list in normalized_quotes.items():
                            if isinstance(quote_list, list):
                                for quote_data in quote_list:
                                    if isinstance(quote_data, dict):
                                        quote_text = quote_data.get("text", "")

                                        if quote_text.strip():
                                            coords = _extract_quote_coordinates(quote_data.get("location"))
                                            # Use the category as parameter (usually "general" for instrument-level)
                                            parameter = category if category in ['time', 'wavelength', 'physobs', 'general'] else 'general'

                                            # get_or_create: see period-level note — re-entries
                                            # must not duplicate quotes.
                                            quote, created = SupportQuote.objects.get_or_create(
                                                paper_analysis=paper_analysis,
                                                quote=quote_text,
                                                instrument=instrument_name[:100],
                                                parameter=parameter,
                                                defaults={
                                                    "page_number": coords["page_number"],
                                                    "y_coord": coords["y_coord"],
                                                    "x_coord_start": coords["x_coord_start"],
                                                    "x_coord_end": coords["x_coord_end"],
                                                    "y_coord_start": coords["y_coord_start"],
                                                    "y_coord_end": coords["y_coord_end"],
                                                    "coordinate_regions": coords["coordinate_regions"],
                                                },
                                            )
                                            instrument_quotes_created.append(quote)
                                            if created or quote.embedding is None:
                                                all_new_quotes.append(quote)
                                            if created:
                                                quotes_created += 1

                # Link instrument-level quotes to ALL DatasetUsages for this instrument
                if instrument_quotes_created and instrument_dataset_usages:
                    for du in instrument_dataset_usages:
                        du.supporting_quotes.add(*instrument_quotes_created)
                        create_categorized_quote_usage_links(du, instrument_quotes_created)
                    logger.debug(f"Created {len(instrument_quotes_created)} instrument quotes and linked to {len(instrument_dataset_usages)} DatasetUsages")
            except SoftTimeLimitExceeded:
                raise  # celery time limits must still fire
            except Exception:  # noqa: BLE001
                # Issue #169 hardening: one instrument's bad data must not
                # abort DU materialization for the paper's other instruments.
                label = (inst_entry.get("name") or {}).get("original", "?") \
                    if isinstance(inst_entry, dict) else "?"
                logger.exception(
                    f"DU upsert failed for instrument '{label}' "
                    f"(PaperAnalysis {paper_analysis.id}); skipping instrument.")
                continue

        # Batch-embed all newly created quotes in one (or a few) API calls, then reconnect signal.
        # Corpus-mode commits DEFER embedding entirely (embedding stays NULL): a
        # synchronous OpenAI call per paper inside the commit hot path is latency and
        # failure surface the corpus run doesn't need — embed_missing_quotes sweeps
        # NULL-embedding quotes in bulk off the critical path instead.
        if all_new_quotes and not _in_corpus_mode_commit():
            from openai import OpenAI
            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            chunk_size = 500  # well under the 2048-input API limit
            for i in range(0, len(all_new_quotes), chunk_size):
                chunk = all_new_quotes[i:i + chunk_size]
                texts = [q.quote for q in chunk]
                try:
                    response = client.embeddings.create(input=texts, model='text-embedding-3-small')
                    for quote, emb_data in zip(chunk, response.data):
                        SupportQuote.objects.filter(id=quote.id).update(embedding=emb_data.embedding)
                    logger.info(f"Batch-embedded {len(chunk)} quotes for PaperAnalysis {paper_analysis.id}")
                except Exception as e:
                    logger.error(f"Batch embedding failed for chunk starting at {i}: {e}")
    finally:
        post_save.connect(_create_embedding_signal, sender=SupportQuote)

    logger.info(f"Created {dataset_usages_created} DatasetUsages and {quotes_created} SupportQuotes for PaperAnalysis {paper_analysis.id}")
    return dataset_usages_created


@shared_task
@close_db_connection
def batch_analyze_instruments_structure(paper_analysis_ids=None, limit=None, force_reprocess=False):
    """
    Process multiple PaperAnalysis objects to structure their instruments_details.
    """
    try:
        if paper_analysis_ids:
            queryset = PaperAnalysis.objects.filter(
                id__in=paper_analysis_ids,
                status='completed'
            ).exclude(instruments_details__isnull=True).exclude(instruments_details='')
        else:
            queryset = PaperAnalysis.objects.filter(
                status='completed'
            ).exclude(instruments_details__isnull=True).exclude(instruments_details='')
            if not force_reprocess:
                queryset = queryset.filter(structured_instruments_details__isnull=True)

        if limit:
            queryset = queryset[:limit]

        total_count = queryset.count()
        if total_count == 0:
            return {
                "success": True,
                "message": "No PaperAnalysis objects found to process",
                "total_count": 0
            }

        logger.info(f"Starting batch processing of {total_count} PaperAnalysis objects")
        results = []
        for pa in queryset:
            task_result = analyze_paper_instruments_structure.delay(pa.id)
            results.append({
                "paper_analysis_id": str(pa.id),
                "paper_bibcode": pa.paper.bibcode,
                "task_id": task_result.id
            })

        return {
            "success": True,
            "message": f"Queued {total_count} structured instruments analysis tasks",
            "total_count": total_count,
            "queued_tasks": results,
            "force_reprocess": force_reprocess
        }

    except Exception as e:
        error_msg = f"Error in batch instruments structure analysis: {str(e)}"
        logger.exception(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "total_count": 0
        }


@shared_task
@close_db_connection
def check_and_extract_text(paper_id):
    """Check if text extraction is needed and perform it if necessary."""
    try:
        paper = Paper.objects.get(id=paper_id)
        
        if not paper.full_text and paper.pdf:
            logger.info(f"Running text extraction for paper {paper.bibcode}")
            success = extract_paper_text_task(paper_id)
            return {
                "success": success,
                "paper_id": str(paper_id),
                "paper_bibcode": paper.bibcode,
                "action": "extracted"
            }
        else:
            return {
                "success": True,
                "paper_id": str(paper_id),
                "paper_bibcode": paper.bibcode,
                "action": "skipped"
            }
    except Exception as e:
        return {
            "success": False,
            "paper_id": str(paper_id),
            "error": str(e),
            "action": "failed"
        }


@shared_task
@close_db_connection
def check_and_analyze_paper(extract_result, paper_id, configuration_name='standard'):
    """Check if paper analysis is needed and perform it if necessary."""
    try:
        # Check if previous step failed
        if not extract_result.get("success"):
            return extract_result
            
        paper = Paper.objects.get(id=paper_id)
        
        # Check if analysis already exists for this configuration and is completed
        try:
            paper_analysis = PaperAnalysis.objects.get(
                paper=paper, 
                configuration_name=configuration_name, 
                status='completed'
            )
            return {
                "success": True,
                "paper_id": str(paper_id),
                "paper_bibcode": paper.bibcode,
                "paper_analysis_id": paper_analysis.id,
                "action": "skipped"
            }
        except PaperAnalysis.DoesNotExist:
            if not paper.full_text:
                return {
                    "success": False,
                    "paper_id": str(paper_id),
                    "paper_bibcode": paper.bibcode,
                    "error": "No text available for analysis",
                    "action": "failed"
                }
            
            logger.info(f"Running paper analysis for paper {paper.bibcode}")
            success = analyze_paper_task(paper_id, configuration_name)
            
            if success:
                paper_analysis = PaperAnalysis.objects.get(
                    paper=paper, 
                    configuration_name=configuration_name,
                    status='completed'
                )
                return {
                    "success": True,
                    "paper_id": str(paper_id),
                    "paper_bibcode": paper.bibcode,
                    "paper_analysis_id": paper_analysis.id,
                    "action": "analyzed"
                }
            else:
                return {
                    "success": False,
                    "paper_id": str(paper_id),
                    "paper_bibcode": paper.bibcode,
                    "error": "Paper analysis failed",
                    "action": "failed"
                }
    except Exception as e:
        return {
            "success": False,
            "paper_id": str(paper_id),
            "error": str(e),
            "action": "failed"
        }


@shared_task
@close_db_connection
def check_and_structure_analysis(analysis_result, configuration_name='standard'):
    """Check if structure analysis is needed and perform it if necessary."""
    try:
        # Check if previous step failed
        if not analysis_result.get("success"):
            return analysis_result
            
        paper_analysis_id = analysis_result.get("paper_analysis_id")
        paper_analysis = PaperAnalysis.objects.get(id=paper_analysis_id)
        
        if not paper_analysis.structured_instruments_details:
            logger.info(f"Running structure analysis for paper {paper_analysis.paper.bibcode}")
            return analyze_paper_instruments_structure(paper_analysis_id, configuration_name)
        else:
            return {
                "success": True,
                "paper_analysis_id": str(paper_analysis_id),
                "paper_bibcode": paper_analysis.paper.bibcode,
                "action": "skipped"
            }
    except Exception as e:
        return {
            "success": False,
            "paper_analysis_id": analysis_result.get("paper_analysis_id"),
            "error": str(e),
            "action": "failed"
        }


@shared_task
@close_db_connection
def check_and_normalize(structure_result, configuration_name='standard'):
    """Check if normalization is needed and perform it if necessary."""
    try:
        # Check if previous step failed
        if not structure_result.get("success"):
            return structure_result
            
        paper_analysis_id = structure_result.get("paper_analysis_id")
        paper_analysis = PaperAnalysis.objects.get(id=paper_analysis_id)
        
        if not paper_analysis.normalized_instrument_details:
            logger.info(f"Running normalization for paper {paper_analysis.paper.bibcode}")
            return normalize_structured_instrument_details(paper_analysis_id, configuration_name)
        else:
            return {
                "success": True,
                "paper_analysis_id": str(paper_analysis_id),
                "paper_bibcode": paper_analysis.paper.bibcode,
                "action": "skipped"
            }
    except Exception as e:
        return {
            "success": False,
            "paper_analysis_id": structure_result.get("paper_analysis_id"),
            "error": str(e),
            "action": "failed"
        }


@shared_task
@close_db_connection
def create_dataset_usages(normalize_result):
    """Create dataset usages from normalized data."""
    try:
        # Check if previous step failed
        if not normalize_result.get("success"):
            return normalize_result
            
        paper_analysis_id = normalize_result.get("paper_analysis_id")
        paper_analysis = PaperAnalysis.objects.get(id=paper_analysis_id)
        
        if not paper_analysis.normalized_instrument_details:
            return {
                "success": False,
                "paper_analysis_id": str(paper_analysis_id),
                "error": "No normalized data available",
                "action": "failed"
            }
        
        logger.info(f"Creating dataset usages for paper {paper_analysis.paper.bibcode}")
        dataset_usages_created = _upsert_dataset_usages_from_normalized(paper_analysis)
        # Phenomena are intentional-only: the always-on upsert here OOM-killed
        # cohort_10k's final 10 commits via the unbounded IR PDF search, and the
        # subsystem has no dedicated test coverage. run_phenomena_enrichment is
        # the deliberate entry point (extraction + upsert, bounded).
        
        return {
            "success": True,
            "paper_id": str(paper_analysis.paper.id),
            "paper_analysis_id": str(paper_analysis_id),
            "paper_bibcode": paper_analysis.paper.bibcode,
            "dataset_usages_created": dataset_usages_created,
            "action": "created"
        }
    except Exception as e:
        return {
            "success": False,
            "paper_analysis_id": normalize_result.get("paper_analysis_id"),
            "error": str(e),
            "action": "failed"
        }


@shared_task(soft_time_limit=90, time_limit=120)
@close_db_connection
def analyze_dataset_usage(dataset_usage_id, run_execution=True):
    """Analyze a single DatasetUsage record with granular analyzers.

    Runs on the prefork `cpu` queue: the bandit subprocess + live Fido `exec` are
    bounded by inner timeouts (implementations.py) and this task's soft/hard
    time_limit, so a hang kills one process instead of wedging the worker.

    run_execution=False (bulk/corpus default via submit_batch_analysis) keeps the
    deterministic snippet + syntax check but SKIPS the live Fido `QueryExecution`
    (~630k network calls to VSO/CDAWeb at 90k scale — far too slow and abusive to
    those servers) and the bandit `QuerySecurity` check (only needed to gate
    execution). The download snippet — the deliverable — is still produced."""
    try:
        dataset_usage = DatasetUsage.objects.select_related(
            'instrument__observatory__datasource',
            'paper'
        ).get(id=dataset_usage_id)
    except DatasetUsage.DoesNotExist:
        logger.error(f"DatasetUsage {dataset_usage_id} not found")
        return f"DatasetUsage {dataset_usage_id} not found"

    # Custom group-level grounding (e.g. generic GOES/SEM): the instrument is a
    # program-level (ObservatoryGroup) record, NOT a real CDAWeb-tagged InstrumentID,
    # so the standard CDAWeb/VSO query would silently return nothing. Skip standard
    # snippet generation + analyzers and record an honest custom marker instead.
    if dataset_usage.instrument.catalog_source == CatalogSource.CUSTOM:
        obs = dataset_usage.instrument.observatory
        marker = (
            f"# Custom group-level grounding ({obs.name} / "
            f"{dataset_usage.instrument.full_name or dataset_usage.instrument.short_name}).\n"
            "# No standard download script: this is a program-level (ObservatoryGroup) "
            "grounding, not a specific CDAWeb/VSO product.\n"
            f"# Data are available via the {obs.short_name} ObservatoryGroup "
            "(HDPWS ObservatoryGroupID query)."
        )
        DatasetUsageAnalysis.objects.update_or_create(
            dataset_usage=dataset_usage,
            defaults={
                'python_snippet': marker,
                'analyzer_outputs': {'custom_grounding': True},
                'is_valid_syntax': False,
                'syntax_error': '',
                'execution_successful': False,
                'execution_error': '',
                'total_results_found': None,
            },
        )
        logger.info(f"DatasetUsage {dataset_usage_id}: custom grounding — skipped standard analysis.")
        return f"Custom grounding (no standard download): {dataset_usage_id}"

    # Generate snippet
    generator = DatasetUsageSnippetGenerator()
    try:
        snippet = generator.generate_snippet(dataset_usage)
    except UnsupportedDataSourceError as e:
        logger.warning(f"Skipping analysis for DatasetUsage {dataset_usage_id}: {str(e)}")
        return f"Skipped: {str(e)}"

    # Get data source from dataset usage
    data_source = dataset_usage.instrument.observatory.datasource.slug
    logger.info(f"Analyzing DatasetUsage {dataset_usage_id} for data source: {data_source}")

    # Get data source-aware analyzers
    analyzers = DatasetUsageAnalyzerRegistry.get_available_analyzers_for_data_source(data_source)

    if not run_execution:
        # Bulk mode: only the deterministic syntax check; skip live Fido execution
        # and the bandit security gate (pointless without execution).
        analyzers = {k: v for k, v in analyzers.items() if k == 'QuerySyntax'}

    # Run all appropriate analyzers
    all_results = {}
    for analyzer_type, analyzer_class in analyzers.items():
        try:
            analyzer = analyzer_class()
            results = analyzer.analyze_snippet(dataset_usage, snippet)
            all_results[analyzer_type] = results
            logger.info(f"Completed {analyzer_type} for DatasetUsage {dataset_usage_id} (data source: {data_source})")
        except Exception as e:
            error_msg = f"Analyzer {analyzer_type} failed: {str(e)}"
            all_results[analyzer_type] = {'error': error_msg}
            logger.error(error_msg)

    # Extract key results for model fields using analyzer type keys
    syntax_results = all_results.get('QuerySyntax', {})
    execution_results = all_results.get('QueryExecution', {})

    # Create or update analysis record
    analysis, created = DatasetUsageAnalysis.objects.get_or_create(
        dataset_usage=dataset_usage,
        defaults={
            'python_snippet': snippet,
            'analyzer_outputs': all_results,
            'is_valid_syntax': syntax_results.get('is_valid', False),
            'syntax_error': syntax_results.get('syntax_error', ''),
            'execution_successful': execution_results.get('execution_successful', False),
            'execution_error': execution_results.get('execution_error', ''),
            'total_results_found': execution_results.get('total_results_found'),
        }
    )

    if not created:
        analysis.python_snippet = snippet
        analysis.analyzer_outputs = all_results
        analysis.is_valid_syntax = syntax_results.get('is_valid', False)
        analysis.syntax_error = syntax_results.get('syntax_error', '')
        analysis.execution_successful = execution_results.get('execution_successful', False)
        analysis.execution_error = execution_results.get('execution_error', '')
        analysis.total_results_found = execution_results.get('total_results_found')
        analysis.save()

    action = "Created" if created else "Updated"
    logger.info(f"{action} DatasetUsageAnalysis for {dataset_usage_id}")

    return f"Completed analysis for DatasetUsage {dataset_usage_id}"


@shared_task
@close_db_connection
def run_dataset_usage_analyses(dataset_usage_ids):
    """Run analyses for multiple DatasetUsage records"""
    for dataset_usage_id in dataset_usage_ids:
        analyze_dataset_usage.delay(str(dataset_usage_id))


@shared_task
@close_db_connection
def _finalize_paper_pipeline(results, paper_analysis_id):
    """Chord callback: mark PaperAnalysis pipeline as fully complete."""
    from django.utils import timezone
    PaperAnalysis.objects.filter(id=paper_analysis_id).update(
        pipeline_completed_at=timezone.now()
    )


@shared_task
@close_db_connection
def analyze_paper_dataset_usages(usage_result):
    """Analyze all dataset usages for a paper in parallel."""
    try:
        # Check if previous step failed
        if not usage_result.get("success"):
            return usage_result

        paper_id = usage_result.get("paper_id")
        paper = Paper.objects.get(id=paper_id)

        # Filter dataset usages by the specific paper analysis from this workflow
        paper_analysis_id = usage_result.get("paper_analysis_id")
        if paper_analysis_id:
            try:
                pa = PaperAnalysis.objects.get(id=paper_analysis_id)
                # Only analyze usages that were created by THIS specific paper analysis
                dataset_usages = paper.dataset_usages.filter(
                    analysis__isnull=True,
                    paper_analysis=pa,
                )
            except PaperAnalysis.DoesNotExist:
                pa = None
                dataset_usages = paper.dataset_usages.filter(analysis__isnull=True)
        else:
            pa = None
            dataset_usages = paper.dataset_usages.filter(analysis__isnull=True)

        if not dataset_usages.exists():
            # Mark pipeline complete immediately when there are no usages to analyze
            if pa is not None:
                from django.utils import timezone
                pa.pipeline_completed_at = timezone.now()
                pa.save(update_fields=['pipeline_completed_at'])
            return {
                "success": True,
                "paper_id": str(paper_id),
                "paper_bibcode": paper.bibcode,
                "action": "skipped",
                "message": "No dataset usages to analyze"
            }

        usage_ids = [str(usage.id) for usage in dataset_usages]
        logger.info(f"Analyzing {len(usage_ids)} dataset usages for paper {paper.bibcode}")

        if pa is not None:
            # Use a chord so the callback sets pipeline_completed_at after all usages finish
            chord(
                group(analyze_dataset_usage.s(usage_id) for usage_id in usage_ids),
                _finalize_paper_pipeline.s(pa.id),
            ).apply_async()
        else:
            # No paper_analysis_id — fall back to fire-and-forget
            analysis_group = group(analyze_dataset_usage.s(usage_id) for usage_id in usage_ids)
            analysis_group.apply_async()

        return {
            "success": True,
            "paper_id": str(paper_id),
            "paper_bibcode": paper.bibcode,
            "action": "analyzed",
            "total_usages": len(usage_ids),
            "analyses_started": True
        }
    except Exception as e:
        return {
            "success": False,
            "paper_id": usage_result.get("paper_id"),
            "error": str(e),
            "action": "failed"
        }


@shared_task
@close_db_connection
def run_normalized_workflow_chain(paper_id, configuration_name='standard'):
    """
    Run the complete normalized workflow for a single paper using Celery chains
    for proper dependency handling and parallelization where possible.
    """
    try:
        paper = Paper.objects.get(id=paper_id)
        logger.info(f"Starting normalized workflow chain for paper {paper.bibcode}")
        
        # Validate configuration early
        from paper_data_linking.config.settings import get_llm_configuration
        get_llm_configuration(configuration_name)  # Will raise if invalid
        
        # Create a chain of dependent tasks
        workflow_chain = chain(
            # Step 1: Text extraction
            check_and_extract_text.s(paper_id),
            # Step 2: Paper analysis  
            check_and_analyze_paper.s(paper_id, configuration_name),
            # Step 3: Structure analysis (needs paper_analysis_id from step 2)
            check_and_structure_analysis.s(configuration_name),
            # Step 4: Normalization (needs paper_analysis_id from step 3)
            check_and_normalize.s(configuration_name),
            # Step 5: Dataset usage creation (needs paper_analysis_id from step 4)
            create_dataset_usages.s(),
            # Step 6: Dataset usage analysis (can be parallel internally)
            analyze_paper_dataset_usages.s()
        )
        
        # Execute the chain
        result = workflow_chain.apply_async()
        
        return {
            "success": True,
            "paper_id": str(paper_id),
            "paper_bibcode": paper.bibcode,
            "chain_id": result.id,
            "message": "Workflow chain started"
        }
        
    except Paper.DoesNotExist:
        return {
            "success": False,
            "error": f"Paper with id {paper_id} does not exist",
            "paper_id": str(paper_id)
        }
    except Exception as e:
        error_msg = f"Failed to start workflow chain for paper {paper_id}: {str(e)}"
        logger.exception(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "paper_id": str(paper_id)
        }


@shared_task
@close_db_connection
def run_batch_normalized_workflow(paper_ids, configuration_name='standard'):
    """
    Run the complete normalized workflow for multiple papers in parallel.
    Each paper runs its own chain, and all chains execute in parallel.
    """
    try:
        logger.info(f"Starting batch normalized workflow for {len(paper_ids)} papers")
        
        # Validate configuration early
        from paper_data_linking.config.settings import get_llm_configuration
        get_llm_configuration(configuration_name)  # Will raise if invalid
        
        # Create a group of workflow chains - each paper gets its own chain
        # This allows maximum parallelization while maintaining dependencies within each paper
        workflow_group = group(
            run_normalized_workflow_chain.s(paper_id, configuration_name) for paper_id in paper_ids
        )
        
        # Execute all chains in parallel
        group_result = workflow_group.apply_async()
        
        return {
            "success": True,
            "total_papers": len(paper_ids),
            "group_id": group_result.id,
            "message": f"Started {len(paper_ids)} parallel workflow chains"
        }
        
    except Exception as e:
        error_msg = f"Failed to start batch normalized workflow: {str(e)}"
        logger.exception(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "total_papers": len(paper_ids)
        }


# ----------------------------
# Batch API Tasks
# ----------------------------
BATCH_POLL_INTERVAL_SECONDS = 60
BATCH_POLL_MAX_RETRIES = 1440  # 24h at 60s intervals


def _load_paper_analysis_system_prompt():
    """Load the paper_analysis system prompt from XML template.

    Reuses the same loading logic as DirectPaperAnalyzer.forward().
    """
    import xml.etree.ElementTree as ET
    from pathlib import Path

    import paper_data_linking.linkers.general.direct_paper_analyzer as _analyzer_mod
    module_dir = Path(_analyzer_mod.__file__).parent
    prompts_dir = module_dir / "prompts" / "paper_analysis"

    with open(prompts_dir / "system.xml", "r", encoding="utf-8") as f:
        system_content = f.read()

    system_root = ET.fromstring(system_content)
    system_prompt = ET.tostring(system_root, encoding="unicode", method="xml").strip()
    if system_prompt.startswith("<?xml"):
        system_prompt = system_prompt.split("?>", 1)[1].strip()

    return system_prompt


@shared_task(bind=True)
@close_db_connection
def submit_batch_paper_analysis(self, paper_ids, configuration_name='standard',
                                trigger_downstream=True):
    """Extract text for all papers and submit paper_analysis calls as a batch.

    Supports OpenAI and Bedrock providers (detected from model name).
    Creates a BatchJob record and schedules polling for completion.

    trigger_downstream=False stops at PaperAnalysis (the batch pipeline runs
    downstream via the wave runner instead of the old sync chain).
    """
    from django.utils import timezone
    from paper_data_linking.config.settings import get_llm_configuration
    from paper_data_linking.clients.batch_client import BatchClient

    try:
        llm_config = get_llm_configuration(configuration_name)
        system_prompt = _load_paper_analysis_system_prompt()

        # Collect papers with extracted text
        papers_with_text = []
        skipped = []
        for paper_id in paper_ids:
            paper = Paper.objects.get(id=paper_id)

            # Skip if already has a completed analysis for this config
            if PaperAnalysis.objects.filter(
                paper=paper, configuration_name=configuration_name, status='completed'
            ).exists():
                skipped.append(str(paper_id))
                continue

            # Ensure text is extracted
            if not paper.full_text:
                extractor = PDFTextExtractor()
                if not paper.pdf:
                    logger.warning(f"Paper {paper_id} has no PDF, skipping")
                    skipped.append(str(paper_id))
                    continue
                try:
                    text, used_ocr = extractor.extract_text(read_pdf_bytes(paper.pdf))
                except Exception as e:
                    logger.warning(f"Paper {paper_id} PDF extraction failed: {e}, skipping")
                    skipped.append(str(paper_id))
                    continue
                paper.full_text = text
                paper.used_ocr = used_ocr
                paper.save(update_fields=['full_text', 'used_ocr'])

            # Validate text length
            from paper_data_linking.processing.text_validation import validate_text_length, TextValidationError
            try:
                validate_text_length(paper.full_text, str(paper_id))
            except TextValidationError as e:
                logger.warning(f"Paper {paper_id} text validation failed: {e}, skipping")
                skipped.append(str(paper_id))
                continue

            papers_with_text.append({
                "paper_id": str(paper.id),
                "text": paper.full_text,
            })

        if not papers_with_text:
            return {
                "success": True,
                "message": "No papers to process (all skipped or already analyzed)",
                "skipped": skipped,
            }

        # Detect provider from model name
        paper_analysis_config = llm_config.paper_analysis
        model = paper_analysis_config.model
        provider = "bedrock" if model.startswith("bedrock/") else "openai"

        # Bedrock batch requires a minimum of 100 records — fail fast with a clear message
        if provider == "bedrock" and len(papers_with_text) < 100:
            return {
                "success": False,
                "error": (
                    f"Bedrock batch requires at least 100 papers; got {len(papers_with_text)}. "
                    "Use a non-batch configuration for smaller sets."
                ),
            }

        # Get bare model name for batch (strip provider prefix)
        batch_model = model
        if '/' in batch_model:
            batch_model = batch_model.rsplit('/', 1)[1]

        # SIZE-AWARE CHUNKING (same constraints as the downstream dispatcher):
        # step-1 prompts embed full paper text (~70KB/record), so Bedrock's 1GB
        # input-file limit binds around ~15k papers — one job for a 40k cohort
        # is impossible. Serialize per paper, cut a job at MAX_JOB_BYTES /
        # MAX_RECORDS_PER_JOB, and never strand a sub-100-record remainder
        # (Bedrock's floor): keep filling past the soft byte cap instead.
        from .batch_downstream import MAX_JOB_BYTES, MAX_RECORDS_PER_JOB

        client = BatchClient()

        def _submit_chunk(lines, chunk_papers):
            result = client.submit(
                "\n".join(lines),
                provider=provider,
                model_name=batch_model,
                aws_region_name=paper_analysis_config.aws_region_name,
                aws_batch_role_arn=os.environ.get("AWS_BATCH_ROLE_ARN"),
            )
            bj = BatchJob.objects.create(
                batch_id=result["batch_id"],
                input_file_id=result["input_file_id"],
                status="submitted",
                provider=provider,
                configuration_name=configuration_name,
                aws_region_name=paper_analysis_config.aws_region_name,
                paper_mapping={pid: f"paper_analysis|{pid}" for pid in chunk_papers},
                total_requests=len(chunk_papers),
                submitted_at=timezone.now(),
                trigger_downstream=trigger_downstream,
            )
            logger.info(
                f"Submitted step-1 batch job {bj.id} with {len(chunk_papers)} papers, "
                f"{sum(len(l) + 1 for l in lines)} bytes (batch_id={result['batch_id']})"
            )
            poll_batch_job.apply_async(args=[bj.id], countdown=BATCH_POLL_INTERVAL_SECONDS)
            return bj

        jobs = []
        lines, chunk_papers, nbytes = [], [], 0
        remaining = len(papers_with_text)
        for p in papers_with_text:
            line = client.prepare_requests(
                [p], paper_analysis_config, system_prompt, provider=provider)
            full = (len(chunk_papers) >= MAX_RECORDS_PER_JOB
                    or nbytes + len(line) + 1 > MAX_JOB_BYTES)
            # Only cut if BOTH sides of the cut make valid Bedrock jobs
            # (>=100 records each); otherwise keep filling past the soft cap.
            if chunk_papers and full and (
                    provider != "bedrock"
                    or (len(chunk_papers) >= 100 and remaining >= 100)):
                jobs.append(_submit_chunk(lines, chunk_papers))
                lines, chunk_papers, nbytes = [], [], 0
            lines.append(line)
            chunk_papers.append(p["paper_id"])
            nbytes += len(line) + 1
            remaining -= 1
        if chunk_papers:
            jobs.append(_submit_chunk(lines, chunk_papers))

        return {
            "success": True,
            "batch_job_id": jobs[0].id,
            "batch_job_ids": [j.id for j in jobs],
            "batch_id": jobs[0].batch_id,
            "total_papers": len(papers_with_text),
            "skipped": skipped,
        }

    except Exception as e:
        error_msg = f"Failed to submit batch paper analysis: {str(e)}"
        logger.exception(error_msg)
        return {"success": False, "error": error_msg}


@shared_task(bind=True)
@close_db_connection
def poll_batch_job(self, batch_job_id, retry_count=0):
    """Poll an OpenAI batch job for completion.

    Re-schedules itself with a countdown until the batch completes or fails.
    """
    from paper_data_linking.clients.batch_client import BatchClient

    try:
        batch_job = BatchJob.objects.get(id=batch_job_id)

        if batch_job.status in ('completed', 'failed', 'partially_failed'):
            logger.info(f"Batch job {batch_job_id} already in terminal state: {batch_job.status}")
            return {"success": True, "status": batch_job.status}

        client = BatchClient()
        status = client.check_status(
            batch_job.batch_id,
            provider=batch_job.provider,
            aws_region_name=batch_job.aws_region_name,
        )

        batch_job.completed_requests = status["completed"]
        batch_job.failed_requests = status["failed"]

        logger.info(
            f"Batch job {batch_job_id}: status={status['status']}, "
            f"completed={status['completed']}/{status['total']}, "
            f"failed={status['failed']}"
        )

        if status["status"] == "completed":
            batch_job.status = "completed"
            batch_job.output_file_id = status.get("output_file_id")
            batch_job.save()

            # Trigger result ingestion
            ingest_batch_results.delay(batch_job_id)
            return {"success": True, "status": "completed", "batch_job_id": batch_job_id}

        elif status["status"] in ("failed", "cancelled", "expired"):
            batch_job.status = "failed"
            batch_job.error_details = {"api_status": status["status"]}
            batch_job.save()
            return {"success": False, "status": status["status"], "batch_job_id": batch_job_id}

        else:
            # Still processing — re-schedule
            batch_job.status = "processing"
            batch_job.save()

            if retry_count >= BATCH_POLL_MAX_RETRIES:
                batch_job.status = "failed"
                batch_job.error_details = {"reason": "polling timeout"}
                batch_job.save()
                return {"success": False, "status": "timeout", "batch_job_id": batch_job_id}

            poll_batch_job.apply_async(
                args=[batch_job_id, retry_count + 1],
                countdown=BATCH_POLL_INTERVAL_SECONDS,
            )
            return {"success": True, "status": "polling", "retry_count": retry_count + 1}

    except BatchJob.DoesNotExist:
        return {"success": False, "error": f"BatchJob {batch_job_id} not found"}
    except Exception as e:
        logger.exception(f"Error polling batch job {batch_job_id}")
        # Re-schedule on transient errors (network issues, etc.)
        if retry_count < BATCH_POLL_MAX_RETRIES:
            poll_batch_job.apply_async(
                args=[batch_job_id, retry_count + 1],
                countdown=BATCH_POLL_INTERVAL_SECONDS,
            )
        return {"success": False, "error": str(e), "will_retry": retry_count < BATCH_POLL_MAX_RETRIES}


@shared_task
@close_db_connection
def ingest_batch_results(batch_job_id):
    """Retrieve batch results and create PaperAnalysis + LLMCall records.

    For each successful result, kicks off the downstream chain
    (structure → normalize → create usages → analyze usages).
    """
    from django.utils import timezone
    from paper_data_linking.clients.batch_client import BatchClient
    from paper_data_linking.config.settings import get_llm_configuration
    from .models import LLMCall

    try:
        batch_job = BatchJob.objects.get(id=batch_job_id)
        llm_config = get_llm_configuration(batch_job.configuration_name)
        paper_analysis_config = llm_config.paper_analysis
        system_prompt = _load_paper_analysis_system_prompt()

        client = BatchClient()
        results = client.retrieve_results(
            batch_job.batch_id,
            provider=batch_job.provider,
            aws_region_name=batch_job.aws_region_name,
        )

        # Invert mapping: custom_id -> paper_id
        custom_id_to_paper_id = {v: k for k, v in batch_job.paper_mapping.items()}

        succeeded = 0
        failed = 0

        for result in results:
            custom_id = result["custom_id"]
            paper_id = custom_id_to_paper_id.get(custom_id)

            if not paper_id:
                logger.warning(f"Unknown custom_id in batch results: {custom_id}")
                failed += 1
                continue

            if "error" in result:
                logger.error(f"Batch result error for paper {paper_id}: {result['error']}")
                failed += 1
                continue

            try:
                paper = Paper.objects.get(id=paper_id)

                # Idempotency: skip if this batch result was already ingested
                already_ingested = LLMCall.objects.filter(
                    metadata__batch_id=batch_job.batch_id,
                    paper_analyses__paper=paper,
                ).exists()
                if already_ingested:
                    logger.warning(
                        f"Duplicate ingest detected: paper {paper_id} already has a "
                        f"PaperAnalysis linked to batch {batch_job.batch_id}. "
                        f"Skipping to avoid duplicates. If this is unexpected, "
                        f"check whether ingest_batch_results was called more than once "
                        f"for batch_job_id={batch_job_id}."
                    )
                    succeeded += 1
                    continue

                # Extract reasoning block from batch output.
                # gpt-oss-120b uses <reasoning>...</reasoning>;
                # Qwen3 uses <think>...</think>.
                # Strip whichever is present; store in LLMCall metadata.
                import re as _re
                raw_content = result["content"]
                reasoning_text = None
                reasoning_match = _re.search(
                    r'<(?:reasoning|think)>(.*?)</(?:reasoning|think)>',
                    raw_content, _re.DOTALL
                )
                if reasoning_match:
                    reasoning_text = reasoning_match.group(1).strip()
                    clean_content = _re.sub(
                        r'<(?:reasoning|think)>.*?</(?:reasoning|think)>\s*',
                        '', raw_content, flags=_re.DOTALL
                    ).strip()
                else:
                    clean_content = raw_content

                # Create PaperAnalysis record (reasoning stripped from instruments_details)
                analysis = PaperAnalysis.objects.create(
                    paper=paper,
                    configuration_name=batch_job.configuration_name,
                    context=[paper.full_text] if paper.full_text else [],
                    instruments_details=clean_content,
                    annotated_pdf=None,
                    token_usage={},
                    status='completed',
                )

                # Create LLMCall record from batch result
                usage = result.get("usage", {})
                provider = paper_analysis_config.model.split('/')[0] if '/' in paper_analysis_config.model else 'unknown'

                # Estimate cost from usage data
                estimated_cost = 0.0
                try:
                    import litellm
                    # Strip all provider prefixes for litellm cost lookup.
                    # e.g. "bedrock/converse/openai.gpt-oss-120b-1:0" -> "openai.gpt-oss-120b-1:0"
                    #      "openai/gpt-4o" -> "gpt-4o"
                    cost_model = paper_analysis_config.model.rsplit('/', 1)[-1]
                    input_cost, output_cost = litellm.cost_per_token(
                        model=cost_model,
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                    )
                    # Apply 50% batch discount
                    estimated_cost = (input_cost + output_cost) * 0.5
                except Exception as cost_err:
                    logger.warning(f"Could not calculate batch cost: {cost_err}")

                llm_call = LLMCall.objects.create(
                    call_type="paper_analysis",
                    model_name=paper_analysis_config.model,
                    provider=provider,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    estimated_cost_usd=estimated_cost,
                    input_messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": paper.full_text or ""},
                    ],
                    output_content=raw_content,  # full output including reasoning
                    duration_ms=0,
                    metadata={
                        "finish_reason": result.get("finish_reason", ""),
                        "batch_job_id": batch_job.id,
                        "batch_id": batch_job.batch_id,
                        **({"reasoning": reasoning_text} if reasoning_text else {}),
                    },
                )
                analysis.llm_calls.add(llm_call)

                # Create a paper_analysis PipelineNode so downstream tasks can parent under it.
                # The batch path bypasses analyze_paper_task, so we create this node manually.
                from django.utils import timezone as tz
                pa_node = PipelineNode.objects.create(
                    analysis=analysis,
                    stage='paper_analysis',
                    label='Paper Analysis',
                    status='completed',
                    started_at=tz.now(),
                    completed_at=tz.now(),
                    metadata={'source': 'batch', 'batch_job_id': batch_job.id},
                )
                pa_node.llm_calls.add(llm_call)

                # Kick off downstream chain (steps 3-6) — unless this batch is part of
                # the wave-pipeline, which runs downstream via BatchDownstreamRun.
                if getattr(batch_job, 'trigger_downstream', True):
                    downstream = chain(
                        check_and_structure_analysis.s(batch_job.configuration_name),
                        check_and_normalize.s(batch_job.configuration_name),
                        create_dataset_usages.s(),
                        analyze_paper_dataset_usages.s(),
                    )
                    # Feed the initial result dict that downstream tasks expect
                    downstream.apply_async(args=[{
                        "success": True,
                        "paper_id": str(paper.id),
                        "paper_analysis_id": analysis.id,
                        "paper_bibcode": paper.bibcode,
                        "action": "analyzed",
                    }])

                succeeded += 1

            except Paper.DoesNotExist:
                logger.error(f"Paper {paper_id} not found during batch ingestion")
                failed += 1
            except Exception as e:
                logger.exception(f"Failed to ingest batch result for paper {paper_id}")
                failed += 1

        # Update batch job
        batch_job.completed_requests = succeeded
        batch_job.failed_requests = failed
        batch_job.completed_at = timezone.now()
        batch_job.status = "completed" if failed == 0 else "partially_failed"
        batch_job.save()

        logger.info(
            f"Batch job {batch_job_id} ingestion complete: "
            f"{succeeded} succeeded, {failed} failed"
        )

        return {
            "success": True,
            "batch_job_id": batch_job_id,
            "succeeded": succeeded,
            "failed": failed,
        }

    except BatchJob.DoesNotExist:
        return {"success": False, "error": f"BatchJob {batch_job_id} not found"}
    except Exception as e:
        logger.exception(f"Failed to ingest batch results for job {batch_job_id}")
        return {"success": False, "error": str(e)}


@shared_task
@close_db_connection
def run_batch_normalized_workflow_via_batch_api(paper_ids, configuration_name='standard'):
    """Batch-mode workflow: submit paper_analysis via Batch API (50% cost savings).

    Unlike run_batch_normalized_workflow() which runs synchronous chains per-paper,
    this submits all paper_analysis calls as a single OpenAI batch, then triggers
    downstream processing on completion.

    Args:
        paper_ids: List of paper IDs to process
        configuration_name: LLM configuration to use (default: 'standard')
    """
    return submit_batch_paper_analysis(paper_ids, configuration_name)




# ----------------------------
# PDF Location Update Tasks
# ----------------------------
@shared_task
@close_db_connection
def update_single_quote_location_task(quote_id):
    """
    Update PDF location for a single supporting quote using the improved PDF annotator.

    Args:
        quote_id: ID of the SupportQuote to update

    Returns:
        dict: Task result with success status and location data
    """
    try:
        # Get the quote
        quote = SupportQuote.objects.select_related('paper_analysis__paper').get(id=quote_id)

        # Prepare quote for PDF annotation
        quote_data = {
            'quote': quote.quote,
            'instrument': quote.instrument,
            'parameter': quote.parameter,
        }

        logger.info(f"Processing quote {quote_id}: {quote.quote[:50]}...")

        # Read PDF bytes from storage (works for both local and S3)
        pdf_bytes = read_pdf_bytes(quote.paper_analysis.paper.pdf)

        # Use the improved PDF annotator to find location
        try:
            annotated_pdf_file, processed_quotes = annotate_pdf(pdf_bytes, [quote_data])
        except Exception as e:
            logger.error(f"PDF annotation failed for quote {quote_id}: {str(e)}")
            return {
                "success": False,
                "error": f"PDF annotation failed: {str(e)}",
                "quote_id": quote_id,
                "quote_text": quote.quote[:50] + "..."
            }
        
        # Update quote with new location data
        if processed_quotes and len(processed_quotes) > 0:
            processed_quote = processed_quotes[0]
            location = processed_quote.get('location')
            
            if location:
                quote.page_number = location.get('page_number', 0)
                quote.x_coord_start = location.get('x0', 0.0)
                quote.x_coord_end = location.get('x1', 0.0)
                quote.y_coord_start = location.get('y0', 0.0)
                quote.y_coord_end = location.get('y1', 0.0)
                quote.y_coord = (location.get('y0', 0.0) + location.get('y1', 0.0)) / 2  # Vertical middle
                quote.coordinate_regions = location.get('coordinate_regions', [])
                quote.save(update_fields=[
                    'page_number', 'x_coord_start', 'x_coord_end', 
                    'y_coord_start', 'y_coord_end', 'y_coord', 'coordinate_regions'
                ])
                
                logger.info(f"✓ Updated quote {quote_id} location: page {location.get('page_number')}")
                return {
                    "success": True,
                    "quote_id": quote_id,
                    "location_found": True,
                    "page_number": location.get('page_number'),
                    "quote_text": quote.quote[:50] + "..."
                }
            else:
                logger.warning(f"✗ No location found for quote {quote_id}")
                return {
                    "success": True,
                    "quote_id": quote_id,
                    "location_found": False,
                    "quote_text": quote.quote[:50] + "..."
                }
        else:
            logger.warning(f"✗ No processed results for quote {quote_id}")
            return {
                "success": True,
                "quote_id": quote_id,
                "location_found": False,
                "quote_text": quote.quote[:50] + "..."
            }
            
    except SupportQuote.DoesNotExist:
        error_msg = f"SupportQuote with id {quote_id} does not exist"
        logger.error(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "quote_id": quote_id
        }
    except Exception as e:
        error_msg = f"Unexpected error updating quote {quote_id}: {str(e)}"
        logger.exception(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "quote_id": quote_id
        }


@shared_task
@close_db_connection
def update_supporting_quote_locations_batch_task(paper_analysis_id):
    """
    Spawn individual tasks to update PDF locations for all supporting quotes in a PaperAnalysis.
    
    Args:
        paper_analysis_id: ID of the PaperAnalysis to update quotes for
        
    Returns:
        dict: Task result with info about spawned tasks
    """
    try:
        # Get the PaperAnalysis and ensure it has a PDF
        paper_analysis = PaperAnalysis.objects.select_related('paper').get(id=paper_analysis_id)
        
        if not paper_analysis.paper.pdf:
            return {
                "success": False,
                "error": "No PDF found for this paper",
                "paper_analysis_id": str(paper_analysis_id),
                "paper_bibcode": paper_analysis.paper.bibcode
            }
        
        # Get all supporting quotes for this analysis
        support_quotes = paper_analysis.support_quotes.all()
        
        if not support_quotes.exists():
            return {
                "success": True,
                "message": "No supporting quotes found to update",
                "paper_analysis_id": str(paper_analysis_id),
                "paper_bibcode": paper_analysis.paper.bibcode,
                "tasks_spawned": 0
            }
        
        total_quotes = support_quotes.count()

        logger.info(f"Spawning {total_quotes} individual quote location tasks for paper {paper_analysis.paper.bibcode}")

        # Spawn individual tasks for each quote
        task_ids = []
        for quote in support_quotes:
            task = update_single_quote_location_task.delay(quote.id)
            task_ids.append(task.id)
        
        result = {
            "success": True,
            "paper_analysis_id": str(paper_analysis_id),
            "paper_bibcode": paper_analysis.paper.bibcode,
            "tasks_spawned": len(task_ids),
            "task_ids": task_ids,
            "message": f"Spawned {len(task_ids)} individual quote location tasks"
        }
        
        logger.info(f"Spawned {len(task_ids)} quote location tasks for paper {paper_analysis.paper.bibcode}")
        return result
        
    except PaperAnalysis.DoesNotExist:
        error_msg = f"PaperAnalysis with id {paper_analysis_id} does not exist"
        logger.error(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "paper_analysis_id": str(paper_analysis_id)
        }
    except Exception as e:
        error_msg = f"Unexpected error spawning quote location tasks for PaperAnalysis {paper_analysis_id}: {str(e)}"
        logger.exception(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "paper_analysis_id": str(paper_analysis_id)
        }



@shared_task
def update_specific_quotes_task(quote_ids, method='ir'):
    """
    Update PDF locations for specific quote IDs only.
    
    Args:
        quote_ids: List of SupportQuote IDs to update
        method: Method to use ('ir', 'original', 'legacy')
        
    Returns:
        dict: Task result with success info
    """
    import time
    from paper_data_linking.processing.pdf_text_search import PDFTextSearcher
    
    try:
        # Get the quotes
        quotes = SupportQuote.objects.filter(id__in=quote_ids).select_related('paper_analysis__paper')
        
        if not quotes.exists():
            return {
                "success": False,
                "error": "No quotes found for provided IDs",
                "quote_ids": quote_ids
            }
        
        # Group quotes by paper (in case quotes are from different papers)
        papers_to_quotes = {}
        for quote in quotes:
            paper = quote.paper_analysis.paper
            if paper not in papers_to_quotes:
                papers_to_quotes[paper] = []
            papers_to_quotes[paper].append(quote)
        
        total_processed = 0
        total_found = 0
        
        for paper, paper_quotes in papers_to_quotes.items():
            if not paper.pdf:
                logger.warning(f"No PDF for paper {paper.bibcode}, skipping {len(paper_quotes)} quotes")
                continue
                
            pdf_bytes = read_pdf_bytes(paper.pdf)

            # Prepare quote objects for PDF searcher
            quote_objects = []
            for quote in paper_quotes:
                quote_objects.append({
                    'quote': quote.quote,
                    'instrument': quote.instrument,
                    'parameter': quote.parameter
                })

            logger.info(f"Processing {len(quote_objects)} quotes for paper {paper.bibcode} using {method} method")

            try:
                searcher = PDFTextSearcher(pdf_bytes)
                
                # Use the specified method
                if method == 'ir':
                    processed_quotes = searcher.find_quotes_ir(quote_objects, debug=False)
                elif method == 'original':
                    processed_quotes = searcher.find_quotes_original(quote_objects, debug=False)
                else:  # legacy
                    processed_quotes = searcher.find_quotes(quote_objects, debug=False)
                
                searcher.close()
                
                # Update the database with found locations
                for quote, result in zip(paper_quotes, processed_quotes):
                    location = result.get('location')
                    if location:
                        # Update the quote with new location data
                        quote.page_number = location.get('page_number', 0)
                        quote.x_coord_start = location.get('x0', 0.0)
                        quote.y_coord_start = location.get('y0', 0.0)
                        quote.x_coord_end = location.get('x1', 0.0)
                        quote.y_coord_end = location.get('y1', 0.0)
                        quote.coordinate_regions = location.get('coordinate_regions', [])
                        quote.save()
                        total_found += 1
                        logger.info(f"✓ Updated quote {quote.id} location: page {quote.page_number}")
                    else:
                        logger.warning(f"✗ No location found for quote {quote.id}")
                    
                    total_processed += 1
                
            except Exception as e:
                logger.error(f"PDF processing failed for paper {paper.bibcode}: {str(e)}")
                continue
        
        result = {
            "success": True,
            "total_processed": total_processed,
            "total_found": total_found,
            "method_used": method,
            "quote_ids": quote_ids
        }
        
        logger.info(f"Completed processing {total_processed} quotes, found locations for {total_found}")
        return result
        
    except Exception as e:
        error_msg = f"Unexpected error in update_specific_quotes_task: {str(e)}"
        logger.error(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "quote_ids": quote_ids
        }


@shared_task
def test_gevent_status():
    """
    Test to verify if gevent monkey patching is actually active and what modules are patched.
    """
    import socket
    import threading
    import time
    
    results = {
        "gevent_available": False,
        "monkey_patched": {},
        "current_greenlet": None,
        "socket_type": None,
        "threading_type": None
    }
    
    try:
        import gevent
        from gevent import monkey
        results["gevent_available"] = True
        
        # Check what's been monkey patched
        results["monkey_patched"] = {
            "socket": monkey.is_module_patched('socket'),
            "ssl": monkey.is_module_patched('ssl'), 
            "threading": monkey.is_module_patched('threading'),
            "select": monkey.is_module_patched('select'),
            "subprocess": monkey.is_module_patched('subprocess'),
            "time": monkey.is_module_patched('time')
        }
        
        # Check current greenlet
        current = gevent.getcurrent()
        results["current_greenlet"] = str(type(current))
        
        # Check if socket and threading are actually gevent versions
        results["socket_type"] = str(type(socket.socket))
        results["threading_type"] = str(type(threading.Thread))
        
        logger.info(f"Gevent status: {results}")
        
    except ImportError as e:
        results["error"] = f"Gevent not available: {str(e)}"

    return results


# ---------------------------------------------------------------------------
# Phenomenon mention upsert task (called after normalization)
# ---------------------------------------------------------------------------


@shared_task
@close_db_connection
def upsert_phenomenon_mentions_task(paper_analysis_id):
    """
    Create/update PhenomenonMention records from phenomenon normalizer output
    already stored in normalized_instrument_details. Run this after normalization
    to backfill mentions without re-running the full normalization pipeline.
    """
    try:
        pa = PaperAnalysis.objects.get(id=paper_analysis_id)
    except PaperAnalysis.DoesNotExist:
        return {"success": False, "error": f"PaperAnalysis {paper_analysis_id} not found"}

    if not pa.normalized_instrument_details:
        return {"success": False, "error": "No normalized_instrument_details — run normalization first"}

    created = _upsert_phenomenon_mentions_from_normalized(pa)
    return {"success": True, "paper_analysis_id": str(paper_analysis_id), "mentions_created": created}


@shared_task(soft_time_limit=540, time_limit=600)
@close_db_connection
def run_phenomena_enrichment(paper_analysis_id):
    """THE deliberate entry point for phenomena (they never run in the standard
    chain): run phenomenon extraction over the stored normalized periods, merge
    results into normalized_instrument_details, then upsert PhenomenonMentions.

    Idempotent: periods that already carry a phenomenon result are not
    re-extracted; the mention upsert is get_or_create throughout. Covers both
    grounded and ungrounded instruments (the old chain's ungrounded-only pass
    is subsumed). Routed to the prefork cpu queue.
    """
    from types import SimpleNamespace
    from paper_data_linking.config.settings import get_llm_configuration
    from paper_data_linking.linkers.general.normalizers import NormalizerRegistry
    from .clients import DjangoLiteLLMClient
    from .models import Phenomenon

    try:
        pa = PaperAnalysis.objects.get(id=paper_analysis_id)
    except PaperAnalysis.DoesNotExist:
        return {"success": False, "error": f"PaperAnalysis {paper_analysis_id} not found"}
    nj = pa.normalized_instrument_details
    if not nj or not nj.get("instruments"):
        return {"success": False, "error": "No normalized_instrument_details — run normalization first"}

    vocab = [{"id": p.id, "name": p.name, "iri": p.iri} for p in Phenomenon.objects.all()]
    if not vocab:
        return {"success": False, "error": "Phenomenon vocabulary table is empty"}

    llm_config = get_llm_configuration(pa.configuration_name)
    normalizer_cls = NormalizerRegistry.get_normalizer_for_data_source("phenomenon", "vso")
    normalizer = normalizer_cls(llm_client=DjangoLiteLLMClient(), llm_config=llm_config)

    extracted = skipped = 0
    for inst_entry in nj["instruments"]:
        if not isinstance(inst_entry, dict):
            continue
        name = inst_entry.get("name", {})
        inst_name = (name.get("original", "") if isinstance(name, dict) else str(name)).strip()
        for period in inst_entry.get("data_collection_periods", []):
            if not isinstance(period, dict):
                continue
            if (period.get("phenomenon") or {}).get("phenomena") is not None:
                skipped += 1
                continue
            phys = period.get("physical_observable", {})
            phys_text = phys.get("original", "") if isinstance(phys, dict) else (phys or "")
            if not phys_text:
                continue
            quotes = ((period.get("supporting_quotes") or {}).get("normalized") or {}).get("physobs", [])
            ctx = SimpleNamespace(
                period_data=SimpleNamespace(
                    physical_observable=phys_text,
                    physobs_quotes=[q.get("text", "") for q in quotes if isinstance(q, dict)]),
                phenomena=vocab,
                instrument_name=inst_name,
                period_name=period.get("period_name", ""),
            )
            period["phenomenon"] = normalizer.normalize(ctx)
            extracted += 1

    if extracted:
        pa.normalized_instrument_details = nj
        pa.save(update_fields=["normalized_instrument_details"])

    mentions = _upsert_phenomenon_mentions_from_normalized(pa)
    return {"success": True, "paper_analysis_id": str(paper_analysis_id),
            "periods_extracted": extracted, "periods_already_done": skipped,
            "mentions_created": mentions}


@shared_task
@close_db_connection
def submit_batch_phenomena_enrichment(configuration_name, paper_ids=None, only_grounded=False):
    """Fan phenomena enrichment out across the cpu fleet for a config's papers.
    ``only_grounded`` restricts to papers with at least one grounded instrument —
    the cheap way to skip the out-of-scope tail entirely."""
    qs = PaperAnalysis.objects.filter(configuration_name=configuration_name,
                                      normalized_instrument_details__isnull=False)
    if paper_ids:
        qs = qs.filter(paper_id__in=list(paper_ids))
    if only_grounded:
        from .models import InstrumentMention
        grounded = InstrumentMention.objects.filter(
            paper_analysis__configuration_name=configuration_name,
            matched_instrument__isnull=False).values_list('paper_analysis_id', flat=True)
        qs = qs.filter(id__in=grounded)
    n = 0
    for pa_id in qs.values_list('id', flat=True).iterator(chunk_size=2000):
        run_phenomena_enrichment.delay(pa_id)
        n += 1
    logger.info("submit_batch_phenomena_enrichment: dispatched %d papers (config=%s, only_grounded=%s)",
                n, configuration_name, only_grounded)
    return {"dispatched": n}




# =========================================================================
# Batch-downstream wave runner (crash-safe Celery wrappers)
# =========================================================================

@shared_task
@close_db_connection
def submit_batch_downstream(paper_ids, configuration_name, aws_region_name=None,
                            corpus_mode=False):
    """Entry point: create a BatchDownstreamRun and kick the driver."""
    from . import batch_downstream as bd
    run = bd.create_run(paper_ids, configuration_name, aws_region_name,
                        corpus_mode=corpus_mode)
    advance_run_task.delay(str(run.id))
    return {"run_id": str(run.id), "total_papers": run.total_papers}


@shared_task(bind=True)
@close_db_connection
def advance_run_task(self, run_id):
    """Drive a run one idempotent step. Collection is fanned out across the fleet
    (chord); other steps re-enqueue with a countdown. Safe to fire redundantly —
    the lease serializes drivers."""
    from . import batch_downstream as bd
    res = bd.advance_run(run_id, collect=False)
    if res.get("state") == "need_collection":
        bd.dispatch_parallel_collection(run_id)
    elif res.get("state") == "need_commit":
        bd.dispatch_parallel_commit(run_id)
    elif res.get("reschedule"):
        advance_run_task.apply_async(args=[run_id], countdown=res["reschedule"])
    return res


@shared_task(soft_time_limit=600, time_limit=660)
@close_db_connection
def commit_chunk_task(run_id, paper_ids):
    """Commit a chunk of LLM-complete papers (prefork cpu queue: per-task process
    isolation keeps @close_db_connection harmless and avoids the gevent worker's
    shared-connection churn). Merges its OWN outcomes (select_for_update) and
    re-enters the driver — no chord: the prefork->gevent chord callback silently
    never fires in this deployment."""
    from . import batch_downstream as bd
    from .models import BatchDownstreamRun
    run = BatchDownstreamRun.objects.get(id=run_id)
    results = [bd.commit_single_paper(run, pid) for pid in paper_ids]
    bd.finish_commit_chunk(run_id, results)
    advance_run_task.delay(run_id)
    return results


@shared_task
@close_db_connection
def merge_commit_task(results, run_id):
    """DEPRECATED (kept for in-flight message compatibility): merging now happens
    inside commit_chunk_task; a stray invocation just re-enters the driver."""
    advance_run_task.delay(run_id)
    return {"merged": 0}


@shared_task(soft_time_limit=600, time_limit=660)
@close_db_connection
def collect_chunk_task(run_id, paper_ids):
    """Run a collection pass for one chunk of papers (fleet-parallel, `replay`
    queue on the prefork worker). Applies its OWN outcomes to the RunPaper state
    machine and re-enters the driver — chord-free. A killed/hung chunk is
    bounded by the time limit and its claims are reclaimed by the driver."""
    import logging as _lg
    # Replays re-execute the (very chatty) pipeline dozens of times per paper;
    # INFO logging is measurable overhead and pure noise here.
    _lg.getLogger('paper_data_linking').setLevel(_lg.WARNING)
    from . import batch_downstream as bd
    from .models import BatchDownstreamRun
    run = BatchDownstreamRun.objects.get(id=run_id)
    res = bd.collect_papers(run, paper_ids, bd.default_prefix_fn)
    bd.finish_collection_chunk(run_id, paper_ids, res)
    advance_run_task.delay(run_id)
    return res


@shared_task
@close_db_connection
def merge_collection_task(results, run_id):
    """DEPRECATED (kept for in-flight message compatibility): outcomes now apply
    inside collect_chunk_task; a stray invocation just re-enters the driver."""
    advance_run_task.delay(run_id)
    return {"merged_chunks": 0}


@shared_task(soft_time_limit=540, time_limit=600)
@close_db_connection
def embed_missing_quotes(max_quotes=20_000, chunk_size=2000):
    """Bulk-embed SupportQuotes whose embedding is NULL — the off-critical-path
    counterpart to corpus-mode commits deferring embeddings. One call embeds up
    to 2{,}000 texts, so a 20k sweep is ~10 API calls instead of one call per
    paper inside the commit loop. Safe to run concurrently with commits.

    SELF-CHAINING (issue #175): if a backlog remains after this sweep's cap, the
    task re-delays itself, so a single kick (corpus-run completion or a beat
    tick) drains the whole backlog continuously instead of 20k per 10-min beat
    cadence. Terminates at remaining=0; an overlapping sweep re-embeds at most
    one in-flight chunk (same values, last write wins) — wasteful, not wrong.
    """
    from openai import OpenAI
    from .models import SupportQuote

    client = None  # lazy: a no-backlog beat tick shouldn't touch the API at all
    embedded = 0
    while embedded < max_quotes:
        batch = list(SupportQuote.objects.filter(embedding__isnull=True)
                     .exclude(quote='')[:chunk_size])
        if not batch:
            break
        if client is None:
            client = OpenAI(api_key=settings.OPENAI_API_KEY)
        resp = client.embeddings.create(
            input=[q.quote for q in batch], model='text-embedding-3-small')
        for q, emb in zip(batch, resp.data):
            q.embedding = emb.embedding
        # bulk_update fires no post_save (same signal-bypass as queryset.update)
        # and turns 2000 per-row round-trips into a few statements.
        SupportQuote.objects.bulk_update(batch, ['embedding'], batch_size=500)
        embedded += len(batch)
    remaining = SupportQuote.objects.filter(embedding__isnull=True).exclude(quote='').count()
    if embedded and remaining:
        embed_missing_quotes.delay(max_quotes=max_quotes, chunk_size=chunk_size)
    logger.info("embed_missing_quotes: embedded=%d remaining=%d", embedded, remaining)
    return {"embedded": embedded, "remaining": remaining}


@shared_task
@close_db_connection
def refresh_paper_usage_stats_task():
    """Recompute the denormalized dataset-usage rollups on Paper.

    Backs the public papers listing's fast path (see PublicValidatedPapersListView),
    which reads these columns instead of aggregating over DatasetUsage per request.
    Rollups only change when usages are created/deleted/revalidated, so a low
    cadence (daily by default; see beat_schedule) keeps the listing fresh while
    the public page pays no aggregation cost. Also safe to trigger after bulk
    ingestion via ``refresh_paper_usage_stats_task.delay()``.
    """
    from .management.commands.refresh_paper_usage_stats import refresh_paper_usage_stats
    updated = refresh_paper_usage_stats()
    logger.info("refresh_paper_usage_stats_task: updated=%d papers", updated)
    return {"updated": updated}


@shared_task
@close_db_connection
def reconcile_batch_downstream_runs():
    """Beat backstop: re-kick any non-terminal wave-run OR pipeline-run whose lease
    has gone stale (crashed worker / lost countdown task). Durable DB state makes
    this safe."""
    from . import batch_downstream as bd
    from . import batch_pipeline as bp
    stalled = list(bd.find_stalled_runs())
    for run in stalled:
        advance_run_task.delay(str(run.id))
    stalled_p = list(bp.find_stalled_pipelines())
    for run in stalled_p:
        advance_pipeline_task.delay(str(run.id))
    return {"rekicked_runs": [str(r.id) for r in stalled],
            "rekicked_pipelines": [str(r.id) for r in stalled_p]}


# =========================================================================
# CPU regime: idempotent parallel fan-out for the hang-prone stages.
# Per-ITEM tasks (not per-chunk) so each PDF / DU is isolated by its own
# time_limit — one hang kills one prefork process, never a batch of siblings.
# Both drivers are idempotent (skip-if-done); re-running mops up stragglers.
# =========================================================================

def _in_batches(seq, n=1000):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


@shared_task
@close_db_connection
def submit_batch_extraction(paper_ids=None, only_missing=True, allow_ocr=False):
    """Fan out PDF text extraction across the prefork `cpu` workers.
    OCR is OFF by default for corpus runs (scanned PDFs are skipped, not OCR'd)."""
    from django.db.models import Q
    qs = Paper.objects.all() if paper_ids is None else Paper.objects.filter(id__in=paper_ids)
    qs = qs.exclude(Q(pdf='') | Q(pdf__isnull=True))  # need a PDF to extract
    if only_missing:
        qs = qs.filter(Q(full_text__isnull=True) | Q(full_text=''))
    ids = list(qs.values_list('id', flat=True))
    for chunk in _in_batches(ids):
        group(extract_paper_text_task.s(str(pid), allow_ocr) for pid in chunk).apply_async()
    logger.info("submit_batch_extraction: dispatched %s extraction tasks (allow_ocr=%s)",
                len(ids), allow_ocr)
    return {"submitted": len(ids)}


@shared_task
@close_db_connection
def submit_batch_analysis(paper_analysis_ids=None, configuration_name=None,
                          only_missing=True, run_execution=False):
    """Fan out DatasetUsage snippet analysis across the prefork `cpu` workers.
    Live Fido execution is OFF by default for corpus runs (snippet + syntax only —
    no ~630k live queries to VSO/CDAWeb)."""
    dus = DatasetUsage.objects.all()
    if configuration_name:
        dus = dus.filter(paper_analysis__configuration_name=configuration_name)
    if paper_analysis_ids:
        dus = dus.filter(paper_analysis_id__in=paper_analysis_ids)
    if only_missing:
        done = DatasetUsageAnalysis.objects.values_list('dataset_usage_id', flat=True)
        dus = dus.exclude(id__in=done)
    ids = list(dus.values_list('id', flat=True))
    for chunk in _in_batches(ids):
        group(analyze_dataset_usage.s(str(du_id), run_execution) for du_id in chunk).apply_async()
    logger.info("submit_batch_analysis: dispatched %s analysis tasks (run_execution=%s)",
                len(ids), run_execution)
    return {"submitted": len(ids)}


@shared_task(soft_time_limit=150, time_limit=180)
@close_db_connection
def enrich_quote_coordinates(paper_id):
    """Fill review-UI PDF-highlight coordinates for ONE paper's absent SupportQuotes.

    The bulk, off-hot-path counterpart to the corpus-commit coordinate skip
    (coordinates are review-UI-only and never enter a prompt → hash-safe).

    Idempotent + re-runnable: only rows with coordinate_regions == [] are touched;
    a quote that still can't be located stays [] and is retried on the next run.
    Skips OCR'd / PDF-less papers (their text won't align with the token map).
    Builds ONE PDFTextSearcher(fast_index) per PDF, amortized over all the paper's
    absent quotes across every analysis, and writes back via queryset.update() —
    which bypasses post_save, so it touches NO embedding and NO prompt/request_hash.
    """
    from paper_data_linking.processing.pdf_text_search import PDFTextSearcher

    paper = Paper.objects.filter(id=paper_id).first()
    if not paper or not paper.pdf or paper.used_ocr:
        return {"paper_id": str(paper_id), "skipped": "no_pdf_or_ocr", "enriched": 0}

    quotes = list(SupportQuote.objects.filter(
        paper_analysis__paper_id=paper_id, coordinate_regions=[]).exclude(quote=''))
    if not quotes:
        return {"paper_id": str(paper_id), "candidates": 0, "enriched": 0}

    # A missing/corrupt PDF must isolate to this one paper, not abort the sweep.
    try:
        pdf_bytes = read_pdf_bytes(paper.pdf)
        searcher = PDFTextSearcher(pdf_bytes, fast_index=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("enrich_quote_coordinates: paper=%s unreadable PDF (%s); skipping",
                       paper_id, e)
        return {"paper_id": str(paper_id), "skipped": "pdf_unreadable", "enriched": 0}
    try:
        results = searcher.find_quotes_enrich([
            {"quote": q.quote, "instrument": q.instrument, "parameter": q.parameter}
            for q in quotes
        ])
    finally:
        searcher.close()

    enriched = 0
    for q, res in zip(quotes, results):
        location = res.get('location')
        if not location:
            continue
        SupportQuote.objects.filter(id=q.id).update(**_extract_quote_coordinates(location))
        enriched += 1
    logger.info("enrich_quote_coordinates: paper=%s candidates=%d enriched=%d",
                paper_id, len(quotes), enriched)
    return {"paper_id": str(paper_id), "candidates": len(quotes), "enriched": enriched}


@shared_task
@close_db_connection
def submit_batch_enrich_coordinates(paper_ids=None, configuration_name=None):
    """Fan out per-PAPER coordinate enrichment across the prefork `cpu` workers.

    One task per paper (one PDF index amortized over all its absent quotes).
    Selects only papers that actually have absent quotes AND a usable (non-OCR)
    PDF, so never-reviewed / already-filled papers cost nothing. Idempotent +
    re-runnable — a repeat call just mops up the still-unlocated tail.
    """
    from django.db.models import Q
    sq = SupportQuote.objects.filter(coordinate_regions=[]).exclude(quote='')
    if configuration_name:
        sq = sq.filter(paper_analysis__configuration_name=configuration_name)
    if paper_ids:
        sq = sq.filter(paper_analysis__paper_id__in=paper_ids)
    sq = sq.filter(paper_analysis__paper__used_ocr=False).exclude(
        Q(paper_analysis__paper__pdf='') | Q(paper_analysis__paper__pdf__isnull=True))
    pids = list(sq.values_list('paper_analysis__paper_id', flat=True).distinct())
    for chunk in _in_batches(pids):
        group(enrich_quote_coordinates.s(str(pid)) for pid in chunk).apply_async()
    logger.info("submit_batch_enrich_coordinates: dispatched %d papers", len(pids))
    return {"submitted": len(pids)}


# =========================================================================
# End-to-end batch pipeline (extract -> step1 -> downstream -> analyze).
# The 90k entrypoint. Crash-safe via lease + the beat reconciler below.
# =========================================================================

@shared_task
@close_db_connection
def submit_batch_pipeline(paper_ids, configuration_name, aws_region_name=None,
                          allow_ocr=False, run_execution=False):
    from . import batch_pipeline as bp
    run = bp.create_pipeline(paper_ids, configuration_name, aws_region_name,
                             allow_ocr=allow_ocr, run_execution=run_execution)
    advance_pipeline_task.delay(str(run.id))
    return {"pipeline_run_id": str(run.id), "papers": len(run.paper_ids)}


@shared_task(bind=True)
@close_db_connection
def advance_pipeline_task(self, run_id):
    from . import batch_pipeline as bp
    res = bp.advance_pipeline(run_id)
    if res.get("reschedule"):
        advance_pipeline_task.apply_async(args=[run_id], countdown=res["reschedule"])
    return res


@shared_task
@close_db_connection
def pipeline_stage_done(results, run_id, stage):
    """Chord callback for the fan-out stages (extract, analyze): mark the stage done
    and re-enter the driver. `results` is the chord's aggregated task results."""
    from .models import BatchPipelineRun
    run = BatchPipelineRun.objects.get(id=run_id)
    setattr(run, f"{stage}_done", True)
    run.save(update_fields=[f"{stage}_done", "updated_at"])
    advance_pipeline_task.delay(run_id)
    return {"stage": stage, "done": True}
