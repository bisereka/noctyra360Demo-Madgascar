"""
NOCTYRA360™ — SFTP Intake Watcher
Monitors the SFTP drop folder for new CDR files from operators.
When a file arrives → processing starts automatically.
No human intervention required.
"""

import os
import sys
import time
import json
import shutil
import hashlib
import logging
import requests
from pathlib import Path
from datetime import datetime
from threading import Thread

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [WATCHER] %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("noctyra_watcher")

# ── Configuration ──────────────────────────────────────────────────────────────
WATCH_DIR   = Path(os.environ.get("SFTP_WATCH_DIR",   "/home/noctyra/sftp_intake"))
DONE_DIR    = Path(os.environ.get("SFTP_DONE_DIR",    "/home/noctyra/sftp_done"))
ERROR_DIR   = Path(os.environ.get("SFTP_ERROR_DIR",   "/home/noctyra/sftp_error"))
API_URL     = os.environ.get("NOCTYRA_API_URL",        "http://localhost:8000")
POLL_SECS   = int(os.environ.get("WATCHER_POLL_SECS", "30"))

# ── Operator → Country mapping ─────────────────────────────────────────────────
# File naming convention: {OPERATOR}_{PERIOD}_{TYPE}.csv
# e.g.: orange_mdg_march2026_voice.csv
#       telma_march2026_momo.csv

OPERATOR_MAP = {
    "orange_mdg":  {"operator": "Orange MDG",  "country": "Madagascar"},
    "telma":       {"operator": "Telma",        "country": "Madagascar"},
    "airtel_mdg":  {"operator": "Airtel MDG",   "country": "Madagascar"},
    "blueline":    {"operator": "Blueline",     "country": "Madagascar"},
    "vodacom":     {"operator": "Vodacom",      "country": "Mozambique"},
    "movitel":     {"operator": "Movitel",      "country": "Mozambique"},
    "tmcel":       {"operator": "Tmcel",        "country": "Mozambique"},
    "airtel_mwi":  {"operator": "Airtel Malawi","country": "Malawi"},
    "tnm":         {"operator": "TNM",          "country": "Malawi"},
    "telecel_car": {"operator": "Telecel CAR",  "country": "CAR"},
}

# Supported file extensions
SUPPORTED_EXTENSIONS = {".csv", ".txt", ".tsv", ".gz", ".zip"}


def parse_filename(filename: str) -> dict:
    """
    Extract operator, period, type from filename.
    Convention: {operator_key}_{period}[_{type}].{ext}
    Example: orange_mdg_march2026_voice.csv
    """
    stem = Path(filename).stem.lower()
    parts = stem.split("_")

    # Try to match known operators
    operator_key = None
    operator_info = {}
    for key in sorted(OPERATOR_MAP.keys(), key=len, reverse=True):
        if stem.startswith(key):
            operator_key  = key
            operator_info = OPERATOR_MAP[key]
            break

    if not operator_key:
        # Try first two parts
        for i in range(min(3, len(parts))):
            attempt = "_".join(parts[:i+1])
            if attempt in OPERATOR_MAP:
                operator_key  = attempt
                operator_info = OPERATOR_MAP[attempt]
                break

    if not operator_key:
        return {
            "operator": parts[0].upper() if parts else "Unknown",
            "country":  "Madagascar",  # default
            "period":   "Unknown",
            "is_momo":  False,
        }

    # Extract period and type from remaining parts
    remaining = stem[len(operator_key):].strip("_")
    is_momo   = any(kw in remaining for kw in
                    ["momo","mobile_money","mm","wallet"])

    # Try to detect period (month + year)
    import re
    months = ["jan","feb","mar","apr","may","jun",
              "jul","aug","sep","oct","nov","dec",
              "january","february","march","april","june",
              "july","august","september","october","november","december"]
    period = "Unknown"
    for m in months:
        if m in remaining:
            # Find year
            year_match = re.search(r"20\d{2}", remaining)
            year = year_match.group() if year_match else str(datetime.now().year)
            period = f"{m.capitalize()} {year}"
            break

    return {
        "operator": operator_info.get("operator", "Unknown"),
        "country":  operator_info.get("country",  "Madagascar"),
        "period":   period,
        "is_momo":  is_momo,
    }


def file_is_stable(filepath: Path, wait_sec: int = 5) -> bool:
    """Check that file has stopped growing (fully uploaded)."""
    try:
        size1 = filepath.stat().st_size
        time.sleep(wait_sec)
        size2 = filepath.stat().st_size
        return size1 == size2 and size1 > 0
    except Exception:
        return False


def submit_to_api(filepath: Path, meta: dict) -> Optional[str]:
    """Submit file to NOCTYRA360™ API for processing."""
    try:
        with open(filepath, "rb") as f:
            resp = requests.post(
                f"{API_URL}/api/process",
                files={"file": (filepath.name, f, "text/csv")},
                data={
                    "operator":    meta["operator"],
                    "country":     meta["country"],
                    "period":      meta["period"],
                    "declaration": "{}",  # no declaration — pure CDR mode
                },
                timeout=300,  # 5 min timeout for large files
            )
        if resp.status_code == 200:
            return resp.json().get("job_id")
        else:
            log.error(f"API error {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        log.error(f"Submit failed: {e}")
        return None


def monitor_job(job_id: str, max_wait_min: int = 120) -> bool:
    """Poll job status until complete or timeout."""
    deadline = time.time() + max_wait_min * 60
    while time.time() < deadline:
        try:
            resp = requests.get(f"{API_URL}/api/job/{job_id}", timeout=10)
            if resp.status_code == 200:
                job = resp.json()
                status   = job.get("status", "unknown")
                progress = job.get("progress", 0)
                log.info(f"  Job {job_id}: {status} ({progress}%)")

                if status == "complete":
                    return True
                elif status == "error":
                    log.error(f"  Job failed: {job.get('error','unknown error')}")
                    return False
        except Exception as e:
            log.warning(f"  Poll error: {e}")

        time.sleep(15)

    log.error(f"  Job {job_id} timed out after {max_wait_min} min")
    return False


def process_file(filepath: Path):
    """Full pipeline for one incoming file."""
    log.info(f"New file detected: {filepath.name} "
             f"({filepath.stat().st_size/1_048_576:.1f} MB)")

    # Wait for upload to complete
    if not file_is_stable(filepath):
        log.warning(f"File {filepath.name} appears unstable — skipping")
        return

    # Parse metadata from filename
    meta = parse_filename(filepath.name)
    log.info(f"  Operator: {meta['operator']} | "
             f"Country: {meta['country']} | "
             f"Period: {meta['period']} | "
             f"MoMo: {meta['is_momo']}")

    # Submit to API
    job_id = submit_to_api(filepath, meta)
    if not job_id:
        log.error(f"  Failed to submit — moving to error folder")
        shutil.move(str(filepath), str(ERROR_DIR / filepath.name))
        return

    log.info(f"  Submitted — job: {job_id}")

    # Monitor processing
    success = monitor_job(job_id)

    if success:
        log.info(f"  ✅ Processing complete — moving to done folder")
        shutil.move(str(filepath), str(DONE_DIR / filepath.name))
    else:
        log.error(f"  ❌ Processing failed — moving to error folder")
        shutil.move(str(filepath), str(ERROR_DIR / filepath.name))


def watch_loop():
    """Main watch loop — runs forever."""
    log.info(f"NOCTYRA360™ SFTP Watcher started")
    log.info(f"Watching: {WATCH_DIR}")
    log.info(f"Poll interval: {POLL_SECS} seconds")

    processed = set()

    while True:
        try:
            if WATCH_DIR.exists():
                for filepath in sorted(WATCH_DIR.iterdir()):
                    if (filepath.is_file() and
                        filepath.suffix.lower() in SUPPORTED_EXTENSIONS and
                        str(filepath) not in processed):
                        processed.add(str(filepath))
                        # Process in a separate thread
                        Thread(target=process_file,
                               args=(filepath,),
                               daemon=True).start()
        except Exception as e:
            log.error(f"Watch loop error: {e}")

        time.sleep(POLL_SECS)


if __name__ == "__main__":
    # Create directories
    for d in [WATCH_DIR, DONE_DIR, ERROR_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    watch_loop()
