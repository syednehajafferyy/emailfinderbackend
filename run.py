import uvicorn
import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    display_host = "localhost" if host == "0.0.0.0" else host
    print(f"Starting WebMail Finder Backend on http://{display_host}:{port} (Swagger docs: http://{display_host}:{port}/docs) ...")
    uvicorn.run("app.main:app", host=host, port=port, reload=True)
