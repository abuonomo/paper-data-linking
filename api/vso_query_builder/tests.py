from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import (
    DataSource, Observatory, Instrument,
    Paper, PaperAnalysis, InstrumentMention, Phenomenon, PhenomenonMention,
    SupportQuote,
)
from .models import LLMCall
from .tasks import (
    _upsert_instrument_mentions_from_normalized,
    _upsert_mission_only_from_llm_calls,
    _backfill_mission_only_from_input_messages,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_norm_entry(
    original="SDO/AIA",
    inst_code="AIA",
    mission_code="SDO",
    data_system="vso",
    periods=None,
):
    """Build one instruments[] entry for normalized_instrument_details."""
    if periods is None:
        periods = [{"time_range": {"normalized": {
            "start_datetime": "2010-01-01T00:00:00Z",
            "end_datetime":   "2010-12-31T00:00:00Z",
        }}}]
    return {
        "name": {
            "original": original,
            "normalized": {
                "matched_instrument_code": inst_code,
                "matched_mission_code": mission_code,
                "data_system": data_system,
            },
        },
        "general_comments": "",
        "data_collection_periods": periods,
    }


def make_catalog(ds_slug="vso", obs_short="SDO", inst_short="AIA"):
    """Create DataSource → Observatory → Instrument and return all three."""
    ds  = DataSource.objects.create(slug=ds_slug, name=ds_slug.upper())
    obs = Observatory.objects.create(
        datasource=ds, short_name=obs_short, name=obs_short, display_name=obs_short
    )
    inst = Instrument.objects.create(
        observatory=obs, short_name=inst_short, full_name=inst_short, display_name=inst_short
    )
    return ds, obs, inst


def make_paper_analysis(norm_json, bibcode="2024test.0001A", config="test"):
    paper = Paper.objects.create(bibcode=bibcode)
    pa = PaperAnalysis.objects.create(
        paper=paper,
        configuration_name=config,
        context={},
        instruments_details="",
        normalized_instrument_details=norm_json,
    )
    return pa


# ---------------------------------------------------------------------------
# _upsert_instrument_mentions_from_normalized
# ---------------------------------------------------------------------------

class UpsertInstrumentMentionsTests(TestCase):

    def setUp(self):
        self.ds, self.obs, self.inst = make_catalog()

    def test_full_match_creates_row(self):
        pa = make_paper_analysis({"instruments": [make_norm_entry()]})
        count = _upsert_instrument_mentions_from_normalized(pa)
        self.assertEqual(count, 1)
        m = InstrumentMention.objects.get(paper_analysis=pa)
        self.assertEqual(m.match_level, InstrumentMention.MATCH_LEVEL_FULL)
        self.assertEqual(m.matched_instrument, self.inst)
        self.assertIsNone(m.matched_observatory)

    def test_full_match_observatory_not_stored(self):
        """matched_observatory must be None — derived from matched_instrument.observatory."""
        pa = make_paper_analysis({"instruments": [make_norm_entry()]})
        _upsert_instrument_mentions_from_normalized(pa)
        m = InstrumentMention.objects.get(paper_analysis=pa)
        self.assertIsNone(m.matched_observatory)
        self.assertEqual(m.matched_instrument.observatory, self.obs)

    def test_instrument_no_time_no_periods(self):
        entry = make_norm_entry(periods=[])
        pa = make_paper_analysis({"instruments": [entry]})
        _upsert_instrument_mentions_from_normalized(pa)
        m = InstrumentMention.objects.get(paper_analysis=pa)
        self.assertEqual(m.match_level, InstrumentMention.MATCH_LEVEL_INSTRUMENT_NO_TIME)

    def test_instrument_no_time_unparseable_periods(self):
        entry = make_norm_entry(periods=[
            {"time_range": {"normalized": {"start_datetime": "bad", "end_datetime": "bad"}}},
        ])
        pa = make_paper_analysis({"instruments": [entry]})
        _upsert_instrument_mentions_from_normalized(pa)
        m = InstrumentMention.objects.get(paper_analysis=pa)
        self.assertEqual(m.match_level, InstrumentMention.MATCH_LEVEL_INSTRUMENT_NO_TIME)

    def test_partial_match_some_periods_bad(self):
        entry = make_norm_entry(periods=[
            {"time_range": {"normalized": {
                "start_datetime": "2010-01-01T00:00:00Z",
                "end_datetime":   "2010-06-01T00:00:00Z",
            }}},
            {"time_range": {"normalized": {"start_datetime": "bad", "end_datetime": "bad"}}},
        ])
        pa = make_paper_analysis({"instruments": [entry]})
        _upsert_instrument_mentions_from_normalized(pa)
        m = InstrumentMention.objects.get(paper_analysis=pa)
        self.assertEqual(m.match_level, InstrumentMention.MATCH_LEVEL_PARTIAL)

    def test_mission_only_no_instrument_code(self):
        entry = make_norm_entry(inst_code=None)
        pa = make_paper_analysis({"instruments": [entry]})
        count = _upsert_instrument_mentions_from_normalized(pa)
        self.assertEqual(count, 1)
        m = InstrumentMention.objects.get(paper_analysis=pa)
        self.assertEqual(m.match_level, InstrumentMention.MATCH_LEVEL_MISSION_ONLY)
        self.assertEqual(m.matched_observatory, self.obs)
        self.assertIsNone(m.matched_instrument)

    def test_mission_only_unknown_instrument_code(self):
        entry = make_norm_entry(inst_code="UNKNOWN_INST")
        pa = make_paper_analysis({"instruments": [entry]})
        _upsert_instrument_mentions_from_normalized(pa)
        m = InstrumentMention.objects.get(paper_analysis=pa)
        self.assertEqual(m.match_level, InstrumentMention.MATCH_LEVEL_MISSION_ONLY)
        self.assertIsNone(m.matched_instrument)

    def test_unmatched_skipped(self):
        """When nothing in the catalog matches, no row is written."""
        # data_system unknown → ds/obs both None; inst_code unknown → fallback also misses
        entry = make_norm_entry(data_system="nonexistent", inst_code="NOINST")
        pa = make_paper_analysis({"instruments": [entry]})
        count = _upsert_instrument_mentions_from_normalized(pa)
        self.assertEqual(count, 0)
        self.assertEqual(InstrumentMention.objects.filter(paper_analysis=pa).count(), 0)

    def test_malformed_name_norm_list_skipped(self):
        entry = {
            "name": {"original": "Weird", "normalized": ["a", "b"]},
            "data_collection_periods": [],
        }
        pa = make_paper_analysis({"instruments": [entry]})
        count = _upsert_instrument_mentions_from_normalized(pa)
        self.assertEqual(count, 0)

    def test_malformed_name_norm_none_skipped(self):
        entry = {
            "name": {"original": "Weird", "normalized": None},
            "data_collection_periods": [],
        }
        pa = make_paper_analysis({"instruments": [entry]})
        count = _upsert_instrument_mentions_from_normalized(pa)
        self.assertEqual(count, 0)

    def test_empty_normalized_details_returns_zero(self):
        pa = make_paper_analysis({})
        count = _upsert_instrument_mentions_from_normalized(pa)
        self.assertEqual(count, 0)

    def test_null_normalized_details_returns_zero(self):
        pa = make_paper_analysis(None)
        count = _upsert_instrument_mentions_from_normalized(pa)
        self.assertEqual(count, 0)

    def test_idempotent(self):
        """Running twice produces the same single row."""
        pa = make_paper_analysis({"instruments": [make_norm_entry()]})
        _upsert_instrument_mentions_from_normalized(pa)
        _upsert_instrument_mentions_from_normalized(pa)
        self.assertEqual(InstrumentMention.objects.filter(paper_analysis=pa).count(), 1)

    def test_multiple_instruments(self):
        make_catalog(ds_slug="cdaweb", obs_short="WIND", inst_short="3DP")
        entries = [
            make_norm_entry(),
            make_norm_entry(
                original="Wind/3DP",
                inst_code="3DP",
                mission_code="WIND",
                data_system="cdaweb",
            ),
        ]
        pa = make_paper_analysis({"instruments": entries}, bibcode="2024test.multi")
        count = _upsert_instrument_mentions_from_normalized(pa)
        self.assertEqual(count, 2)
        self.assertEqual(InstrumentMention.objects.filter(paper_analysis=pa).count(), 2)


# ---------------------------------------------------------------------------
# PublicPaperInstrumentMentionsView
# ---------------------------------------------------------------------------

class InstrumentMentionsViewTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.ds, self.obs, self.inst = make_catalog()
        self.pa = make_paper_analysis(
            {"instruments": [make_norm_entry()]},
            bibcode="2024view.0001A",
        )
        _upsert_instrument_mentions_from_normalized(self.pa)

    def _url(self, bibcode):
        return f"/builder/public/papers/{bibcode}/instrument-mentions/"

    def test_returns_mentions(self):
        resp = self.client.get(self._url("2024view.0001A"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("mentions", data)
        self.assertEqual(len(data["mentions"]), 1)

    def test_mention_shape(self):
        resp = self.client.get(self._url("2024view.0001A"))
        m = resp.json()["mentions"][0]
        self.assertIn("id", m)
        self.assertIn("match_level", m)
        self.assertIn("observatory", m)
        self.assertIn("instrument", m)
        # removed fields must not leak through
        self.assertNotIn("paper_name", m)
        self.assertNotIn("general_comments", m)
        self.assertNotIn("data_system", m)

    def test_observatory_derived_from_instrument(self):
        """For a full match the serializer derives observatory from matched_instrument."""
        resp = self.client.get(self._url("2024view.0001A"))
        m = resp.json()["mentions"][0]
        self.assertEqual(m["match_level"], "full")
        self.assertEqual(m["observatory"]["short_name"], "SDO")
        self.assertEqual(m["instrument"]["short_name"], "AIA")

    def test_match_level_filter(self):
        obs2 = Observatory.objects.create(
            datasource=self.ds, short_name="SOHO", name="SOHO", display_name="SOHO"
        )
        InstrumentMention.objects.create(
            paper_analysis=self.pa,
            matched_observatory=obs2,
            match_level=InstrumentMention.MATCH_LEVEL_MISSION_ONLY,
        )
        resp = self.client.get(self._url("2024view.0001A") + "?match_level=mission_only")
        data = resp.json()
        self.assertEqual(len(data["mentions"]), 1)
        self.assertEqual(data["mentions"][0]["match_level"], "mission_only")

    def test_invalid_match_level_ignored(self):
        """A bogus level is silently dropped — falls back to returning all."""
        resp = self.client.get(self._url("2024view.0001A") + "?match_level=bogus")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["mentions"]), 1)

    def test_404_unknown_bibcode(self):
        resp = self.client.get(self._url("9999.notreal"))
        self.assertEqual(resp.status_code, 404)

    def test_ordering_worst_to_best(self):
        """mission_only < instrument_no_time < full in response order."""
        obs2 = Observatory.objects.create(
            datasource=self.ds, short_name="SOHO", name="SOHO", display_name="SOHO"
        )
        inst2 = Instrument.objects.create(
            observatory=obs2, short_name="LASCO", full_name="LASCO", display_name="LASCO"
        )
        InstrumentMention.objects.create(
            paper_analysis=self.pa,
            matched_observatory=obs2,
            match_level=InstrumentMention.MATCH_LEVEL_MISSION_ONLY,
        )
        InstrumentMention.objects.create(
            paper_analysis=self.pa,
            matched_instrument=inst2,
            match_level=InstrumentMention.MATCH_LEVEL_INSTRUMENT_NO_TIME,
        )
        resp = self.client.get(self._url("2024view.0001A"))
        levels = [m["match_level"] for m in resp.json()["mentions"]]
        self.assertEqual(levels, ["mission_only", "instrument_no_time", "full"])


# ---------------------------------------------------------------------------
# PhenomenaQueuePapersView
# ---------------------------------------------------------------------------

class PhenomenaQueuePapersViewTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(
            user=get_user_model().objects.create_user(username='phenomena-validator')
        )
        phenomenon = Phenomenon.objects.create(name='Solar Wind', iri='hkp:SolarWind')

        self.pending_paper = Paper.objects.create(bibcode='2024queue.pending')
        pending_analysis = PaperAnalysis.objects.create(
            paper=self.pending_paper,
            configuration_name='test',
            context={},
            instruments_details='',
        )
        PhenomenonMention.objects.create(
            paper_analysis=pending_analysis,
            phenomenon=phenomenon,
            instrument_name='AIA',
            validation_status='pending',
        )
        PhenomenonMention.objects.create(
            paper_analysis=pending_analysis,
            phenomenon=phenomenon,
            instrument_name='HMI',
            validation_status='accepted',
        )

        self.complete_paper = Paper.objects.create(bibcode='2024queue.complete')
        complete_analysis = PaperAnalysis.objects.create(
            paper=self.complete_paper,
            configuration_name='test',
            context={},
            instruments_details='',
        )
        PhenomenonMention.objects.create(
            paper_analysis=complete_analysis,
            phenomenon=phenomenon,
            instrument_name='LASCO',
            validation_status='accepted',
        )

        Paper.objects.create(bibcode='2024queue.no-mentions')

    def _get_queue(self, validation_status):
        response = self.client.get(
            '/builder/phenomenon-mentions/papers-queue/',
            {'validation_status': validation_status},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()['results']

    def test_pending_queue_uses_annotated_counts(self):
        results = self._get_queue('pending')

        self.assertEqual([item['bibcode'] for item in results], ['2024queue.pending'])
        self.assertEqual(results[0]['total_mentions'], 2)
        self.assertEqual(results[0]['pending_mentions'], 1)
        self.assertEqual(results[0]['accepted_mentions'], 1)

    def test_complete_queue_excludes_pending_and_empty_papers(self):
        results = self._get_queue('complete')

        self.assertEqual([item['bibcode'] for item in results], ['2024queue.complete'])
        self.assertEqual(results[0]['total_mentions'], 1)
        self.assertEqual(results[0]['pending_mentions'], 0)
        self.assertEqual(results[0]['accepted_mentions'], 1)

    def test_paper_phenomena_prefetches_supporting_quotes(self):
        analysis = self.pending_paper.paperanalysis_set.get(configuration_name='test')
        quote = SupportQuote.objects.create(
            paper_analysis=analysis,
            quote='Observed solar wind.',
            instrument='AIA',
            parameter='speed',
            page_number=1,
            y_coord=0,
        )
        mention = analysis.phenomenon_mentions.get(instrument_name='AIA')
        mention.supporting_quote = quote
        mention.save(update_fields=['supporting_quote'])
        mention.supporting_quotes.add(quote)

        with self.assertNumQueries(3):
            response = self.client.get(
                f'/builder/papers/{self.pending_paper.id}/phenomena/'
            )

        self.assertEqual(response.status_code, 200)
        result = next(item for item in response.json()['mentions'] if item['id'] == str(mention.id))
        self.assertEqual(result['supporting_quote']['id'], quote.id)
        self.assertEqual([item['id'] for item in result['supporting_quotes']], [quote.id])

    def test_phenomena_analysis_view_is_filtered_and_lightweight(self):
        response = self.client.get(
            f'/builder/papers/{self.pending_paper.id}/analysis/',
            {'configuration_name': 'test', 'view': 'phenomena'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        analysis = response.json()[0]
        self.assertEqual(analysis['configuration_name'], 'test')
        self.assertIn('instruments_details', analysis)
        self.assertNotIn('context', analysis)
        self.assertNotIn('llm_calls', analysis)


# ---------------------------------------------------------------------------
# _upsert_mission_only_from_llm_calls
# ---------------------------------------------------------------------------

def make_llm_call(call_type, render_context, output_content):
    return LLMCall.objects.create(
        call_type=call_type,
        model_name='test-model',
        provider='test',
        render_context=render_context,
        output_content=output_content,
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        estimated_cost_usd=0,
    )


class UpsertMissionOnlyFromLLMCallsTests(TestCase):

    def setUp(self):
        self.ds, self.obs, self.inst = make_catalog(
            ds_slug='vso', obs_short='SOHO', inst_short='LASCO'
        )

    def _make_pa(self, bibcode='2024llm.0001A'):
        paper = Paper.objects.create(bibcode=bibcode)
        return PaperAnalysis.objects.create(
            paper=paper,
            configuration_name='test',
            context={},
            instruments_details='',
        )

    def _candidates_text(self, entries):
        """Build candidates_text string from list of (code, name) tuples."""
        return '\n'.join(
            f'{i+1}. {code} ({name})' for i, (code, name) in enumerate(entries)
        )

    # ------------------------------------------------------------------
    # mission_selection path
    # ------------------------------------------------------------------

    def test_mission_selection_creates_mission_only_row(self):
        pa = self._make_pa()
        call = make_llm_call(
            call_type='mission_selection',
            render_context={'candidates_text': self._candidates_text([('SOHO', 'Solar Heliospheric Observatory')])},
            output_content='1',
        )
        pa.llm_calls.add(call)

        count = _upsert_mission_only_from_llm_calls(pa)
        self.assertEqual(count, 1)
        m = InstrumentMention.objects.get(paper_analysis=pa)
        self.assertEqual(m.match_level, InstrumentMention.MATCH_LEVEL_MISSION_ONLY)
        self.assertEqual(m.matched_observatory, self.obs)
        self.assertIsNone(m.matched_instrument)

    def test_mission_selection_skipped_when_instrument_already_resolved(self):
        """If a specific instrument for this observatory already exists, skip."""
        pa = self._make_pa()
        # Pre-create a resolved instrument mention
        InstrumentMention.objects.create(
            paper_analysis=pa,
            matched_instrument=self.inst,
            match_level=InstrumentMention.MATCH_LEVEL_FULL,
        )
        call = make_llm_call(
            call_type='mission_selection',
            render_context={'candidates_text': self._candidates_text([('SOHO', 'Solar Heliospheric Observatory')])},
            output_content='1',
        )
        pa.llm_calls.add(call)

        count = _upsert_mission_only_from_llm_calls(pa)
        self.assertEqual(count, 0)
        # Only the pre-existing full-match row should exist
        self.assertEqual(InstrumentMention.objects.filter(paper_analysis=pa).count(), 1)

    def test_mission_selection_unknown_output_creates_nothing(self):
        pa = self._make_pa()
        call = make_llm_call(
            call_type='mission_selection',
            render_context={'candidates_text': self._candidates_text([('SOHO', 'Solar Heliospheric Observatory')])},
            output_content='UNKNOWN',
        )
        pa.llm_calls.add(call)

        count = _upsert_mission_only_from_llm_calls(pa)
        self.assertEqual(count, 0)

    # ------------------------------------------------------------------
    # mission_identification calls must NOT create rows
    # ------------------------------------------------------------------

    def test_mission_identification_single_candidate_creates_nothing(self):
        """mission_identification is a ranking step, not a selection — never creates rows."""
        pa = self._make_pa()
        call = make_llm_call(
            call_type='mission_identification',
            render_context={'missions_text': self._candidates_text([('SOHO', 'Solar Heliospheric Observatory')])},
            output_content='1',
        )
        pa.llm_calls.add(call)

        count = _upsert_mission_only_from_llm_calls(pa)
        self.assertEqual(count, 0)
        self.assertEqual(InstrumentMention.objects.filter(paper_analysis=pa).count(), 0)

    def test_mission_identification_multi_candidate_not_created(self):
        """Multi-candidate mission_identification output also creates nothing."""
        pa = self._make_pa()
        call = make_llm_call(
            call_type='mission_identification',
            render_context={'missions_text': self._candidates_text([
                ('SOHO', 'Solar Heliospheric Observatory'),
                ('SDO', 'Solar Dynamics Observatory'),
            ])},
            output_content='1,2',
        )
        pa.llm_calls.add(call)

        count = _upsert_mission_only_from_llm_calls(pa)
        self.assertEqual(count, 0)

    def test_mission_identification_ignored_even_when_selection_call_exists(self):
        """mission_identification calls are always ignored, even alongside selection calls."""
        pa = self._make_pa()
        sel_call = make_llm_call(
            call_type='mission_selection',
            render_context={'candidates_text': ''},
            output_content='UNKNOWN',
        )
        ident_call = make_llm_call(
            call_type='mission_identification',
            render_context={'missions_text': self._candidates_text([('SOHO', 'Solar Heliospheric Observatory')])},
            output_content='1',
        )
        pa.llm_calls.add(sel_call, ident_call)

        count = _upsert_mission_only_from_llm_calls(pa)
        self.assertEqual(count, 0)
        self.assertEqual(InstrumentMention.objects.filter(paper_analysis=pa).count(), 0)

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_malformed_render_context_no_crash(self):
        pa = self._make_pa()
        call = make_llm_call(
            call_type='mission_selection',
            render_context=None,
            output_content='1',
        )
        pa.llm_calls.add(call)

        count = _upsert_mission_only_from_llm_calls(pa)
        self.assertEqual(count, 0)

    def test_empty_output_content_no_crash(self):
        pa = self._make_pa()
        call = make_llm_call(
            call_type='mission_selection',
            render_context={'candidates_text': self._candidates_text([('SOHO', 'Solar Heliospheric Observatory')])},
            output_content='',
        )
        pa.llm_calls.add(call)

        count = _upsert_mission_only_from_llm_calls(pa)
        self.assertEqual(count, 0)

    def test_unknown_mission_code_skipped_gracefully(self):
        pa = self._make_pa()
        call = make_llm_call(
            call_type='mission_selection',
            render_context={'candidates_text': self._candidates_text([('NONEXISTENT', 'Made Up Mission')])},
            output_content='1',
        )
        pa.llm_calls.add(call)

        count = _upsert_mission_only_from_llm_calls(pa)
        self.assertEqual(count, 0)
        self.assertEqual(InstrumentMention.objects.filter(paper_analysis=pa).count(), 0)

    def test_idempotent(self):
        pa = self._make_pa()
        call = make_llm_call(
            call_type='mission_selection',
            render_context={'candidates_text': self._candidates_text([('SOHO', 'Solar Heliospheric Observatory')])},
            output_content='1',
        )
        pa.llm_calls.add(call)

        _upsert_mission_only_from_llm_calls(pa)
        _upsert_mission_only_from_llm_calls(pa)
        self.assertEqual(InstrumentMention.objects.filter(paper_analysis=pa).count(), 1)


# ---------------------------------------------------------------------------
# _backfill_mission_only_from_input_messages
# ---------------------------------------------------------------------------

def make_llm_call_input_messages(call_type, input_messages, output_content):
    """Create an LLMCall with null render_context and explicit input_messages."""
    return LLMCall.objects.create(
        call_type=call_type,
        model_name='test-model',
        provider='test',
        render_context=None,
        input_messages=input_messages,
        output_content=output_content,
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        estimated_cost_usd=0,
    )


def _make_user_message(tag, entries):
    """Build a user message dict with an XML block of numbered entries."""
    lines = '\n'.join(f'{i+1}. {name}' for i, name in enumerate(entries))
    return [{'role': 'user', 'content': f'<{tag}>\n{lines}\n</{tag}>'}]


class BackfillMissionOnlyFromInputMessagesTests(TestCase):

    def setUp(self):
        self.ds, self.obs, self.inst = make_catalog(
            ds_slug='vso', obs_short='SOHO', inst_short='LASCO'
        )
        # obs.name is the full name used in input_messages XML
        self.obs.name = 'Solar Heliospheric Observatory'
        self.obs.save()

    def _make_pa(self, bibcode='2024old.0001A'):
        paper = Paper.objects.create(bibcode=bibcode)
        return PaperAnalysis.objects.create(
            paper=paper,
            configuration_name='test',
            context={},
            instruments_details='',
        )

    # ------------------------------------------------------------------
    # mission_selection path
    # ------------------------------------------------------------------

    def test_mission_selection_null_rc_creates_row(self):
        """mission_selection with null render_context and valid <candidate_missions> creates row."""
        pa = self._make_pa()
        call = make_llm_call_input_messages(
            call_type='mission_selection',
            input_messages=_make_user_message('candidate_missions', ['Solar Heliospheric Observatory']),
            output_content='1',
        )
        pa.llm_calls.add(call)

        count, warnings = _backfill_mission_only_from_input_messages(pa)
        self.assertEqual(count, 1)
        self.assertEqual(warnings, [])
        m = InstrumentMention.objects.get(paper_analysis=pa)
        self.assertEqual(m.match_level, InstrumentMention.MATCH_LEVEL_MISSION_ONLY)
        self.assertEqual(m.matched_observatory, self.obs)

    # ------------------------------------------------------------------
    # mission_identification calls must NOT create rows
    # ------------------------------------------------------------------

    def test_mission_identification_single_candidate_null_rc_creates_nothing(self):
        """mission_identification is excluded — never creates rows even with null render_context."""
        pa = self._make_pa(bibcode='2024old.0002A')
        call = make_llm_call_input_messages(
            call_type='mission_identification',
            input_messages=_make_user_message('available_missions', ['Solar Heliospheric Observatory']),
            output_content='1',
        )
        pa.llm_calls.add(call)

        count, warnings = _backfill_mission_only_from_input_messages(pa)
        self.assertEqual(count, 0)
        self.assertEqual(warnings, [])

    def test_mission_identification_multi_candidate_skipped(self):
        """mission_identification with multiple indices is also excluded."""
        pa = self._make_pa(bibcode='2024old.0003A')
        call = make_llm_call_input_messages(
            call_type='mission_identification',
            input_messages=_make_user_message('available_missions', [
                'Solar Heliospheric Observatory',
                'Solar Dynamics Observatory',
            ]),
            output_content='1,2',
        )
        pa.llm_calls.add(call)

        count, warnings = _backfill_mission_only_from_input_messages(pa)
        self.assertEqual(count, 0)

    def test_ambiguous_name_skipped_with_warning(self):
        """Observatory name matching multiple DB rows produces warning and is skipped."""
        # Create a second Observatory with the same name to trigger MultipleObjectsReturned
        ds2 = DataSource.objects.create(slug='cdaweb', name='CDAWeb')
        Observatory.objects.create(
            datasource=ds2,
            short_name='SOHO2',
            name='Solar Heliospheric Observatory',
            display_name='SOHO2',
        )
        pa = self._make_pa(bibcode='2024old.0004A')
        call = make_llm_call_input_messages(
            call_type='mission_selection',
            input_messages=_make_user_message('candidate_missions', ['Solar Heliospheric Observatory']),
            output_content='1',
        )
        pa.llm_calls.add(call)

        count, warnings = _backfill_mission_only_from_input_messages(pa)
        self.assertEqual(count, 0)
        self.assertEqual(len(warnings), 1)
        self.assertIn('Solar Heliospheric Observatory', warnings[0])

    def test_unknown_name_skipped_gracefully(self):
        """Observatory name not in DB is skipped without crash."""
        pa = self._make_pa(bibcode='2024old.0005A')
        call = make_llm_call_input_messages(
            call_type='mission_selection',
            input_messages=_make_user_message('candidate_missions', ['Nonexistent Observatory']),
            output_content='1',
        )
        pa.llm_calls.add(call)

        count, warnings = _backfill_mission_only_from_input_messages(pa)
        self.assertEqual(count, 0)
        self.assertEqual(warnings, [])

    def test_missing_xml_tag_no_crash(self):
        """User message without the expected XML tag produces 0 rows, no crash."""
        pa = self._make_pa(bibcode='2024old.0006A')
        call = make_llm_call_input_messages(
            call_type='mission_selection',
            input_messages=[{'role': 'user', 'content': 'No XML tags here at all.'}],
            output_content='1',
        )
        pa.llm_calls.add(call)

        count, warnings = _backfill_mission_only_from_input_messages(pa)
        self.assertEqual(count, 0)

    def test_null_input_messages_no_crash(self):
        """Null input_messages produces 0 rows, no crash."""
        pa = self._make_pa(bibcode='2024old.0007A')
        call = make_llm_call_input_messages(
            call_type='mission_selection',
            input_messages=None,
            output_content='1',
        )
        pa.llm_calls.add(call)

        count, warnings = _backfill_mission_only_from_input_messages(pa)
        self.assertEqual(count, 0)

    def test_idempotent(self):
        """Running twice produces the same single row."""
        pa = self._make_pa(bibcode='2024old.0008A')
        call = make_llm_call_input_messages(
            call_type='mission_selection',
            input_messages=_make_user_message('candidate_missions', ['Solar Heliospheric Observatory']),
            output_content='1',
        )
        pa.llm_calls.add(call)

        _backfill_mission_only_from_input_messages(pa)
        _backfill_mission_only_from_input_messages(pa)
        self.assertEqual(InstrumentMention.objects.filter(paper_analysis=pa).count(), 1)

    def test_instrument_already_resolved_skipped(self):
        """If a specific instrument for this observatory is already resolved, skip mission_only creation."""
        pa = self._make_pa(bibcode='2024old.0009A')
        InstrumentMention.objects.create(
            paper_analysis=pa,
            matched_instrument=self.inst,
            match_level=InstrumentMention.MATCH_LEVEL_FULL,
        )
        call = make_llm_call_input_messages(
            call_type='mission_selection',
            input_messages=_make_user_message('candidate_missions', ['Solar Heliospheric Observatory']),
            output_content='1',
        )
        pa.llm_calls.add(call)

        count, warnings = _backfill_mission_only_from_input_messages(pa)
        self.assertEqual(count, 0)
        self.assertEqual(InstrumentMention.objects.filter(paper_analysis=pa).count(), 1)
