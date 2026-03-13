"""Validation helpers for origin host and IP addresses."""

import ipaddress
import re
import socket

from api.config import settings

# Private / link-local ranges that must not be used as origins
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

# Strict public hostname regex for production mode.
_PUBLIC_HOSTNAME_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
)
_LOCAL_HOSTNAME_RE = re.compile(
    r"^(?:localhost|[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*)$"
)
_LOCAL_HOST_SUFFIXES = (".local", ".lan", ".localhost", ".internal", ".home.arpa")


def _looks_local_hostname(host: str) -> bool:
    return "." not in host or host == "localhost" or host.endswith(_LOCAL_HOST_SUFFIXES)


def _is_private_ip(address: str) -> bool:
    """Return True if *address* falls within a blocked network range."""
    try:
        ip = ipaddress.ip_address(address)
        return any(ip in net for net in _BLOCKED_NETWORKS)
    except ValueError:
        return False


def validate_origin_host(host: str) -> str:
    """Validate *host* as either a public IP address or a resolvable hostname.

    Raises ``ValueError`` with a user-facing message on failure.
    Returns the (unchanged) host on success.
    """
    host = host.strip()
    if not host:
        raise ValueError("Origin host cannot be empty.")

    # Try to parse as an IP address first.
    try:
        ipaddress.ip_address(host)  # validates format; raises ValueError if not a valid IP
        if _is_private_ip(host) and not settings.allow_private_origin_hosts:
            raise ValueError(
                "Private, loopback, and link-local IP addresses are not permitted as origin hosts."
            )
        return host
    except ValueError as exc:
        # Re-raise if it is an explicit private-IP error.
        if "not permitted" in str(exc):
            raise

    hostname_re = _LOCAL_HOSTNAME_RE if settings.allow_private_origin_hosts else _PUBLIC_HOSTNAME_RE
    if not hostname_re.match(host):
        message = (
            f"'{host}' is not a valid IP address or hostname."
            if settings.allow_private_origin_hosts
            else f"'{host}' is not a valid public IP address or hostname."
        )
        raise ValueError(message)

    try:
        results = socket.getaddrinfo(host, None)
        for result in results:
            ip_str = result[4][0]
            if _is_private_ip(ip_str) and not settings.allow_private_origin_hosts:
                raise ValueError(
                    f"The hostname '{host}' resolves to a private or link-local address, "
                    "which is not permitted as an origin host."
                )
    except OSError:
        if settings.allow_private_origin_hosts and _looks_local_hostname(host):
            return host
        raise ValueError(f"The hostname '{host}' could not be resolved.") from None

    return host
