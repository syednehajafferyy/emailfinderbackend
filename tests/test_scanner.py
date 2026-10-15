import pytest
from app.scanner import (
    extract_emails_from_html, rank_emails, find_internal_links, clean_email
)

def test_clean_email_filters():
    assert clean_email("info@acme.com") == "info@acme.com"
    assert clean_email("CONTACT@ACME.COM.") == "contact@acme.com"
    
    # Image assets should be rejected
    assert clean_email("logo@2x.png") is None
    assert clean_email("icon@header.jpg") is None
    assert clean_email("style@bundle.css") is None

    # Example/dummy domains should be rejected
    assert clean_email("user@example.com") is None
    assert clean_email("test@domain.com") is None

def test_extract_emails_from_html():
    sample_html = """
    <html>
        <head>
            <title>Acme Corp</title>
            <meta name="contact" content="team@acmecorp.com" />
        </head>
        <body>
            <p>Welcome to Acme. Get in touch at <a href="mailto:info@acmecorp.com?subject=Hi">Email Us</a></p>
            <div>General inquiries: help@acmecorp.com or call us.</div>
            <div>Ignore this asset image: banner@2x.png</div>
        </body>
    </html>
    """
    candidates = extract_emails_from_html(sample_html, "https://acmecorp.com")
    emails = [c[0] for c in candidates]
    assert "info@acmecorp.com" in emails
    assert "team@acmecorp.com" in emails
    assert "help@acmecorp.com" in emails
    assert "banner@2x.png" not in emails

def test_rank_emails_prioritizes_general_business_addresses():
    candidates = [
        ("noreply@acme.com", "https://acme.com", 30),
        ("john.doe@gmail.com", "https://acme.com", 30),
        ("info@acme.com", "https://acme.com/contact", 50),
        ("sales@acme.com", "https://acme.com", 40),
    ]
    primary, others, src = rank_emails(candidates, "acme.com")
    assert primary == "info@acme.com"
    assert "sales@acme.com" in others
    assert "noreply@acme.com" not in others  # Negative score filtered out
    assert src == "https://acme.com/contact"

def test_find_internal_links():
    html = """
    <html>
        <body>
            <a href="/contact-us">Contact Us</a>
            <a href="/about">About Acme</a>
            <a href="/pricing">Pricing</a>
            <a href="https://external.com/partner">External Partner</a>
            <a href="/assets/catalog.pdf">Download PDF</a>
        </body>
    </html>
    """
    links = find_internal_links(html, "https://acmecorp.com")
    assert "https://acmecorp.com/contact-us" in links
    assert "https://acmecorp.com/about" in links
    assert "https://external.com/partner" not in links
    assert not any(l.endswith(".pdf") for l in links)
