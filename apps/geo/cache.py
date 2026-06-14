"""
Cached-JSON response helper, replacing the in-memory dicts + ETag handling that
the Flask app did by hand. Uses Django's cache framework so the behaviour can
extend across workers via Redis (see settings CACHES).
"""

import hashlib

from django.core.cache import cache
from django.http import HttpResponse, HttpResponseNotModified


def cached_json_response(request, cache_key, build_json, max_age):
    """
    Return a JSON HttpResponse for `cache_key`, building it via `build_json()` on
    a cache miss. Adds an ETag and honours If-None-Match with a 304.

    build_json: zero-arg callable returning a JSON string.
    max_age:    Cache-Control max-age in seconds.
    """
    entry = cache.get(cache_key)
    if entry is None:
        body = build_json()
        etag = hashlib.md5(body.encode()).hexdigest()
        entry = {"json": body, "etag": etag}
        cache.set(cache_key, entry, timeout=None)  # invalidated explicitly on ingest

    if request.headers.get("If-None-Match") == entry["etag"]:
        return HttpResponseNotModified()

    resp = HttpResponse(entry["json"], content_type="application/json")
    resp["ETag"] = entry["etag"]
    resp["Cache-Control"] = f"public, max-age={max_age}"
    return resp


def clear_geo_caches():
    """Drop all cached geo responses (called after ingest)."""
    cache.clear()
