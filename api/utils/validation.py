"""Validation helpers for origin host and IP addresses."""

import ipaddress
import re
import socket

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

# Very permissive hostname regex – actual DNS resolution is not performed here.
_HOSTNAME_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
)


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

    # Try to parse as an IP address first.
    try:
        ipaddress.ip_address(host)  # validates format; raises ValueError if not a valid IP
        if _is_private_ip(host):
            raise ValueError(
                "Private, loopback, and link-local IP addresses are not permitted as origin hosts."
            )
        return host
    except ValueError as exc:
        # Re-raise if it is an explicit private-IP error.
        if "not permitted" in str(exc):
            raise

    # Not an IP – validate as hostname.
    if not _HOSTNAME_RE.match(host):
        raise ValueError(
            f"'{host}' is not a valid public IP address or hostname."
        )

    # Resolve hostname and check all returned IPs.
    try:
        results = socket.getaddrinfo(host, None)
        for result in results:
            ip_str = result[4][0]
            if _is_private_ip(ip_str):
                raise ValueError(
                    f"The hostname '{host}' resolves to a private or link-local address, "
                    "which is not permitted as an origin host."
                )
    except OSError:
        # Cannot resolve – reject to be safe.
        raise ValueError(f"The hostname '{host}' could not be resolved.") from None

    return host
