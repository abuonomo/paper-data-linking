"""Login endpoints are rate-limited per client IP (paper_analyzer_app/throttles.py)."""
import pytest
from django.core.cache import cache
from django.urls import reverse

BURST = 10  # settings default LOGIN_RATE_BURST=10/min


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _xff(client_ip):
    # What production sees: <client>, <load balancer> (nginx is REMOTE_ADDR).
    return {"HTTP_X_FORWARDED_FOR": f"{client_ip}, 10.0.0.5"}


def _bad_login(client, ip, spoof=None):
    xff = f"{spoof}, {ip}, 10.0.0.5" if spoof else f"{ip}, 10.0.0.5"
    return client.post(reverse("token_obtain_pair"),
                       {"username": "nobody", "password": "wrong"},
                       content_type="application/json", HTTP_X_FORWARDED_FOR=xff)


@pytest.mark.django_db
def test_token_login_throttled_after_burst(client):
    codes = [_bad_login(client, "203.0.113.7").status_code for _ in range(BURST + 1)]
    assert codes[:BURST] == [401] * BURST
    assert codes[BURST] == 429


@pytest.mark.django_db
def test_throttle_is_per_client_ip(client):
    for _ in range(BURST + 1):
        _bad_login(client, "203.0.113.7")
    assert _bad_login(client, "198.51.100.9").status_code == 401


@pytest.mark.django_db
def test_spoofed_forwarded_for_does_not_reset_the_limit(client):
    """A caller-supplied X-Forwarded-For entry sits left of the real client IP
    that the load balancer appends, so changing it does not change the bucket."""
    for i in range(BURST):
        _bad_login(client, "203.0.113.7", spoof=f"192.0.2.{i}")
    assert _bad_login(client, "203.0.113.7", spoof="192.0.2.250").status_code == 429


@pytest.mark.django_db
def test_successful_login_still_works_under_limit(client, django_user_model):
    django_user_model.objects.create_user(username="reviewer", password="pw-123456")
    r = client.post(reverse("token_obtain_pair"), {"username": "reviewer", "password": "pw-123456"},
                    content_type="application/json", **_xff("203.0.113.8"))
    assert r.status_code == 200 and "access" in r.json()


@pytest.mark.django_db
def test_token_refresh_not_throttled(client):
    for _ in range(BURST + 2):
        r = client.post(reverse("token_refresh"), {"refresh": "bad"},
                        content_type="application/json", **_xff("203.0.113.7"))
        assert r.status_code == 401


@pytest.mark.django_db
def test_admin_login_throttled(client):
    for _ in range(BURST):
        r = client.post("/admin/login/", {"username": "nobody", "password": "wrong"}, **_xff("203.0.113.7"))
        assert r.status_code == 200  # admin re-renders the form on failure
    r = client.post("/admin/login/", {"username": "nobody", "password": "wrong"}, **_xff("203.0.113.7"))
    assert r.status_code == 429
    assert client.get("/admin/login/", **_xff("203.0.113.7")).status_code == 200  # GET unaffected
