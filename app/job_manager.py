import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
import httpx

from app.config import settings, DATA_DIR, UPLOADS_DIR
from app.models import (
    JobStatus, JobSummary, WebsiteResult, ScanStatus, JobResultsResponse
)
from app.scanner import WebsiteScanner, validate_and_resolve_url
from app.excel_handler import (
    parse_uploaded_file, export_updated_excel, export_updated_csv
)

class Job:
    def __init__(
        self,
        job_id: str,
        file_id: str,
        original_filename: str,
        file_path: Path,
        url_col: str,
        company_col: Optional[str] = None
    ):
        self.job_id = job_id
        self.file_id = file_id
        self.original_filename = original_filename
        self.file_path = file_path
        self.url_col = url_col
        self.company_col = company_col

        self.summary = JobSummary(
            job_id=job_id,
            filename=original_filename,
            total_rows=0,
            valid_urls=0,
            empty_urls=0,
            invalid_urls=0,
            duplicate_urls=0,
            processed_count=0,
            remaining_count=0,
            emails_found_count=0,
            no_email_count=0,
            failed_count=0,
            status=JobStatus.PENDING,
            created_at=datetime.utcnow().isoformat(),
            url_column_name=url_col,
            company_column_name=company_col
        )

        self.results_by_row: Dict[int, WebsiteResult] = {}
        self.rows_data: List[Dict[str, str]] = []
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Not paused initially
        self._cancel_flag = False
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary.model_dump(),
            "results": [r.model_dump() for r in self.results_by_row.values()],
            "file_id": self.file_id,
            "original_filename": self.original_filename,
            "url_col": self.url_col,
            "company_col": self.company_col,
        }

    def save_snapshot(self):
        """Saves interim progress to disk so jobs survive mild restarts."""
        try:
            snapshot_file = DATA_DIR / f"job_{self.job_id}.json"
            with open(snapshot_file, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
        except Exception:
            pass

class JobManager:
    """Manages scan jobs, concurrency, pause/resume/cancel/retry operations."""

    def __init__(self):
        self.jobs: Dict[str, Job] = {}
        self._global_lock = asyncio.Lock()

    def create_job(
        self,
        job_id: str,
        file_id: str,
        original_filename: str,
        file_path: Path,
        url_col: str,
        company_col: Optional[str] = None
    ) -> Job:
        job = Job(
            job_id=job_id,
            file_id=file_id,
            original_filename=original_filename,
            file_path=file_path,
            url_col=url_col,
            company_col=company_col
        )
        self.jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        # First check in-memory
        if job_id in self.jobs:
            return self.jobs[job_id]
        # Check disk snapshot
        snapshot_file = DATA_DIR / f"job_{job_id}.json"
        if snapshot_file.exists():
            try:
                with open(snapshot_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                file_path = UPLOADS_DIR / f"{data['file_id']}_{data['original_filename']}"
                job = Job(
                    job_id=data["summary"]["job_id"],
                    file_id=data["file_id"],
                    original_filename=data["original_filename"],
                    file_path=file_path,
                    url_col=data["url_col"],
                    company_col=data.get("company_col")
                )
                job.summary = JobSummary(**data["summary"])
                for r in data.get("results", []):
                    res = WebsiteResult(**r)
                    job.results_by_row[res.row_index] = res
                self.jobs[job_id] = job
                return job
            except Exception:
                return None
        return None

    async def start_job(self, job_id: str) -> Job:
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        headers, rows_as_dicts, _ = parse_uploaded_file(job.file_path, job.original_filename)
        job.rows_data = rows_as_dicts

        # Compute initial metrics
        total = len(rows_as_dicts)
        valid = 0
        empty = 0
        invalid = 0
        seen_urls: Set[str] = set()
        duplicates = 0

        for row in rows_as_dicts:
            val = row.get(job.url_col, "").strip()
            if not val:
                empty += 1
                continue
            safe, norm, _ = validate_and_resolve_url(val)
            if not safe:
                invalid += 1
            else:
                if norm in seen_urls:
                    duplicates += 1
                else:
                    seen_urls.add(norm)
                valid += 1

        job.summary.total_rows = total
        job.summary.valid_urls = valid
        job.summary.empty_urls = empty
        job.summary.invalid_urls = invalid
        job.summary.duplicate_urls = duplicates
        job.summary.remaining_count = total
        job.summary.status = JobStatus.RUNNING

        # Launch scanning task
        job._task = asyncio.create_task(self._run_scan_pipeline(job))
        return job

    async def _run_scan_pipeline(self, job: Job, only_row_indices: Optional[List[int]] = None):
        """Worker loop with polite concurrency and pause/cancel handling."""
        semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_REQUESTS)
        client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=settings.REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": settings.USER_AGENT},
            verify=False
        )
        scanner = WebsiteScanner(client=client)

        try:
            target_indices = (
                only_row_indices
                if only_row_indices is not None
                else list(range(len(job.rows_data)))
            )

            async def process_row(idx: int):
                # Respect pause event
                await job._pause_event.wait()
                if job._cancel_flag:
                    return

                row = job.rows_data[idx]
                raw_url = row.get(job.url_col, "").strip()
                company_name = row.get(job.company_col, "").strip() if job.company_col else None

                job.summary.current_website = raw_url or f"Row {idx+1}"

                # Handle empty URL without network call
                if not raw_url:
                    res = WebsiteResult(
                        row_index=idx,
                        company_name=company_name,
                        original_url="",
                        status=ScanStatus.SKIPPED,
                        error_message="Empty URL cell in spreadsheet"
                    )
                else:
                    async with semaphore:
                        if job._cancel_flag:
                            return
                        res = await scanner.scan_website(
                            row_index=idx,
                            raw_url=raw_url,
                            company_name=company_name
                        )
                        # Polite small delay between website requests
                        await asyncio.sleep(settings.CRAWL_DELAY_SECONDS)

                async with job._lock:
                    job.results_by_row[idx] = res
                    # Recalculate stats accurately
                    self._update_counts(job)
                    job.save_snapshot()

            # Schedule all row tasks
            tasks = [asyncio.create_task(process_row(i)) for i in target_indices]
            await asyncio.gather(*tasks, return_exceptions=True)

            if job._cancel_flag:
                job.summary.status = JobStatus.CANCELLED
            else:
                job.summary.status = JobStatus.COMPLETED
                job.summary.completed_at = datetime.utcnow().isoformat()
                job.summary.current_website = None

        except asyncio.CancelledError:
            job.summary.status = JobStatus.CANCELLED
        except Exception as e:
            job.summary.status = JobStatus.FAILED
            job.summary.error_message = f"Job processing error: {e}"
        finally:
            await client.aclose()
            job.save_snapshot()

    def _update_counts(self, job: Job):
        processed = len(job.results_by_row)
        job.summary.processed_count = processed
        job.summary.remaining_count = max(0, job.summary.total_rows - processed)

        found = 0
        no_email = 0
        failed = 0

        for r in job.results_by_row.values():
            if r.status == ScanStatus.FOUND:
                found += 1
            elif r.status in (ScanStatus.NOT_FOUND, ScanStatus.SKIPPED):
                no_email += 1
            elif r.status in (ScanStatus.CONNECTION_FAILED, ScanStatus.BLOCKED, ScanStatus.INVALID_URL):
                failed += 1

        job.summary.emails_found_count = found
        job.summary.no_email_count = no_email
        job.summary.failed_count = failed

    async def pause_job(self, job_id: str) -> JobSummary:
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        if job.summary.status == JobStatus.RUNNING:
            job._pause_event.clear()
            job.summary.status = JobStatus.PAUSED
            job.save_snapshot()
        return job.summary

    async def resume_job(self, job_id: str) -> JobSummary:
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        if job.summary.status == JobStatus.PAUSED:
            job.summary.status = JobStatus.RUNNING
            job._pause_event.set()
            job.save_snapshot()
        return job.summary

    async def cancel_job(self, job_id: str) -> JobSummary:
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        job._cancel_flag = True
        job._pause_event.set()  # Unblock if paused so tasks can exit
        if job._task and not job._task.done():
            job._task.cancel()
        job.summary.status = JobStatus.CANCELLED
        job.save_snapshot()
        return job.summary

    async def retry_failed(self, job_id: str) -> JobSummary:
        """Retries websites that had connection failures or were blocked."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        failed_indices = [
            idx for idx, res in job.results_by_row.items()
            if res.status in (ScanStatus.CONNECTION_FAILED, ScanStatus.BLOCKED)
        ]

        if not failed_indices:
            return job.summary

        # Reset those results and restart worker for them
        for idx in failed_indices:
            del job.results_by_row[idx]

        self._update_counts(job)
        job.summary.status = JobStatus.RUNNING
        job._cancel_flag = False
        job._pause_event.set()
        job._task = asyncio.create_task(self._run_scan_pipeline(job, only_row_indices=failed_indices))
        return job.summary

    def get_results_view(
        self,
        job_id: str,
        page: int = 1,
        per_page: int = 25,
        filter_status: Optional[str] = None,
        search: Optional[str] = None
    ) -> JobResultsResponse:
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Sort results by row index (preserves original order)
        all_results = sorted(job.results_by_row.values(), key=lambda r: r.row_index)

        # Apply search and filters
        filtered: List[WebsiteResult] = []
        for r in all_results:
            if filter_status and filter_status != "all":
                if filter_status.lower() == "found" and r.status != ScanStatus.FOUND:
                    continue
                elif filter_status.lower() == "not_found" and r.status != ScanStatus.NOT_FOUND:
                    continue
                elif filter_status.lower() == "connection_failed" and r.status != ScanStatus.CONNECTION_FAILED:
                    continue
                elif filter_status.lower() == "blocked" and r.status != ScanStatus.BLOCKED:
                    continue
                elif filter_status.lower() == "needs_review" and r.status != ScanStatus.NEEDS_REVIEW:
                    continue

            if search:
                term = search.lower().strip()
                matches_url = term in r.original_url.lower()
                matches_company = r.company_name and term in r.company_name.lower()
                matches_email = r.primary_email and term in r.primary_email.lower()
                if not (matches_url or matches_company or matches_email):
                    continue

            filtered.append(r)

        total_matching = len(filtered)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_items = filtered[start_idx:end_idx]

        return JobResultsResponse(
            job=job.summary,
            results=paginated_items,
            page=page,
            per_page=per_page,
            total=total_matching
        )

job_manager = JobManager()
