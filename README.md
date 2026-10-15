# WebMail Finder Backend

Asynchronous backend engine for **WebMail Finder** — an automated tool that extracts publicly listed business contact emails directly from company websites uploaded in Excel (.xlsx, .xls) and CSV spreadsheets.

## 🚀 Key Features

- **Asynchronous Web Crawler:** High-performance, concurrent website discovery using `httpx` and `asyncio`.
- **Intelligent Page Navigation:** Automatically discovers and scrapes Contact Us, About, Team, and Support pages.
- **Smart Email Ranking & Filtering:** Filters out spam traps, static image assets, and placeholders; prioritizes high-confidence business inboxes (`info@`, `contact@`, `hello@`, `sales@`, `support@`).
- **SSRF Protection:** Validates IP addresses to prevent scanning internal addresses, local network infrastructure, or cloud metadata endpoints.
- **Spreadsheet Preservation:** Reads, maps, and enriches Excel spreadsheets using `openpyxl`, cleanly inserting discovered emails and source URLs next to the website column while preserving existing formulas, styles, and data.
- **Task Management:** Real-time job lifecycle control (pause, resume, cancel, retry failed, live progress reporting).

## 🛠️ Tech Stack

- **Framework:** [FastAPI](https://fastapi.tiangolo.com/)
- **Server:** [Uvicorn](https://www.uvicorn.org/)
- **HTTP Client:** [HTTPX](https://www.python-httpx.org/)
- **HTML Parsing:** [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) + [lxml](https://lxml.de/)
- **Spreadsheet Engine:** [openpyxl](https://openpyxl.readthedocs.io/)
- **Testing:** [pytest](https://docs.pytest.org/) + `pytest-asyncio`

---

## 📦 Installation & Setup

### 1. Clone the repository
```bash
git clone https://github.com/syednehajafferyy/emailfinderbackend.git
cd emailfinderbackend
```

### 2. Create and activate a virtual environment
```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the backend server
```bash
python run.py
```

The API will be live at:
- **Service:** `http://localhost:8000`
- **Swagger Documentation:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

---

## 🧪 Running Tests

Execute the automated test suite with pytest:
```bash
pytest
```

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Service health check |
| `POST` | `/api/upload` | Upload spreadsheet (.xlsx, .csv) and preview columns |
| `POST` | `/api/jobs/start` | Start email scanning job |
| `GET` | `/api/jobs/{job_id}/status` | Get progress, found counts, and job status |
| `GET` | `/api/jobs/{job_id}/results` | Paginated and filtered results |
| `POST` | `/api/jobs/{job_id}/pause` | Pause scanning job |
| `POST` | `/api/jobs/{job_id}/resume` | Resume paused job |
| `POST` | `/api/jobs/{job_id}/cancel` | Cancel scanning job |
| `POST` | `/api/jobs/{job_id}/retry` | Retry failed website scans |
| `GET` | `/api/jobs/{job_id}/download` | Download updated spreadsheet with discovered emails |
