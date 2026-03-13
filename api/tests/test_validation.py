"""RED tests for validation utilities – must fail until implemented."""

import pytest

from api.utils.validation import validate_origin_host

# ---------------------------------------------------------------------------
# Valid inputs
# ---------------------------------------------------------------------------

def test_valid_public_ipv4():
    assert validate_origin_host("203.0.113.10") == "203.0.113.10"


def test_valid_public_ipv4_with_leading_spaces():
    """Leading/trailing whitespace should be stripped."""
    assert validate_origin_host("  8.8.8.8  ") == "8.8.8.8"


# ---------------------------------------------------------------------------
# Private / blocked ranges
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("addr", [
    "127.0.0.1",
    "10.0.0.1",
    "10.255.255.255",
    "192.168.0.1",
    "192.168.100.200",
    "169.254.0.1",
    "172.16.0.1",
    "::1",
])
def test_private_ip_rejected(addr):
    with pytest.raises(ValueError, match="not permitted"):
        validate_origin_host(addr)


# ---------------------------------------------------------------------------
# Invalid hostnames / garbage input
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "",
    "not a hostname",
    "has space.com",
    "-starts-with-dash.com",
])
def test_invalid_hostname_rejected(bad):
    with pytest.raises(ValueError):
        validate_origin_host(bad)
