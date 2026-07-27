"""Deterministic test for the Cluster-dedup management command.

Stale numbered Cluster/C1..C4 observatories are collapsed into the named
spacecraft (C1->Rumba ...): duplicate instruments are removed and their
DatasetUsages / InstrumentMentions repointed to the named equivalent; the
numbered observatory is deleted. No LLM, no network.
"""
import pytest
from datetime import datetime
import pytz
from psycopg2.extras import DateTimeTZRange


@pytest.fixture
def cdaweb_datasource(db):
    from vso_query_builder.models import DataSource
    return DataSource.objects.get_or_create(
        slug="cdaweb", defaults={"name": "Coordinated Data Analysis Web"})[0]


@pytest.mark.django_db
def test_dedupe_collapses_numbered_into_named(cdaweb_datasource, paper_analysis_factory):
    from django.core.management import call_command
    from vso_query_builder.models import (
        Observatory, Instrument, DatasetUsage, InstrumentMention,
    )

    # numbered (stale) C1 with a duplicate WBD; named Rumba with its own WBD + an FGM
    c1 = Observatory.objects.create(datasource=cdaweb_datasource,
        short_name="spase://SMWG/Observatory/Cluster/C1", name="Cluster-C1")
    c1_wbd = Instrument.objects.create(observatory=c1,
        short_name="spase://SMWG/Instrument/Cluster/C1/WBD", full_name="WBD")
    rumba = Observatory.objects.create(datasource=cdaweb_datasource,
        short_name="spase://SMWG/Observatory/Cluster-Rumba", name="Cluster-Rumba")
    rumba_wbd = Instrument.objects.create(observatory=rumba,
        short_name="spase://SMWG/Instrument/Cluster-Rumba/WBD", full_name="WBD")

    pa = paper_analysis_factory()
    win = DateTimeTZRange(datetime(2003, 1, 1, tzinfo=pytz.UTC),
                          datetime(2003, 1, 2, tzinfo=pytz.UTC), bounds="[]")
    du = DatasetUsage.objects.create(paper=pa.paper, instrument=c1_wbd,
                                     paper_analysis=pa, observation_window=win)
    m = InstrumentMention.objects.create(paper_analysis=pa, matched_instrument=c1_wbd,
                                         match_level=InstrumentMention.MATCH_LEVEL_PARTIAL)

    call_command("dedupe_cluster_observatories")
    call_command("dedupe_cluster_observatories")  # idempotent: second run is a no-op

    # numbered observatory + instrument are gone
    assert not Observatory.objects.filter(short_name="spase://SMWG/Observatory/Cluster/C1").exists()
    assert not Instrument.objects.filter(short_name="spase://SMWG/Instrument/Cluster/C1/WBD").exists()
    # the DU and mention survived, repointed to the named WBD
    du.refresh_from_db(); m.refresh_from_db()
    assert du.instrument_id == rumba_wbd.id
    assert m.matched_instrument_id == rumba_wbd.id


@pytest.mark.django_db
def test_dedupe_reparents_unique_instrument(cdaweb_datasource):
    """An instrument under the numbered record with NO named equivalent is re-parented,
    not deleted (no coverage lost)."""
    from django.core.management import call_command
    from vso_query_builder.models import Observatory, Instrument

    c2 = Observatory.objects.create(datasource=cdaweb_datasource,
        short_name="spase://SMWG/Observatory/Cluster/C2", name="Cluster-C2")
    uniq = Instrument.objects.create(observatory=c2,
        short_name="spase://SMWG/Instrument/Cluster/C2/ONLYHERE", full_name="ONLYHERE")
    salsa = Observatory.objects.create(datasource=cdaweb_datasource,
        short_name="spase://SMWG/Observatory/Cluster-Salsa", name="Cluster-Salsa")

    call_command("dedupe_cluster_observatories")

    assert not Observatory.objects.filter(short_name="spase://SMWG/Observatory/Cluster/C2").exists()
    uniq.refresh_from_db()
    assert uniq.observatory_id == salsa.id            # re-parented, kept
    assert uniq.short_name == "spase://SMWG/Instrument/Cluster/C2/ONLYHERE"


@pytest.mark.django_db
def test_dry_run_changes_nothing(cdaweb_datasource):
    from django.core.management import call_command
    from vso_query_builder.models import Observatory, Instrument

    c3 = Observatory.objects.create(datasource=cdaweb_datasource,
        short_name="spase://SMWG/Observatory/Cluster/C3", name="Cluster-C3")
    Instrument.objects.create(observatory=c3,
        short_name="spase://SMWG/Instrument/Cluster/C3/WBD", full_name="WBD")
    Observatory.objects.create(datasource=cdaweb_datasource,
        short_name="spase://SMWG/Observatory/Cluster-Samba", name="Cluster-Samba")

    call_command("dedupe_cluster_observatories", "--dry-run")

    assert Observatory.objects.filter(short_name="spase://SMWG/Observatory/Cluster/C3").exists()
