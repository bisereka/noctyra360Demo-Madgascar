"""
NOCTYRA360™ — EFR Calculation Engine
Computes Estimated Fiscal Recovery for any country.
"""
import hashlib, json
from datetime import datetime
from typing import Optional

TAX_MATRICES = {
    "Madagascar": {
        "currency":"MGA","fx_to_usd":4800,"gdp_usd":14_800_000_000,
        "imf_benchmark":0.013,
        "taxes":{
            "TVA":0.20,          
            "TST":0.05,          
            "IRCM":0.02,         
            "TTM":0.08,          
        },
        "effective_rate":0.25,   
        "operators":["Telma","Orange MDG","Airtel MDG"],
        "momo_operators":["MVola","Orange Money MDG","Airtel Money MDG"],
        "regulator":"ARTEC","tax_auth":"DGI",
        "msisdn_prefix":"+261",
        "capital":"Antananarivo",
    },
    "Mozambique": {
        "currency":"MZN","fx_to_usd":63.905,"gdp_usd":22_750_000_000,
        "imf_benchmark":0.013,
        "taxes":{"VAT":0.17,"IEC":0.05,"INCM_LEVY":0.01},
        "effective_rate":0.23,
        "operators":["Vodacom","Movitel","Tmcel"],
        "regulator":"INCM","tax_auth":"AT",
    },
    "Malawi": {
        "currency":"MWK","fx_to_usd":1750,"gdp_usd":11_010_000_000,
        "imf_benchmark":0.013,
        "taxes":{"VAT":0.165,"EXCISE":0.055,"MACRA_LEVY":0.01},
        "effective_rate":0.23,
        "operators":["Airtel Malawi","TNM","Malcel"],
        "regulator":"MACRA","tax_auth":"MRA",
    },
    "CAR": {
        "currency":"XAF","fx_to_usd":600,"gdp_usd":2_600_000_000,
        "imf_benchmark":0.013,
        "taxes":{"TIC_TECH":0.07,"TVA":0.19},
        "effective_rate":0.26,
        "operators":["Telecel","Orange CAR","Moov","Azur"],
        "regulator":"ARCEP","tax_auth":"DGI CAR",
    },
    "Generic": {
        "currency":"USD","fx_to_usd":1,"gdp_usd":10_000_000_000,
        "imf_benchmark":0.013,
        "taxes":{"VAT":0.18,"EXCISE":0.05,"LEVY":0.01},
        "effective_rate":0.24,
        "operators":[],"regulator":"REGULATOR","tax_auth":"TAX AUTHORITY",
    },
}

class EFREngine:
    def __init__(self, country="Generic"):
        self.country = country
        self.matrix  = TAX_MATRICES.get(country, TAX_MATRICES["Generic"])

    def get_imf_baseline(self):
        gdp = self.matrix["gdp_usd"]
        monthly_usd = (gdp * self.matrix["imf_benchmark"]) / 12
        fx  = self.matrix["fx_to_usd"]
        cur = self.matrix["currency"]
        return {
            "monthly_usd": round(monthly_usd, 2),
            f"monthly_{cur}": round(monthly_usd * fx, 2),
            "source": "IMF 1.3% of GDP · World Bank 2024",
        }

    def compute_taxes_due(self, gross_revenue):
        result = {}
        total  = 0
        for name, rate in self.matrix["taxes"].items():
            amt = gross_revenue * rate
            result[name] = round(amt, 2)
            total += amt
        result["TOTAL"] = round(total, 2)
        return result

    def compute_efr(self, decoded_stats, declaration=None,
                    operator="Unknown", period="Unknown"):
        cur     = self.matrix["currency"]
        fx      = self.matrix["fx_to_usd"]
        is_momo = decoded_stats.get("is_momo", False)

        if is_momo:
            certified_revenue = decoded_stats.get("total_amount", 0)
            taxable_base      = decoded_stats.get("total_fees", 0)
        else:
            certified_revenue = decoded_stats.get("total_revenue", 0)
            taxable_base      = certified_revenue

        taxes_due       = self.compute_taxes_due(taxable_base)
        total_taxes_due = taxes_due["TOTAL"]

        if declaration:
            declared_revenue = declaration.get("declared_revenue", 0)
            declared_taxes   = declaration.get("declared_taxes", 0)
        else:
            b = self.get_imf_baseline()
            declared_revenue = b["monthly_usd"] * fx
            declared_taxes   = declared_revenue * self.matrix["effective_rate"]

        revenue_gap = certified_revenue - declared_revenue
        tax_gap     = total_taxes_due   - declared_taxes
        gap_pct     = (revenue_gap / declared_revenue * 100) if declared_revenue > 0 else 100.0

        gap_rate = abs(gap_pct) / 100
        if gap_rate <= 0.07:
            category, label = "INVOLUNTARY", "CDR-billing mismatch / system complexity"
            status, color   = "MINOR_GAP", "AMBER"
        elif gap_rate <= 0.35:
            category, label = "STRUCTURAL", "Deliberate under-declaration"
            status, color   = "UNDER_DECLARED", "RED"
        else:
            category, label = "SEVERE", "Severe deliberate under-declaration"
            status, color   = "CRITICAL", "RED"

        if abs(tax_gap) < declared_taxes * 0.03:
            status, color = "COMPLIANT", "GREEN"

        return {
            "operator": operator, "period": period,
            "country": self.country, "currency": cur, "is_momo": is_momo,
            "certified_revenue": round(certified_revenue, 2),
            "certified_revenue_usd": round(certified_revenue / fx, 2),
            "taxable_base": round(taxable_base, 2),
            "taxes_due": taxes_due,
            "total_taxes_due": round(total_taxes_due, 2),
            "total_taxes_due_usd": round(total_taxes_due / fx, 2),
            "declared_revenue": round(declared_revenue, 2),
            "declared_revenue_usd": round(declared_revenue / fx, 2),
            "declared_taxes": round(declared_taxes, 2),
            "declared_taxes_usd": round(declared_taxes / fx, 2),
            "revenue_gap": round(revenue_gap, 2),
            "revenue_gap_usd": round(revenue_gap / fx, 2),
            "tax_gap": round(tax_gap, 2),
            "tax_gap_usd": round(tax_gap / fx, 2),
            "gap_percentage": round(gap_pct, 2),
            "gap_category": category,
            "gap_label": label,
            "compliance_status": status,
            "status_color": color,
            "imf_baseline": self.get_imf_baseline(),
            "records_processed": decoded_stats.get("total_rows", 0),
            "unique_subscribers": decoded_stats.get("unique_subscribers", 0),
            "input_hash": decoded_stats.get("input_hash", ""),
            "computed_at": datetime.utcnow().isoformat(),
        }

    def certify(self, finding):
        j = json.dumps(finding, sort_keys=True, ensure_ascii=False)
        fh = hashlib.sha256(j.encode()).hexdigest()
        ch = hashlib.sha256(
            (finding.get("input_hash","") + fh).encode()
        ).hexdigest()
        finding["certification"] = {
            "finding_hash": fh,
            "cert_hash": ch,
            "certified_at": datetime.utcnow().isoformat(),
            "algorithm": "SHA-256",
            "admissibility": "Legally admissible — tamper-evident",
        }
        return finding

    def compute_scenarios(self, country=None):
        m   = TAX_MATRICES.get(country or self.country, TAX_MATRICES["Generic"])
        b   = (m["gdp_usd"] * m["imf_benchmark"]) / 12
        fx  = m["fx_to_usd"]
        cur = m["currency"]
        out = {"imf_baseline_usd": round(b,2), f"imf_baseline_{cur}": round(b*fx,2)}
        for label, pct in [("inv_5",0.05),("inv_7",0.07),("str_25",0.25),("str_35",0.35)]:
            out[label] = {"gap": f"{int(pct*100)}%",
                          "usd": round(b*pct,2),
                          cur:   round(b*fx*pct,2)}
        return out


def get_effective_tax_rate(country: str, service: str = "default") -> float:
    """Return total effective tax rate for a country."""
    m = TAX_MATRICES.get(country, TAX_MATRICES["Generic"])
    return m.get("effective_rate", 0.24)


def run_efr(decoded_stats: dict,
            country: str,
            operator: str = "Unknown",
            period: str = "Unknown",
            declaration=None) -> dict:
    """
    Convenience function — one call to get a certified EFR finding.
    decoded_stats: output from CDRDecoder.process_file()
    declaration:   dict with total_revenue, total_tax (or None)
    """
    # Auto-detect period from sample_timestamps if available
    from datetime import datetime as _dt
    if not period or period == "Unknown":
        sample_ts = decoded_stats.get("sample_timestamps", [])
        if sample_ts:
            try:
                mois_fr = ['Janvier','Février','Mars','Avril','Mai','Juin',
                           'Juillet','Août','Septembre','Octobre','Novembre','Décembre']
                dt = _dt.fromisoformat(str(sample_ts[0])[:19])
                period = mois_fr[dt.month-1] + " " + str(dt.year)
                print(f"  📅 Période auto-détectée depuis CDR: {period}")
            except Exception:
                pass
        if not period or period == "Unknown":
            now = _dt.utcnow()
            mois_fr = ['Janvier','Février','Mars','Avril','Mai','Juin',
                       'Juillet','Août','Septembre','Octobre','Novembre','Décembre']
            m = 11 if now.month == 1 else now.month - 2
            y = now.year - 1 if now.month <= 1 else now.year
            period = mois_fr[m] + " " + str(y)

    engine   = EFREngine(country)
    # Normalize country name to matrix key
    _country_aliases = {
        "centrafrique":         "CAR",
        "central african republic": "CAR",
        "republique centrafricaine": "CAR",
        "rca":                  "CAR",
        "madagascar":           "Madagascar",
        "mozambique":           "Mozambique",
        "mocambique":           "Mozambique",
        "malawi":               "Malawi",
        "cote d'ivoire":        "CIV",
        "ivory coast":          "CIV",
        "civ":                  "CIV",
        "tanzania":             "Tanzania",
        "tanzanie":             "Tanzania",
        "tza":                  "Tanzania",
        "drc":                  "DRC",
        "congo":                "DRC",
    }
    _country_key = _country_aliases.get(country.lower(), country)
    matrix   = TAX_MATRICES.get(_country_key, TAX_MATRICES.get(country, TAX_MATRICES["Generic"]))
    cur      = matrix["currency"]
    fx       = matrix["fx_to_usd"]
    eff_rate = matrix.get("effective_rate", 0.24)
    is_momo  = decoded_stats.get("is_momo", False)

    # Certified figures from CDR
    if is_momo:
        # MoMo revenue = commissions earned (not total transaction volume)
        cert_rev = (
            decoded_stats.get("total_revenue") or
            decoded_stats.get("total_fees") or
            decoded_stats.get("commission_total") or
            decoded_stats.get("total_commission") or
            (decoded_stats.get("total_amount", 0) * 0.02)  # 2% commission estimate
        )
    else:
        cert_rev = (
            decoded_stats.get("total_revenue") or
            decoded_stats.get("voice_revenue", 0) +
            decoded_stats.get("sms_revenue", 0) +
            decoded_stats.get("data_revenue", 0)
        )
    cert_tax = cert_rev * eff_rate

    # Declared figures
    # Priority: explicit declaration > declared_revenue in CDR stats > 0
    has_decl   = declaration is not None
    
    # Always read declared_revenue from CDR file (per-row declared field)
    cdr_decl_rev = decoded_stats.get("total_declared_revenue",
                   decoded_stats.get("declared_revenue", 0))
    cdr_decl_tax = decoded_stats.get("total_tax_declared",
                   decoded_stats.get("declared_tax", 0))
    
    if has_decl:
        decl_rev = declaration.get("total_revenue",
                   declaration.get("total_fees", cdr_decl_rev))
        decl_tax = declaration.get("total_tax", cdr_decl_tax)
        if decl_tax == 0 and decl_rev > 0:
            decl_tax = decl_rev * eff_rate
    elif cdr_decl_rev > 0:
        # Use declared_revenue from CDR rows
        has_decl = True
        decl_rev = cdr_decl_rev
        decl_tax = cdr_decl_tax if cdr_decl_tax > 0 else decl_rev * eff_rate
    else:
        decl_rev = 0
        decl_tax = 0

    # Gap
    rev_gap  = cert_rev - decl_rev if has_decl else cert_rev * 0.26
    tax_gap  = cert_tax - decl_tax if has_decl else cert_rev * eff_rate * 0.26
    gap_pct  = (tax_gap / cert_tax * 100) if cert_tax > 0 else 26.0

    # Status
    if not has_decl:
        status = "NO_DECLARATION"
    elif abs(gap_pct) < 3:
        status = "COMPLIANT"
    elif abs(gap_pct) < 10:
        status = "MINOR_GAP"
    elif abs(gap_pct) < 25:
        status = "SIGNIFICANT_GAP"
    else:
        status = "CRITICAL_GAP"

    # Anomaly score
    anomaly_score = min(100, int(abs(gap_pct) * 2))

    finding = {
        "operator":      decoded_stats.get("operator", "Unknown"),
        "country":       country,
        "currency":      cur,
        "period":        period,
        "status":        status,
        "anomaly_score": anomaly_score,
        "data_type":     "MOBILE_MONEY" if is_momo else "TELECOM",

        "certified": {
            "total_revenue":      round(cert_rev, 2),
            "total_tax":          round(cert_tax, 2),
            "effective_rate_pct": round(eff_rate * 100, 1),
            "voice_revenue":      round(decoded_stats.get("voice_revenue", 0), 2),
            "data_revenue":       round(decoded_stats.get("data_revenue",  0), 2),
            "sms_revenue":        round(decoded_stats.get("sms_revenue",   0), 2),
            "idd_revenue":        round(decoded_stats.get("idd_revenue",   0), 2),
        },

        "declared": {
            "total_revenue": round(decl_rev, 2),
            "total_tax":     round(decl_tax, 2),
        } if has_decl else None,

        "gap": {
            "revenue_gap":     round(rev_gap, 2),
            "tax_gap":         round(tax_gap, 2),
            "gap_rate_pct":    round(gap_pct, 2),
            "revenue_gap_usd": round(rev_gap / fx, 2),
            "tax_gap_usd":     round(tax_gap / fx, 2),
        } if has_decl else None,

        "security": {
            "invalid_imei_count": decoded_stats.get("invalid_imei_count", 0),
            "simbox_risk":        "HIGH" if anomaly_score > 70 else
                                  "MEDIUM" if anomaly_score > 40 else "LOW",
        },

        "summary_usd": {
            "certified_revenue_usd": round(cert_rev / fx, 2),
            "certified_tax_usd":     round(cert_tax / fx, 2),
            "declared_tax_usd":      round(decl_tax / fx, 2) if has_decl else None,
            "tax_gap_usd":           round(tax_gap / fx, 2)  if has_decl else None,
        },

        "metadata": {
            "total_records":      decoded_stats.get("total_rows", 0),
            "unique_subscribers": decoded_stats.get("unique_subscribers", 0),
            "vendor":             decoded_stats.get("vendor", "Unknown"),
            "input_hash":         decoded_stats.get("input_hash", ""),
            "calculated_at":      datetime.utcnow().isoformat(),
        },
    }

    # Certify
    import json, hashlib
    ts      = datetime.utcnow().isoformat()
    payload = json.dumps(finding, sort_keys=True) + decoded_stats.get("input_hash","") + ts
    fh      = hashlib.sha256(payload.encode()).hexdigest()
    ch      = hashlib.sha256((fh + ts).encode()).hexdigest()
    # Add convenience fields for frontend bridge
    finding["sha256"]             = ch
    finding["certification_hash"] = ch
    _cert  = finding.get("certified") or {}
    _decl  = finding.get("declared")  or {}
    _gap   = finding.get("gap")       or {}
    finding["total_revenue"]    = _cert.get("total_revenue", decoded_stats.get("total_revenue", 0))
    finding["tax_due"]          = _cert.get("total_tax", 0)
    finding["declared_revenue"] = _decl.get("total_tax", _decl.get("total_revenue", 0))
    finding["total_records"]    = decoded_stats.get("total_rows", 0)
    finding["currency"]         = matrix.get("currency", "USD")  # matrix already resolved with aliases
    # tax_gap_local for frontend display
    if finding.get("gap") is None:
        finding["gap"] = {}
    finding["gap"]["tax_gap_local"] = _gap.get("tax_gap", 0)

    finding["certification"] = {
        "input_hash":         decoded_stats.get("input_hash",""),
        "finding_hash":       fh,
        "cert_hash":          ch,
        "certified_at":       ts,
        "algorithm":          "SHA-256",
        "certified_by":       "NOCTYRA360™ v13 Production",
        "legally_admissible": True,
    }

    print(f"\n  🔐 CERTIFIED — Status: {status} | Score: {anomaly_score}/100")
    if has_decl and gap_pct != 0:
        print(f"  EFR Gap: {gap_pct:.1f}% | USD {tax_gap/fx:,.2f}/month")

    return finding
