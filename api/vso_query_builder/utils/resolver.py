from ..models import Observatory


def resolve_observatory(instr: str, explicit_source: str | None = None):
    """
    Decide which observatory (VSO 'source') to attach to an instrument.

    Returns
    -------
    (source_slug | None, reason)
        source_slug is UPPER‑CASE text or None if ambiguous / unknown.
        reason is one of: 'explicit', 'lookup-unique', 'lookup-none',
        'ambiguous'.
    """
    instr_u = instr.upper()

    # script used a.Source("SOHO") etc.
    if explicit_source:
        return explicit_source.upper(), "explicit"

    # all observatories that have an instrument with this short_name
    cand = list(
        Observatory.objects
        .filter(instrument__short_name=instr_u)
        .values_list("short_name", flat=True)
        .distinct()
    )

    if len(cand) == 1:
        return cand[0].upper(), "lookup-unique"      # safe auto‑assign
    if len(cand) == 0:
        return None, "lookup-none"           # unknown instrument
    return None, "ambiguous"                 # multiple possible sources

