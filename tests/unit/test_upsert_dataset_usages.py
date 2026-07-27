"""Tests for _upsert_dataset_usages_from_normalized in tasks.py.

This is the core function that creates DatasetUsage records (and SupportQuotes)
from a PaperAnalysis's normalized_instrument_details JSON.
"""
import pytest
from vso_query_builder.tasks import _upsert_dataset_usages_from_normalized
from vso_query_builder.models import DatasetUsage, SupportQuote, QuoteUsageLink


def _make_normalized_json(instruments):
    """Helper to build normalized_instrument_details JSON."""
    return {"instruments": instruments}


def _make_instrument_entry(
    original="LASCO",
    inst_code="LASCO",
    mission_code="SOHO",
    data_system="vso",
    periods=None,
    supporting_quotes=None,
):
    """Helper to build a single instrument entry."""
    entry = {
        "name": {
            "original": original,
            "normalized": {
                "matched_instrument_code": inst_code,
                "matched_mission_code": mission_code,
                "data_system": data_system,
            },
        },
        "data_collection_periods": periods or [],
    }
    if supporting_quotes is not None:
        entry["supporting_quotes"] = supporting_quotes
    return entry


def _make_period(
    start="2003-01-01T00:00:00Z",
    end="2003-01-02T00:00:00Z",
    period_name="Period 1",
    extra_fields=None,
    supporting_quotes=None,
):
    """Helper to build a data collection period."""
    period = {
        "period_name": period_name,
        "time_range": {
            "normalized": {
                "start_datetime": start,
                "end_datetime": end,
            }
        },
    }
    if extra_fields:
        period.update(extra_fields)
    if supporting_quotes is not None:
        period["supporting_quotes"] = supporting_quotes
    return period


@pytest.fixture
def catalog_setup(vso_datasource, observatory_factory, instrument_factory):
    """Create a minimal instrument catalog: VSO > SOHO > LASCO."""
    obs_soho = observatory_factory("SOHO")
    inst_lasco = instrument_factory(obs_soho, "LASCO")
    return {
        "datasource": vso_datasource,
        "observatory": obs_soho,
        "instrument": inst_lasco,
    }


@pytest.mark.django_db
class TestUpsertDatasetUsages:

    def test_happy_path_single_instrument_single_period(
        self, catalog_setup, paper_analysis_factory
    ):
        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json([
                _make_instrument_entry(periods=[_make_period()])
            ])
        )

        count = _upsert_dataset_usages_from_normalized(pa)

        assert count == 1
        du = DatasetUsage.objects.get()
        assert du.paper == pa.paper
        assert du.paper_analysis == pa
        assert du.instrument == catalog_setup["instrument"]
        assert du.observation_window is not None

    def test_multiple_periods_creates_multiple_usages(
        self, catalog_setup, paper_analysis_factory
    ):
        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json([
                _make_instrument_entry(periods=[
                    _make_period(start="2003-01-01T00:00:00Z", end="2003-01-02T00:00:00Z"),
                    _make_period(start="2003-06-01T00:00:00Z", end="2003-06-02T00:00:00Z"),
                ])
            ])
        )

        count = _upsert_dataset_usages_from_normalized(pa)

        assert count == 2
        assert DatasetUsage.objects.count() == 2

    def test_multiple_instruments(
        self, catalog_setup, paper_analysis_factory, observatory_factory, instrument_factory
    ):
        obs_stereo = observatory_factory("STEREO_A")
        instrument_factory(obs_stereo, "SECCHI")

        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json([
                _make_instrument_entry(
                    original="LASCO", inst_code="LASCO", mission_code="SOHO",
                    periods=[_make_period()],
                ),
                _make_instrument_entry(
                    original="SECCHI", inst_code="SECCHI", mission_code="STEREO_A",
                    periods=[_make_period(start="2010-01-01T00:00:00Z", end="2010-01-02T00:00:00Z")],
                ),
            ])
        )

        count = _upsert_dataset_usages_from_normalized(pa)

        assert count == 2
        assert DatasetUsage.objects.count() == 2

    def test_idempotency_no_duplicates(
        self, catalog_setup, paper_analysis_factory
    ):
        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json([
                _make_instrument_entry(periods=[_make_period()])
            ])
        )

        count1 = _upsert_dataset_usages_from_normalized(pa)
        count2 = _upsert_dataset_usages_from_normalized(pa)

        assert count1 == 1
        assert count2 == 0  # get_or_create returns existing
        assert DatasetUsage.objects.count() == 1

    def test_missing_data_system_skips_instrument(
        self, catalog_setup, paper_analysis_factory
    ):
        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json([
                _make_instrument_entry(data_system=None, periods=[_make_period()])
            ])
        )

        count = _upsert_dataset_usages_from_normalized(pa)

        assert count == 0
        assert DatasetUsage.objects.count() == 0

    def test_unknown_datasource_slug_skips(
        self, catalog_setup, paper_analysis_factory
    ):
        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json([
                _make_instrument_entry(data_system="nonexistent", periods=[_make_period()])
            ])
        )

        count = _upsert_dataset_usages_from_normalized(pa)

        assert count == 0

    def test_unknown_instrument_code_skips(
        self, catalog_setup, paper_analysis_factory
    ):
        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json([
                _make_instrument_entry(inst_code="UNKNOWN_INST", periods=[_make_period()])
            ])
        )

        count = _upsert_dataset_usages_from_normalized(pa)

        assert count == 0

    def test_missing_start_datetime_skips_period(
        self, catalog_setup, paper_analysis_factory
    ):
        period = _make_period()
        period["time_range"]["normalized"]["start_datetime"] = None

        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json([
                _make_instrument_entry(periods=[period])
            ])
        )

        count = _upsert_dataset_usages_from_normalized(pa)

        assert count == 0

    def test_invalid_iso_datetime_skips_period(
        self, catalog_setup, paper_analysis_factory
    ):
        period = _make_period(start="not-a-date", end="also-not-a-date")

        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json([
                _make_instrument_entry(periods=[period])
            ])
        )

        count = _upsert_dataset_usages_from_normalized(pa)

        assert count == 0

    def test_reversed_time_range_skips_period_not_paper(
        self, catalog_setup, paper_analysis_factory
    ):
        """Issue #169: a model-emitted reversed range (start > end) must skip only
        its own period. Pre-fix, Postgres rejected the reversed tstzrange and the
        uncaught error aborted every remaining period AND instrument."""
        reversed_period = _make_period(
            start="2005-06-01T00:00:00Z", end="2003-06-01T00:00:00Z",
            period_name="reversed")
        good_period = _make_period(period_name="good")
        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json([
                _make_instrument_entry(periods=[reversed_period, good_period]),
            ])
        )

        count = _upsert_dataset_usages_from_normalized(pa)

        assert count == 1  # the good period survives its reversed sibling
        du = DatasetUsage.objects.get()
        assert du.observation_window.lower.year == 2003

    def test_reversed_range_does_not_abort_later_instruments(
        self, catalog_setup, paper_analysis_factory, observatory_factory,
        instrument_factory
    ):
        """Issue #169, the prod shape: instrument A has ONLY a reversed period;
        instrument B (processed after) must still get its DatasetUsage."""
        obs = observatory_factory("STEREO_A")
        instrument_factory(obs, "SECCHI")
        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json([
                _make_instrument_entry(periods=[_make_period(
                    start="2005-06-01T00:00:00Z", end="2003-06-01T00:00:00Z")]),
                _make_instrument_entry(
                    original="SECCHI", inst_code="SECCHI",
                    mission_code="STEREO_A", periods=[_make_period()]),
            ])
        )

        count = _upsert_dataset_usages_from_normalized(pa)

        assert count == 1
        assert DatasetUsage.objects.get().instrument.short_name == "SECCHI"

    def test_instrument_error_is_isolated_and_signal_reconnected(
        self, catalog_setup, paper_analysis_factory, observatory_factory,
        instrument_factory, monkeypatch
    ):
        """Issue #169 hardening: an unexpected per-instrument error skips only that
        instrument, and the post_save embedding signal is ALWAYS reconnected (the
        pre-fix escape path left it disconnected for the worker's lifetime)."""
        from django.db.models.signals import post_save
        from vso_query_builder import tasks as tasks_mod
        obs = observatory_factory("STEREO_B")
        instrument_factory(obs, "HET")
        bad = _make_instrument_entry(periods=[_make_period()])
        bad["name"] = {"original": "LASCO"}  # missing 'normalized' -> KeyError in body
        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json([
                bad,
                _make_instrument_entry(
                    original="HET", inst_code="HET",
                    mission_code="STEREO_B", periods=[_make_period()]),
            ])
        )

        count = _upsert_dataset_usages_from_normalized(pa)

        assert count == 1  # HET survives LASCO's KeyError
        # Signal must be live again: post_save.disconnect returns True only if
        # the receiver was still connected.
        assert post_save.disconnect(
            tasks_mod._create_embedding_signal, sender=SupportQuote) is True
        post_save.connect(tasks_mod._create_embedding_signal, sender=SupportQuote)

    def test_extra_params_populated(
        self, catalog_setup, paper_analysis_factory
    ):
        period = _make_period(extra_fields={
            "wavelengths": {"normalized": [{"min": 171, "max": 171, "unit": "Angstrom"}]},
            "physical_observable": {"normalized": {"physobs": "intensity"}},
        })

        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json([
                _make_instrument_entry(periods=[period])
            ])
        )

        _upsert_dataset_usages_from_normalized(pa)

        du = DatasetUsage.objects.get()
        assert du.extra_params["wavelengths"] == [{"min": 171, "max": 171, "unit": "Angstrom"}]
        assert du.extra_params["physical_observable"] == {"physobs": "intensity"}

    def test_period_quotes_created_and_linked(
        self, catalog_setup, paper_analysis_factory
    ):
        period = _make_period(supporting_quotes={
            "normalized": {
                "time": [{"text": "observed on Jan 1 2003", "location": {"page": 1}}],
            }
        })

        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json([
                _make_instrument_entry(periods=[period])
            ])
        )

        _upsert_dataset_usages_from_normalized(pa)

        assert SupportQuote.objects.count() == 1
        du = DatasetUsage.objects.get()
        assert du.supporting_quotes.count() == 1
        assert QuoteUsageLink.objects.count() == 1

    def test_quotes_idempotent_across_reruns(
        self, catalog_setup, paper_analysis_factory
    ):
        """Commit re-entries re-run this function (DatasetUsage is get_or_create,
        so re-running is the designed recovery path) — quotes must not duplicate.
        Bare create() multiplied quotes ~30x on runs whose commits re-entered
        repeatedly (observed live on the effort-matrix mixed arms)."""
        period_quotes = {"normalized": {
            "time": [{"text": "observed on Jan 1 2003", "location": {"page": 1}}],
            "general": [{"text": "we analyze LASCO data", "location": None}],
        }}
        inst_quotes = {"normalized": {
            "general": [{"text": "an instrument-level quote", "location": None}],
        }}
        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json([
                _make_instrument_entry(
                    periods=[_make_period(supporting_quotes=period_quotes)],
                    supporting_quotes=inst_quotes,
                )
            ])
        )

        _upsert_dataset_usages_from_normalized(pa)
        n_quotes = SupportQuote.objects.count()
        n_links = QuoteUsageLink.objects.count()
        assert n_quotes == 3

        _upsert_dataset_usages_from_normalized(pa)
        _upsert_dataset_usages_from_normalized(pa)

        assert SupportQuote.objects.count() == n_quotes
        assert QuoteUsageLink.objects.count() == n_links
        assert DatasetUsage.objects.get().supporting_quotes.count() == n_quotes

    def test_empty_normalized_details_returns_zero(
        self, paper_analysis_factory
    ):
        pa = paper_analysis_factory(normalized_instrument_details=None)
        assert _upsert_dataset_usages_from_normalized(pa) == 0

        pa2 = paper_analysis_factory(normalized_instrument_details={})
        assert _upsert_dataset_usages_from_normalized(pa2) == 0

    def test_null_normalized_name_skips(
        self, catalog_setup, paper_analysis_factory
    ):
        entry = {
            "name": {"original": "LASCO", "normalized": None},
            "data_collection_periods": [_make_period()],
        }
        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json([entry])
        )

        count = _upsert_dataset_usages_from_normalized(pa)
        assert count == 0


@pytest.mark.django_db
class TestCorpusModeCommitPath:
    """Corpus-mode commits skip the UI-only expensive work (coordinates,
    inline embeddings); default runs are untouched."""

    def _quote_pa(self, paper_analysis_factory):
        return paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json([
                _make_instrument_entry(periods=[_make_period(supporting_quotes={
                    "normalized": {"time": [{"text": "a corpus quote", "location": None}]}
                })])
            ])
        )

    def test_gate_helper_reads_mode_and_run_flag(self):
        from paper_data_linking.pipeline_context import batch_execution
        from vso_query_builder import batch_downstream as bd
        from vso_query_builder.tasks import _in_corpus_mode_commit

        corpus = bd.create_run([], "bedrock-120b-high-v5", corpus_mode=True)
        normal = bd.create_run([], "bedrock-120b-high-v5")

        assert _in_corpus_mode_commit() is False          # off-mode (interactive)
        with batch_execution('commit', corpus.id):
            assert _in_corpus_mode_commit() is True
        with batch_execution('commit', normal.id):
            assert _in_corpus_mode_commit() is False
        with batch_execution('collection', corpus.id):
            assert _in_corpus_mode_commit() is False      # only commits are gated

    def test_corpus_commit_defers_embeddings(self, catalog_setup, paper_analysis_factory,
                                             monkeypatch):
        from paper_data_linking.pipeline_context import batch_execution
        from vso_query_builder import batch_downstream as bd
        import vso_query_builder.tasks as tasks_mod

        def _boom(*a, **k):
            raise AssertionError("OpenAI must not be called in a corpus-mode commit")
        monkeypatch.setattr("openai.OpenAI", _boom)

        run = bd.create_run([], "bedrock-120b-high-v5", corpus_mode=True)
        pa = self._quote_pa(paper_analysis_factory)
        with batch_execution('commit', run.id):
            count = tasks_mod._upsert_dataset_usages_from_normalized(pa)

        assert count == 1
        q = SupportQuote.objects.get()
        assert q.embedding is None                        # deferred to the sweeper

    def test_embed_missing_quotes_sweeps_nulls(self, catalog_setup, paper_analysis_factory,
                                               monkeypatch):
        from types import SimpleNamespace
        from paper_data_linking.pipeline_context import batch_execution
        from vso_query_builder import batch_downstream as bd
        import vso_query_builder.tasks as tasks_mod

        run = bd.create_run([], "bedrock-120b-high-v5", corpus_mode=True)
        pa = self._quote_pa(paper_analysis_factory)
        with batch_execution('commit', run.id):
            tasks_mod._upsert_dataset_usages_from_normalized(pa)
        assert SupportQuote.objects.filter(embedding__isnull=True).count() == 1

        class FakeClient:
            def __init__(self, **kw):
                self.embeddings = self
            def create(self, input, model):
                return SimpleNamespace(data=[
                    SimpleNamespace(embedding=[0.5] * 1536) for _ in input])
        monkeypatch.setattr("openai.OpenAI", FakeClient)

        res = tasks_mod.embed_missing_quotes()
        assert res == {"embedded": 1, "remaining": 0}
        assert SupportQuote.objects.filter(embedding__isnull=True).count() == 0


@pytest.mark.django_db
class TestEmbeddingSignalCorpusGate:
    def test_signal_skips_embedding_in_corpus_commit(self, paper_analysis_factory, monkeypatch):
        """Quotes created OUTSIDE the upsert's signal-disconnect window (e.g. the
        phenomenon-mentions physobs path) fire the post_save signal — in a
        corpus-mode commit the signal must NOT call OpenAI (the sweeper embeds
        later). Observed live pre-fix: 124/2593 quotes sync-embedded."""
        from paper_data_linking.pipeline_context import batch_execution
        from vso_query_builder import batch_downstream as bd
        import vso_query_builder.signals as signals_mod

        def _boom(*a, **k):
            raise AssertionError("signal must not embed during corpus-mode commit")
        monkeypatch.setattr(signals_mod.client.embeddings, "create", _boom)

        pa = paper_analysis_factory()
        run = bd.create_run([], "bedrock-120b-high-v5", corpus_mode=True)
        q = SupportQuote.objects.create(
            paper_analysis=pa, quote="signal-path quote",
            instrument="LASCO", parameter="physobs",
            page_number=0, y_coord=0.0, x_coord_start=0.0, x_coord_end=0.0,
            y_coord_start=0.0, y_coord_end=0.0)
        # Invoke the handler directly (unit env has no receivers wired; the
        # runtime wiring is what produced the live leak this fix closes).
        with batch_execution('commit', run.id):
            signals_mod.create_embedding(SupportQuote, q, created=True)
        q.refresh_from_db()
        assert q.embedding is None                # deferred, not embedded

    def test_signal_still_embeds_outside_corpus_commit(self, paper_analysis_factory, monkeypatch):
        from types import SimpleNamespace
        import vso_query_builder.signals as signals_mod
        calls = []
        monkeypatch.setattr(
            signals_mod.client.embeddings, "create",
            lambda input, model: (calls.append(input),
                                  SimpleNamespace(data=[SimpleNamespace(embedding=[0.1] * 1536)]))[1])
        pa = paper_analysis_factory()
        q = SupportQuote.objects.create(
            paper_analysis=pa, quote="interactive quote",
            instrument="LASCO", parameter="physobs",
            page_number=0, y_coord=0.0, x_coord_start=0.0, x_coord_end=0.0,
            y_coord_start=0.0, y_coord_end=0.0)
        signals_mod.create_embedding(SupportQuote, q, created=True)
        q.refresh_from_db()
        assert calls == [["interactive quote"]]   # handler embeds normally
        assert q.embedding is not None


@pytest.mark.django_db
class TestPhenomenaIntentionalOnly:
    """Phenomena never run in the standard chain; run_phenomena_enrichment is
    the deliberate entry point (extraction + merge + mention upsert)."""

    def test_create_dataset_usages_writes_no_phenomenon_mentions(
            self, catalog_setup, paper_analysis_factory):
        import vso_query_builder.tasks as tasks_mod
        from vso_query_builder.models import Phenomenon, PhenomenonMention
        Phenomenon.objects.create(name="Solar Wind", iri="hkp:SolarWind")
        period = _make_period(extra_fields={
            "physical_observable": {"original": "proton density"},
            "phenomenon": {"phenomena": [{"iri": "hkp:SolarWind", "name": "Solar Wind"}]},
        })
        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json(
                [_make_instrument_entry(periods=[period])]))
        tasks_mod.create_dataset_usages({
            "success": True, "paper_id": str(pa.paper_id),
            "paper_analysis_id": str(pa.id), "paper_bibcode": pa.paper.bibcode})
        assert PhenomenonMention.objects.count() == 0  # intentional-only now

    def test_enrichment_extracts_merges_and_upserts(
            self, catalog_setup, paper_analysis_factory, monkeypatch):
        import vso_query_builder.tasks as tasks_mod
        from vso_query_builder.models import Phenomenon, PhenomenonMention
        from paper_data_linking.linkers.general.normalizers import NormalizerRegistry
        Phenomenon.objects.create(name="Solar Wind", iri="hkp:SolarWind")

        class StubNormalizer:
            calls = 0
            def __init__(self, llm_client=None, llm_config=None): pass
            def normalize(self, ctx):
                StubNormalizer.calls += 1
                assert ctx.period_data.physical_observable == "proton density"
                return {"phenomena": [{"iri": "hkp:SolarWind", "name": "Solar Wind"}]}
        monkeypatch.setattr(NormalizerRegistry, "get_normalizer_for_data_source",
                            classmethod(lambda cls, *a, **k: StubNormalizer))

        period = _make_period(extra_fields={
            "physical_observable": {"original": "proton density"}})
        pa = paper_analysis_factory(
            normalized_instrument_details=_make_normalized_json(
                [_make_instrument_entry(periods=[period])]))

        res = tasks_mod.run_phenomena_enrichment.run(pa.id)
        assert res["success"] and res["periods_extracted"] == 1
        pa.refresh_from_db()
        stored = pa.normalized_instrument_details["instruments"][0][
            "data_collection_periods"][0]["phenomenon"]["phenomena"]
        assert stored[0]["iri"] == "hkp:SolarWind"      # merged into the JSON
        assert PhenomenonMention.objects.count() == 1    # upserted

        # Idempotent: second run extracts nothing, mentions don't duplicate.
        res2 = tasks_mod.run_phenomena_enrichment.run(pa.id)
        assert res2["periods_extracted"] == 0 and res2["periods_already_done"] == 1
        assert PhenomenonMention.objects.count() == 1
        assert StubNormalizer.calls == 1
