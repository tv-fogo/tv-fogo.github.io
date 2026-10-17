# -*- coding: utf-8 -*-
"""HTTPS-only URL normalization for public addon requests."""

import ipaddress

try:
    from urllib.parse import urlsplit, urlunsplit
except ImportError:
    from urlparse import urlsplit, urlunsplit


def is_enabled():
    """The add-on privacy mode is fixed on; there is no user toggle."""
    return True


def _is_local_or_private(host):
    host = str(host or '').strip('[]').lower().rstrip('.')
    if not host or host == 'localhost' or host.endswith('.localhost') or host.endswith('.local'):
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return '.' not in host
    except Exception:
        return True


def to_https(url):
    """Upgrade public HTTP URLs while preserving path, query, and Kodi headers.

    A nonstandard port is kept and tried with TLS. If that service does not
    support HTTPS, the strict request layer fails instead of sending HTTP.
    """
    if not isinstance(url, str):
        return url
    base, separator, options = url.partition('|')
    try:
        parsed = urlsplit(base)
        scheme = parsed.scheme.lower()
        if scheme == 'https' or scheme != 'http' or _is_local_or_private(parsed.hostname):
            return url
        netloc = parsed.netloc
        if parsed.port == 80 and netloc.endswith(':80'):
            netloc = netloc[:-3]
        upgraded = urlunsplit(('https', netloc, parsed.path, parsed.query, parsed.fragment))
        return upgraded + (separator + options if separator else '')
    except Exception:
        return url


def play_url(url, headers=None):
    """Return the HTTPS form; callers never fall back to the HTTP address."""
    return to_https(url)


def patch_requests():
    """Compatibility no-op; HTTPS enforcement lives in localproxy requests."""
    return None
