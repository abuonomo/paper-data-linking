"""Recompute the denormalized dataset-usage rollups on Paper.

The public papers listing (``PublicValidatedPapersListView``) orders and counts
by dataset-usage aggregates. Computing those aggregates on every request grows
linearly with the number of ``DatasetUsage`` rows, which is why the public list
page slowed down as predictions scaled up. Instead we precompute the rollups
here and let the listing read plain indexed columns.

This is intended to run on a schedule (see ``settings.CELERY_BEAT_SCHEDULE``)
and/or after bulk ingestion. It is safe to run at any time and is idempotent:
it fully recomputes every paper's rollups from the current ``DatasetUsage``
rows, so papers whose usages were deleted are correctly reset to zero/NULL.

The four rollups mirror exactly what the listing needs:

* ``approved_usage_count``            -> COUNT of ``approved`` usages
* ``pending_usage_count``             -> COUNT of ``pending`` usages
* ``latest_observation_end_approved`` -> MAX(upper(window)) over ``approved`` usages
* ``latest_observation_end_all``      -> MAX(upper(window)) over ``approved`` + ``pending`` usages

The two ``latest_*`` columns are the sort keys for, respectively, the
validated-only view and the ``include_unvalidated=true`` view.
"""

from django.core.management.base import BaseCommand
from django.db import connection

# A single set-based UPDATE over all papers. Uses a LEFT JOIN so that papers
# with no (or no longer any) matching usages are reset to 0 / NULL rather than
# left stale from a previous run.
_REFRESH_SQL = """
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


def refresh_paper_usage_stats():
    """Recompute rollups for every Paper. Returns the number of rows updated.

    Shared by the management command and the celery task so there is a single
    implementation of the refresh SQL.
    """
    with connection.cursor() as cursor:
        cursor.execute(_REFRESH_SQL)
        return cursor.rowcount


class Command(BaseCommand):
    help = "Recompute denormalized dataset-usage rollups on Paper for the public listing."

    def handle(self, *args, **options):
        updated = refresh_paper_usage_stats()
        self.stdout.write(self.style.SUCCESS(
            f"Refreshed paper usage stats for {updated} paper(s)."
        ))
