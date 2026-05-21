"""
NOCTYRA360™ — Universal CDR Decoder Engine
Handles Huawei, Ericsson, Nokia, ZTE, and any custom format.
Auto-detects vendor, delimiter, encoding, date format.
One-time column mapping for unknown formats — saved permanently.
Processes in chunks — handles any file size (1M to 1B+ rows).
"""

import pandas as pd
import numpy as np
import chardet
import hashlib
import json
import re
import os
from datetime import datetime
from typing import Optional, Dict, Tuple, List

# ── Vendor signature patterns ──────────────────────────────────────────────────
VENDOR_SIGNATURES = {
    "Huawei": [
        r"MSC_ID|IMSI|CALLING_NUMBER|CALLED_NUMBER",
        r"servedMSISDN|callingPartyNumber",
        r"^\d{15}\|",
    ],
    "Ericsson": [
        r"MSISDN;DATE;TIME;DURATION",
        r"A-number;B-number",
        r"A-number;CallType",
        r"CallAttemptState",
    ],
    "Nokia": [
        r"originatingMSISDN,terminatingMSISDN",
        r"serviceId,chargeAmount",
        r"Nokia.*CDR",
    ],
    "ZTE": [
        r"GSMCDR|GPRS_CDR",
        r"calling_nbr\|called_nbr",
    ],
    "Comverse": [r"CALL_TYPE,ORIG_MSISDN"],
    "Amdocs":   [r"SUBSCRIBER_ID,SERVICE_TYPE,USAGE"],
}

# ── Known column mappings per vendor ───────────────────────────────────────────
KNOWN_SCHEMAS = {
    "Huawei": {
        "msisdn":    ["CALLING_NUMBER","callingPartyNumber","servedMSISDN",
                      "MSISDN","A_NUMBER","NUMERO_APPELANT","calling_nbr"],
        "call_type": ["SERVICE_TYPE","CALL_TYPE","serviceType","TYPE_APPEL"],
        "date":      ["CALL_DATE","DATE","callDate","DATE_APPEL","START_DATE"],
        "time":      ["CALL_TIME","TIME","callTime","HEURE_APPEL","START_TIME"],
        "duration":  ["DURATION","CALL_DURATION","durationSec","DUREE",
                      "DUREE_APPEL","duration_s"],
        "revenue":   ["CHARGE","AMOUNT","chargeAmount","MONTANT","REVENUE",
                      "REVENU","TARIFF_AMOUNT","revenue"],
        "declared_revenue": ["declared_revenue","DECLARED_REVENUE",
                      "declared","DECL_REVENUE","rev_declared"],
        "tax_declared": ["tax_declared","TAX_DECLARED","tax_decl",
                      "TAX_DECL","impot_declare"],
        "tax_due":    ["tax_due","TAX_DUE","impot_du","TAX_DU"],
        "tax_gap":    ["tax_gap","TAX_GAP","ecart_fiscal","ECART"],
        "b_number":  ["CALLED_NUMBER","terminatingMSISDN","B_NUMBER",
                      "NUMERO_APPELE","called_nbr"],
        "imsi":      ["IMSI","imsi"],
        "imei":      ["IMEI","imei","TERMINAL_ID"],
        "cell_id":   ["CELL_ID","cellId","CELL","CELLULE"],
    },
    "Ericsson": {
        "msisdn":    ["A-number","A_NUMBER","MSISDN","CallingParty","a-number"],
        "call_type": ["CallType","CALL_TYPE","ServiceType","SERVICE"],
        "date":      ["Date","DATE","StartDate","START_DATE"],
        "time":      ["Time","TIME","StartTime","START_TIME"],
        "duration":  ["Duration","DURATION","CallDuration","DurationSec"],
        "revenue":   ["Charge","CHARGE","Amount","AMOUNT","TariffAmount"],
        "b_number":  ["B-number","B_NUMBER","CalledParty","called_party","b-number"],
        "imei":      ["IMEI","Imei","TerminalId"],
        "cell_id":   ["CellId","CELL_ID","LocationAreaCode"],
    },
    "Nokia": {
        "msisdn":    ["originatingMSISDN","MSISDN","originParty"],
        "call_type": ["serviceId","SERVICE_ID","callType"],
        "date":      ["startDate","START_DATE","callDate"],
        "time":      ["startTime","START_TIME","callTime"],
        "duration":  ["duration","DURATION","callDuration"],
        "revenue":   ["chargeAmount","CHARGE_AMOUNT","amount"],
        "b_number":  ["terminatingMSISDN","terminParty","B_MSISDN"],
    },
    "Generic": {
        "msisdn":    ["msisdn","MSISDN","phone","subscriber","calling",
                      "a_number","a-number","numero","NUMERO","A_MSISDN"],
        "call_type": ["type","call_type","service","SERVICE","TYPE","CALL_TYPE"],
        "date":      ["date","DATE","call_date","jour","JOUR","CALL_DATE"],
        "time":      ["time","TIME","heure","HEURE","call_time","CALL_TIME"],
        "duration":  ["duration","DURATION","duree","DUREE","dur","seconds"],
        "revenue":   ["revenue","REVENUE","amount","AMOUNT","charge","Charge",
                      "montant","MONTANT","tariff","REVENUE_MGA"],
        "b_number":  ["b_number","B_NUMBER","called","destination","dest",
                      "B_MSISDN","CALLED_NUMBER"],
        "imei":      ["imei","IMEI","terminal","TERMINAL"],
    }
}

MOMO_SCHEMAS = {
    "Generic_MoMo": {
        "msisdn":       ["MSISDN","msisdn","subscriber","SUBSCRIBER","wallet","WALLET"],
        "tx_type":      ["TX_TYPE","transaction_type","TYPE","type","operation","OPERATION"],
        "date":         ["DATE","date","tx_date","TRANSACTION_DATE","CALL_DATE"],
        "time":         ["TIME","time","tx_time","CALL_TIME"],
        "amount":       ["AMOUNT","amount","MONTANT","montant","value","VALUE","REVENUE_MGA"],
        "fee":          ["FEE","fee","FRAIS","frais","commission","COMMISSION","CHARGE"],
        "counterparty": ["COUNTERPARTY","to_msisdn","TO","destination","DEST","B_NUMBER"],
        "agent_id":     ["AGENT_ID","agent","AGENT","agent_code","AGENT_CODE"],
        "status":       ["STATUS","status","STATUT","result","RESULT","STATE"],
        "tx_id":        ["TX_ID","transaction_id","TRANSACTION_ID","ref","REF","ID"],
    }
}


class CDRDecoder:
    """
    Universal CDR/MoMo decoder.
    Call process_file() — everything else is automatic.
    """

    CHUNK_SIZE = 100_000  # rows per chunk — safe for any RAM

    def __init__(self, schema_registry_path: str = "schema_registry.json"):
        self.registry_path      = schema_registry_path
        self.registry           = self._load_registry()
        self.detected_vendor    = "Generic"
        self.detected_delimiter = ","
        self.detected_encoding  = "utf-8"
        self.column_map         = {}
        self.is_momo            = False

    # ── Registry ──────────────────────────────────────────────────────────────
    def _load_registry(self) -> dict:
        if os.path.exists(self.registry_path):
            with open(self.registry_path, "r") as f:
                return json.load(f)
        return {}

    def _save_registry(self):
        with open(self.registry_path, "w") as f:
            json.dump(self.registry, f, indent=2)

    def _key(self, operator: str) -> str:
        return operator.lower().replace(" ", "_")

    def has_saved_schema(self, operator: str) -> bool:
        return self._key(operator) in self.registry

    def load_saved_schema(self, operator: str) -> bool:
        key = self._key(operator)
        if key in self.registry:
            s = self.registry[key]
            self.column_map         = s["column_map"]
            self.detected_vendor    = s.get("vendor", "Generic")
            self.detected_delimiter = s.get("delimiter", ",")
            self.detected_encoding  = s.get("encoding", "utf-8")
            self.is_momo            = s.get("is_momo", False)
            print(f"  ✅ Loaded saved schema for {operator} "
                  f"(vendor: {self.detected_vendor}) — fully automatic")
            return True
        return False

    def save_schema(self, operator: str):
        self.registry[self._key(operator)] = {
            "operator":   operator,
            "vendor":     self.detected_vendor,
            "delimiter":  self.detected_delimiter,
            "encoding":   self.detected_encoding,
            "column_map": self.column_map,
            "is_momo":    self.is_momo,
            "saved_at":   datetime.utcnow().isoformat(),
        }
        self._save_registry()
        print(f"  ✅ Schema saved permanently — "
              f"next month {operator} will be fully automatic")

    # ── Detection ─────────────────────────────────────────────────────────────
    def detect_encoding(self, filepath: str) -> str:
        with open(filepath, "rb") as f:
            raw = f.read(50_000)
        result = chardet.detect(raw)
        enc = (result.get("encoding") or "utf-8")
        enc = enc.replace("ISO-8859-1", "latin-1").replace("windows-1252", "latin-1")
        self.detected_encoding = enc
        print(f"  Encoding: {enc} (confidence: {result.get('confidence',0):.0%})")
        return enc

    def detect_delimiter(self, filepath: str, encoding: str) -> str:
        candidates = ["|", ";", ",", "\t", "^", "~"]
        counts = {d: 0 for d in candidates}
        try:
            with open(filepath, "r", encoding=encoding, errors="replace") as f:
                sample = "".join(f.readline() for _ in range(20))
            for d in candidates:
                counts[d] = sample.count(d)
        except Exception:
            pass
        delim = max(counts, key=counts.get)
        if counts[delim] == 0:
            delim = ","
        self.detected_delimiter = delim
        names = {"|":"PIPE",";":"SEMICOLON",",":"COMMA","\t":"TAB","^":"CARET"}
        print(f"  Delimiter: {names.get(delim, repr(delim))}")
        return delim

    def detect_vendor(self, filepath: str, encoding: str,
                      delimiter: str) -> str:
        try:
            with open(filepath, "r", encoding=encoding, errors="replace") as f:
                header_block = "".join(f.readline() for _ in range(5))
        except Exception:
            return "Generic"

        # MoMo detection
        momo_kw = ["TRANSACTION","TX_TYPE","WALLET","MOBILE_MONEY","TX_ID",
                   "MOMO","AIRTEL_MONEY","MVOLA","ORANGE_MONEY",
                   "commission","FEE","transfer","TRANSFER"]
        if sum(1 for kw in momo_kw if kw.lower() in header_block.lower()) >= 2:
            self.is_momo = True
            print(f"  File type: MOBILE MONEY (MoMo)")
            return "Generic_MoMo"

        # Vendor detection
        scores = {}
        for vendor, patterns in VENDOR_SIGNATURES.items():
            score = sum(1 for p in patterns
                        if re.search(p, header_block, re.IGNORECASE))
            if score > 0:
                scores[vendor] = score

        if scores:
            best = max(scores, key=scores.get)
            print(f"  Vendor: {best}")
            return best

        print(f"  Vendor: Generic (will use auto-mapping)")
        return "Generic"

    def map_columns(self, actual_columns: List[str], vendor: str) -> Dict[str, str]:
        schema_src = MOMO_SCHEMAS if self.is_momo else KNOWN_SCHEMAS
        schema = schema_src.get(vendor, schema_src.get("Generic", {}))
        if not schema:
            schema = KNOWN_SCHEMAS["Generic"]

        mapping = {}
        actual_lower = {c.lower(): c for c in actual_columns}

        for field, candidates in schema.items():
            # Exact match
            for cand in candidates:
                if cand.lower() in actual_lower:
                    mapping[field] = actual_lower[cand.lower()]
                    break
            # Fuzzy match if still not found
            if field not in mapping:
                for actual in actual_columns:
                    if field.lower() in actual.lower():
                        mapping[field] = actual
                        break

        found = len(mapping)
        total = len(schema)
        print(f"  Columns mapped: {found}/{total} fields automatically")
        return mapping

    # ── Normalization ──────────────────────────────────────────────────────────
    def normalize_chunk(self, chunk: pd.DataFrame) -> pd.DataFrame:
        cm = self.column_map

        def get_col(field, default=None):
            col = cm.get(field)
            if col and col in chunk.columns:
                return chunk[col]
            return pd.Series([default] * len(chunk), index=chunk.index)

        result = pd.DataFrame(index=chunk.index)

        if self.is_momo:
            result["msisdn"]       = get_col("msisdn", "").astype(str).str.strip()
            result["tx_type"]      = get_col("tx_type", "UNKNOWN").astype(str)
            result["date"]         = get_col("date", "").astype(str)
            result["time"]         = get_col("time", "00:00:00").astype(str)
            result["amount"]       = pd.to_numeric(get_col("amount", 0), errors="coerce").fillna(0)
            result["fee"]          = pd.to_numeric(get_col("fee", 0), errors="coerce").fillna(0)
            result["counterparty"] = get_col("counterparty", "").astype(str)
            result["agent_id"]     = get_col("agent_id", "").astype(str)
            result["status"]       = get_col("status", "OK").astype(str)
            result["tx_id"]        = get_col("tx_id", "").astype(str)
        else:
            result["msisdn"]    = get_col("msisdn", "").astype(str).str.strip()
            result["call_type"] = get_col("call_type", "VOICE").astype(str)
            result["date"]      = get_col("date", "").astype(str)
            result["time"]      = get_col("time", "00:00:00").astype(str)
            result["duration"]  = pd.to_numeric(get_col("duration", 0), errors="coerce").fillna(0)
            result["revenue"]          = pd.to_numeric(get_col("revenue", 0), errors="coerce").fillna(0)
            # Preserve declared_revenue, tax_declared, tax_gap from CDR rows
            # Direct access to raw declared columns (bypass schema mapping)
            def raw_col(name, default=0):
                if name in chunk.columns:
                    return pd.to_numeric(chunk[name], errors="coerce").fillna(default)
                return pd.Series([default]*len(chunk), index=chunk.index)
            result["declared_revenue"] = raw_col("declared_revenue")
            result["tax_declared"]     = raw_col("tax_declared")
            result["tax_due_row"]      = raw_col("tax_due")
            result["tax_gap_row"]      = raw_col("tax_gap")
            result["b_number"]  = get_col("b_number", "").astype(str)
            result["imei"]      = get_col("imei", "").astype(str)
            result["cell_id"]   = get_col("cell_id", "").astype(str)

        # Filter invalid MSISDNs
        result = result[result["msisdn"].str.len() >= 7]
        result = result[result["msisdn"].str.lower() != "nan"]
        return result.reset_index(drop=True)

    @staticmethod
    def validate_imei(imei: str) -> bool:
        digits = re.sub(r"\D", "", str(imei))
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

    # ── MAIN ENTRY POINT ──────────────────────────────────────────────────────
    def process_file(self, filepath: str, operator: str,
                     progress_callback=None) -> dict:
        """
        Process ANY CDR file — any size, any vendor format.
        Returns aggregated statistics ready for EFR calculation.
        """
        print(f"\n{'='*60}")
        print(f"  NOCTYRA360™ CDR DECODER")
        print(f"  File:     {os.path.basename(filepath)}")
        print(f"  Operator: {operator}")
        print(f"  Size:     {os.path.getsize(filepath)/1_048_576:.1f} MB")
        print(f"{'='*60}")

        # Step 1: Load saved schema OR auto-detect
        if self.has_saved_schema(operator):
            self.load_saved_schema(operator)
        else:
            print(f"\n  [AUTO-DETECTING FORMAT...]")
            enc    = self.detect_encoding(filepath)
            delim  = self.detect_delimiter(filepath, enc)
            vendor = self.detect_vendor(filepath, enc, delim)
            self.detected_vendor = vendor

            try:
                header_df = pd.read_csv(
                    filepath, sep=delim, encoding=enc,
                    nrows=0, on_bad_lines="skip",
                    encoding_errors="replace"
                )
                actual_cols = list(header_df.columns)
            except Exception:
                actual_cols = []

            self.column_map = self.map_columns(actual_cols, vendor)
            self.save_schema(operator)

        # Step 2: Process in chunks
        print(f"\n  [PROCESSING RECORDS...]")
        all_chunks = []
        total_rows = 0
        bad_rows   = 0
        chunk_num  = 0

        try:
            reader = pd.read_csv(
                filepath,
                sep=self.detected_delimiter,
                encoding=self.detected_encoding,
                chunksize=self.CHUNK_SIZE,
                on_bad_lines="skip",
                encoding_errors="replace",
                low_memory=False,
            )

            for chunk in reader:
                chunk_num += 1
                raw_count  = len(chunk)
                normalized = self.normalize_chunk(chunk)
                good       = len(normalized)
                bad_rows  += (raw_count - good)
                total_rows += good
                all_chunks.append(normalized)

                if progress_callback:
                    progress_callback(chunk_num, total_rows)
                if chunk_num % 10 == 0:
                    print(f"  ... {total_rows:,} records processed")

        except Exception as e:
            return {"error": str(e), "total_rows": 0}

        print(f"  Valid records:    {total_rows:,}")
        print(f"  Rejected rows:    {bad_rows:,}")

        if not all_chunks:
            return {"error": "No valid records", "total_rows": 0}

        # Step 3: Aggregate
        full_df    = pd.concat(all_chunks, ignore_index=True)
        input_hash = hashlib.sha256(
            full_df.to_json().encode()
        ).hexdigest()

        stats = self._compute_stats(full_df)
        stats.update({
            "operator":     operator,
            "vendor":       self.detected_vendor,
            "total_rows":   total_rows,
            "bad_rows":     bad_rows,
            "is_momo":      self.is_momo,
            "input_hash":   input_hash,
            "processed_at": datetime.utcnow().isoformat(),
        })

        print(f"\n  ✅ DECODE COMPLETE — {total_rows:,} records")
        print(f"  Input hash: {input_hash[:20]}...")
        return stats

    def _compute_stats(self, df: pd.DataFrame) -> dict:
        if self.is_momo:
            return {
                "total_transactions":  len(df),
                "total_amount":        float(df["amount"].sum()),
                "total_fees":          float(df["fee"].sum()),
                "unique_subscribers":  int(df["msisdn"].nunique()),
                "unique_agents":       int(df["agent_id"].nunique()),
                "tx_types":            df["tx_type"].value_counts().to_dict(),
                "failed_tx":           int(
                    df["status"].str.upper().isin(
                        ["FAILED","ERROR","REJECTED"]).sum()),
            }
        else:
            def rev_for(keywords):
                mask = df["call_type"].str.upper().str.contains(
                    keywords, na=False)
                return float(df.loc[mask, "revenue"].sum())

            invalid_imei = 0
            if "imei" in df.columns:
                imei_col = df["imei"].astype(str)
                has_imei = imei_col[imei_col.str.len() > 5]
                invalid_imei = int(
                    has_imei.apply(self.validate_imei).eq(False).sum())

            return {
                "total_revenue":       float(df["revenue"].sum()),
                "total_declared_revenue": float(df["declared_revenue"].sum())
                                          if "declared_revenue" in df.columns else 0,
                "declared_revenue":    float(df["declared_revenue"].sum()) if "declared_revenue" in df.columns and df["declared_revenue"].sum() > 0 else 0,
                "total_tax_declared":  float(df["tax_declared"].sum())
                                       if "tax_declared" in df.columns else 0,
                "total_tax_due":       float(df["tax_due"].sum())
                                       if "tax_due" in df.columns else 0,
                "total_tax_gap":       float(df["tax_gap"].sum())
                                       if "tax_gap" in df.columns else 0,
                "total_duration_sec":  float(df["duration"].sum()),
                "unique_subscribers":  int(df["msisdn"].nunique()),
                "voice_revenue":       rev_for(r"VOICE|CALL|VOX|APP"),
                "data_revenue":        rev_for(r"DATA|GPRS|LTE|4G|3G|INTERNET"),
                "sms_revenue":         rev_for(r"SMS|TEXT|MSG"),
                "idd_revenue":         rev_for(r"IDD|INTER|ROAM|INTL"),
                "invalid_imei_count":  invalid_imei,
                "call_type_breakdown": df["call_type"].value_counts().head(10).to_dict(),
            }
