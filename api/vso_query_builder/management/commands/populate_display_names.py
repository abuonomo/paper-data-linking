from django.core.management.base import BaseCommand
from ...models import Observatory, Instrument


def parse_spase_observatory(short_name):
    """Parse a SPASE observatory ID into a human-readable name.

    e.g. 'spase://SMWG/Observatory/Cluster-Salsa' -> 'Cluster-Salsa'
    """
    for prefix in ["spase://SMWG/Observatory/", "spase://NASA/Observatory/"]:
        if short_name.startswith(prefix):
            return short_name[len(prefix):].replace("/", "-")
    return short_name


def parse_spase_instrument(inst_short_name, obs_short_name):
    """Parse a SPASE instrument ID into a human-readable name.

    Strips the observatory path from the instrument path so you get
    just the instrument portion.

    e.g. 'spase://SMWG/Instrument/Cluster-Salsa/FGM' -> 'FGM'
    """
    for inst_prefix, obs_prefix in [
        ("spase://SMWG/Instrument/", "spase://SMWG/Observatory/"),
        ("spase://NASA/Instrument/", "spase://NASA/Observatory/"),
    ]:
        if inst_short_name.startswith(inst_prefix):
            remainder = inst_short_name[len(inst_prefix):]
            if obs_short_name and obs_short_name.startswith(obs_prefix):
                obs_path = obs_short_name[len(obs_prefix):]
                if remainder.startswith(obs_path + "/"):
                    remainder = remainder[len(obs_path) + 1:]
            return remainder.replace("/", "-")
    return inst_short_name


class Command(BaseCommand):
    help = "Populate display_name for Observatory and Instrument records."

    def handle(self, *args, **kwargs):
        obs_updated = 0
        for obs in Observatory.objects.all():
            if obs.datasource and obs.datasource.slug == "cdaweb":
                display_name = parse_spase_observatory(obs.short_name)
            else:
                # VSO and others: short_name is already human-readable
                display_name = obs.short_name

            if obs.display_name != display_name:
                obs.display_name = display_name
                obs.save(update_fields=["display_name"])
                obs_updated += 1

        self.stdout.write(f"Updated {obs_updated} observatories.")

        inst_updated = 0
        for inst in Instrument.objects.select_related("observatory__datasource").all():
            if inst.observatory.datasource and inst.observatory.datasource.slug == "cdaweb":
                display_name = parse_spase_instrument(
                    inst.short_name, inst.observatory.short_name
                )
            else:
                display_name = inst.short_name

            if inst.display_name != display_name:
                inst.display_name = display_name
                inst.save(update_fields=["display_name"])
                inst_updated += 1

        self.stdout.write(f"Updated {inst_updated} instruments.")
        self.stdout.write(self.style.SUCCESS("Done."))
