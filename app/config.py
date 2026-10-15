from pydantic import BaseModel
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR = DATA_DIR / "exports"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

class Settings:
    PROJECT_NAME: str = "WebMail Finder"
    VERSION: str = "1.0.0"
    API_PREFIX: str = "/api"
    
    # Limits for free tier and safety
    MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB limit
    MAX_ROWS_PER_FILE: int = 1000                # Safe limit for bulk processing
    REQUEST_TIMEOUT_SECONDS: float = 8.0          # Polite timeout per HTTP request
    MAX_INTERNAL_PAGES_TO_SCAN: int = 4          # Homepage + up to 3 relevant pages
    MAX_CONCURRENT_REQUESTS: int = 4             # Safe concurrency to prevent IP blocks
    CRAWL_DELAY_SECONDS: float = 0.2             # Delay between internal page requests
    
    # Job expiration
    JOB_RETENTION_HOURS: int = 24
    
    # User-Agent for ethical, polite scanning
    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 (WebMailFinder/1.0; Public Business Contact Discovery)"
    )

settings = Settings()
