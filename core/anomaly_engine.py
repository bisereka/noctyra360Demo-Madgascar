"""
NOCTYRA360™ — Anomaly Detection Engine
Scores SIM Box activity, IMEI fraud, MoMo laundering patterns.
All AI scoring built on field-validated rules from CAR deployment.
"""
import re
from typing import List, Dict

class AnomalyEngine:
    SIMBOX_THRESHOLD = 85

    def score_simbox(self, records: List[Dict]) -> List[Dict]:
        """Score each MSISDN for SIM Box probability (0-100)."""
        from collections import defaultdict
        msisdn_stats = defaultdict(lambda: {
            "idd_count":0,"local_count":0,"total":0,
            "nocturnal":0,"short_calls":0,"revenue":0
        })
        for r in records:
            m = r.get("msisdn","")
            ct = str(r.get("call_type","")).upper()
            hour = int(str(r.get("time","00:00:00"))[:2] or 0)
            dur  = float(r.get("duration",0))
            msisdn_stats[m]["total"] += 1
            msisdn_stats[m]["revenue"] += float(r.get("revenue",0))
            if any(k in ct for k in ["IDD","INTL","INTER","ROAM"]):
                msisdn_stats[m]["idd_count"] += 1
            else:
                msisdn_stats[m]["local_count"] += 1
            if 0 <= hour <= 5 or hour >= 22:
                msisdn_stats[m]["nocturnal"] += 1
            if 0 < dur < 30:
                msisdn_stats[m]["short_calls"] += 1

        flagged = []
        for msisdn, s in msisdn_stats.items():
            score = 0
            t = s["total"]
            if t == 0:
                continue
            # IDD ratio >70% of calls
            if t > 0 and (s["idd_count"]/t) > 0.70:
                score += 40
            # Nocturnal pattern >60% of calls between 22:00-05:00
            if (s["nocturnal"]/t) > 0.60:
                score += 25
            # High volume >500 calls/day equivalent
            if t > 500:
                score += 15
            # Short duration >80% calls under 30s
            if (s["short_calls"]/t) > 0.80:
                score += 20
            if score >= self.SIMBOX_THRESHOLD:
                flagged.append({
                    "msisdn": msisdn,
                    "score":  score,
                    "type":   "SIM_BOX",
                    "idd_ratio": round(s["idd_count"]/t*100,1),
                    "nocturnal_ratio": round(s["nocturnal"]/t*100,1),
                    "total_calls": t,
                    "revenue_lost": s["revenue"],
                    "action": "Criminal prosecution / Interconnect recovery",
                })
        return sorted(flagged, key=lambda x: x["score"], reverse=True)

    def _luhn_checksum(self, s):
        digits = [int(d) for d in s]
        odd = digits[-1::-2]
        even = digits[-2::-2]
        return (sum(odd) + sum(sum(int(x) for x in str(d*2)) for d in even)) % 10

    def check_imei(self, imei: str) -> dict:
        """Professional IMEI validation: Luhn + TAC check."""
        digits = re.sub(r"\D","",str(imei))
        if len(digits) != 15:
            return {"valid":False,"reason":"Wrong length","imei":imei}
        if digits in ("0"*15,"1"*15) or digits[:2]=="00":
            return {"valid":False,"reason":"Invalid TAC","imei":imei}
        cs = self._luhn_checksum(digits)
        valid = cs == 0
        return {"valid":valid,"reason":"Valid" if valid else "Luhn check failed","imei":imei}

    def score_momo_aml(self, records: List[Dict]) -> List[Dict]:
        """Detect AML patterns in MoMo transactions."""
        from collections import defaultdict
        msisdn_stats = defaultdict(lambda:{
            "p2p_count":0,"total_sent":0,"total_recv":0,
            "unique_counterparties":set(),"tx_count":0,
            "amounts":[]
        })
        for r in records:
            m  = r.get("msisdn","")
            tt = str(r.get("tx_type","")).upper()
            amt = float(r.get("amount",0))
            cp  = r.get("counterparty","")
            msisdn_stats[m]["tx_count"] += 1
            msisdn_stats[m]["amounts"].append(amt)
            if cp:
                msisdn_stats[m]["unique_counterparties"].add(cp)
            if "P2P" in tt or "TRANSFER" in tt or "SEND" in tt:
                msisdn_stats[m]["p2p_count"] += 1
                msisdn_stats[m]["total_sent"] += amt
            if "RECEIVE" in tt or "RECV" in tt:
                msisdn_stats[m]["total_recv"] += amt

        flagged = []
        for msisdn, s in msisdn_stats.items():
            score = 0
            reasons = []
            # High P2P volume
            if s["p2p_count"] > 200:
                score += 30
                reasons.append(f"High P2P volume: {s['p2p_count']} transfers")
            # Structuring: many transactions just below reporting threshold
            amounts = s["amounts"]
            if amounts:
                threshold = max(amounts) * 0.95
                near_threshold = sum(1 for a in amounts if a >= threshold*0.85)
                if near_threshold/len(amounts) > 0.3:
                    score += 35
                    reasons.append("Structuring pattern detected")
            # Many unique counterparties (chain layering)
            n_cp = len(s["unique_counterparties"])
            if n_cp > 50:
                score += 25
                reasons.append(f"Layering: {n_cp} unique counterparties")
            # Send/receive imbalance (circular)
            if s["total_sent"] > 0 and s["total_recv"] > 0:
                ratio = min(s["total_sent"],s["total_recv"]) / \
                        max(s["total_sent"],s["total_recv"])
                if ratio > 0.85:
                    score += 20
                    reasons.append("Circular transfer pattern")
            if score >= 60:
                flagged.append({
                    "msisdn":  msisdn,
                    "score":   score,
                    "type":    "AML_SUSPICION",
                    "reasons": reasons,
                    "total_sent": s["total_sent"],
                    "total_recv": s["total_recv"],
                    "tx_count":   s["tx_count"],
                    "action": "SAR — Submit to Financial Intelligence Unit",
                })
        return sorted(flagged, key=lambda x: x["score"], reverse=True)
