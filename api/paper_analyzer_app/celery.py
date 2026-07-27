# celery.py

# Only apply gevent monkey patching when running as a Celery worker
# This prevents interference with Django management commands (migrations, etc.)
import os
import sys

# Detect Celery worker processes
is_celery_worker = (
    'celery' in os.environ.get('_', '') or
    'worker' in sys.argv or
    (any('celery' in arg for arg in sys.argv) and any('worker' in arg for arg in sys.argv))
)

# Only gevent-pool workers should be monkey-patched. The prefork `cpu` worker runs
# the hang-prone subprocess/exec analyzers and MUST NOT be patched (gevent + fork +
# subprocess is the wedge we're avoiding); `celery beat` must not be patched either.
_argv = ' '.join(sys.argv)
is_prefork = '--pool=prefork' in _argv or '-P prefork' in _argv
is_gevent_pool = 'gevent' in _argv

if is_celery_worker and is_gevent_pool and not is_prefork:
    # =========================================================================
    # THIS MUST BE AT THE VERY TOP, BEFORE ANY OTHER IMPORTS (LIKE OS, CELERY)
    from gevent import monkey
    monkey.patch_all()

    from psycogreen.gevent import patch_psycopg
    patch_psycopg()
    # =========================================================================

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'paper_analyzer_app.settings')

app = Celery('paper_analyzer_app')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Cadence for the public-listing usage-stats refresh. Rollups change rarely, so
# once a day is plenty; override the hour via env (UTC) without a code change.
_usage_stats_hour = int(os.environ.get('PAPER_USAGE_STATS_REFRESH_HOUR', '7'))

# Periodic reconciler (requires a `celery beat` process). Re-kicks any
# batch-downstream run whose lease has gone stale — the crash-proof backstop that
# guarantees a long corpus run cannot silently stall after a worker restart.
app.conf.beat_schedule = {
    'reconcile-batch-downstream-runs': {
        'task': 'vso_query_builder.tasks.reconcile_batch_downstream_runs',
        'schedule': 300.0,  # every 5 minutes
    },
    # Corpus-mode commits DEFER quote embeddings; this sweep fills them in.
    # Idempotent + no-op when no NULL embeddings remain, so a 10-min cadence
    # keeps the embedding lag behind a corpus run ≤ ~1h, automatic + self-healing.
    'embed-missing-quotes': {
        'task': 'vso_query_builder.tasks.embed_missing_quotes',
        'schedule': 600.0,  # every 10 minutes
    },
    # Recompute the denormalized dataset-usage rollups that back the public
    # papers listing's fast path. Runs once a day (rollups change rarely); the
    # listing otherwise pays zero aggregation cost. Bulk ingestion can also
    # trigger it directly via refresh_paper_usage_stats_task.delay().
    'refresh-paper-usage-stats': {
        'task': 'vso_query_builder.tasks.refresh_paper_usage_stats_task',
        'schedule': crontab(hour=_usage_stats_hour, minute=0),
    },
}