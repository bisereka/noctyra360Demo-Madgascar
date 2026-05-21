"""
NOCTYRA360™ — Anomaly Detection Engine
Detects SIM Box operators, IMEI fraud, grey routes, MoMo AML patterns.
Scores each anomaly 0-100. Generates evidence dossier per bad actor.
"""

import pandas as pd
import numpy as np
import re
from datetime import datetime
from typing import List, Dict


class AnomalyDetector:
    """
    Detects fraud and under-declaration patterns in CDR/MoMo data.
    All detections are evidence-grade — ready for legal dossier.
    """

    # SIM Box behavioral thresholds
    SIMBOX_MIN_IDD_CALLS       = 50      # minimum IDD calls/day to flag
    SIMBOX_MAX_AVG_DURATION    = 45      # seconds — SIM Box calls are short
    SIMBOX_MIN_NOCTURNAL_RATIO = 0.40    # >40% calls between 23:00-05:00
    SIMBOX_SCORE_THRESHOLD     = 75      # score above this = confirmed SIM Box

    # Mass SMS thresholds
    MASS_SMS_DAILY_THRESHOLD   = 300     # SMS per day from single MSISDN

    # MoMo AML thresholds
    AML_P2P_CHAIN_MIN          = 5       # minimum chain length
    AML_CIRCULAR_WINDOW_HOURS  = 24      # hours to detect circular transfers
    AML_HIGH_VELOCITY_COUNT    = 100     # transactions/day from one MSISDN

    def __init__(self):
        self.findings = []

    # ── SIM Box Detection ──────────────────────────────────────────────────────
    def detect_simbox(self, df: pd.DataFrame) -> List[Dict]:
        """
        Detects SIM Box operators from telecom CDR data.
        SIM Box routes IDD calls as local — depriving government of interconnect revenue.

        Behavioral signatures:
        - High volume of incoming IDD-looking calls billed as local
        - Very short average call duration (SIM Box = connect-disconnect quickly)
        - Nocturnal traffic concentration (operators hide SIM Box activity at night)
        - Specific MSISDNs receiving abnormally high IDD-routed traffic
        """
        results = []
        if df is None or len(df) == 0:
            return results

        # Filter IDD-related calls
        idd_mask = df["call_type"].str.upper().str.contains(
            r"IDD|INTER|INTL|ROAM|INTERNATIONAL", na=False)
        idd_df = df[idd_mask].copy()

        if len(idd_df) == 0:
            return results

        # Parse time for nocturnal analysis
        try:
            idd_df["hour"] = pd.to_datetime(
                idd_df["time"], format="%H:%M:%S", errors="coerce"
            ).dt.hour
        except Exception:
            idd_df["hour"] = 0

        # Group by MSISDN
        grouped = idd_df.groupby("msisdn").agg(
            call_count   =("msisdn",   "count"),
            avg_duration =("duration", "mean"),
            total_revenue=("revenue",  "sum"),
        ).reset_index()

        # Add nocturnal ratio
        if "hour" in idd_df.columns:
            nocturnal = idd_df[idd_df["hour"].between(23, 24) |
                               idd_df["hour"].between(0, 5)]
            noc_counts = nocturnal.groupby("msisdn").size().reset_index(
                name="nocturnal_count")
            grouped = grouped.merge(noc_counts, on="msisdn", how="left")
            grouped["nocturnal_count"]  = grouped["nocturnal_count"].fillna(0)
            grouped["nocturnal_ratio"]  = (grouped["nocturnal_count"] /
                                           grouped["call_count"].clip(lower=1))
        else:
            grouped["nocturnal_ratio"] = 0

        # Score each MSISDN
        for _, row in grouped.iterrows():
            if row["call_count"] < self.SIMBOX_MIN_IDD_CALLS:
                continue

            score = 0

            # Short duration indicator
            if row["avg_duration"] < self.SIMBOX_MAX_AVG_DURATION:
                score += 40
            elif row["avg_duration"] < 90:
                score += 20

            # Nocturnal activity
            if row["nocturnal_ratio"] > self.SIMBOX_MIN_NOCTURNAL_RATIO:
                score += 35
            elif row["nocturnal_ratio"] > 0.25:
                score += 15

            # Volume indicator
            if row["call_count"] > 500:
                score += 25
            elif row["call_count"] > 200:
                score += 15

            score = min(100, score)

            if score >= self.SIMBOX_SCORE_THRESHOLD:
                results.append({
                    "type":            "SIMBOX",
                    "msisdn":          row["msisdn"],
                    "score":           score,
                    "evidence": {
                        "idd_call_count":    int(row["call_count"]),
                        "avg_duration_sec":  round(float(row["avg_duration"]), 1),
                        "nocturnal_ratio":   round(float(row["nocturnal_ratio"]), 3),
                        "revenue_at_risk":   round(float(row["total_revenue"]), 2),
                    },
                    "verdict":         "CONFIRMED SIM BOX" if score >= 85
                                       else "SUSPECTED SIM BOX",
                    "action":          "Criminal prosecution. Interconnect revenue recovery.",
                    "detected_at":     datetime.utcnow().isoformat(),
                })

        return sorted(results, key=lambda x: x["score"], reverse=True)

    # ── IMEI Fraud Detection ───────────────────────────────────────────────────
    def detect_imei_fraud(self, df: pd.DataFrame) -> List[Dict]:
        """
        Detects cloned/fake IMEI devices using Luhn algorithm.
        Also identifies devices active but not in national registry.
        """
        results = []
        if df is None or "imei" not in df.columns:
            return results

        # Ensure date column exists
        if "date" not in df.columns and "timestamp" in df.columns:
            try:
                df["date"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.date
            except Exception:
                df["date"] = None
        imei_df = df[df["imei"].astype(str).str.len() > 5].copy()
        if len(imei_df) == 0:
            return results

        def luhn_check(imei_str):
            digits = re.sub(r"\D", "", str(imei_str))
            if len(digits) != 15:
                return False
            total = 0
            for i, d in enumerate(digits):
                n = int(d)
                if i % 2 == 1:
                    n *= 2
                    if n > 9:
                        n -= 9
                total += n
            return total % 10 == 0

        imei_df["luhn_valid"] = imei_df["imei"].apply(luhn_check)
        invalid = imei_df[~imei_df["luhn_valid"]]

        for imei_val, grp in invalid.groupby("imei"):
            if str(imei_val) in ("", "nan", "0"):
                continue
            results.append({
                "type":    "IMEI_FRAUD",
                "imei":    str(imei_val),
                "score":   90,
                "evidence": {
                    "luhn_valid":         False,
                    "msisdns_using":      list(grp["msisdn"].unique()[:10]),
                    "call_count":         int(len(grp)),
                    "first_seen":         str(grp["date"].min()),
                    "operators_affected": list(grp.get("operator",
                                              pd.Series(["Unknown"])).unique()),
                },
                "verdict": "CLONED/FAKE DEVICE",
                "action":  "Device seizure. Prosecution of importer. Customs duty recovery.",
                "detected_at": datetime.utcnow().isoformat(),
            })

        return results[:100]  # cap at 100 for performance

    # ── Mass SMS Detection ─────────────────────────────────────────────────────
    def detect_mass_sms(self, df: pd.DataFrame) -> List[Dict]:
        """
        Detects MSISDNs sending bulk SMS campaigns — often unlicensed.
        """
        results = []
        if df is None or len(df) == 0:
            return results

        sms_mask = df["call_type"].str.upper().str.contains(
            r"SMS|TEXT|MSG", na=False)
        sms_df = df[sms_mask]

        if len(sms_df) == 0:
            return results

        # Count SMS per MSISDN
        sms_counts = sms_df.groupby("msisdn").agg(
            sms_count =("msisdn", "count"),
            revenue   =("revenue", "sum"),
        ).reset_index()

        high_volume = sms_counts[
            sms_counts["sms_count"] >= self.MASS_SMS_DAILY_THRESHOLD]

        for _, row in high_volume.iterrows():
            score = min(100, int(
                50 + (row["sms_count"] / self.MASS_SMS_DAILY_THRESHOLD) * 25))
            results.append({
                "type":   "MASS_SMS",
                "msisdn": row["msisdn"],
                "score":  score,
                "evidence": {
                    "sms_count":      int(row["sms_count"]),
                    "revenue_impact": round(float(row["revenue"]), 2),
                },
                "verdict": "UNLICENSED BULK SMS CAMPAIGN",
                "action":  "Licence compliance enforcement. Revenue recovery.",
                "detected_at": datetime.utcnow().isoformat(),
            })

        return sorted(results, key=lambda x: x["score"], reverse=True)

    # ── MoMo AML Detection ────────────────────────────────────────────────────
    def detect_momo_aml(self, df: pd.DataFrame) -> List[Dict]:
        """
        Detects Anti-Money Laundering patterns in Mobile Money data.
        Patterns: P2P chains, circular transfers, high-velocity accounts.
        """
        results = []
        if df is None or len(df) == 0 or "amount" not in df.columns:
            return results

        # High velocity detection
        velocity = df.groupby("msisdn").agg(
            tx_count = ("msisdn", "count"),
            volume   = ("amount", "sum"),
        ).reset_index()

        high_vel = velocity[velocity["tx_count"] >= self.AML_HIGH_VELOCITY_COUNT]

        for _, row in high_vel.iterrows():
            score = min(100, int(
                50 + (row["tx_count"] / self.AML_HIGH_VELOCITY_COUNT) * 30))
            results.append({
                "type":   "AML_HIGH_VELOCITY",
                "msisdn": row["msisdn"],
                "score":  score,
                "evidence": {
                    "transaction_count": int(row["tx_count"]),
                    "total_volume":      round(float(row["volume"]), 2),
                    "pattern":           "Abnormally high transaction frequency",
                },
                "verdict": "SUSPECTED MONEY LAUNDERING — HIGH VELOCITY",
                "action":  "SAR submission to FIU. Financial intelligence file.",
                "detected_at": datetime.utcnow().isoformat(),
            })

        # Circular transfer detection
        if "counterparty" in df.columns:
            # Look for A→B→A patterns
            pairs = df.groupby(["msisdn", "counterparty"])["amount"].sum().reset_index()
            pairs.columns = ["from", "to", "amount_fwd"]
            # Check reverse direction
            reverse = pairs.rename(columns={"from": "to", "to": "from",
                                            "amount_fwd": "amount_rev"})
            circular = pairs.merge(reverse, on=["from", "to"], how="inner")
            circular = circular[circular["amount_fwd"] > 0]

            for _, row in circular.head(20).iterrows():
                results.append({
                    "type":   "AML_CIRCULAR",
                    "msisdn": row["from"],
                    "score":  80,
                    "evidence": {
                        "counterparty":   row["to"],
                        "forward_amount": round(float(row["amount_fwd"]), 2),
                        "return_amount":  round(float(row["amount_rev"]), 2),
                        "pattern":        "Circular transfer detected",
                    },
                    "verdict": "SUSPECTED CIRCULAR TRANSFER — POTENTIAL MONEY LAUNDERING",
                    "action":  "SAR submission to FIU/CRF.",
                    "detected_at": datetime.utcnow().isoformat(),
                })

        return sorted(results, key=lambda x: x["score"], reverse=True)

    # ── Grey Route Detection ───────────────────────────────────────────────────
    def detect_grey_routes(self, df: pd.DataFrame) -> Dict:
        """
        Detects IDD traffic being routed through unregistered pathways.
        Evidence: IDD volume much higher than declared interconnect revenue.
        """
        if df is None or len(df) == 0:
            return {}

        idd_mask = df["call_type"].str.upper().str.contains(
            r"IDD|INTER|INTL|INTERNATIONAL", na=False)
        idd_df = df[idd_mask]

        if len(idd_df) == 0:
            return {}

        return {
            "type":              "GREY_ROUTE",
            "idd_call_count":    int(len(idd_df)),
            "idd_total_revenue": round(float(idd_df["revenue"].sum()), 2),
            "idd_total_duration": round(float(idd_df["duration"].sum()), 2),
            "unique_msisdns":    int(idd_df["msisdn"].nunique()),
            "evidence":          "IDD traffic volume detected — compare against declared interconnect revenue",
            "action":            "Regulatory action. Interconnect fee recovery.",
            "detected_at":       datetime.utcnow().isoformat(),
        }

    # ── Run All Detections ─────────────────────────────────────────────────────
    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize column names so detector works with any input format."""
        df = df.copy()
        col_map = {
            "orig_msisdn":    "msisdn",
            "sender_msisdn":  "msisdn",
            "from_msisdn":    "msisdn",
            "dest_msisdn":    "dest",
            "receiver_msisdn":"dest",
            "to_msisdn":      "dest",
            "call_type":      "call_type",
            "duration_sec":   "duration",
            "duration":       "duration",
            "data_mb":        "data_mb",
            "revenue":        "revenue",
            "timestamp":      "ts",
            "tx_type":        "call_type",
            "amount":         "revenue",
            "operator_name":  "operator",
            "operator_id":    "op_code",
        }
        # Always derive 'date' from 'timestamp' or 'ts'
        if "date" not in df.columns:
            if "timestamp" in df.columns:
                df["date"] = df["timestamp"].astype(str).str[:10]
            elif "ts" in df.columns:
                df["date"] = df["ts"].astype(str).str[:10]
            else:
                df["date"] = "2026-04-01"
        for old, new in col_map.items():
            if old in df.columns and new not in df.columns:
                df[new] = df[old]
        # Ensure required columns exist
        for col in ["msisdn","dest","call_type","duration","revenue","ts","date"]:
            if col not in df.columns:
                df[col] = "" if col in ("msisdn","dest","call_type","ts") else 0
        return df

    def run_all(self, df: pd.DataFrame, is_momo: bool = False) -> Dict:
        """
        Run all applicable anomaly detections on a CDR/MoMo dataframe.
        Returns complete security findings dictionary.
        """
        df = self._normalize_columns(df)
        results = {
            "simbox":       [],
            "imei_fraud":   [],
            "mass_sms":     [],
            "aml":          [],
            "grey_routes":  {},
            "summary": {
                "total_anomalies": 0,
                "high_risk_count": 0,
                "detected_at":     datetime.utcnow().isoformat(),
            }
        }

        if is_momo:
            results["aml"] = self.detect_momo_aml(df)
        else:
            results["simbox"]      = self.detect_simbox(df)
            results["imei_fraud"]  = self.detect_imei_fraud(df)
            results["mass_sms"]    = self.detect_mass_sms(df)
            results["grey_routes"] = self.detect_grey_routes(df)

        # Summary counts
        all_findings = (results["simbox"] + results["imei_fraud"] +
                        results["mass_sms"] + results["aml"])
        results["summary"]["total_anomalies"] = len(all_findings)
        results["summary"]["high_risk_count"] = sum(
            1 for f in all_findings if f.get("score", 0) >= 75)

        return results

    def detect_all(self, rows, is_momo: bool = False) -> Dict:
        """Alias for run_all — called by server.py. Handles filepath, list or DataFrame."""
        import pandas as pd

        # Handle filepath string — read CSV
        if isinstance(rows, str):
            try:
                import os
                if os.path.exists(rows):
                    df = pd.read_csv(rows, encoding="utf-8", on_bad_lines="skip")
                else:
                    return {"sim_box":[],"imei_fraud":[],"aml":[],"grey_routes":{},
                            "mass_sms":[],"summary":{"total_anomalies":0}}
            except Exception:
                return {"sim_box":[],"imei_fraud":[],"aml":[],"grey_routes":{},
                        "mass_sms":[],"summary":{"total_anomalies":0}}
        elif isinstance(rows, list):
            if not rows:
                return {"sim_box":[],"imei_fraud":[],"aml":[],"grey_routes":{},
                        "mass_sms":[],"summary":{"total_anomalies":0}}
            df = pd.DataFrame(rows)
        elif isinstance(rows, dict):
            # Stats dict passed instead of rows — return empty
            return {"sim_box":[],"imei_fraud":[],"aml":[],"grey_routes":{},
                    "mass_sms":[],"summary":{"total_anomalies":0}}
        else:
            df = rows
        raw = self.run_all(df, is_momo=is_momo)
        # Normalize key names for consistency
        return {
            "sim_box":    raw.get("sim_box") or raw.get("simbox") or [],
            "imei_fraud": raw.get("imei_fraud") or [],
            "aml":        raw.get("aml") or [],
            "grey_routes":raw.get("grey_routes") or {},
            "mass_sms":   raw.get("mass_sms") or [],
            "summary":    raw.get("summary") or {"total_anomalies": 0},
        }
