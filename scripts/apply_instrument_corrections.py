#!/usr/bin/env python
"""
Manual corrections map for instrument and observatory data quality issues
identified in the post-enrichment audit.

Covers:
  - Critical: STEREO-A/B mismatch, FOXSI/GOES-17/SUNRISE wrong observatory names,
    Cluster-Samba wrong spacecraft number in descriptions
  - High:  Circular "X On Y" descriptions (SOHO, Geotail, MMS-ASPOC, BARREL camp 3-5)
  - Medium: Typos, "The ..." prefix, verbose full_names, display_name improvements
  - Low:   IAGA station names, BARREL observatory probe-specific names,
           generic fleet names (DMSP, LANL, Pioneer, IMP, ISEE, Helios)

Run inside the api container:
    python manage.py shell < /tmp/apply_instrument_corrections.py
Or via remote_execute.sh:
    ./scripts/remote_execute.sh django-shell-file scripts/apply_instrument_corrections.py
"""

import re
from django.db import transaction
from vso_query_builder.models import Instrument, Observatory

# ── Instrument corrections ────────────────────────────────────────────────────
# Key: short_name string  OR  (short_name, observatory_short_name) tuple
# Value: dict of field→value to update (description, full_name, display_name)

INSTRUMENT_CORRECTIONS = {

    # ── CRITICAL: STEREO-A descriptions say "STEREO-B" (wrong probe) ──────────
    ("IMPACT", "STEREO_A"): {
        "description": "STEREO-A IMPACT in-situ particle and CME transients suite measuring"
                       " suprathermal electrons, ions, energetic particles, and magnetic fields"
                       " in the solar wind",
    },
    ("PLASTIC", "STEREO_A"): {
        "description": "STEREO-A PLASTIC solar wind ion composition spectrometer measuring bulk"
                       " solar wind properties, suprathermal ion fluxes, elemental composition,"
                       " and charge states from 0.3 to 80 keV/q",
    },
    ("SECCHI", "STEREO_A"): {
        "description": "STEREO-A SECCHI remote-sensing suite imaging the solar corona and inner"
                       " heliosphere via EUV imager (EUVI), white-light coronagraphs (COR1, COR2),"
                       " and heliospheric imagers (HI1, HI2)",
    },
    ("SWAVES", "STEREO_A"): {
        "description": "STEREO-A SWAVES radio and plasma wave instrument measuring solar and"
                       " interplanetary radio burst spectra and in situ electric field wave spectra"
                       " from 2.5 kHz to 16 MHz",
    },

    # ── CRITICAL: FOXSI circular descriptions ─────────────────────────────────
    ("FOXSI", "FOXSI1"): {
        "description": "FOXSI sounding rocket hard X-ray solar telescope (flight 1, 2012-11-02)"
                       " using focusing optics to image microflare and active region X-ray emission"
                       " in the 4–15 keV band",
    },
    ("FOXSI", "FOXSI2"): {
        "description": "FOXSI sounding rocket hard X-ray solar telescope (flight 2, 2014-12-11)"
                       " using focusing optics to image solar coronal X-ray emission with improved"
                       " sensitivity in the 4–20 keV band",
    },

    # ── CRITICAL: SUNRISE-1 circular descriptions ─────────────────────────────
    ("IMaX", "SUNRISE1"): {
        "description": "SUNRISE-1 IMaX imaging magnetograph measuring photospheric vector magnetic"
                       " fields and Doppler velocities via Stokes polarimetry of the Fe I 5250.2 Å"
                       " spectral line during the June 2009 balloon flight",
    },
    ("SuFI", "SUNRISE1"): {
        "description": "SUNRISE-1 SuFI ultraviolet filter imager measuring high-resolution solar"
                       " photospheric and chromospheric intensity in five UV passbands between"
                       " 214 and 397 nm during the June 2009 balloon flight",
    },

    # ── CRITICAL: Cluster-Samba (SC3) described as "Cluster-2" ───────────────
    # Rumba=SC1, Salsa=SC2, Samba=SC3, Tango=SC4
    "spase://SMWG/Instrument/Cluster-Samba/WHISPER": {
        "description": "Cluster-Samba (SC3) WHISPER relaxation sounder measuring electron plasma"
                       " density and high-frequency electric field wave spectra up to 80 kHz",
    },
    "spase://SMWG/Instrument/Cluster-Samba/STAFF": {
        "description": "Cluster-Samba (SC3) STAFF search-coil magnetometer and spectrum analyzer"
                       " measuring AC magnetic and electric field fluctuations from 8 Hz to 4 kHz",
    },
    "spase://SMWG/Instrument/Cluster-Samba/PEACE": {
        "description": "Cluster-Samba (SC3) PEACE dual electron spectrometer measuring 3D electron"
                       " velocity distributions and pitch-angle distributions from 0.6 eV to 26 keV",
    },
    "spase://SMWG/Instrument/Cluster-Samba/WBD": {
        "description": "Cluster-Samba (SC3) WBD wideband plasma wave receiver measuring"
                       " high-resolution electric and magnetic field waveforms from 25 Hz to 577 kHz",
    },
    # Cluster-Salsa (SC2) described as "Cluster-4"
    "spase://SMWG/Instrument/Cluster-Salsa/STAFF": {
        "description": "Cluster-Salsa (SC2) STAFF search-coil magnetometer and spectrum analyzer"
                       " measuring AC magnetic and electric field fluctuations from 8 Hz to 4 kHz",
    },

    # ── HIGH: SOHO circular "X On SOHO" descriptions ──────────────────────────
    "spase://SMWG/Instrument/SOHO/COSTEP": {
        "description": "SOHO COSTEP suprathermal and energetic particle telescope measuring solar"
                       " energetic ion and electron intensities from ~0.04 to ~700 MeV/nucleon at L1",
    },
    "spase://SMWG/Instrument/SOHO/ERNE": {
        "description": "SOHO ERNE energetic and relativistic nuclei and electron spectrometer"
                       " measuring solar energetic protons, helium, and heavy ion intensities"
                       " from ~1.4 to ~540 MeV/nucleon",
    },
    "spase://SMWG/Instrument/SOHO/CELIAS": {
        "description": "SOHO CELIAS charge, element, and isotope analysis system measuring solar"
                       " wind heavy ion composition, charge states, and velocity distributions"
                       " using time-of-flight mass spectrometry at L1",
    },

    # ── HIGH: Geotail circular description ────────────────────────────────────
    "spase://SMWG/Instrument/Geotail/EFD": {
        "description": "Geotail EFD electric field detector measuring three-component DC and"
                       " low-frequency electric field vectors in the Earth's magnetotail"
                       " and magnetopause regions",
    },

    # ── HIGH: MMS ASPOC — circular description (MMS-3) + display/full_name ───
    "spase://SMWG/Instrument/MMS/3/InstrumentControl/ASPOC": {
        "description": "MMS-3 ASPOC active spacecraft potential control device emitting indium"
                       " ion beams to reduce spacecraft charging and enable undisturbed plasma"
                       " and electric field measurements",
        "full_name": "ASPOC",
        "display_name": "ASPOC",
    },
    # Fix full_name and display_name for MMS-1/2/4 ASPOC too (descriptions already OK)
    "spase://SMWG/Instrument/MMS/1/InstrumentControl/ASPOC": {
        "full_name": "ASPOC",
        "display_name": "ASPOC",
    },
    "spase://SMWG/Instrument/MMS/2/InstrumentControl/ASPOC": {
        "full_name": "ASPOC",
        "display_name": "ASPOC",
    },
    "spase://SMWG/Instrument/MMS/4/InstrumentControl/ASPOC": {
        "full_name": "ASPOC",
        "display_name": "ASPOC",
    },

    # ── MEDIUM: MMS PascalCase display_names and full_names ───────────────────
    "spase://SMWG/Instrument/MMS/1/HotPlasmaCompositionAnalyzer": {
        "full_name": "HPCA", "display_name": "HPCA",
    },
    "spase://SMWG/Instrument/MMS/2/HotPlasmaCompositionAnalyzer": {
        "full_name": "HPCA", "display_name": "HPCA",
    },
    "spase://SMWG/Instrument/MMS/3/HotPlasmaCompositionAnalyzer": {
        "full_name": "HPCA", "display_name": "HPCA",
    },
    "spase://SMWG/Instrument/MMS/4/HotPlasmaCompositionAnalyzer": {
        "full_name": "HPCA", "display_name": "HPCA",
    },
    "spase://SMWG/Instrument/MMS/1/EnergeticParticleDetector/FEEPS": {
        "full_name": "FEEPS", "display_name": "FEEPS",
    },
    "spase://SMWG/Instrument/MMS/2/EnergeticParticleDetector/FEEPS": {
        "full_name": "FEEPS", "display_name": "FEEPS",
    },
    "spase://SMWG/Instrument/MMS/3/EnergeticParticleDetector/FEEPS": {
        "full_name": "FEEPS", "display_name": "FEEPS",
    },
    "spase://SMWG/Instrument/MMS/4/EnergeticParticleDetector/FEEPS": {
        "full_name": "FEEPS", "display_name": "FEEPS",
    },
    "spase://SMWG/Instrument/MMS/1/EnergeticParticleDetector/EIS": {
        "full_name": "EIS", "display_name": "EIS",
    },
    "spase://SMWG/Instrument/MMS/2/EnergeticParticleDetector/EIS": {
        "full_name": "EIS", "display_name": "EIS",
    },
    "spase://SMWG/Instrument/MMS/3/EnergeticParticleDetector/EIS": {
        "full_name": "EIS", "display_name": "EIS",
    },
    "spase://SMWG/Instrument/MMS/4/EnergeticParticleDetector/EIS": {
        "full_name": "EIS", "display_name": "EIS",
    },
    "spase://SMWG/Instrument/MMS/1/FastPlasmaInstrument/DES": {
        "full_name": "FPI-DES", "display_name": "FPI-DES",
    },
    "spase://SMWG/Instrument/MMS/2/FastPlasmaInstrument/DES": {
        "full_name": "FPI-DES", "display_name": "FPI-DES",
    },
    "spase://SMWG/Instrument/MMS/3/FastPlasmaInstrument/DES": {
        "full_name": "FPI-DES", "display_name": "FPI-DES",
    },
    "spase://SMWG/Instrument/MMS/4/FastPlasmaInstrument/DES": {
        "full_name": "FPI-DES", "display_name": "FPI-DES",
    },
    "spase://SMWG/Instrument/MMS/1/FastPlasmaInstrument/DIS": {
        "full_name": "FPI-DIS", "display_name": "FPI-DIS",
    },
    "spase://SMWG/Instrument/MMS/2/FastPlasmaInstrument/DIS": {
        "full_name": "FPI-DIS", "display_name": "FPI-DIS",
    },
    "spase://SMWG/Instrument/MMS/3/FastPlasmaInstrument/DIS": {
        "full_name": "FPI-DIS", "display_name": "FPI-DIS",
    },
    "spase://SMWG/Instrument/MMS/4/FastPlasmaInstrument/DIS": {
        "full_name": "FPI-DIS", "display_name": "FPI-DIS",
    },

    # ── MEDIUM: Typos ─────────────────────────────────────────────────────────
    "EUI": {"full_name": "Extreme Ultraviolet Imager"},           # "Ultravoilet"
    "X123": {"full_name": "X123 SXR Spectrometer"},               # "Spectometer"

    # ── MEDIUM: "The ..." prefix in full_name ─────────────────────────────────
    "SUTRI":    {"full_name": "Solar Upper Transition Region Imager"},
    "ICON/IVM": {"full_name": "Ion Velocity Meter"},
    "ICON/EUV": {"full_name": "Extreme Ultraviolet Spectrograph"},
    "ICON/FUV": {"full_name": "Far Ultraviolet Imaging Spectrograph"},

    # ── MEDIUM: PSP TDS display stutter (FIELDS-FIELDS2-TDS) ─────────────────
    "spase://SMWG/Instrument/ParkerSolarProbe/FIELDS/FIELDS2/TDS": {
        "full_name": "FIELDS/TDS",
        "display_name": "FIELDS/TDS",
    },

    # ── LOW: IBEX ambiguous display names ─────────────────────────────────────
    "spase://SMWG/Instrument/IBEX/Hi": {"display_name": "IBEX-Hi"},
    "spase://SMWG/Instrument/IBEX/Lo": {"display_name": "IBEX-Lo"},
}


# ── Observatory corrections ───────────────────────────────────────────────────
# Key: observatory short_name.  Value: dict of field→value (name, display_name).

OBSERVATORY_CORRECTIONS = {

    # ── CRITICAL: STEREO_A has name="STEREO-B" ───────────────────────────────
    "STEREO_A": {"name": "STEREO-A"},

    # ── CRITICAL: FOXSI1 and FOXSI2 have name="...flight #3..." ──────────────
    "FOXSI1": {"name": "Focusing Optics X-ray Solar Imager (flight 1, 2012-11-02)"},
    "FOXSI2": {"name": "Focusing Optics X-ray Solar Imager (flight 2, 2014-12-11)"},

    # ── CRITICAL: GOES-17 has name="GOES-16" ─────────────────────────────────
    "GOES17": {"name": "GOES-17"},

    # ── CRITICAL: SUNRISE1 has name="...Flight #2..." ─────────────────────────
    "SUNRISE1": {"name": "Sunrise Balloon Flight #1 (June 2009)"},

    # ── HIGH: Generic fleet names → probe-specific ────────────────────────────
    "spase://SMWG/Observatory/Pioneer10": {"name": "Pioneer 10"},
    "spase://SMWG/Observatory/IMP8":      {"name": "IMP-8"},
    "spase://SMWG/Observatory/ISEE2":     {"name": "ISEE 2"},
    "spase://SMWG/Observatory/ISEE3":     {"name": "ISEE 3"},
    "spase://SMWG/Observatory/Helios2":   {"name": "Helios 2"},

    "spase://SMWG/Observatory/DMSP_5D-3/F16": {"name": "DMSP F16"},
    "spase://SMWG/Observatory/DMSP_5D-3/F17": {"name": "DMSP F17"},
    "spase://SMWG/Observatory/DMSP_5D-3/F18": {"name": "DMSP F18"},

    "spase://SMWG/Observatory/LANL/1989": {"name": "LANL-1989"},
    "spase://SMWG/Observatory/LANL/1990": {"name": "LANL-1990"},
    "spase://SMWG/Observatory/LANL/1991": {"name": "LANL-1991"},
    "spase://SMWG/Observatory/LANL/1994": {"name": "LANL-1994"},
    "spase://SMWG/Observatory/LANL/1997": {"name": "LANL-1997"},
    "spase://SMWG/Observatory/LANL/2001": {"name": "LANL-2001"},
    "spase://SMWG/Observatory/LANL/2002": {"name": "LANL-2002"},
}


# ── Pattern-based corrections (not enumerable one-by-one) ────────────────────

def barrel_description_from_uri(short_name: str, balloon_id: str, inst_type: str) -> str | None:
    """Return a good description for a BARREL instrument given type."""
    t = inst_type.upper()
    if t == "XRI":
        return (f"BARREL {balloon_id} X-ray Instrument NaI(Tl) scintillator measuring"
                f" bremsstrahlung X-ray spectra from precipitating electrons during"
                f" stratospheric balloon flight (~34 km altitude)")
    if t == "MAG":
        return (f"BARREL {balloon_id} tilt-compensated three-axis magnetometer measuring"
                f" local magnetic field variations and ULF wave activity during"
                f" stratospheric balloon flight")
    if t == "DATAPROCESSINGUNIT":
        return (f"BARREL {balloon_id} data processing unit controlling instrument"
                f" operations and acquiring X-ray spectrometer, magnetometer, GPS,"
                f" and engineering telemetry during stratospheric balloon flight")
    if t == "EPHEMERIS":
        return (f"BARREL {balloon_id} ephemeris providing balloon trajectory positions"
                f" and altitude in multiple coordinate systems during stratospheric flight")
    return None


def iaga_station_name_from_short_name(short_name: str) -> str | None:
    """Derive a readable station name from IAGA observatory short_name.

    spase://SMWG/Observatory/IAGA/Arctic.Village  →  'Arctic Village Magnetometer'
    """
    prefix = "spase://SMWG/Observatory/IAGA/"
    if not short_name.startswith(prefix):
        return None
    station = short_name.removeprefix(prefix).replace(".", " ")
    return f"{station} Magnetometer"


# ── Application ───────────────────────────────────────────────────────────────

def apply_corrections(dry_run: bool = False):
    inst_changed = 0
    obs_changed = 0

    with transaction.atomic():

        # 1. Named instrument corrections
        # Build lookup: short_name → list of Instrument objects
        all_short_names = set()
        for key in INSTRUMENT_CORRECTIONS:
            sn = key[0] if isinstance(key, tuple) else key
            all_short_names.add(sn)

        instruments_qs = Instrument.objects.filter(
            short_name__in=all_short_names
        ).select_related("observatory")

        for inst in instruments_qs:
            sn = inst.short_name
            obs_sn = inst.observatory.short_name if inst.observatory else None

            # Try tuple key first, fall back to plain key
            updates = INSTRUMENT_CORRECTIONS.get((sn, obs_sn)) \
                   or INSTRUMENT_CORRECTIONS.get(sn)
            if not updates:
                continue

            changed_fields = []
            for field, value in updates.items():
                if getattr(inst, field) != value:
                    if not dry_run:
                        setattr(inst, field, value)
                    changed_fields.append(field)

            if changed_fields:
                if not dry_run:
                    inst.save(update_fields=changed_fields)
                print(f"  [INST] {sn!r:.60} obs={obs_sn!r:.30} → {changed_fields}")
                inst_changed += 1

        # 2. BARREL pattern-based description fixes
        barrel_qs = Instrument.objects.filter(
            short_name__startswith="spase://SMWG/Instrument/BARREL/"
        ).select_related("observatory")

        barrel_fixed = 0
        for inst in barrel_qs:
            desc = inst.description or ""
            if "On BARREL" not in desc and not desc.endswith(", Instrument"):
                continue  # already has a good description
            # Extract balloon_id and instrument type from URI
            # e.g. spase://SMWG/Instrument/BARREL/3B/MAG  →  balloon=3B, type=MAG
            parts = inst.short_name.split("/")
            if len(parts) < 2:
                continue
            balloon_id = parts[-2]  # e.g. "3B"
            inst_type  = parts[-1]  # e.g. "MAG"
            new_desc = barrel_description_from_uri(inst.short_name, balloon_id, inst_type)
            if new_desc and inst.description != new_desc:
                if not dry_run:
                    inst.description = new_desc
                    inst.save(update_fields=["description"])
                print(f"  [BARREL] {inst.short_name!r:.70} → description rewritten")
                barrel_fixed += 1

        inst_changed += barrel_fixed

        # 3. Named observatory corrections
        all_obs_short = set(OBSERVATORY_CORRECTIONS)
        obs_qs = Observatory.objects.filter(short_name__in=all_obs_short)

        for obs in obs_qs:
            updates = OBSERVATORY_CORRECTIONS.get(obs.short_name, {})
            changed_fields = []
            for field, value in updates.items():
                if getattr(obs, field) != value:
                    if not dry_run:
                        setattr(obs, field, value)
                    changed_fields.append(field)
            if changed_fields:
                if not dry_run:
                    obs.save(update_fields=changed_fields)
                print(f"  [OBS]  {obs.short_name!r:.60} → {changed_fields}")
                obs_changed += 1

        # 4. BARREL observatory name → probe-specific (from display_name)
        barrel_obs = Observatory.objects.filter(
            short_name__startswith="spase://SMWG/Observatory/BARREL/"
        )
        barrel_obs_fixed = 0
        for obs in barrel_obs:
            # display_name is already "BARREL-2P" etc.
            if obs.display_name and obs.name != obs.display_name:
                if not dry_run:
                    obs.name = obs.display_name
                    obs.save(update_fields=["name"])
                print(f"  [BARREL-OBS] {obs.short_name!r:.50} name → {obs.display_name!r}")
                barrel_obs_fixed += 1
        obs_changed += barrel_obs_fixed

        # 5. IAGA observatory name → station-specific
        iaga_obs = Observatory.objects.filter(
            short_name__startswith="spase://SMWG/Observatory/IAGA/"
        )
        iaga_fixed = 0
        for obs in iaga_obs:
            new_name = iaga_station_name_from_short_name(obs.short_name)
            if new_name and obs.name != new_name:
                if not dry_run:
                    obs.name = new_name
                    obs.save(update_fields=["name"])
                print(f"  [IAGA] {obs.short_name!r:.55} → {new_name!r}")
                iaga_fixed += 1
        obs_changed += iaga_fixed

        if dry_run:
            raise RuntimeError("DRY RUN — rolling back")

    print()
    print(f"Instruments updated : {inst_changed}")
    print(f"Observatories updated: {obs_changed}")
    print("Done.")


# ── Entry point ───────────────────────────────────────────────────────────────
import sys
dry_run = "--dry-run" in sys.argv
if dry_run:
    print("DRY RUN — no changes will be written.\n")
    try:
        apply_corrections(dry_run=True)
    except RuntimeError:
        pass
else:
    apply_corrections(dry_run=False)
