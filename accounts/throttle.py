"""Minimal cache-backed rate limiting for expensive endpoints.

Code execution spins up a container (or subprocess), so unthrottled access is a
denial-of-service and cost risk. This decorator limits each (user or IP) to a
configurable number of calls per time window using Django's cache framework.

Configure with environment variables (read in settings.py):
    EXECUTION_RATE_LIMIT_MAX    e.g. 20
    EXECUTION_RATE_LIMIT_WINDOW e.g. 60   (seconds)
"""

import time
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse


def _client_key(request):
    if request.user.is_authenticated:
        return f"user:{request.user.id}"
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "unknown")
    return f"ip:{ip}"


def rate_limit(max_calls=None, window_seconds=None, scope="exec_default"):
    """Decorator limiting calls per client within a sliding fixed window."""
    max_calls = max_calls or getattr(settings, "EXECUTION_RATE_LIMIT_MAX", 20)
    window_seconds = window_seconds or getattr(settings, "EXECUTION_RATE_LIMIT_WINDOW", 60)

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            bucket = int(time.time() // window_seconds)
            cache_key = f"ratelimit:{scope}:{_client_key(request)}:{bucket}"
            try:
                count = cache.get(cache_key, 0)
            except Exception:
                # If the cache backend is unavailable, fail open rather than
                # blocking all learners.
                return view_func(request, *args, **kwargs)

            if count >= max_calls:
                return JsonResponse(
                    {
                        "status": "error",
                        "output": "Rate limit reached. Please wait a moment before running code again.",
                    },
                    status=429,
                )
            try:
                cache.set(cache_key, count + 1, timeout=window_seconds)
            except Exception:
                pass
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
