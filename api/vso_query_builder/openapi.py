"""drf-spectacular hooks: restrict the published schema to the public API.

The authenticated endpoints are the backend of the review interface and are
intentionally undocumented; only the unauthenticated read-only endpoints
under /builder/public/ (plus /builder/version/) are described.
"""

PUBLIC_PREFIXES = ("/builder/public/", "/builder/version/")
# Under public/ for historical reasons but requires authentication (paper full
# texts are publisher-licensed), so it is not part of the public API.
EXCLUDED_SUFFIXES = ("/pdf/",)


def public_only(endpoints, **kwargs):
    """Preprocessing hook: keep only public, unauthenticated routes."""
    return [
        (path, path_regex, method, callback)
        for (path, path_regex, method, callback) in endpoints
        if path.startswith(PUBLIC_PREFIXES) and not path.endswith(EXCLUDED_SUFFIXES)
    ]


def set_version(result, generator, request, public):
    """Postprocessing hook: stamp the package version into the schema info."""
    from paper_data_linking import __version__
    result.setdefault("info", {})["version"] = __version__
    return result
