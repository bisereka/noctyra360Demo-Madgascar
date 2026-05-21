"""
NOCTYRA360™ — Couche de persistance PostgreSQL
Connect Now USA LLC — Confidentiel

Toutes les données survivent aux redémarrages du serveur.
Tables : jobs · findings · anomalies · reports · config_history
"""

import os, json, hashlib
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import (
    create_engine, text, Column, String, Integer, Float,
    DateTime, Boolean, Text, BigInteger, JSON
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import StaticPool

# ── Connexion ──────────────────────────────────────────────────────────────
DB_URL = os.environ.get(
    "N360_DATABASE_URL",
    "postgresql://noctyra360:@/noctyra360db"
)

# Fallback SQLite si PostgreSQL non disponible
def _create_engine():
    try:
        eng = create_engine(
            DB_URL,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            echo=False
        )
        # Tester la connexion
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        print(f"  ✅ Base de données: PostgreSQL ({DB_URL.split('@')[-1]})")
        return eng, "postgresql"
    except Exception as e:
        # Fallback SQLite persistant
        sqlite_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "noctyra360.db"
        )
        eng = create_engine(
            f"sqlite:///{sqlite_path}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            echo=False
        )
        # PostgreSQL pas disponible — SQLite persistant (données sauvegardées sur disque)
        print(f"  ⚠️  PostgreSQL: {str(e)[:60]}")
        print(f"  ✅  SQLite persistant: {sqlite_path}")
        print(f"  ℹ️   Données conservées au redémarrage via SQLite")
        return eng, "sqlite"

engine, DB_TYPE = _create_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

# ── Modèles ────────────────────────────────────────────────────────────────

class Job(Base):
    """Tâche de traitement CDR."""
    __tablename__ = "n360_jobs"

    id          = Column(String(64), primary_key=True)
    status      = Column(String(32), default="pending")   # pending|processing|complete|error
    progress    = Column(Integer, default=0)
    total_rows  = Column(BigInteger, default=0)
    operator    = Column(String(100), default="")
    country     = Column(String(100), default="")
    period      = Column(String(50), default="")
    is_momo     = Column(Boolean, default=False)
    filename    = Column(String(255), default="")
    error       = Column(Text, default="")
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at= Column(DateTime, nullable=True)

class Finding(Base):
    """Résultat EFR certifié d'un traitement."""
    __tablename__ = "n360_findings"

    id              = Column(String(64), primary_key=True)
    job_id          = Column(String(64), index=True)
    operator        = Column(String(100), index=True)
    country         = Column(String(100), index=True)
    period          = Column(String(50),  index=True)
    currency        = Column(String(10))
    is_momo         = Column(Boolean, default=False)

    # Chiffres clés
    total_revenue   = Column(Float, default=0)
    tax_due         = Column(Float, default=0)
    declared_revenue= Column(Float, default=0)
    efr_gap         = Column(Float, default=0)
    gap_pct         = Column(Float, default=0)
    total_records   = Column(BigInteger, default=0)
    compliance_pct  = Column(Float, default=0)

    # Certification
    sha256          = Column(String(128))
    certified_at    = Column(DateTime, default=datetime.utcnow)

    # Données complètes (JSON)
    finding_json    = Column(Text)   # finding dict complet
    anomalies_json  = Column(Text)   # anomalies dict complet
    reports_json    = Column(Text)   # chemins des fichiers générés

    created_at      = Column(DateTime, default=datetime.utcnow)

class ConfigHistory(Base):
    """Historique des configurations pays."""
    __tablename__ = "n360_config_history"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    country    = Column(String(100))
    currency   = Column(String(10))
    ccode      = Column(String(10))
    config_json= Column(Text)
    applied_at = Column(DateTime, default=datetime.utcnow)

class AuditLog(Base):
    """Journal d'audit pour ISO 27001."""
    __tablename__ = "n360_audit_log"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    action     = Column(String(100))
    operator   = Column(String(100), default="")
    country    = Column(String(100), default="")
    details    = Column(Text, default="")
    ip_addr    = Column(String(50), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

# ── Initialisation ─────────────────────────────────────────────────────────

def init_db():
    """Créer toutes les tables si elles n'existent pas."""
    try:
        Base.metadata.create_all(engine)
        print("  ✅ Tables créées/vérifiées: n360_jobs · n360_findings · n360_config_history · n360_audit_log")
        return True
    except Exception as e:
        print(f"  ❌ Erreur création tables: {e}")
        return False

def get_db() -> Session:
    """Obtenir une session de base de données."""
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise

# ── CRUD Jobs ──────────────────────────────────────────────────────────────

def db_create_job(jid: str, data: dict) -> bool:
    db = SessionLocal()
    try:
        job = Job(
            id=jid,
            status=data.get("status","pending"),
            progress=data.get("progress",0),
            total_rows=data.get("total_rows",0),
            operator=data.get("operator",""),
            country=data.get("country",""),
            period=data.get("period",""),
            is_momo=data.get("is_momo",False),
            filename=data.get("filename",""),
        )
        db.add(job)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"  ❌ db_create_job: {e}")
        return False
    finally:
        db.close()

def db_update_job(jid: str, updates: dict) -> bool:
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == jid).first()
        if not job:
            return False
        for k, v in updates.items():
            if hasattr(job, k):
                setattr(job, k, v)
        job.updated_at = datetime.utcnow()
        if updates.get("status") == "complete":
            job.completed_at = datetime.utcnow()
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"  ❌ db_update_job: {e}")
        return False
    finally:
        db.close()

def db_get_job(jid: str) -> Optional[dict]:
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == jid).first()
        if not job:
            return None
        return {
            "job_id":    job.id,
            "status":    job.status,
            "progress":  job.progress,
            "total_rows":job.total_rows,
            "operator":  job.operator,
            "country":   job.country,
            "period":    job.period,
            "error":     job.error,
            "created_at":str(job.created_at),
        }
    finally:
        db.close()

def db_get_jobs_recent(limit: int = 50) -> List[dict]:
    db = SessionLocal()
    try:
        jobs = db.query(Job).order_by(Job.created_at.desc()).limit(limit).all()
        return [
            {"job_id":j.id,"status":j.status,"operator":j.operator,
             "country":j.country,"period":j.period,"total_rows":j.total_rows,
             "created_at":str(j.created_at)}
            for j in jobs
        ]
    finally:
        db.close()

# ── CRUD Findings ──────────────────────────────────────────────────────────

def db_save_finding(jid: str, finding: dict,
                    anomalies: dict, reports: dict) -> bool:
    db = SessionLocal()
    try:
        gap     = finding.get("gap") or {}
        efr_gap = gap.get("tax_gap_local") or gap.get("tax_gap") or 0
        tax_due = finding.get("tax_due") or 0
        tax_dcl = finding.get("declared_revenue") or 0
        comp    = (tax_dcl / tax_due * 100) if tax_due > 0 else 0

        fid = hashlib.sha256(f"{jid}{finding.get('sha256','')}".encode()).hexdigest()[:32]

        f = Finding(
            id=fid, job_id=jid,
            operator  = finding.get("operator",""),
            country   = finding.get("country",""),
            period    = finding.get("period",""),
            currency  = finding.get("currency","XAF"),
            is_momo   = finding.get("is_momo", False),
            total_revenue   = finding.get("total_revenue",0),
            tax_due         = tax_due,
            declared_revenue= tax_dcl,
            efr_gap         = efr_gap,
            gap_pct         = gap.get("gap_pct", 0),
            total_records   = finding.get("total_records",0),
            compliance_pct  = comp,
            sha256    = finding.get("sha256",""),
            finding_json  = json.dumps(finding,  default=str),
            anomalies_json= json.dumps(anomalies, default=str),
            reports_json  = json.dumps(reports,   default=str),
        )
        db.merge(f)  # INSERT OR UPDATE
        db.commit()

        # Audit log
        db_audit("CDR_PROCESSED",
                  finding.get("operator",""),
                  finding.get("country",""),
                  f"EFR Gap: {efr_gap:,.0f} {finding.get('currency','')}")
        return True
    except Exception as e:
        db.rollback()
        print(f"  ❌ db_save_finding: {e}")
        return False
    finally:
        db.close()

def db_get_finding_by_job(jid: str) -> Optional[dict]:
    db = SessionLocal()
    try:
        f = db.query(Finding).filter(Finding.job_id == jid).first()
        if not f:
            return None
        result = {
            "finding":   json.loads(f.finding_json)   if f.finding_json   else {},
            "anomalies": json.loads(f.anomalies_json) if f.anomalies_json else {},
            "reports":   json.loads(f.reports_json)   if f.reports_json   else {},
        }
        return result
    finally:
        db.close()

def db_get_findings_history(country: str = "", limit: int = 100) -> List[dict]:
    """Historique des résultats par pays."""
    db = SessionLocal()
    try:
        q = db.query(Finding).order_by(Finding.certified_at.desc())
        if country:
            q = q.filter(Finding.country.ilike(f"%{country}%"))
        findings = q.limit(limit).all()
        return [{
            "id":           f.id,
            "operator":     f.operator,
            "country":      f.country,
            "period":       f.period,
            "currency":     f.currency,
            "total_revenue":f.total_revenue,
            "tax_due":      f.tax_due,
            "efr_gap":      f.efr_gap,
            "compliance":   f.compliance_pct,
            "total_records":f.total_records,
            "sha256":       f.sha256,
            "certified_at": str(f.certified_at),
        } for f in findings]
    finally:
        db.close()

def db_get_stats(country: str = "") -> dict:
    """Statistiques agrégées pour le dashboard."""
    db = SessionLocal()
    try:
        q = db.query(Finding)
        if country:
            q = q.filter(Finding.country.ilike(f"%{country}%"))
        findings = q.all()
        if not findings:
            return {"total_findings":0, "total_efr_gap":0, "avg_compliance":0}
        return {
            "total_findings": len(findings),
            "total_efr_gap":  sum(f.efr_gap or 0 for f in findings),
            "total_revenue":  sum(f.total_revenue or 0 for f in findings),
            "total_records":  sum(f.total_records or 0 for f in findings),
            "avg_compliance": sum(f.compliance_pct or 0 for f in findings)/len(findings),
            "countries":      list({f.country for f in findings}),
            "operators":      list({f.operator for f in findings}),
        }
    finally:
        db.close()

# ── Config History ─────────────────────────────────────────────────────────

def db_save_config(config: dict) -> bool:
    db = SessionLocal()
    try:
        c = ConfigHistory(
            country    = config.get("country",""),
            currency   = config.get("currency",""),
            ccode      = config.get("ccode",""),
            config_json= json.dumps(config, default=str),
        )
        db.add(c)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"  ❌ db_save_config: {e}")
        return False
    finally:
        db.close()

# ── Audit Log ──────────────────────────────────────────────────────────────

def db_audit(action: str, operator: str = "",
             country: str = "", details: str = "") -> None:
    db = SessionLocal()
    try:
        log = AuditLog(
            action=action, operator=operator,
            country=country, details=details
        )
        db.add(log)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

def db_get_audit_log(limit: int = 200) -> List[dict]:
    db = SessionLocal()
    try:
        logs = db.query(AuditLog).order_by(
            AuditLog.created_at.desc()
        ).limit(limit).all()
        return [{
            "action":    l.action,
            "operator":  l.operator,
            "country":   l.country,
            "details":   l.details,
            "created_at":str(l.created_at),
        } for l in logs]
    finally:
        db.close()

# ── Initialiser au démarrage ───────────────────────────────────────────────
if __name__ != "__main__":
    init_db()

if __name__ == "__main__":
    print("=== TEST DATABASE ===")
    init_db()

    # Test complet
    db_create_job("test-001", {
        "status":"complete","operator":"Telma",
        "country":"Madagascar","period":"Avril 2026",
        "total_rows":100000
    })

    db_save_finding("test-001",
        {"operator":"Telma","country":"Madagascar","period":"Avril 2026",
         "currency":"MGA","total_revenue":2081479529,"tax_due":520369882,
         "declared_revenue":385073713,"total_records":100000,
         "sha256":"abc123","gap":{"tax_gap":135296169,"tax_gap_local":135296169}},
        {"sim_box":[],"imei_fraud":[],"aml":[]},
        {"pdf":"/reports/test.pdf"}
    )

    history = db_get_findings_history("Madagascar")
    print(f"✅ Findings sauvegardés: {len(history)}")

    stats = db_get_stats("Madagascar")
    print(f"✅ Stats: {stats}")

    jobs = db_get_jobs_recent()
    print(f"✅ Jobs récents: {len(jobs)}")

    print("✅ Base de données opérationnelle")
