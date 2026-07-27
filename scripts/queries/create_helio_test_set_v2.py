"""
Create a stratified test set of ~200 papers optimized for DatasetUsage yield.
Stratified by mission tag with abstract-based filtering for general helio papers.

Run via:
    docker compose exec -T api python manage.py shell < scripts/queries/create_helio_test_set_v2.py
"""
import random
import re
from collections import Counter

from vso_query_builder.models import Paper, PaperAnalysis

TAG = "test_set_helio_v2_2026_04_06"
TOTAL = 200
random.seed(42)

# ── Exclusion filters ────────────────────────────────────────────────

# Existing test set tags to exclude
EXISTING_TEST_SETS = [
    "test_set_2025_10_10", "test_set_2025_11_26",
    "test_set_2026_01_15", "test_set_2026_01_26",
    "test_set_2026_02_23", "test_set_helio_2026_03_13",
]

# Papers already processed (have any PaperAnalysis)
processed_ids = set(PaperAnalysis.objects.values_list("paper_id", flat=True).distinct())
print(f"Already processed papers: {len(processed_ids)}")

# ── Abstract keyword filter (for general helio stratum) ──────────────

# Exclusion: theory, modeling, reviews, non-helio, lab work
EXCLUDE_PATTERNS = [
    r"\bsimulation\b", r"\bnumerical\s+simulation", r"\bMHD\s+simulation",
    r"\bwe\s+model\b", r"\btheoretical\s+model", r"\banalytical\s+model",
    r"\bMonte\s+Carlo\b", r"\bGeant4\b",
    r"\breview\s+of\b", r"\bwe\s+review\b", r"\bsurvey\s+of\b",
    r"\bare\s+reviewed\b", r"\bare\s+discussed\s+critically\b",
    r"\bmachine\s+learning\b", r"\bneural\s+network\b", r"\bdeep\s+learning\b",
    r"\bclassifier\b",
    r"\btropospheric\b", r"\bcontinental\b", r"\boceanic\b", r"\bmonsoon\b",
    r"\bprototype\b", r"\blaboratory\s+measurement", r"\btest\s+facility\b",
]

# Strong inclusion: known instruments, observatories, data archives
# Any single match qualifies
INCLUDE_STRONG = [
    # SOHO instruments
    r"\bEIT\b", r"\bLASCO\b", r"\bMDI\b", r"\bSUMER\b", r"\bCDS\b",
    r"\bUVCS\b", r"\bCELIAS\b", r"\bCOSTEP\b", r"\bERNE\b", r"\bGOLF\b",
    r"\bVIRGO\b", r"\bSWAN\b",
    # Wind instruments
    r"\bSWE\b", r"\b3DP\b", r"\bWAVES\b", r"\bMFI\b", r"\bEPACT\b",
    # ACE instruments
    r"\bEPAM\b", r"\bSWICS\b", r"\bSWEPAM\b", r"\bULEIS\b",
    r"\bSIS\b", r"\bCRIS\b", r"\bSEPICA\b",
    # PSP instruments
    r"\bFIELDS\b", r"\bSWEAP\b", r"\bISIS\-EPI\b", r"\bWISPR\b",
    # SDO instruments
    r"\bAIA\b", r"\bHMI\b", r"\bEVE\b",
    # Hinode instruments
    r"\bEIS\b", r"\bXRT\b", r"\bSOT\b",
    # Other missions/instruments
    r"\bRHESSI\b", r"\bFERMI\b", r"\bGOES\b", r"\bMMS\b",
    r"\bCluster\b", r"\bTHEMIS\b", r"\bMAVEN\b",
    # Observatories
    r"\bSDO\b", r"\bHinode\b", r"\bSTEREO\b", r"\bTRACE\b",
    r"\bYohkoh\b", r"\bSMM\b", r"\bPROBA2\b", r"\bSolar\s+Orbiter\b",
    r"\bParker\s+Solar\s+Probe\b", r"\bUlysses\b",
    # Data archives
    r"\bCDAWeb\b", r"\bCDA\s*web\b", r"\bOMNIWeb\b",
    r"\bSSCWeb\b", r"\bVSO\b", r"\bSDAC\b", r"\bSPDF\b",
]

# Medium inclusion: contextual phrases suggesting data usage (need 2+)
INCLUDE_MEDIUM = [
    r"\bdata\s+from\b", r"\bobservations?\s+from\b", r"\bobserved\s+by\b",
    r"\bmeasured\s+by\b", r"\brecorded\s+by\b", r"\bdetected\s+by\b",
    r"\bin[\- ]situ\b", r"\bremote[\- ]sensing\b",
    r"\bspectrograph\b", r"\bspectrometer\b", r"\bcoronagraph\b",
    r"\bmagnetograph\b", r"\bmagnetometer\b", r"\bimager\b",
    r"\blevel[\- ][12]\b", r"\bcalibrated\s+data\b",
    r"\bdata\s*set\b", r"\btime\s+series\b", r"\blight\s+curve\b",
    r"\bflux\s+measurements?\b", r"\bin[\- ]situ\s+measurements?\b",
]


def abstract_suggests_data_usage(abstract):
    """Return True if abstract suggests the paper uses actual instrument data."""
    if not abstract:
        return False
    text = abstract

    # Check exclusions first
    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return False

    # Check strong inclusion (any 1 match)
    for pattern in INCLUDE_STRONG:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    # Check medium inclusion (need 2+)
    medium_hits = sum(1 for p in INCLUDE_MEDIUM if re.search(p, text, re.IGNORECASE))
    return medium_hits >= 2


# ── Build base pool ──────────────────────────────────────────────────

base = Paper.objects.filter(tags__contains=["helio_ml_high_conf"])
for t in EXISTING_TEST_SETS:
    base = base.exclude(tags__contains=[t])
base = base.exclude(id__in=processed_ids)
print(f"Base pool (helio_ml_high_conf, unprocessed, not in test sets): {base.count()}")

# Also build a wider pool for PSP/ACE that may not all be in helio_ml
wider = Paper.objects.all()
for t in EXISTING_TEST_SETS:
    wider = wider.exclude(tags__contains=[t])
wider = wider.exclude(id__in=processed_ids)

# ── Define strata ────────────────────────────────────────────────────

MISSION_TAGS = ["soho", "SOHO", "wind", "Wind", "IRIS", "PSP_FIELDS", "PSP_SWEAP", "ACE"]

strata_config = [
    ("SOHO",       ["soho", "SOHO"],  base, 45),
    ("Wind",       ["wind", "Wind"],  base, 40),
    ("IRIS",       ["IRIS"],          base, 35),
    ("PSP_FIELDS", ["PSP_FIELDS"],    wider, 25),
    ("PSP_SWEAP",  ["PSP_SWEAP"],     wider, 15),
    ("ACE",        ["ACE"],           wider, 15),
]

# ── Sample from each stratum (with deduplication) ────────────────────

selected_ids = set()
stratum_results = []

print(f"\n{'='*60}")
print(f"Sampling from mission strata")
print(f"{'='*60}")

for name, tags, pool, target in strata_config:
    # Filter by tags (overlap = any of the tag variants)
    qs = pool.filter(tags__overlap=tags)
    # Exclude already-selected papers
    if selected_ids:
        qs = qs.exclude(id__in=selected_ids)
    ids = list(qs.values_list("id", flat=True))
    n = min(target, len(ids))
    sampled = random.sample(ids, n)
    selected_ids.update(sampled)
    stratum_results.append((name, len(ids), n))
    print(f"  {name:15s}: pool={len(ids):>5d}, sampled={n:>3d} (target={target})")

# ── General helio stratum (abstract-filtered) ────────────────────────

print(f"\n{'='*60}")
print(f"Filtering general helio papers by abstract")
print(f"{'='*60}")

# Papers in helio_ml_high_conf with NO mission tag
general_pool = base
for tag in MISSION_TAGS:
    general_pool = general_pool.exclude(tags__contains=[tag])
if selected_ids:
    general_pool = general_pool.exclude(id__in=selected_ids)

total_general = general_pool.count()
print(f"General helio pool (no mission tags): {total_general}")

# Apply abstract filter
filtered_ids = []
excluded_count = 0
no_abstract_count = 0
for paper_id, abstract in general_pool.values_list("id", "abstract").iterator():
    if not abstract:
        no_abstract_count += 1
        continue
    if abstract_suggests_data_usage(abstract):
        filtered_ids.append(paper_id)
    else:
        excluded_count += 1

print(f"  Passed abstract filter: {len(filtered_ids)}")
print(f"  Excluded by filter:     {excluded_count}")
print(f"  No abstract:            {no_abstract_count}")

# Sample from filtered general pool
general_target = TOTAL - len(selected_ids)
n = min(general_target, len(filtered_ids))
sampled_general = random.sample(filtered_ids, n)
selected_ids.update(sampled_general)
stratum_results.append(("General helio", len(filtered_ids), n))
print(f"  Sampled: {n} (target={general_target})")

# ── Summary ──────────────────────────────────────────────────────────

print(f"\n{'='*60}")
print(f"Summary: {len(selected_ids)} papers selected")
print(f"{'='*60}")

for name, pool_size, sampled in stratum_results:
    print(f"  {name:15s}: {sampled:>3d} from pool of {pool_size}")

selected = Paper.objects.filter(id__in=selected_ids)

# Year distribution
years = Counter(selected.values_list("year", flat=True))
print(f"\nYear distribution:")
for yr in sorted(years.keys(), key=lambda x: x or "0000"):
    print(f"  {yr}: {years[yr]}")

# Journal distribution
journals = Counter()
for bib in selected.values_list("bibcode", flat=True):
    if bib and len(bib) > 4:
        j = ""
        for k, c in enumerate(bib[4:]):
            if c == "." or c.isdigit():
                j = bib[4:4+k]
                break
        journals[j] += 1
print(f"\nTop 15 journals:")
for j, c in journals.most_common(15):
    print(f"  {c:>4d}  {j}")

# Has text / has PDF
has_text = selected.exclude(full_text__isnull=True).exclude(full_text="").count()
has_pdf = selected.exclude(pdf="").exclude(pdf__isnull=True).count()
print(f"\nHas full text: {has_text}, Has PDF: {has_pdf}")

# Mission tag overlap in selected set
print(f"\nMission tag distribution in selected papers:")
for tag in MISSION_TAGS:
    count = selected.filter(tags__contains=[tag]).count()
    if count > 0:
        print(f"  {tag}: {count}")

# Spot-check: show 5 general helio abstracts
print(f"\nSpot-check: 5 general helio paper abstracts:")
spot_check = Paper.objects.filter(id__in=sampled_general[:5])
for p in spot_check:
    print(f"  {p.bibcode}: {(p.abstract or '')[:150]}...")
    print()

# ── Apply the tag ────────────────────────────────────────────────────

print(f"\nApplying tag '{TAG}' to {len(selected_ids)} papers...")

tagged = 0
for paper in Paper.objects.filter(id__in=selected_ids):
    if TAG not in (paper.tags or []):
        paper.tags = (paper.tags or []) + [TAG]
        paper.save(update_fields=["tags"])
        tagged += 1

print(f"Tagged {tagged} papers with '{TAG}'")
print(f"\nVerification: {Paper.objects.filter(tags__contains=[TAG]).count()} papers now have tag '{TAG}'")
