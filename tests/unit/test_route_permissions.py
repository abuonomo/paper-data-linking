"""Every API route is authenticated unless it is on this allowlist.

DRF's permission default is closed (``DEFAULT_PERMISSION_CLASSES`` =
IsAuthenticated in settings). This test walks the URLconf and checks each DRF
view's effective permission classes, so a new view cannot become anonymous by
forgetting ``permission_classes``, and an allowlisted route cannot quietly
start requiring login.

To make a route anonymous: set ``permission_classes = [AllowAny]`` on the view
AND add its URL name here with the reason.
"""
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

ANONYMOUS_ROUTES = {
    # Public read API (docs/PUBLIC_API.md, OpenAPI schema)
    "public-paper-validated-usages",
    "public-paper-instrument-mentions",
    "public-validated-papers",
    "public-validated-papers-csv",
    "public-papers-filter-options",
    "public-similar-papers",
    "version",
    "schema",
    "schema-swagger",
    # Public web pages: /usage-explorer and /monitoring
    "usage-by-mission",
    "mission-launches",
    "solar-events",
    "available-configurations",
    "monitoring-dashboard",
    # Login
    "token_obtain_pair",
    "token_refresh",
}


def _walk(patterns, prefix=""):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from _walk(p.url_patterns, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            yield prefix + str(p.pattern), p


def _drf_routes():
    for route, pattern in _walk(get_resolver().url_patterns):
        view_cls = getattr(pattern.callback, "cls", None)
        if view_cls is not None and issubclass(view_cls, APIView):
            yield route, pattern.name, view_cls


def _is_anonymous(view_cls):
    perms = list(view_cls.permission_classes)
    return not perms or any(issubclass(p, AllowAny) for p in perms)


def test_route_walk_finds_the_api():
    names = {name for _, name, _ in _drf_routes()}
    assert "public-validated-papers" in names and "list_papers" in names


def test_only_allowlisted_routes_are_anonymous():
    open_routes = sorted(
        f"{route} ({name})"
        for route, name, cls in _drf_routes()
        if _is_anonymous(cls) and name not in ANONYMOUS_ROUTES
    )
    assert open_routes == [], (
        "These routes accept anonymous requests but are not allowlisted in "
        f"{__file__}: {open_routes}"
    )


def test_allowlisted_routes_are_anonymous():
    closed = sorted(
        f"{route} ({name})"
        for route, name, cls in _drf_routes()
        if name in ANONYMOUS_ROUTES and not _is_anonymous(cls)
    )
    assert closed == [], f"Allowlisted routes now require login: {closed}"


def test_every_allowlisted_name_exists():
    names = {name for _, name, _ in _drf_routes()}
    assert ANONYMOUS_ROUTES - names == set()
