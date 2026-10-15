import re
import socket
import ipaddress
import urllib.parse
from typing import List, Tuple, Optional, Set, Dict
import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.models import ScanStatus, WebsiteResult

# High-priority general business contact prefixes
PREFERRED_PREFIXES = {
    "info": 100,
    "contact": 100,
    "hello": 95,
    "office": 90,
    "support": 90,
    "sales": 90,
    "enquiries": 85,
    "inquiries": 85,
    "help": 75,
    "team": 75,
    "admin": 70,
    "service": 70,
    "reachus": 70,
    "reach": 70,
    "mail": 65,
    "general": 65,
    "business": 65,
    "connect": 60,
}

# Prefixes to discard or deprioritize heavily
DISQUALIFIED_PREFIXES = {
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "postmaster", "abuse", "webmaster", "hostmaster",
    "privacy", "mailer-daemon", "security", "dpo", "legal"
}

# Image extensions or asset suffixes mistakenly captured by broad email regex
INVALID_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp",
    ".ico", ".tiff", ".css", ".js", ".woff", ".woff2", ".ttf",
    ".eot", ".mp4", ".mp3", ".pdf", ".zip"
)

# Common placeholder domains
PLACEHOLDER_DOMAINS = {
    "example.com", "example.org", "example.net", "domain.com",
    "yourdomain.com", "mysite.com", "test.com", "email.com",
    "sentry.io", "wixpress.com", "cloudflare.com", "googleapis.com",
    "github.com", "schema.org", "w3.org", "gravatar.com"
}

# Keywords to detect Contact / About pages
CONTACT_KEYWORDS = ["contact", "contact-us", "contactus", "get-in-touch", "reach-us", "reach"]
ABOUT_KEYWORDS = ["about", "about-us", "aboutus", "company", "team", "who-we-are"]
SUPPORT_KEYWORDS = ["support", "help"]

# Regex for email extraction
EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
    re.IGNORECASE
)

def is_safe_ip(ip_str: str) -> bool:
    """Checks if an IP address is a public, safe address (SSRF prevention)."""
    try:
        ip = ipaddress.ip_address(ip_str)
        # Block private, loopback, link-local, multicast, reserved
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
        # Block cloud metadata addresses specifically
        if str(ip) in ("169.254.169.254", "fe80::1"):
            return False
        return True
    except ValueError:
        return False

def validate_and_resolve_url(raw_url: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Normalizes a URL and verifies SSRF safety.
    Returns: (is_safe, normalized_url, error_message)
    """
    if not raw_url or not isinstance(raw_url, str):
        return False, None, "Empty URL"

    url_str = raw_url.strip()
    if not url_str:
        return False, None, "Empty URL"

    # Check if a scheme is already specified
    if "://" in url_str:
        scheme_candidate = url_str.split("://", 1)[0].lower()
        if scheme_candidate not in ("http", "https"):
            return False, None, f"Unsupported scheme: {scheme_candidate}"
    else:
        # Support URLs omitting protocol
        url_str = "https://" + url_str

    try:
        parsed = urllib.parse.urlsplit(url_str)
    except Exception as e:
        return False, None, f"Malformed URL: {e}"

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return False, None, f"Unsupported scheme: {scheme}"

    hostname = parsed.hostname
    if not hostname:
        return False, None, "Missing hostname"

    # Reject localhost or common internal names
    hostname_lower = hostname.lower()
    if (
        hostname_lower == "localhost"
        or hostname_lower.endswith(".local")
        or hostname_lower.endswith(".internal")
        or hostname_lower.endswith(".lan")
    ):
        return False, None, "Access to local or internal domain is blocked"

    # Check for direct IP in hostname
    try:
        ip = ipaddress.ip_address(hostname)
        if not is_safe_ip(str(ip)):
            return False, None, "Access to private or local IP is blocked (SSRF Protection)"
    except ValueError:
        # Not a direct IP, hostname needs DNS resolution check
        try:
            addr_info = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
            for item in addr_info:
                resolved_ip = item[4][0]
                if not is_safe_ip(resolved_ip):
                    return False, None, "Resolved to internal/private IP (SSRF Protection)"
        except socket.gaierror:
            # Let HTTP request handle DNS resolution failure naturally during fetch
            pass
        except Exception as e:
            return False, None, f"Host validation error: {e}"

    # Build clean normalized URL without fragment
    clean_url = urllib.parse.urlunsplit((scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))
    return True, clean_url, None

def clean_email(email: str) -> Optional[str]:
    """Cleans and validates an extracted email string."""
    if not email:
        return None
    email = email.strip().lower()
    
    # Strip any trailing punctation like . , ; : ) ]
    email = re.sub(r"[.,;:!?)\]]+$", "", email)
    email = re.sub(r"^[<(\[]+", "", email)
    
    if "@" not in email:
        return None
        
    parts = email.split("@")
    if len(parts) != 2:
        return None
        
    local, domain = parts
    if not local or not domain:
        return None
        
    if len(local) > 64 or len(domain) > 255:
        return None
        
    # Check for asset extensions
    for ext in INVALID_EXTENSIONS:
        if domain.endswith(ext):
            return None
            
    # Check for placeholder domains
    if domain in PLACEHOLDER_DOMAINS:
        return None

    # TLD validation (must have at least one dot, and TLD at least 2 chars)
    domain_parts = domain.split(".")
    if len(domain_parts) < 2:
        return None
    tld = domain_parts[-1]
    if not tld.isalpha() or len(tld) < 2 or len(tld) > 24:
        return None

    # Check for invalid characters
    if not re.match(r"^[a-zA-Z0-9_.+-]+$", local):
        return None
    if not re.match(r"^[a-zA-Z0-9.-]+$", domain):
        return None

    return email

def extract_emails_from_html(html_text: str, current_page_url: str) -> List[Tuple[str, str, int]]:
    """
    Extracts emails from HTML, returning a list of tuples: (email, source_url, base_score)
    """
    results: List[Tuple[str, str, int]] = []
    seen: Set[str] = set()

    try:
        soup = BeautifulSoup(html_text, "html.parser")
    except Exception:
        # Fallback to direct regex on raw text if parser fails
        raw_matches = EMAIL_REGEX.findall(html_text)
        for m in raw_matches:
            c = clean_email(m)
            if c and c not in seen:
                seen.add(c)
                results.append((c, current_page_url, 30))
        return results

    # 1. Inspect mailto: links (highest confidence)
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            email_part = href[7:].split("?")[0].strip()
            # Handle multiple mailto recipients if comma separated
            for em in email_part.split(","):
                cleaned = clean_email(em)
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    results.append((cleaned, current_page_url, 50))

    # 2. Inspect meta tags (e.g. meta name="contact", property="og:email")
    for meta in soup.find_all("meta"):
        content = meta.get("content", "")
        if "@" in content:
            matches = EMAIL_REGEX.findall(content)
            for m in matches:
                c = clean_email(m)
                if c and c not in seen:
                    seen.add(c)
                    results.append((c, current_page_url, 45))

    # 3. Clean script/style tags before parsing body text
    for tag in soup(["script", "style", "noscript", "svg", "canvas", "iframe"]):
        tag.decompose()

    body_text = soup.get_text(separator=" ")
    matches = EMAIL_REGEX.findall(body_text)
    for m in matches:
        c = clean_email(m)
        if c and c not in seen:
            seen.add(c)
            results.append((c, current_page_url, 30))

    return results

def rank_emails(
    candidates: List[Tuple[str, str, int]],
    website_domain: str
) -> Tuple[Optional[str], List[str], Optional[str]]:
    """
    Ranks extracted candidate emails and selects the primary business contact email.
    Returns: (primary_email, other_emails, source_url)
    """
    if not candidates:
        return None, [], None

    scored_emails: Dict[str, Tuple[int, str]] = {}
    base_domain = website_domain.lower().replace("www.", "")

    for email, src, base_score in candidates:
        score = base_score
        local_part, domain_part = email.split("@", 1)
        local_lower = local_part.lower()
        domain_lower = domain_part.lower().replace("www.", "")

        # Check disqualified prefixes
        if local_lower in DISQUALIFIED_PREFIXES:
            score -= 100

        # Check preferred general business prefixes
        if local_lower in PREFERRED_PREFIXES:
            score += PREFERRED_PREFIXES[local_lower]
        elif any(local_lower.startswith(p) for p in ("contact", "info", "hello", "sales", "office")):
            score += 60

        # Bonus if email domain matches website domain
        if domain_lower == base_domain or domain_lower.endswith("." + base_domain):
            score += 35

        # Bonus if source URL is a contact or about page
        src_lower = src.lower()
        if any(kw in src_lower for kw in CONTACT_KEYWORDS):
            score += 25
        elif any(kw in src_lower for kw in ABOUT_KEYWORDS):
            score += 15

        # Keep highest score for this email
        if email not in scored_emails or score > scored_emails[email][0]:
            scored_emails[email] = (score, src)

    # Sort descending by score
    sorted_candidates = sorted(
        scored_emails.items(),
        key=lambda item: item[1][0],
        reverse=True
    )

    valid_candidates = [
        (email, info[1], info[0])
        for email, info in sorted_candidates
        if info[0] > 0
    ]

    if not valid_candidates:
        return None, [], None

    primary_email, primary_source, _ = valid_candidates[0]
    other_emails = [email for email, _, _ in valid_candidates[1:]]

    return primary_email, other_emails, primary_source

def find_internal_links(html_text: str, base_url: str) -> List[str]:
    """
    Identifies relevant internal pages like Contact, About, Support.
    """
    try:
        soup = BeautifulSoup(html_text, "html.parser")
    except Exception:
        return []

    base_parsed = urllib.parse.urlsplit(base_url)
    base_netloc = base_parsed.netloc.lower().replace("www.", "")

    contact_links: List[str] = []
    about_links: List[str] = []
    other_links: List[str] = []
    seen: Set[str] = {base_url}

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:") or href.startswith("tel:"):
            continue

        resolved = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlsplit(resolved)

        if parsed.scheme not in ("http", "https"):
            continue

        target_netloc = parsed.netloc.lower().replace("www.", "")
        # Only crawl same domain
        if target_netloc != base_netloc:
            continue

        # Skip asset files
        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in INVALID_EXTENSIONS):
            continue

        clean_link = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))
        if clean_link in seen:
            continue
        seen.add(clean_link)

        text_lower = (a.get_text() or "").lower()
        combined = f"{path_lower} {text_lower}"

        if any(kw in combined for kw in CONTACT_KEYWORDS):
            contact_links.append(clean_link)
        elif any(kw in combined for kw in ABOUT_KEYWORDS):
            about_links.append(clean_link)
        elif any(kw in combined for kw in SUPPORT_KEYWORDS):
            other_links.append(clean_link)

    # Prioritize Contact first, then About, then Support
    prioritized = contact_links + about_links + other_links
    return prioritized[:settings.MAX_INTERNAL_PAGES_TO_SCAN]

class WebsiteScanner:
    """Scans websites for business contact emails with SSRF safety and rate limits."""

    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._external_client = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._external_client:
            return self._external_client
        return httpx.AsyncClient(
            follow_redirects=True,
            timeout=settings.REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": settings.USER_AGENT},
            verify=False  # Allow sites with expired or slightly mismatched certs to be scanned
        )

    async def fetch_page(self, client: httpx.AsyncClient, url: str) -> Tuple[Optional[str], Optional[int], Optional[str]]:
        """
        Fetches an individual page.
        Returns: (html_content, status_code, error_message)
        """
        is_safe, norm_url, err = validate_and_resolve_url(url)
        if not is_safe:
            return None, None, f"Blocked: {err}"

        try:
            response = await client.get(norm_url)
            # Check for blocking
            if response.status_code in (403, 429):
                return None, response.status_code, "Access blocked (HTTP 403/429)"
            
            # Check for Cloudflare challenge in HTML
            text = response.text
            if "cf-browser-verification" in text or "Attention Required! | Cloudflare" in text or "Just a moment..." in text:
                return None, 403, "Protected by Cloudflare challenge"

            return text, response.status_code, None
        except httpx.TimeoutException:
            return None, None, "Connection timed out"
        except (httpx.ConnectError, socket.gaierror) as e:
            return None, None, f"Connection failed: {e}"
        except httpx.HTTPError as e:
            return None, None, f"HTTP error: {e}"
        except Exception as e:
            return None, None, f"Fetch error: {e}"

    async def scan_website(
        self,
        row_index: int,
        raw_url: str,
        company_name: Optional[str] = None
    ) -> WebsiteResult:
        """
        Full scan pipeline for a single website row.
        """
        if not raw_url or not str(raw_url).strip():
            return WebsiteResult(
                row_index=row_index,
                company_name=company_name,
                original_url=raw_url or "",
                status=ScanStatus.INVALID_URL,
                error_message="Empty URL"
            )

        is_safe, normalized_url, error_msg = validate_and_resolve_url(raw_url)
        if not is_safe:
            status = ScanStatus.BLOCKED if "SSRF" in (error_msg or "") or "blocked" in (error_msg or "") else ScanStatus.INVALID_URL
            return WebsiteResult(
                row_index=row_index,
                company_name=company_name,
                original_url=raw_url,
                status=status,
                error_message=error_msg
            )

        domain = urllib.parse.urlsplit(normalized_url).netloc
        all_candidates: List[Tuple[str, str, int]] = []
        pages_scanned: List[str] = []

        should_close_client = False
        client = self._external_client
        if client is None:
            client = httpx.AsyncClient(
                follow_redirects=True,
                timeout=settings.REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": settings.USER_AGENT},
                verify=False
            )
            should_close_client = True

        try:
            # 1. Fetch homepage
            pages_scanned.append(normalized_url)
            html, status_code, err = await self.fetch_page(client, normalized_url)

            # If HTTPS fails due to connection error, retry once with HTTP
            if err and normalized_url.startswith("https://") and "Connection" in err:
                http_fallback = "http://" + normalized_url[8:]
                html_fb, code_fb, err_fb = await self.fetch_page(client, http_fallback)
                if html_fb:
                    html, status_code, err = html_fb, code_fb, None
                    normalized_url = http_fallback

            if err:
                status = ScanStatus.BLOCKED if status_code in (403, 429) or "blocked" in err.lower() else ScanStatus.CONNECTION_FAILED
                return WebsiteResult(
                    row_index=row_index,
                    company_name=company_name,
                    original_url=raw_url,
                    normalized_url=normalized_url,
                    status=status,
                    error_message=err,
                    pages_scanned=pages_scanned
                )

            if not html:
                return WebsiteResult(
                    row_index=row_index,
                    company_name=company_name,
                    original_url=raw_url,
                    normalized_url=normalized_url,
                    status=ScanStatus.NOT_FOUND,
                    error_message="Empty response body",
                    pages_scanned=pages_scanned
                )

            # Extract from homepage
            homepage_candidates = extract_emails_from_html(html, normalized_url)
            all_candidates.extend(homepage_candidates)

            # 2. Discover and scan relevant internal pages (Contact, About)
            internal_links = find_internal_links(html, normalized_url)
            for link in internal_links:
                pages_scanned.append(link)
                sub_html, _, _ = await self.fetch_page(client, link)
                if sub_html:
                    sub_candidates = extract_emails_from_html(sub_html, link)
                    all_candidates.extend(sub_candidates)

            # 3. Rank and pick primary email
            primary_email, other_emails, source_url = rank_emails(all_candidates, domain)

            if primary_email:
                return WebsiteResult(
                    row_index=row_index,
                    company_name=company_name,
                    original_url=raw_url,
                    normalized_url=normalized_url,
                    status=ScanStatus.FOUND,
                    primary_email=primary_email,
                    other_emails=other_emails,
                    source_url=source_url,
                    pages_scanned=pages_scanned
                )
            else:
                return WebsiteResult(
                    row_index=row_index,
                    company_name=company_name,
                    original_url=raw_url,
                    normalized_url=normalized_url,
                    status=ScanStatus.NOT_FOUND,
                    pages_scanned=pages_scanned
                )

        except Exception as e:
            return WebsiteResult(
                row_index=row_index,
                company_name=company_name,
                original_url=raw_url,
                normalized_url=normalized_url,
                status=ScanStatus.CONNECTION_FAILED,
                error_message=str(e),
                pages_scanned=pages_scanned
            )
        finally:
            if should_close_client:
                await client.aclose()
