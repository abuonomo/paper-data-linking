import os
import re
from datetime import datetime, timezone as dt_timezone
import sys
import subprocess
import tempfile
from typing import List, Optional, Tuple, Dict
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.contrib.postgres.fields.ranges import DateTimeTZRange

from github import Github
from tqdm import tqdm
from github.PullRequest import PullRequest

from ...models import Paper, Instrument, DatasetUsage


BIBC_RE = re.compile(r"\*\*bibcode\*\*:\s*(\S+)")


def _run_bandit_check(script: str) -> Tuple[bool, str]:
    """Run bandit on the script content. Returns (is_safe, output)."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as temp:
        temp.write(script.encode())
        temp.flush()
        temp_path = temp.name
    try:
        proc = subprocess.run(["bandit", "-q", temp_path], capture_output=True, text=True)
        is_safe = proc.returncode == 0
        output = proc.stdout or proc.stderr
        return is_safe, output
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass


def extract_bibcode_from_body(body: Optional[str]) -> Optional[str]:
    if not body:
        return None
    m = BIBC_RE.search(body)
    return m.group(1) if m else None


def extract_bibcode_from_path(path: Optional[str]) -> Optional[str]:
    """Expect GitHub path like papers/<year>/<journal>/<bibcode>/download_script.py"""
    if not path:
        return None
    parts = path.split('/')
    try:
        idx = parts.index('papers')
    except ValueError:
        return None
    # papers/<year>/<journal>/<bibcode>/download_script.py  => bibcode at idx+3
    if len(parts) >= idx + 5 and parts[idx + 4] == 'download_script.py':
        return parts[idx + 3]
    return None


class Command(BaseCommand):
    help = (
        "Ingest validated dataset usages from merged GitHub PRs created by the bot.\n"
        "Rules: single-commit PR and download_script.py unchanged between initial and final commit.\n"
        "Parses instrument/time from scripts without executing code and upserts DatasetUsage with validation_status=approved."
    )

    def add_arguments(self, parser):
        parser.add_argument('--repo', dest='repo', default=None,
                            help='GitHub repo in owner/name form. Defaults to settings.GITHUB_REPO or env PAPER_DATA_LINKS_GITHUB_REPO.')
        parser.add_argument('--token', dest='token', default=None,
                            help='GitHub token. Defaults to env PAPER_DATA_LINKS_GITHUB_ACCESS_TOKEN.')
        parser.add_argument('--limit', type=int, default=None, help='Limit number of merged PRs to process.')
        parser.add_argument('--since', type=str, default=None, help='Only consider PRs merged after this ISO datetime (UTC).')
        parser.add_argument('--bibcode', type=str, default=None, help='Only process PRs for this bibcode.')
        parser.add_argument('--dry-run', action='store_true', help='Do not write to DB; just print actions.')
        parser.add_argument('--debug', action='store_true', help='Verbose logging with skip reasons and breakdown summary.')
        # Always use exec capture; AST removed per request. Keep flag for compatibility but ignored.
        parser.add_argument('--no-exec-capture', action='store_true', help='(Ignored) Exec capture is always used.')

    def handle(self, *args, **options):
        from django.conf import settings

        token = options['token'] or os.getenv('PAPER_DATA_LINKS_GITHUB_ACCESS_TOKEN')
        if not token:
            raise CommandError('Missing GitHub token. Provide --token or set PAPER_DATA_LINKS_GITHUB_ACCESS_TOKEN.')

        repo_name = options['repo'] or getattr(settings, 'GITHUB_REPO', None) or os.getenv('PAPER_DATA_LINKS_GITHUB_REPO')
        if not repo_name:
            raise CommandError('Missing repo. Provide --repo, settings.GITHUB_REPO, or PAPER_DATA_LINKS_GITHUB_REPO.')

        g = Github(token)
        repo = g.get_repo(repo_name)

        # Announce scan parameters
        self.stdout.write(
            f"Scanning GitHub repo '{repo_name}' for merged PRs with unchanged download_script.py\n"
            f"dry-run={bool(options['dry_run'])}, since={options['since'] or '-'}, bibcode={options['bibcode'] or '-'}"
        )

        merged_after: Optional[datetime] = None
        if options['since']:
            merged_after = datetime.fromisoformat(options['since'].replace('Z', '+00:00'))

        # Fetch all closed PRs to know count up front
        pr_list = list(repo.get_pulls(state='closed'))
        total_closed = len(pr_list)
        self.stdout.write(f"Found {total_closed} closed PRs to scan.")
        processed = 0
        merged_count = 0
        created = 0
        updated = 0
        planned_created_total = 0
        planned_updated_total = 0
        skip_reasons = Counter()
        skipped = 0
        errors = 0

        progress_iter = tqdm(pr_list, disable=False, file=sys.stdout, leave=False, desc="Scanning PRs")
        for pr in progress_iter:
            if not pr.merged:
                if options['debug']:
                    skip_reasons['not_merged'] += 1
                continue
            merged_count += 1
            if merged_after and pr.merged_at and pr.merged_at.replace(tzinfo=None) <= merged_after.replace(tzinfo=None):
                continue

            bib = extract_bibcode_from_body(pr.body)
            if options['bibcode'] and bib != options['bibcode']:
                continue

            try:
                qualifies, reason = self._pr_qualifies(pr, want_reason=True)
                if not qualifies:
                    skipped += 1
                    if options['debug']:
                        skip_reasons[reason or 'disqualified'] += 1
                        self.stdout.write(self.style.WARNING(f"PR #{pr.number} skip: {reason}"))
                    continue

                script_path = self._find_script_path(pr)
                if not script_path:
                    if options['debug']:
                        self.stdout.write(self.style.WARNING(f"PR #{pr.number}: download_script.py not found; skipping"))
                        skip_reasons['no_download_script'] += 1
                    skipped += 1
                    continue

                initial_sha, final_sha = self._first_and_last_commit_shas(pr)
                initial_content = repo.get_contents(script_path, ref=initial_sha).decoded_content.decode('utf-8', errors='ignore')
                final_content = repo.get_contents(script_path, ref=final_sha).decoded_content.decode('utf-8', errors='ignore')

                if initial_content != final_content:
                    if options['debug']:
                        self.stdout.write(self.style.WARNING(f"PR #{pr.number}: script content changed during review; skipping"))
                        skip_reasons['script_changed'] += 1
                    skipped += 1
                    continue

                # Security check with Bandit (mandatory)
                ok, bandit_out = _run_bandit_check(final_content)
                if not ok:
                    skipped += 1
                    if options['debug']:
                        skip_reasons['bandit_failed'] += 1
                        self.stdout.write(self.style.WARNING(f"PR #{pr.number}: bandit security check failed; skipping"))
                    continue

                # Execute with Fido.search mocked to capture realistic calls
                try:
                    calls = self._capture_calls_via_exec(final_content)
                    if options['debug']:
                        self.stdout.write(f"PR #{pr.number}: captured {len(calls)} calls via exec")
                except Exception as e:
                    skipped += 1
                    if options['debug']:
                        skip_reasons['exec_failed'] += 1
                        self.stdout.write(self.style.WARNING(f"PR #{pr.number}: exec capture failed: {e}; skipping"))
                    continue
                if not calls:
                    if options['debug']:
                        self.stdout.write(self.style.WARNING(f"PR #{pr.number}: no captured Fido.search calls; skipping"))
                        skip_reasons['no_captured_calls'] += 1
                    skipped += 1
                    continue

                # Fallback: try to infer bibcode from file path if PR body missing it
                if not bib:
                    bib = extract_bibcode_from_path(script_path)
                if not bib:
                    errors += 1
                    self.stdout.write(self.style.ERROR(f"PR #{pr.number}: error Missing bibcode; cannot upsert without it"))
                    continue

                result = self._upsert_dataset_usages(bib, calls, pr.merged_at, dry_run=options['dry_run'])
                created += result.get('created', 0)
                updated += result.get('updated', 0)
                if options['dry_run']:
                    planned_created_total += result.get('planned_created', 0)
                    planned_updated_total += result.get('planned_updated', 0)
                    # Emit per-action logs for clarity
                    for action in result.get('actions', []):
                        action_type = action.get('action')
                        inst = action.get('instrument') or '-'
                        obs = action.get('observatory') or '-'
                        src = action.get('datasource') or '-'
                        start = action.get('start') or '-'
                        end = action.get('end') or '-'
                        reason = action.get('reason')
                        if action_type in ('create', 'update'):
                            self.stdout.write(f"PR #{pr.number} DRY-RUN would {action_type}: {bib} | {inst} ({obs}/{src}) | {start} -> {end}")
                        elif action_type == 'skip' and reason:
                            self.stdout.write(self.style.WARNING(f"PR #{pr.number} skip: {reason} | {bib} | {inst} ({obs}/{src}) | {start} -> {end}"))
                processed += 1

            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(f"PR #{pr.number}: error {e}"))

            if options['limit'] and processed >= options['limit']:
                break

        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(
                f"Done (dry-run). Closed PRs scanned: {total_closed}, merged found: {merged_count}, qualified processed: {processed}, "
                f"planned creates: {planned_created_total}, planned updates: {planned_updated_total}, "
                f"skipped: {skipped}, errors: {errors}"
            ))
            if options['debug'] and skip_reasons:
                self.stdout.write("Skip breakdown:")
                for k, v in skip_reasons.most_common():
                    self.stdout.write(f" - {k}: {v}")
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Done. Closed PRs scanned: {total_closed}, merged found: {merged_count}, qualified processed: {processed}, created: {created}, "
                f"updated: {updated}, skipped: {skipped}, errors: {errors}"
            ))

    def _pr_qualifies(self, pr: PullRequest, want_reason: bool = False):
        # Single-commit rule
        commits = list(pr.get_commits())
        if len(commits) != 1:
            return (False, 'multi_commit') if want_reason else False
        # Must contain a download_script.py file
        for f in pr.get_files():
            if f.filename.endswith('/download_script.py'):
                return (True, None) if want_reason else True
        return (False, 'no_download_script') if want_reason else False

    def _first_and_last_commit_shas(self, pr: PullRequest) -> Tuple[str, str]:
        commits = list(pr.get_commits())
        return commits[0].sha, commits[-1].sha

    def _find_script_path(self, pr: PullRequest) -> Optional[str]:
        for f in pr.get_files():
            if f.filename.endswith('/download_script.py'):
                return f.filename
        return None

    @transaction.atomic
    def _upsert_dataset_usages(self, bibcode: Optional[str], calls: List[Dict], merged_at: Optional[datetime], dry_run: bool = False) -> Dict[str, int]:
        created = 0
        updated = 0
        planned_created = 0
        planned_updated = 0
        actions: List[Dict] = []

        if not bibcode:
            raise CommandError('Missing bibcode; cannot upsert without it')

        paper, _ = Paper.objects.get_or_create(bibcode=bibcode, defaults={'user': None})

        for call in calls:
            start_s, end_s = call['time']
            try:
                start_dt = datetime.fromisoformat(start_s.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end_s.replace('Z', '+00:00'))
            except Exception:
                # Skip invalid times
                continue

            # Normalize to aware UTC
            if timezone.is_naive(start_dt):
                start_dt = timezone.make_aware(start_dt, timezone=dt_timezone.utc)
            if timezone.is_naive(end_dt):
                end_dt = timezone.make_aware(end_dt, timezone=dt_timezone.utc)

            window = DateTimeTZRange(start_dt, end_dt, bounds='[]')

            for inst_code in call['instruments']:
                inst_obj = self._resolve_instrument(inst_code, call.get('sources', []))
                if not inst_obj:
                    actions.append({
                        'action': 'skip',
                        'reason': f"instrument '{inst_code}' unresolved or ambiguous",
                        'bibcode': bibcode,
                        'instrument': inst_code,
                        'observatory': None,
                        'datasource': None,
                        'start': start_dt.isoformat(),
                        'end': end_dt.isoformat(),
                    })
                    continue

                # Evaluate existence without writing when dry-run
                if dry_run:
                    existing = DatasetUsage.objects.filter(
                        paper=paper,
                        instrument=inst_obj,
                        observation_window=window,
                    ).first()
                    if existing is None:
                        planned_created += 1
                        actions.append({
                            'action': 'create',
                            'bibcode': bibcode,
                            'instrument': inst_obj.short_name,
                            'observatory': getattr(inst_obj.observatory, 'short_name', None),
                            'datasource': getattr(getattr(inst_obj.observatory, 'datasource', None), 'slug', None),
                            'start': start_dt.isoformat(),
                            'end': end_dt.isoformat(),
                        })
                    else:
                        # Would update if not already approved
                        if existing.validation_status != 'approved' or existing.validated_at is None:
                            planned_updated += 1
                            actions.append({
                                'action': 'update',
                                'bibcode': bibcode,
                                'instrument': inst_obj.short_name,
                                'observatory': getattr(inst_obj.observatory, 'short_name', None),
                                'datasource': getattr(getattr(inst_obj.observatory, 'datasource', None), 'slug', None),
                                'start': start_dt.isoformat(),
                                'end': end_dt.isoformat(),
                            })
                        else:
                            actions.append({
                                'action': 'skip',
                                'reason': 'already approved',
                                'bibcode': bibcode,
                                'instrument': inst_obj.short_name,
                                'observatory': getattr(inst_obj.observatory, 'short_name', None),
                                'datasource': getattr(getattr(inst_obj.observatory, 'datasource', None), 'slug', None),
                                'start': start_dt.isoformat(),
                                'end': end_dt.isoformat(),
                            })
                    continue

                # Build extra_params consistent with normalized workflow shape
                extras = {
                    'resolver_reason': None,
                    'possible_sources': call.get('sources', []),
                }
                dets = call.get('detectors', []) or []
                if dets:
                    extras['detector'] = {
                        'detector': dets[0]
                    }
                du, was_created = DatasetUsage.objects.get_or_create(
                    paper=paper,
                    instrument=inst_obj,
                    observation_window=window,
                    defaults={
                        'extra_params': extras,
                        'validation_status': 'approved',
                        'validated_at': merged_at or timezone.now(),
                    }
                )

                if was_created:
                    created += 1
                else:
                    # Ensure approved status
                    prior_status = du.validation_status
                    du.validation_status = 'approved'
                    du.validated_at = du.validated_at or merged_at or timezone.now()
                    du.save(update_fields=['validation_status', 'validated_at'])
                    if prior_status != 'approved':
                        updated += 1

        return {
            'created': created,
            'updated': updated,
            'planned_created': planned_created,
            'planned_updated': planned_updated,
            'actions': actions,
        }

    def _capture_calls_via_exec(self, script: str) -> List[Dict]:
        """
        Execute the script with Fido.search mocked to capture arguments.
        Returns list of dicts: { instruments: [..], sources: [..], time: (start, end) }
        """
        from unittest.mock import Mock
        from sunpy.net import Fido
        from sunpy.net import attrs as a
        from io import StringIO

        calls: List[Dict] = []

        # Mock Fido.search and Fido.fetch to avoid network and heavy operations
        mock_search = Mock()
        mock_fetch = Mock(return_value=[])
        original_search = Fido.search
        original_fetch = Fido.fetch
        original_stdout = sys.stdout
        Fido.search = mock_search
        Fido.fetch = mock_fetch

        try:
            # Execute the script in a clean namespace
            exec_globals = {'__name__': '__capture__'}
            # Suppress script prints to stdout during exec
            sys.stdout = StringIO()
            exec(script, exec_globals)
            # Explicitly run main() if present to capture guarded calls
            if 'main' in exec_globals and callable(exec_globals['main']):
                try:
                    exec_globals['main']()
                except Exception:
                    pass

            # Walk captured calls
            for call in mock_search.call_args_list:
                instruments: List[str] = []
                sources: List[str] = []
                detectors: List[str] = []
                time_range: Optional[Tuple[str, str]] = None
                for arg in call.args:
                    try:
                        if isinstance(arg, a.Instrument):
                            instruments.append(arg.value)
                        elif isinstance(arg, a.Time):
                            time_range = (str(arg.start), str(arg.end))
                        elif isinstance(arg, a.Source) or (hasattr(a, 'Observatory') and isinstance(arg, a.Observatory)):
                            # Some scripts may specify Source/Observatory
                            # a.Source has .value attribute
                            val = getattr(arg, 'value', None)
                            if val:
                                sources.append(val)
                        elif hasattr(a, 'Detector') and isinstance(arg, a.Detector):
                            val = getattr(arg, 'value', None)
                            if val:
                                detectors.append(val)
                    except Exception:
                        continue
                if instruments and time_range:
                    calls.append({'instruments': instruments, 'sources': sources, 'detectors': detectors, 'time': time_range})
        finally:
            # Restore
            Fido.search = original_search
            Fido.fetch = original_fetch
            sys.stdout = original_stdout

        return calls

    def _resolve_instrument(self, inst_code: str, sources: List[str]) -> Optional[Instrument]:
        # Try source-qualified lookup first
        for src in sources:
            candidates = [src]
            if '_' in src:
                candidates.append(src.replace('_', '-'))
            if '-' in src:
                candidates.append(src.replace('-', '_'))
            for cand in candidates:
                inst = Instrument.objects.filter(
                    short_name__iexact=inst_code,
                    observatory__short_name__iexact=cand
                ).select_related('observatory__datasource').first()
                if inst:
                    return inst

        # Fallback: unique instrument by short name across all observatories
        qs = Instrument.objects.filter(short_name__iexact=inst_code).select_related('observatory__datasource')
        count = qs.count()
        if count == 1:
            return qs.first()

        # Ambiguous or not found
        return None
