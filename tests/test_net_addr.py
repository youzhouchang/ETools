"""Tests for local IPv4 suggestion helpers."""

from etools.core.net_addr import suggest_remote_ipv4


def test_suggest_prefers_dot_one():
    assert suggest_remote_ipv4("192.168.1.50") == "192.168.1.1"
    assert suggest_remote_ipv4("10.0.0.23") == "10.0.0.1"


def test_suggest_avoids_self():
    assert suggest_remote_ipv4("192.168.1.1") == "192.168.1.2"


def test_suggest_invalid_falls_back():
    assert suggest_remote_ipv4("not-an-ip") == "192.168.1.1"
    assert suggest_remote_ipv4("") == "192.168.1.1"
