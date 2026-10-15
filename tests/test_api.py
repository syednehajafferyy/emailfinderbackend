import io
import pytest
from starlette.testclient import TestClient
import openpyxl

from app.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "WebMail Finder" in data["app"]

def test_upload_excel_and_create_job():
    # Create in-memory Excel workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Company", "Website"])
    ws.append(["Example Corp", "https://example.com"])
    ws.append(["Empty Site", ""])

    file_bytes = io.BytesIO()
    wb.save(file_bytes)
    file_bytes.seek(0)

    # 1. Test POST /api/upload
    response = client.post(
        "/api/upload",
        files={"file": ("test_sheet.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "test_sheet.xlsx"
    assert data["total_rows"] == 2
    assert data["detected_url_column"] == "Website"
    file_id = data["file_id"]

    # 2. Test POST /api/jobs
    job_payload = {
        "file_id": file_id,
        "url_column": "Website",
        "company_column": "Company"
    }
    job_res = client.post("/api/jobs", json=job_payload)
    assert job_res.status_code == 200
    job_data = job_res.json()
    job_id = job_data["job_id"]
    assert job_data["total_rows"] == 2

    # 3. Test GET /api/jobs/{job_id}
    status_res = client.get(f"/api/jobs/{job_id}")
    assert status_res.status_code == 200
    assert status_res.json()["job_id"] == job_id

    # 4. Test GET /api/jobs/{job_id}/results
    results_res = client.get(f"/api/jobs/{job_id}/results")
    assert results_res.status_code == 200
    assert "job" in results_res.json()
    assert "results" in results_res.json()

    # 5. Test POST /api/jobs/{job_id}/pause and resume
    pause_res = client.post(f"/api/jobs/{job_id}/pause")
    assert pause_res.status_code == 200

    resume_res = client.post(f"/api/jobs/{job_id}/resume")
    assert resume_res.status_code == 200

    # 6. Test GET /api/jobs/{job_id}/download
    download_res = client.get(f"/api/jobs/{job_id}/download?format=xlsx")
    assert download_res.status_code == 200
    assert "spreadsheet" in download_res.headers.get("content-type", "")

    download_csv = client.get(f"/api/jobs/{job_id}/download?format=csv")
    assert download_csv.status_code == 200
    assert "csv" in download_csv.headers.get("content-type", "")
