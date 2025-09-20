import os
import shutil
import uuid
import time
from fastapi import FastAPI, File, UploadFile, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from services import file_handler
from mcp import executor

# Initialize FastAPI app
app = FastAPI(title="AI Testing Factory")

# Mount directories for templates and static files
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Create necessary directories if they don't exist
UPLOADS_DIR = "uploads"
RESULTS_DIR = "test_results"
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)
app.mount("/test_results", StaticFiles(directory=RESULTS_DIR), name="results")

# This will store our final report data in memory
REPORT_DB = {}

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serves the main upload page."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/run-tests", response_class=HTMLResponse)
async def handle_test_run(request: Request, test_file: UploadFile = File(...)):
    """
    Handles file upload, test generation, execution, and reporting.
    """
    file_path = os.path.join(UPLOADS_DIR, test_file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(test_file.file, buffer)

    try:
        test_cases = file_handler.parse_test_file(file_path)
    except Exception as e:
        return templates.TemplateResponse("index.html", {"request": request, "error": f"Failed to parse file: {e}"})

    from services.gemini_client import generate_initial_script
    
    run_id = str(uuid.uuid4())
    final_report = {
        "run_id": run_id,
        "test_cases": []
    }

    for i, test_case in enumerate(test_cases):
        test_case_id = str(test_case.get('TestCase Name/ID', f'TestCase_{i+1}'))
        if not test_case_id:
            print(f"⚠️ Skipping empty or invalid row: {test_case}")
            continue
            
        print(f"\n🚀 Starting process for Test Case: {test_case_id}")

        initial_script = generate_initial_script(test_case)
        
        if not initial_script or "# Gemini API Error" in initial_script:
             test_report = {
                "test_case_id": test_case_id,
                "status": "Fail",
                "retries": 0,
                "history": [{
                    "attempt": 1,
                    "script": "Failed to generate script from Gemini.",
                    "outcome": "Fail",
                    "error": initial_script
                }]
            }
        else:
            test_report = executor.execute_test_case(test_case_id, initial_script, RESULTS_DIR)
        
        final_report["test_cases"].append(test_report)

        print("Pausing for 2 seconds to cool down... ☕")
        time.sleep(2)

    REPORT_DB[run_id] = final_report
    return RedirectResponse(url=f"/report/{run_id}", status_code=303)


@app.get("/report/{run_id}", response_class=HTMLResponse)
async def view_report(request: Request, run_id: str):
    """Displays the final report for a specific test run."""
    report_data = REPORT_DB.get(run_id)
    if not report_data:
        return templates.TemplateResponse("index.html", {"request": request, "error": "Report not found!"})
    
    return templates.TemplateResponse("report.html", {"request": request, "report": report_data})