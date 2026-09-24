"""Rate limits on the two password-login endpoints.

Both the JWT token endpoint (/token/) and the Django admin login
(/admin/login/) accept a username and password. Without a limit they accept
unlimited guesses. The limits are per client IP and shared across the two
endpoints; token refresh is not limited.

The client IP comes from X-Forwarded-For: production sits behind an AWS load
balancer and the client nginx, so REMOTE_ADDR is always nginx. DRF picks the
address ``NUM_PROXIES`` hops back (settings.REST_FRAMEWORK['NUM_PROXIES'],
env ``NUM_PROXIES``, default 2). Without that, every user would share one
bucket.
"""
from django.http import JsonResponse
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView


class _LoginThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LoginBurstThrottle(_LoginThrottle):
    scope = "login_burst"


class LoginSustainedThrottle(_LoginThrottle):
    scope = "login_sustained"


LOGIN_THROTTLES = [LoginBurstThrottle, LoginSustainedThrottle]


class ThrottledTokenObtainPairView(TokenObtainPairView):
    throttle_classes = LOGIN_THROTTLES


class AdminLoginThrottleMiddleware:
    """Apply the login throttles to POST /admin/login/ (not a DRF view)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and request.path == "/admin/login/":
            for cls in LOGIN_THROTTLES:
                throttle = cls()
                if not throttle.allow_request(request, None):
                    wait = throttle.wait()
                    response = JsonResponse(
                        {"detail": "Too many login attempts. Try again later."}, status=429)
                    if wait:
                        response["Retry-After"] = str(int(wait) + 1)
                    return response
        return self.get_response(request)
