import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import settings, UPLOADS_DIR
from app.models import (
    UploadPreviewResponse, StartJobRequest, JobSummary, JobResultsResponse
)
from app.excel_handler import (
    analyze_spreadsheet, export_updated_excel, export_updated_csv
)
from app.job_manager import job_manager

router = APIRouter()

ALLOWED_EXTENSIONS = {".xlsx", ".xlsm", ".csv"}

@router.post("/upload", response_model=UploadPreviewResponse)
async def upload_spreadsheet(file: UploadFile = File(...)):
    """Accepts .xlsx or .csv file, validates it, and returns spreadsheet preview & column detection."""
    filename = file.filename or "upload.xlsx"
    ext = Path(filename).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Please upload an Excel (.xlsx) or CSV (.csv) file."
        )

    # Read content and enforce size limit
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE_BYTES:
        max_mb = settings.MAX_FILE_SIZE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds maximum size of {max_mb} MB. Please upload a smaller spreadsheet."
        )

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    file_id = uuid.uuid4().hex[:10]
    saved_filename = f"{file_id}_{filename}"
    saved_path = UPLOADS_DIR / saved_filename

    with open(saved_path, "wb") as f:
        f.write(content)

    try:
        preview = analyze_spreadsheet(file_id, filename, saved_path)
    except Exception as e:
        # Cleanup uploaded file if parsing fails
        if saved_path.exists():
            saved_path.unlink()
        raise HTTPException(status_code=400, detail=f"Failed to read spreadsheet: {e}")

    return preview

@router.post("/jobs", response_model=JobSummary)
async def create_and_start_job(payload: StartJobRequest):
    """Creates and starts a scanning job for the uploaded spreadsheet."""
    file_id = payload.file_id
    # Find the saved uploaded file
    matching_files = list(UPLOADS_DIR.glob(f"{file_id}_*"))
    if not matching_files:
        raise HTTPException(status_code=404, detail="Uploaded file not found or has expired. Please re-upload.")

    file_path = matching_files[0]
    original_filename = file_path.name[len(file_id) + 1:]
    job_id = uuid.uuid4().hex[:12]

    job = job_manager.create_job(
        job_id=job_id,
        file_id=file_id,
        original_filename=original_filename,
        file_path=file_path,
        url_col=payload.url_column,
        company_col=payload.company_column
    )

    await job_manager.start_job(job_id)
    return job.summary

@router.get("/jobs/{job_id}", response_model=JobSummary)
async def get_job_status(job_id: str):
    """Fetches real-time status and progress counts for a job."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or has expired.")
    return job.summary

@router.get("/jobs/{job_id}/results", response_model=JobResultsResponse)
async def get_job_results(
    job_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=200),
    filter_status: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
):
    """Returns paginated, searchable, and filtered scan results."""
    try:
        return job_manager.get_results_view(
            job_id=job_id,
            page=page,
            per_page=per_page,
            filter_status=filter_status,
            search=search
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/jobs/{job_id}/pause", response_model=JobSummary)
async def pause_scan_job(job_id: str):
    """Pauses an in-progress scan."""
    try:
        return await job_manager.pause_job(job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/jobs/{job_id}/resume", response_model=JobSummary)
async def resume_scan_job(job_id: str):
    """Resumes a paused scan."""
    try:
        return await job_manager.resume_job(job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/jobs/{job_id}/cancel", response_model=JobSummary)
async def cancel_scan_job(job_id: str):
    """Cancels a scan job."""
    try:
        return await job_manager.cancel_job(job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/jobs/{job_id}/retry", response_model=JobSummary)
async def retry_failed_job_items(job_id: str):
    """Retries websites that failed connection or were blocked."""
    try:
        return await job_manager.retry_failed(job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/jobs/{job_id}/download")
async def download_updated_file(
    job_id: str,
    format: str = Query("xlsx", pattern="^(xlsx|csv)$")
):
    """Generates and serves the updated spreadsheet with discovered emails inserted beside the website column."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or has expired.")

    # Allow downloading partial results even if still in progress or paused/completed
    if format == "csv":
        export_path = export_updated_csv(
            original_file_path=job.file_path,
            original_filename=job.original_filename,
            job_id=job_id,
            url_column_name=job.url_col,
            results_by_row=job.results_by_row
        )
        media_type = "text/csv"
        filename = f"webmail_emails_{job_id}.csv"
    else:
        export_path = export_updated_excel(
            original_file_path=job.file_path,
            original_filename=job.original_filename,
            job_id=job_id,
            url_column_name=job.url_col,
            results_by_row=job.results_by_row
        )
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"webmail_emails_{job_id}.xlsx"

    return FileResponse(
        path=export_path,
        filename=filename,
        media_type=media_type
    )
