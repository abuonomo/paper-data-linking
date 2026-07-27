"""ADS query builders for heliophysics bibcode collection."""


def keyword_search(
    keywords: list[str],
    collection: str = "astronomy",
    year_range: tuple[int, int] | None = None,
) -> str:
    kw_clause = " OR ".join(f'keyword:"{k}"' for k in keywords)
    q = f"({kw_clause}) collection:{collection}"
    if year_range:
        q += f" year:[{year_range[0]} TO {year_range[1]}]"
    return q


def bibstem_search(
    bibstems: list[str],
    year_range: tuple[int, int] | None = None,
) -> str:
    stem_clause = " OR ".join(f'bibstem:"{s}"' for s in bibstems)
    q = f"({stem_clause})"
    if year_range:
        q += f" year:[{year_range[0]} TO {year_range[1]}]"
    return q


def bibgroup_search(
    bibgroups: list[str],
    year_range: tuple[int, int] | None = None,
) -> str:
    group_clause = " OR ".join(f'bibgroup:"{g}"' for g in bibgroups)
    q = f"({group_clause})"
    if year_range:
        q += f" year:[{year_range[0]} TO {year_range[1]}]"
    return q


def arxiv_class_search(
    classes: list[str],
    year_range: tuple[int, int] | None = None,
) -> str:
    class_clause = " OR ".join(f'arxiv_class:"{c}"' for c in classes)
    q = f"({class_clause})"
    if year_range:
        q += f" year:[{year_range[0]} TO {year_range[1]}]"
    return q
