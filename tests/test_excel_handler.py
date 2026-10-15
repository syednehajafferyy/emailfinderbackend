import csv
import pytest
from pathlib import Path
import openpyxl

from app.excel_handler import (
    analyze_spreadsheet, export_updated_excel, export_updated_csv, parse_uploaded_file
)
from app.models import WebsiteResult, ScanStatus

def test_excel_parse_and_export(tmp_path: Path):
    # 1. Create a sample .xlsx file
    excel_path = tmp_path / "test_companies.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Companies"
    ws.append(["Company Name", "Website", "Industry"])
    ws.append(["Company Alpha", "https://alpha.com", "Tech"])
    ws.append(["Company Beta", "beta.org", "Finance"])
    ws.append(["Company Gamma", "", "Retail"])  # Empty URL
    ws.append(["Company Delta", "invalid-url", "Services"])  # Invalid
    wb.save(excel_path)
    wb.close()

    # 2. Analyze spreadsheet
    preview = analyze_spreadsheet("file123", "test_companies.xlsx", excel_path)
    assert preview.total_rows == 4
    assert preview.detected_url_column == "Website"
    assert preview.detected_company_column == "Company Name"
    assert preview.valid_urls_count >= 1
    assert preview.empty_urls_count == 1

    # 3. Export updated Excel with mocked scan results
    results_map = {
        0: WebsiteResult(
            row_index=0,
            company_name="Company Alpha",
            original_url="https://alpha.com",
            status=ScanStatus.FOUND,
            primary_email="info@alpha.com",
            source_url="https://alpha.com/contact",
            other_emails=["sales@alpha.com"]
        ),
        1: WebsiteResult(
            row_index=1,
            company_name="Company Beta",
            original_url="beta.org",
            status=ScanStatus.NOT_FOUND
        ),
        2: WebsiteResult(
            row_index=2,
            company_name="Company Gamma",
            original_url="",
            status=ScanStatus.SKIPPED
        ),
        3: WebsiteResult(
            row_index=3,
            company_name="Company Delta",
            original_url="invalid-url",
            status=ScanStatus.INVALID_URL
        )
    }

    out_xlsx = export_updated_excel(
        original_file_path=excel_path,
        original_filename="test_companies.xlsx",
        job_id="job123",
        url_column_name="Website",
        results_by_row=results_map
    )

    assert out_xlsx.exists()
    out_wb = openpyxl.load_workbook(out_xlsx)
    out_ws = out_wb.active

    # Check headers: Contact Email must be right after Website
    headers = [cell.value for cell in out_ws[1]]
    assert headers[0] == "Company Name"
    assert headers[1] == "Website"
    assert headers[2] == "Contact Email"
    assert headers[3] == "Source URL"
    assert headers[4] == "Status"
    assert headers[5] == "Other Emails"
    assert headers[6] == "Industry"  # Original subsequent column preserved!

    # Check row 1 data
    row1 = [cell.value for cell in out_ws[2]]
    assert row1[0] == "Company Alpha"
    assert row1[1] == "https://alpha.com"
    assert row1[2] == "info@alpha.com"
    assert row1[3] == "https://alpha.com/contact"
    assert row1[4] == "Found"
    assert row1[6] == "Tech"

    # Check row 3 (empty URL) preserved
    row3 = [cell.value for cell in out_ws[4]]
    assert row3[0] == "Company Gamma"
    assert row3[2] in ("", None)  # Left empty
    assert row3[6] == "Retail"

    out_wb.close()

def test_csv_parse_and_export(tmp_path: Path):
    csv_path = tmp_path / "test_companies.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Company", "Web Address"])
        writer.writerow(["Acme", "https://acme.org"])
        writer.writerow(["Apex", "https://apex.net"])

    preview = analyze_spreadsheet("csv123", "test_companies.csv", csv_path)
    assert preview.total_rows == 2
    assert preview.detected_url_column == "Web Address"

    results_map = {
        0: WebsiteResult(
            row_index=0,
            company_name="Acme",
            original_url="https://acme.org",
            status=ScanStatus.FOUND,
            primary_email="contact@acme.org",
            source_url="https://acme.org"
        ),
        1: WebsiteResult(
            row_index=1,
            company_name="Apex",
            original_url="https://apex.net",
            status=ScanStatus.NOT_FOUND
        )
    }

    out_csv = export_updated_csv(
        original_file_path=csv_path,
        original_filename="test_companies.csv",
        job_id="jobcsv",
        url_column_name="Web Address",
        results_by_row=results_map
    )

    assert out_csv.exists()
    with open(out_csv, "r", encoding="utf-8-sig") as f:
        reader = list(csv.reader(f))
        assert reader[0] == ["Company", "Web Address", "Contact Email", "Source URL", "Status", "Other Emails"]
        assert reader[1][0] == "Acme"
        assert reader[1][2] == "contact@acme.org"
        assert reader[1][4] == "Found"
