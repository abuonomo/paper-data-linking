# api/vso_query_builder/management/commands/dedupe_cluster_observatories.py
"""Collapse the stale numbered Cluster observatories into the named spacecraft.

The catalog carries the four Cluster spacecraft under TWO naming schemes:
  * numbered: spase://SMWG/Observatory/Cluster/C1..C4  (stale — not in current
    upstream SMWG; each holds only a WBD instrument)
  * named:    spase://SMWG/Observatory/Cluster-{Rumba,Salsa,Samba,Tango}  (current;
    full instrument set including their own WBD)

C1=Rumba, C2=Salsa, C3=Samba, C4=Tango. The numbered records are duplicates that
confuse grounding: a generic "Cluster FGM" mention can land on a numbered record
(which has no FGM, only WBD) and yield a useless mission-only stub.

This command, for each numbered Cluster observatory:
  * for every instrument under it, finds the equivalent on the named spacecraft
    (same trailing instrument path, e.g. .../Cluster/C1/WBD -> .../Cluster-Rumba/WBD):
      - if the named equivalent exists (a true duplicate): repoint any DatasetUsages
        and InstrumentMentions to it, then delete the numbered instrument;
      - if it does NOT exist (the numbered record holds something unique): re-parent
        the instrument to the named observatory (keep its short_name + links);
  * deletes the now-empty numbered observatory.

Idempotent (no numbered Cluster observatories -> no-op). Use --dry-run to preview.
HDPWS resolves both the numbered and named WBD InstrumentIDs, so repointing is
downstream-safe.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from ...models import Observatory, Instrument, DatasetUsage, InstrumentMention


NUMBERED_TO_NAMED = {
    "spase://SMWG/Observatory/Cluster/C1": "spase://SMWG/Observatory/Cluster-Rumba",
    "spase://SMWG/Observatory/Cluster/C2": "spase://SMWG/Observatory/Cluster-Salsa",
    "spase://SMWG/Observatory/Cluster/C3": "spase://SMWG/Observatory/Cluster-Samba",
    "spase://SMWG/Observatory/Cluster/C4": "spase://SMWG/Observatory/Cluster-Tango",
}
_INST_PREFIX = "spase://SMWG/Instrument/"
_OBS_PREFIX = "spase://SMWG/Observatory/"


def _named_instrument_short_name(numbered_inst_sn, numbered_obs_sn, named_obs_sn):
    """.../Cluster/C1/WBD  ->  .../Cluster-Rumba/WBD  (suffix preserved)."""
    numbered_tail = numbered_obs_sn[len(_OBS_PREFIX):]            # Cluster/C1
    named_tail = named_obs_sn[len(_OBS_PREFIX):]                  # Cluster-Rumba
    prefix = f"{_INST_PREFIX}{numbered_tail}/"                    # .../Cluster/C1/
    if not numbered_inst_sn.startswith(prefix):
        return None
    suffix = numbered_inst_sn[len(prefix):]                       # WBD
    return f"{_INST_PREFIX}{named_tail}/{suffix}"


class Command(BaseCommand):
    help = "Collapse stale numbered Cluster/C1..C4 observatories into the named spacecraft."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Preview without writing.")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        tag = "[dry-run] " if dry else ""
        repointed_dus = repointed_mentions = deleted_insts = reparented = deleted_obs = 0

        try:
            with transaction.atomic():
                for numbered_sn, named_sn in NUMBERED_TO_NAMED.items():
                    numbered_obs = Observatory.objects.filter(short_name=numbered_sn).first()
                    if not numbered_obs:
                        continue
                    named_obs = Observatory.objects.filter(short_name=named_sn).first()
                    if not named_obs:
                        self.stderr.write(self.style.WARNING(
                            f"Named obs {named_sn} missing; skipping {numbered_sn}"))
                        continue

                    for inst in Instrument.objects.filter(observatory=numbered_obs):
                        named_sn_inst = _named_instrument_short_name(inst.short_name, numbered_sn, named_sn)
                        named_inst = (Instrument.objects.filter(
                            observatory=named_obs, short_name=named_sn_inst).first()
                            if named_sn_inst else None)

                        if named_inst:
                            n_du = DatasetUsage.objects.filter(instrument=inst).count()
                            n_m = InstrumentMention.objects.filter(matched_instrument=inst).count()
                            self.stdout.write(
                                f"  {tag}dup {inst.short_name} -> {named_inst.short_name} "
                                f"(repoint {n_du} DU, {n_m} mention)")
                            if not dry:
                                DatasetUsage.objects.filter(instrument=inst).update(instrument=named_inst)
                                # mentions: respect the (paper_analysis, matched_instrument) unique constraint
                                for m in InstrumentMention.objects.filter(matched_instrument=inst):
                                    if InstrumentMention.objects.filter(
                                            paper_analysis=m.paper_analysis,
                                            matched_instrument=named_inst).exists():
                                        m.delete()
                                    else:
                                        m.matched_instrument = named_inst
                                        m.save(update_fields=["matched_instrument"])
                                inst.delete()
                            repointed_dus += n_du
                            repointed_mentions += n_m
                            deleted_insts += 1
                        else:
                            self.stdout.write(f"  {tag}re-parent {inst.short_name} -> {named_sn}")
                            if not dry:
                                inst.observatory = named_obs
                                inst.save(update_fields=["observatory"])
                            reparented += 1

                    self.stdout.write(f"  {tag}delete observatory {numbered_sn}")
                    if not dry:
                        numbered_obs.delete()  # matched_observatory mentions are SET_NULL
                    deleted_obs += 1

                if dry:
                    raise _Rollback()
        except _Rollback:
            pass

        self.stdout.write(self.style.SUCCESS(
            f"{tag}Done. observatories removed={deleted_obs}, duplicate instruments "
            f"removed={deleted_insts} (DUs repointed={repointed_dus}, mentions "
            f"repointed={repointed_mentions}), instruments re-parented={reparented}."))


class _Rollback(Exception):
    pass
