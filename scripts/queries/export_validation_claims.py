"""Build the validation-campaign manifest (issue #177 / VALIDATION_PROTOCOL.md).

Computes the DEDUPLICATED CLAIM UNION over the two configs under review —
a claim = (paper, instrument, observation window) — assigns papers to
reviewers (stratified by mission provenance, seeded), and selects the
calibration and reliability subsets. For each claim, ONE DatasetUsage is
chosen (seeded random config when both configs assert it) as the page the
reviewer opens; the claim -> {config: du_id} mapping is kept in the manifest
as the ANSWER KEY for the analysis phase and must NOT be shared with
reviewers.

Run in the prod api container:
  docker compose ... cp scripts/queries/export_validation_claims.py api:/tmp/x.py
  docker compose ... exec -T api python manage.py shell -c "exec(open('/tmp/x.py').read())"
Then copy /tmp/validation_campaign.json out and render workbooks locally with
scripts/queries/render_validation_workbooks.py.
"""
import hashlib
import json
import random
from collections import defaultdict

from vso_query_builder.models import DatasetUsage, Paper

SEED = 20260708
CONFIGS = ['bedrock-120b-mixed-v5@s1', 'standard-gpt54-v5']
REVIEWERS = ['reviewer_1', 'reviewer_2', 'reviewer_3']   # rename at render time
N_CALIBRATION = 25
RELIABILITY_PAPER_FRACTION = 0.15
STRATA = [('SOHO', {'soho', 'SOHO'}), ('Wind', {'wind', 'Wind'}), ('IRIS', {'IRIS'}),
          ('PSP', {'PSP_FIELDS', 'PSP_SWEAP'}), ('ACE', {'ACE'}),
          ('SDO', {'sdo_candidates'})]

rng = random.Random(SEED)

# ---- claim union -----------------------------------------------------------
claims = {}   # key -> claim dict
for cfg in CONFIGS:
    qs = (DatasetUsage.objects
          .filter(paper_analysis__configuration_name=cfg)
          .select_related('instrument__observatory', 'paper', 'paper_analysis'))
    for du in qs:
        w = du.observation_window
        start = w.lower.isoformat() if w and w.lower else None
        end = w.upper.isoformat() if w and w.upper else None
        key = hashlib.sha1('|'.join([
            str(du.paper_id), str(du.instrument_id), str(start), str(end)
        ]).encode()).hexdigest()[:12]
        c = claims.setdefault(key, {
            'claim_key': key,
            'paper_id': str(du.paper_id),
            'bibcode': du.paper.bibcode,
            'paper_title': du.paper.title or '',
            'instrument': du.instrument.short_name,
            'observatory': (du.instrument.observatory.short_name
                            if du.instrument.observatory else ''),
            'window_start': start, 'window_end': end,
            'dus': {},   # ANSWER KEY: config -> du id — never shown to reviewers
        })
        c['dus'][cfg] = str(du.id)

for c in claims.values():
    present = [cfg for cfg in CONFIGS if cfg in c['dus']]
    c['review_du'] = c['dus'][rng.choice(present)]   # seeded; blind page target

# ---- paper strata + reviewer assignment ------------------------------------
papers = sorted({c['paper_id'] for c in claims.values()})
tags_by_paper = {str(p.id): set(p.tags or [])
                 for p in Paper.objects.filter(id__in=papers)}

def stratum(pid):
    t = tags_by_paper.get(pid, set())
    for name, tagset in STRATA:
        if t & tagset:
            return name
    return 'general'

by_stratum = defaultdict(list)
for pid in papers:
    by_stratum[stratum(pid)].append(pid)

reliability_papers, assignment = set(), {}
for name in sorted(by_stratum):
    plist = sorted(by_stratum[name])
    rng.shuffle(plist)
    n_rel = max(1, round(len(plist) * RELIABILITY_PAPER_FRACTION))
    reliability_papers.update(plist[:n_rel])
    for i, pid in enumerate(plist[n_rel:]):
        assignment[pid] = REVIEWERS[i % len(REVIEWERS)]

# ---- calibration subset (oversample config-unique claims) ------------------
all_claims = sorted(claims.values(), key=lambda c: c['claim_key'])
unique_claims = [c for c in all_claims if len(c['dus']) == 1]
shared_claims = [c for c in all_claims if len(c['dus']) > 1]
rng.shuffle(unique_claims); rng.shuffle(shared_claims)
calibration = sorted(
    unique_claims[:(N_CALIBRATION * 3) // 5] + shared_claims[:N_CALIBRATION * 2 // 5],
    key=lambda c: c['claim_key'])[:N_CALIBRATION]
calibration_keys = {c['claim_key'] for c in calibration}

manifest = {
    'meta': {
        'seed': SEED, 'configs': CONFIGS, 'reviewers': REVIEWERS,
        'n_claims': len(claims), 'n_papers': len(papers),
        'n_shared_claims': len(shared_claims), 'n_unique_claims': len(unique_claims),
        'reliability_papers': sorted(reliability_papers),
        'calibration_keys': sorted(calibration_keys),
        'assignment': assignment,   # paper -> reviewer (bulk)
    },
    'claims': all_claims,
}
with open('/tmp/validation_campaign.json', 'w') as f:
    json.dump(manifest, f)
print('claims=%d (shared=%d unique=%d) papers=%d reliability_papers=%d calibration=%d' % (
    len(claims), len(shared_claims), len(unique_claims), len(papers),
    len(reliability_papers), len(calibration)))
for r in REVIEWERS:
    n = sum(1 for v in assignment.values() if v == r)
    print('%s: %d bulk papers' % (r, n))
