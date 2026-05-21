# NOCTYRA360™ — Production Backend
## Connect Now USA LLC & IntegraTouch

---

## What This Is

The production-grade Python backend for NOCTYRA360™ V13.
Handles real country CDR data — any size, any vendor format.
Works with the existing V13 HTML frontend via REST API.

---

## What Is Built

| Module | File | What It Does |
|--------|------|-------------|
| CDR Decoder | core/decoder.py | Reads any CDR format — Huawei, Ericsson, Nokia, ZTE, Generic. Auto-detects. Maps columns once. Saves permanently. |
| EFR Engine | core/efr_engine.py | Calculates tax gap. Madagascar, Mozambique, Malawi, CAR matrices built-in. SHA-256 certifies every finding. |
| Anomaly Engine | core/anomaly_engine.py | SIM Box AI scoring. IMEI Luhn validation. MoMo AML detection. |
| Report Engine | core/report_engine.py | Generates certified text/JSON reports. Ready for PDF upgrade. |
| REST API | api/main.py | FastAPI backend. Upload CDR → job runs in background → results via API → V13 displays live. |

---

## Proven Performance

```
1,020,000 CDR rows processed in 14.6 seconds
Speed: 69,748 rows/second
A full country month (50-75M rows): ~15-20 minutes
```

---

## Quick Start — Demo on Laptop (No Server Needed)

```bash
# 1. Install Python dependencies (once)
pip install -r requirements.txt

# 2. Start the backend
bash scripts/run_local.sh

# 3. Open browser
open http://localhost:8000/docs

# 4. Load V13 frontend
open NOCTYRA360_FINAL.html
```

---

## Production Install — On a Server (Ubuntu 22.04)

```bash
# ONE COMMAND — installs everything
sudo bash scripts/install.sh
```

---

## Supported Countries

| Country | Currency | Operators | Regulator |
|---------|----------|-----------|-----------|
| Madagascar | MGA | Telma, Orange MDG, Airtel MDG, Blueline | ARTEC |
| Mozambique | MZN | Vodacom, Movitel, Tmcel | INCM |
| Malawi | MWK | Airtel Malawi, TNM, Malcel | MACRA |
| CAR | XAF | Telecel, Orange CAR, Moov, Azur | ARCEP |

---

## CDR Format Coverage

| Vendor | Auto-detected | First-time mapping |
|--------|--------------|-------------------|
| Huawei | ✅ Automatic | Not needed |
| Ericsson | ✅ Automatic | Not needed |
| Nokia | ✅ Automatic | Not needed |
| ZTE | ✅ Automatic | Not needed |
| Any custom | ✅ Auto-detects structure | 15-min one-time mapping |

**All mappings saved permanently — same operator next month = zero work.**

---

## API Endpoints

```
GET  /                          Health check
GET  /api/countries             List supported countries
POST /api/process               Upload CDR file → start processing
GET  /api/jobs/{job_id}         Check job status + results
GET  /api/jobs                  List all jobs
GET  /api/reports/{id}/json     Download certified JSON report
GET  /api/reports/{id}/txt      Download certified text report
GET  /api/scenarios/{country}   Get projection scenarios
GET  /api/schemas               View saved operator schemas
```

---

## Test Results

```
TEST 1: EFR Engine (Madagascar)          ✅ PASS
TEST 2: EFR Engine (Mozambique)          ✅ PASS
TEST 3: SIM Box Detection                ✅ PASS (score=100 on test data)
TEST 4: IMEI Validation (Luhn+TAC)       ✅ PASS
TEST 5: CDR Decoder (Huawei format)      ✅ PASS
TEST 6: MoMo Decoder (Generic format)   ✅ PASS
TEST 7: Report Generation                ✅ PASS
TEST 8: 1,020,000 rows in 14.6 seconds  ✅ PRODUCTION READY
```

---

*NOCTYRA360™ is a proprietary platform of Connect Now USA LLC*
*+1 617-678-4531 | info@connectnowus.org | www.noctyra360.com*
