# -*- coding: utf-8 -*-
"""Adapter to the addon's scoped Cloudflare DNS resolver.

This keeps the small DNSOverride API used by the tvfogo modules without
installing a process-wide socket.getaddrinfo patch. Network requests use the
resolver only inside localproxy's request scope.
"""

import ipaddress
from contextlib import contextmanager


def resolve_doh(domain):
    """Return the first IPv4 address resolved by the addon, or None."""
    try:
        import localproxy
        addresses = localproxy.resolve_cloudflare_addresses(domain)
        return addresses[0] if addresses else None
    except Exception:
        return None


def is_valid_ipv4(host):
    try:
        ipaddress.IPv4Address(str(host or '').strip())
        return True
    except Exception:
        return False


@contextmanager
def cloudflare_scope():
    """Apply the addon's strict DoH resolver for the lifetime of a request."""
    import localproxy
    with localproxy.cloudflare_dns_scope():
        yield


class DNSOverride(object):
    """Compatibility facade; resolution remains scoped and fails closed."""

    def resolve(self, domain):
        return resolve_doh(domain)

    def is_valid_ipv4(self, host):
        return is_valid_ipv4(host)

    def __enter__(self):
        self._scope = cloudflare_scope()
        self._scope.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        scope = getattr(self, '_scope', None)
        if scope:
            return scope.__exit__(exc_type, exc_value, traceback)
        return False

    @staticmethod
    def restore():
        # The resolver is restored automatically when cloudflare_scope exits.
        return None
