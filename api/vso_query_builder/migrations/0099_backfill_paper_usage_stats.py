"""Backfill the denormalized dataset-usage rollups added in 0098.

Runs the same set-based recompute as the ``refresh_paper_usage_stats``
management command. Because prod applies migrations (init container) before the
api container starts serving, this guarantees the public listing's precomputed
columns are populated the moment the new code goes live -- there is no window
where the fast path sees all-zero rollups and returns an empty listing.

Kept in sync with refresh_paper_usage_stats.Command._REFRESH_SQL.
"""

from django.db import migrations


_BACKFILL_SQL = """
UPDATE vso_query_builder_paper AS p
SET
    approved_usage_count = COALESCE(s.approved, 0),
    pending_usage_count = COALESCE(s.pending, 0),
    latest_observation_end_approved = s.latest_approved,
    latest_observation_end_all = s.latest_all,
    usage_stats_updated = NOW()
FROM vso_query_builder_paper AS p2
LEFT JOIN (
    SELECT
        paper_id,
        COUNT(*) FILTER (WHERE validation_status = 'approved') AS approved,
        COUNT(*) FILTER (WHERE validation_status = 'pending') AS pending,
        MAX(UPPER(observation_window)) FILTER (WHERE validation_status = 'approved') AS latest_approved,
        MAX(UPPER(observation_window)) FILTER (WHERE validation_status IN ('approved', 'pending')) AS latest_all
    FROM vso_query_builder_datasetusage
    GROUP BY paper_id
) AS s ON s.paper_id = p2.id
WHERE p.id = p2.id;
"""


def backfill(apps, schema_editor):
    schema_editor.execute(_BACKFILL_SQL)


def noop_reverse(apps, schema_editor):
    # Columns are dropped by reversing 0098; nothing to undo here.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("vso_query_builder", "0098_paper_approved_usage_count_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
