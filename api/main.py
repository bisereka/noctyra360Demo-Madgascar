"""
NOCTYRA360™ — Production REST API v13
Serves V13 integrated frontend + handles all CDR processing server-side.
"""
import os, json, hashlib, shutil, sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse

from core.decoder            import CDRDecoder
from core.efr_engine         import run_efr, TAX_MATRICES
from core.anomaly_detector   import AnomalyDetector
from reports.report_generator import ReportGenerator

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent.parent
UPLOAD_DIR   = BASE_DIR / "uploads"
REPORTS_DIR  = BASE_DIR / "reports_out"
REGISTRY     = BASE_DIR / "config" / "schema_registry.json"
FRONTEND     = BASE_DIR / "frontend" / "index.html"

for d in [UPLOAD_DIR, REPORTS_DIR, BASE_DIR / "config"]:
    d.mkdir(parents=True, exist_ok=True)

# ── In-memory jobs ────────────────────────────────────────────────────────────
JOBS: dict = {}

def make_job_id(op, period):
    ts = datetime.utcnow().isoformat()
    return hashlib.md5(f"{op}{period}{ts}".encode()).hexdigest()[:12]

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="NOCTYRA360™", version="13.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# ── Frontend (V13 + Production Bridge) ───────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    if FRONTEND.exists():
        return HTMLResponse(content=FRONTEND.read_text(
            encoding="utf-8", errors="replace"))
    return HTMLResponse("<h1>NOCTYRA360™</h1><p>Place frontend/index.html</p>",
                        status_code=404)

# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "operational", "version": "13.0.0",
            "platform": "NOCTYRA360™ Production",
            "timestamp": datetime.utcnow().isoformat()}

# ── Countries ─────────────────────────────────────────────────────────────────
@app.get("/api/countries")
async def list_countries():
    return {"countries": [
        {"name": c, "currency": TAX_MATRICES[c]["currency"],
         "fx_usd": TAX_MATRICES[c]["fx_to_usd"]}
        for c in TAX_MATRICES
    ]}

# ── Operators (schema registry) ───────────────────────────────────────────────
@app.get("/api/operators")
async def list_operators():
    if not REGISTRY.exists():
        return {"operators": []}
    reg = json.loads(REGISTRY.read_text())
    return {"operators": [
        {"key": k, "operator": v.get("operator"),
         "vendor": v.get("vendor"), "is_momo": v.get("is_momo", False),
         "saved_at": v.get("saved_at")}
        for k, v in reg.items()
    ]}

# ── Upload + Process CDR ──────────────────────────────────────────────────────
@app.post("/api/process")
async def process_cdr(
    background_tasks: BackgroundTasks,
    file:        UploadFile = File(...),
    operator:    str        = Form(...),
    country:     str        = Form("Madagascar"),
    period:      str        = Form("Unknown"),
    declaration: str        = Form("{}"),
):
    safe  = file.filename.replace(" ","_").replace("/","_")
    dest  = UPLOAD_DIR / f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        decl = json.loads(declaration) if declaration != "{}" else None
    except Exception:
        decl = None

    job_id = make_job_id(operator, period)
    JOBS[job_id] = {
        "job_id": job_id, "status": "queued",
        "operator": operator, "country": country,
        "period": period, "file": str(dest),
        "file_size_mb": round(dest.stat().st_size / 1_048_576, 2),
        "created_at": datetime.utcnow().isoformat(),
        "progress": 0, "result": None, "reports": None,
    }
    background_tasks.add_task(
        _process_job, job_id, dest, operator, country, period, decl)

    return {"job_id": job_id, "status": "queued",
            "poll_url": f"/api/job/{job_id}"}

async def _process_job(job_id, filepath, operator, country, period, declaration):
    job = JOBS[job_id]
    try:
        job["status"] = "processing"
        job["started_at"] = datetime.utcnow().isoformat()

        def progress(chunk, rows):
            job["progress"] = min(60, chunk * 5)
            job["rows_processed"] = rows

        # Decode
        decoder = CDRDecoder(schema_registry_path=str(REGISTRY))
        stats   = decoder.process_file(str(filepath), operator, progress)
        if "error" in stats:
            raise ValueError(stats["error"])
        job["progress"] = 65

        # EFR
        finding = run_efr(stats, country, declaration, period)
        job["progress"] = 80

        # Anomalies (sample)
        anomalies = None
        try:
            import pandas as pd
            sample = pd.read_csv(
                str(filepath), sep=decoder.detected_delimiter,
                encoding=decoder.detected_encoding,
                nrows=500_000, on_bad_lines="skip",
                encoding_errors="replace", low_memory=False)
            norm = decoder.normalize_chunk(sample)
            anomalies = AnomalyDetector().run_all(norm, decoder.is_momo)
        except Exception as e:
            anomalies = {"error": str(e),
                         "summary": {"total_anomalies": 0, "high_risk_count": 0}}
        job["progress"] = 90

        # Reports
        gen   = ReportGenerator(output_dir=str(REPORTS_DIR))
        paths = gen.generate_all(finding, anomalies)
        job["progress"] = 100

        job["status"]     = "complete"
        job["result"]     = finding
        job["anomalies"]  = anomalies
        job["reports"]    = {k: Path(v).name for k, v in paths.items() if v}
        job["completed_at"] = datetime.utcnow().isoformat()

        filepath.unlink(missing_ok=True)

    except Exception as e:
        job["status"] = "error"
        job["error"]  = str(e)
        job["completed_at"] = datetime.utcnow().isoformat()

# ── Job status ────────────────────────────────────────────────────────────────
@app.get("/api/job/{job_id}")
async def get_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "Job not found")
    j = dict(JOBS[job_id])
    if j["status"] != "complete":
        j.pop("result", None)
        j.pop("anomalies", None)
    return j

# ── Full result ───────────────────────────────────────────────────────────────
@app.get("/api/result/{job_id}")
async def get_result(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "Job not found")
    j = JOBS[job_id]
    if j["status"] != "complete":
        raise HTTPException(400, f"Job status: {j['status']}")
    return {"finding": j["result"], "anomalies": j.get("anomalies"),
            "reports": j.get("reports")}

# ── Download report ───────────────────────────────────────────────────────────
@app.get("/api/report/{filename}")
async def download_report(filename: str):
    path = REPORTS_DIR / filename
    if not path.exists():
        raise HTTPException(404, "Report not found")
    return FileResponse(str(path), filename=filename,
                        media_type="application/octet-stream")

# ── Demo scenario (instant — no file upload needed) ───────────────────────────
@app.post("/api/demo/scenario")
async def demo_scenario(
    scenario: str = Form("B"),
    country:  str = Form("Madagascar"),
    operator: str = Form("Orange MDG"),
    period:   str = Form("March 2026"),
):
    matrix   = TAX_MATRICES.get(country, TAX_MATRICES["Madagascar"])
    fx       = matrix["fx_to_usd"]
    eff_rate = matrix.get("effective_rate", 0.30)

    base_rev = 60_400_000_000  # MGA 60.4B / month baseline

    if scenario == "A":
        cert_rev  = base_rev
        decl_rev  = base_rev
        decl_tax  = base_rev * eff_rate
    else:
        cert_rev  = base_rev
        decl_rev  = base_rev * 0.70   # 30% hidden
        decl_tax  = decl_rev * eff_rate

    stats = {
        "operator":           operator,
        "total_revenue":      cert_rev,
        "voice_revenue":      cert_rev * 0.45,
        "data_revenue":       cert_rev * 0.30,
        "sms_revenue":        cert_rev * 0.10,
        "idd_revenue":        cert_rev * 0.15,
        "unique_subscribers": 4_200_000,
        "total_rows":         25_000_000,
        "bad_rows":           12_400,
        "is_momo":            False,
        "vendor":             "Huawei (demo)",
        "invalid_imei_count": 847 if scenario == "B" else 12,
        "input_hash":         hashlib.sha256(
            f"demo_{scenario}_{operator}_{period}".encode()).hexdigest(),
        "processed_at":       datetime.utcnow().isoformat(),
    }
    declaration = {"total_revenue": decl_rev, "total_tax": decl_tax}
    finding     = run_efr(stats, country, declaration, period)

    simbox = []
    if scenario == "B":
        finding["demo_simbox"] = [
            {"msisdn":"261320001234","score":94,
             "idd_call_count":2847,"avg_duration_sec":18.3},
            {"msisdn":"261320005678","score":87,
             "idd_call_count":1923,"avg_duration_sec":22.1},
            {"msisdn":"261320009012","score":81,
             "idd_call_count":1456,"avg_duration_sec":31.7},
        ]

    gap    = finding.get("gap", {})
    status = finding.get("status", "")
    msg    = ("✅ EFR = 0 — COMPLIANT" if scenario == "A"
              else f"🔴 CRITICAL GAP — USD {gap.get('tax_gap_usd',0):,.0f}/month missing")

    return {"scenario": scenario, "finding": finding, "message": msg}

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, workers=1)
