from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class ScanStatus(str, Enum):
    FOUND = "Found"
    NOT_FOUND = "Not found"
    CONNECTION_FAILED = "Connection failed"
    BLOCKED = "Blocked"
    NEEDS_REVIEW = "Needs review"
    SKIPPED = "Skipped"
    INVALID_URL = "Invalid URL"

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"

class WebsiteResult(BaseModel):
    row_index: int
    company_name: Optional[str] = None
    original_url: str
    normalized_url: Optional[str] = None
    status: ScanStatus = ScanStatus.NOT_FOUND
    primary_email: Optional[str] = None
    other_emails: List[str] = Field(default_factory=list)
    source_url: Optional[str] = None
    error_message: Optional[str] = None
    pages_scanned: List[str] = Field(default_factory=list)
    attempted_at: Optional[str] = None

class JobSummary(BaseModel):
    job_id: str
    filename: str
    total_rows: int
    valid_urls: int
    empty_urls: int
    invalid_urls: int
    duplicate_urls: int
    processed_count: int = 0
    remaining_count: int = 0
    emails_found_count: int = 0
    no_email_count: int = 0
    failed_count: int = 0
    status: JobStatus = JobStatus.PENDING
    created_at: str
    completed_at: Optional[str] = None
    url_column_name: str
    company_column_name: Optional[str] = None
    current_website: Optional[str] = None
    error_message: Optional[str] = None

class UploadPreviewResponse(BaseModel):
    file_id: str
    filename: str
    headers: List[str]
    preview_rows: List[Dict[str, Any]]
    detected_url_column: Optional[str] = None
    detected_company_column: Optional[str] = None
    total_rows: int
    valid_urls_count: int
    empty_urls_count: int
    invalid_urls_count: int
    duplicate_urls_count: int

class StartJobRequest(BaseModel):
    file_id: str
    url_column: str
    company_column: Optional[str] = None

class JobResultsResponse(BaseModel):
    job: JobSummary
    results: List[WebsiteResult]
    page: int
    per_page: int
    total: int
