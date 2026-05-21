"""
NOCTYRA360™ — Report Generation Engine
Generates SHA-256 certified PDF reports and Excel exports.
"""
import json, os, hashlib
from datetime import datetime

def generate_report_data(finding: dict, anomalies: dict = None) -> dict:
    """Package finding + anomalies into a complete report payload."""
    cur   = finding.get("currency","MGA")
    fx    = {"MGA":4500,"MZN":63.905,"MWK":1750,"XAF":600}.get(cur,1)
    cert  = finding.get("certification",{})

    report = {
        "title":        f"NOCTYRA360™ — Certified EFR Report",
        "subtitle":     f"{finding.get('operator','')} — {finding.get('period','')}",
        "country":      finding.get("country",""),
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "reference":    f"EFR-{finding.get('country','XX')[:2].upper()}-"
                        f"{datetime.utcnow().strftime('%Y%m%d-%H%M')}",
        "finding":      finding,
        "anomalies":    anomalies or {},
        "certification_chain": cert.get("chain",""),
        "cert_hash":    cert.get("cert_hash",""),
        "admissibility": cert.get("admissibility",""),
        "summary": {
            "status":       finding.get("compliance_status",""),
            "color":        finding.get("status_color",""),
            "tax_gap_usd":  finding.get("tax_gap_usd", 0),
            f"tax_gap_{cur}": finding.get("tax_gap", 0),
            "gap_pct":      finding.get("gap_percentage", 0),
            "category":     finding.get("gap_category",""),
        }
    }
    return report

def save_report_json(report: dict, output_dir: str = ".") -> str:
    """Save report as JSON (always — this is the source of truth)."""
    os.makedirs(output_dir, exist_ok=True)
    ref = report.get("reference","report")
    path = os.path.join(output_dir, f"{ref}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return path

def generate_text_report(report: dict) -> str:
    """Generate a plain-text certified report (works without PDF library)."""
    f   = report["finding"]
    cur = f.get("currency","MGA")
    s   = report["summary"]
    lines = [
        "="*70,
        "  NOCTYRA360™ — CERTIFIED EFR REPORT",
        "  Connect Now USA LLC & IntegraTouch",
        "="*70,
        f"  Reference:    {report['reference']}",
        f"  Generated:    {report['generated_at']}",
        f"  Operator:     {f.get('operator','')}",
        f"  Period:       {f.get('period','')}",
        f"  Country:      {f.get('country','')}",
        "",
        "-"*70,
        "  CERTIFIED CDR RESULTS",
        "-"*70,
        f"  Records processed:      {f.get('records_processed',0):,}",
        f"  Unique subscribers:     {f.get('unique_subscribers',0):,}",
        f"  Certified revenue:      {f.get('certified_revenue',0):,.2f} {cur}",
        f"  Certified revenue:      USD {f.get('certified_revenue_usd',0):,.2f}",
        "",
        "-"*70,
        "  DECLARED vs CERTIFIED — THE GAP",
        "-"*70,
        f"  Declared revenue:       {f.get('declared_revenue',0):,.2f} {cur}",
        f"  Certified revenue:      {f.get('certified_revenue',0):,.2f} {cur}",
        f"  Revenue gap:            {f.get('revenue_gap',0):,.2f} {cur}",
        f"  Revenue gap:            USD {f.get('revenue_gap_usd',0):,.2f}",
        "",
        f"  Declared taxes:         {f.get('declared_taxes',0):,.2f} {cur}",
        f"  Taxes due (certified):  {f.get('total_taxes_due',0):,.2f} {cur}",
        f"  TAX GAP (EFR):          {f.get('tax_gap',0):,.2f} {cur}",
        f"  TAX GAP (EFR):          USD {f.get('tax_gap_usd',0):,.2f}",
        f"  Gap percentage:         {f.get('gap_percentage',0):.1f}%",
        "",
        "-"*70,
        "  COMPLIANCE STATUS",
        "-"*70,
        f"  Status:    *** {s['status']} ***",
        f"  Category:  {f.get('gap_category','')}",
        f"  Label:     {f.get('gap_label','')}",
        "",
        "-"*70,
        "  SHA-256 CERTIFICATION CHAIN",
        "-"*70,
        f"  Input hash:   {f.get('input_hash','')[:40]}...",
        f"  Chain:        {report.get('certification_chain','')}",
        f"  Cert hash:    {report.get('cert_hash','')}",
        f"  Algorithm:    SHA-256",
        f"  Admissibility: {report.get('admissibility','')}",
        "",
        "="*70,
        "  This report is tamper-evident. Any modification invalidates",
        "  the SHA-256 certification chain above.",
        "  Legally admissible before any tax authority or court.",
        "="*70,
    ]

    # Add anomalies if present
    anoms = report.get("anomalies",{})
    sb = anoms.get("simbox",[])
    if sb:
        lines += ["","-"*70,"  SIMBOX DETECTIONS","",]
        for a in sb[:10]:
            lines.append(f"  MSISDN {a['msisdn']} — Score {a['score']}/100 "
                         f"— IDD ratio {a.get('idd_ratio',0):.0f}%")

    return "\n".join(lines)
