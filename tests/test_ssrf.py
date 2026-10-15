import pytest
from app.scanner import validate_and_resolve_url, is_safe_ip

def test_public_url_validation():
    safe, norm, err = validate_and_resolve_url("google.com")
    assert safe is True
    assert norm == "https://google.com/"
    assert err is None

    safe, norm, err = validate_and_resolve_url("https://stripe.com/about")
    assert safe is True
    assert norm == "https://stripe.com/about"

def test_ssrf_localhost_blocked():
    safe, norm, err = validate_and_resolve_url("http://localhost:8000")
    assert safe is False
    assert "blocked" in err.lower() or "internal" in err.lower()

    safe, norm, err = validate_and_resolve_url("http://127.0.0.1:8080/test")
    assert safe is False
    assert "blocked" in err.lower() or "private" in err.lower()

def test_ssrf_private_network_blocked():
    safe, norm, err = validate_and_resolve_url("http://192.168.1.100")
    assert safe is False
    assert "blocked" in err.lower()

    safe, norm, err = validate_and_resolve_url("http://10.0.0.5:5000")
    assert safe is False
    assert "blocked" in err.lower()

    safe, norm, err = validate_and_resolve_url("http://172.16.50.1")
    assert safe is False
    assert "blocked" in err.lower()

def test_ssrf_cloud_metadata_blocked():
    safe, norm, err = validate_and_resolve_url("http://169.254.169.254/latest/meta-data/")
    assert safe is False
    assert "blocked" in err.lower()

def test_disallowed_schemes():
    safe, norm, err = validate_and_resolve_url("file:///etc/passwd")
    assert safe is False
    assert "scheme" in err.lower()

    safe, norm, err = validate_and_resolve_url("gopher://evil.com")
    assert safe is False
    assert "scheme" in err.lower()

    safe, norm, err = validate_and_resolve_url("ftp://ftp.example.com")
    assert safe is False
    assert "scheme" in err.lower()
