"""
NOCTYRA360™ — Notifications Email Automatiques
Connect Now USA LLC — Confidentiel

2 types de notifications :
  1. Rapport prêt → email aux utilisateurs gouvernement
  2. Anomalie critique → alerte immédiate au superviseur

Configuration SMTP dans config/email_config.json
Support : Gmail · Outlook · SMTP entreprise
"""

import os, json, asyncio, logging
from pathlib import Path
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Optional

log = logging.getLogger("N360.Email")

BASE_DIR    = Path(__file__).parent.parent
CONFIG_DIR  = BASE_DIR / "config"
EMAIL_CFG   = CONFIG_DIR / "email_config.json"

# ══════════════════════════════════════════════════════════════
# CONFIGURATION EMAIL
# ══════════════════════════════════════════════════════════════

DEFAULT_CONFIG = {
    "enabled":        False,    # Mettre True après configuration
    "smtp_host":      "smtp.gmail.com",
    "smtp_port":      587,
    "smtp_user":      "noctyra360@gmail.com",
    "smtp_password":  "MOT_DE_PASSE_APP_GMAIL",
    "smtp_tls":       True,
    "from_name":      "NOCTYRA360™ — Connect Now USA LLC",
    "from_email":     "noctyra360@gmail.com",

    # Destinataires par type
    "recipients": {
        "report_ready": [
            "dgi@gouvernement.mg",
            "artec@artec.mg",
        ],
        "anomaly_critical": [
            "dgi@gouvernement.mg",
            "superviseur@artec.mg",
        ],
        "anomaly_simbox": [
            "police@securite.mg",
            "artec@artec.mg",
        ],
        "anomaly_aml": [
            "bfm@banquecentrale.mg",
            "dgi@gouvernement.mg",
        ],
        "system_error": [
            "admin@noctyra360.com",
        ],
    },

    # Seuils pour alertes automatiques
    "thresholds": {
        "efr_gap_alert_pct":      5.0,   # Alerter si gap > 5% du revenue
        "simbox_count_alert":     100,   # Alerter si > 100 suspects
        "aml_count_alert":        50,    # Alerter si > 50 transactions AML
        "compliance_low_alert":   70.0,  # Alerter si compliance < 70%
    }
}

def load_email_config() -> dict:
    try:
        if EMAIL_CFG.exists():
            return json.loads(EMAIL_CFG.read_text())
    except Exception:
        pass
    return DEFAULT_CONFIG

def save_email_config(cfg: dict):
    CONFIG_DIR.mkdir(exist_ok=True)
    EMAIL_CFG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))

def update_email_config(**kwargs) -> dict:
    """Mettre à jour la configuration email."""
    cfg = load_email_config()
    cfg.update(kwargs)
    save_email_config(cfg)
    return cfg

# ══════════════════════════════════════════════════════════════
# TEMPLATES EMAIL HTML
# ══════════════════════════════════════════════════════════════

def _base_template(title: str, color: str, icon: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8">
<style>
  body{{font-family:Arial,sans-serif;background:#f4f6f8;margin:0;padding:20px}}
  .wrap{{max-width:620px;margin:0 auto;background:#fff;border-radius:12px;
    overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.1)}}
  .header{{background:#07101C;padding:28px 32px;text-align:center}}
  .logo{{color:#C9A227;font-size:22px;font-weight:900;letter-spacing:2px}}
  .logo-sub{{color:#64748B;font-size:12px;margin-top:4px}}
  .badge{{display:inline-block;background:{color};color:#fff;
    border-radius:20px;padding:6px 18px;font-size:13px;font-weight:700;margin-top:12px}}
  .body{{padding:28px 32px}}
  .title{{color:#07101C;font-size:20px;font-weight:700;margin-bottom:16px}}
  .kpi-row{{display:flex;gap:12px;margin:16px 0;flex-wrap:wrap}}
  .kpi{{background:#f8f9fa;border-radius:8px;padding:14px 18px;flex:1;min-width:140px;
    border-left:4px solid {color}}}
  .kpi-label{{color:#64748B;font-size:11px;font-weight:700;text-transform:uppercase}}
  .kpi-value{{color:#07101C;font-size:20px;font-weight:700;margin-top:4px}}
  .kpi-value.alert{{color:{color}}}
  .section{{margin:20px 0}}
  .section-title{{color:#07101C;font-size:14px;font-weight:700;
    border-bottom:2px solid {color};padding-bottom:6px;margin-bottom:12px}}
  .info-row{{display:flex;padding:8px 0;border-bottom:1px solid #f0f0f0}}
  .info-label{{color:#64748B;font-size:12px;width:140px;flex-shrink:0}}
  .info-value{{color:#07101C;font-size:12px;font-weight:600}}
  .btn{{display:inline-block;background:{color};color:#fff;text-decoration:none;
    padding:12px 28px;border-radius:8px;font-weight:700;font-size:14px;margin:8px 4px}}
  .btn-sec{{background:#f0f0f0;color:#07101C}}
  .sha{{font-family:monospace;font-size:10px;color:#10B981;
    background:#f0fdf4;padding:8px 12px;border-radius:6px;word-break:break-all;
    margin:12px 0}}
  .alert-box{{background:#fef2f2;border:1px solid #fca5a5;border-radius:8px;
    padding:14px;margin:16px 0}}
  .alert-box.gold{{background:#fffbeb;border-color:#fcd34d}}
  .footer{{background:#f8f9fa;padding:16px 32px;text-align:center;
    color:#94A3B8;font-size:11px;border-top:1px solid #e5e7eb}}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <div class="logo">NOCTYRA360™</div>
    <div class="logo-sub">Revenue Compliance & Assurance Platform</div>
    <div class="logo-sub" style="color:#64748B;margin-top:2px">
      Connect Now USA LLC · Tempe, AZ, USA</div>
    <div class="badge">{icon} {title}</div>
  </div>
  <div class="body">
    {body}
  </div>
  <div class="footer">
    NOCTYRA360™ · Connect Now USA LLC · www.noctyra360.com<br>
    Rapport généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')} UTC<br>
    Ce message est confidentiel — usage officiel uniquement
  </div>
</div>
</body></html>"""

def template_report_ready(finding: dict, reports: dict, cfg: dict) -> tuple:
    """Email : rapport certifié prêt."""
    op      = finding.get("operator","Opérateur")
    country = finding.get("country","")
    period  = finding.get("period","")
    sym     = finding.get("currency","XAF")
    gap     = finding.get("gap") or {}
    efr     = gap.get("tax_gap_local") or gap.get("tax_gap") or 0
    rev     = finding.get("total_revenue",0)
    tax     = finding.get("tax_due",0)
    decl    = finding.get("declared_revenue",0)
    recs    = finding.get("total_records",0)
    sha     = finding.get("sha256","")
    comp    = round(decl/tax*100,1) if tax>0 else 0
    pdf_url = reports.get("pdf","")
    pdf_name= Path(pdf_url).name if pdf_url else ""
    server  = cfg.get("server_url","http://localhost:8000")

    def fmt(n): return f"{sym} {round(n):,}".replace(",",".")

    subject = f"[NOCTYRA360™] Rapport certifié — {op} — {period} — EFR Gap {fmt(efr)}"

    body = f"""
    <div class="title">📋 Rapport EFR Certifié Disponible</div>
    <p style="color:#475569;margin-bottom:20px">
      Un nouveau rapport de conformité fiscale a été généré et certifié par
      NOCTYRA360™. Ce rapport est <strong>admissible devant tout tribunal</strong>
      et prêt pour transmission à la DGI.
    </p>

    <div class="section">
      <div class="section-title">Informations du rapport</div>
      <div class="info-row">
        <div class="info-label">Opérateur</div>
        <div class="info-value">{op}</div>
      </div>
      <div class="info-row">
        <div class="info-label">Pays</div>
        <div class="info-value">{country}</div>
      </div>
      <div class="info-row">
        <div class="info-label">Période</div>
        <div class="info-value">{period}</div>
      </div>
      <div class="info-row">
        <div class="info-label">CDRs analysés</div>
        <div class="info-value">{recs:,} enregistrements</div>
      </div>
      <div class="info-row">
        <div class="info-label">Généré le</div>
        <div class="info-value">{datetime.now().strftime('%d/%m/%Y %H:%M')} UTC</div>
      </div>
    </div>

    <div class="kpi-row">
      <div class="kpi">
        <div class="kpi-label">Revenue Total</div>
        <div class="kpi-value">{fmt(rev)}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Tax Due</div>
        <div class="kpi-value">{fmt(tax)}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">EFR Gap Certifié</div>
        <div class="kpi-value alert">{fmt(efr)}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Compliance</div>
        <div class="kpi-value {'alert' if comp < 80 else ''}">{comp}%</div>
      </div>
    </div>

    <div class="sha">
      🔐 SHA-256 · Certification cryptographique infalsifiable<br>
      {sha}
    </div>

    <div style="text-align:center;margin:24px 0">
      <a class="btn" href="{server}/api/report/{pdf_name}">
        📋 Télécharger Rapport PDF
      </a>
      <a class="btn btn-sec" href="{server}">
        📊 Ouvrir NOCTYRA360™
      </a>
    </div>

    <div class="alert-box gold">
      <strong>⚖️ Valeur légale :</strong> Ce rapport est certifié SHA-256 et
      admissible devant la DGI, l'ARTEC et tout tribunal compétent.
      Référence : {sha[:20]}...
    </div>
    """

    html = _base_template("Rapport Certifié Prêt", "#1E8449", "📋", body)
    return subject, html

def template_anomaly_critical(finding: dict, anomalies: dict,
                               anomaly_type: str, cfg: dict) -> tuple:
    """Email : anomalie critique détectée."""
    op      = finding.get("operator","Opérateur")
    country = finding.get("country","")
    period  = finding.get("period","")
    sym     = finding.get("currency","XAF")

    sb  = anomalies.get("sim_box",[])
    im  = anomalies.get("imei_fraud",[])
    aml = anomalies.get("aml",[])

    def fmt(n): return f"{sym} {round(n):,}".replace(",",".")

    if anomaly_type == "simbox":
        count   = len(sb)
        color   = "#DC2626"
        icon    = "🚨"
        title   = f"SIM Box Détecté — {count} Suspects"
        level   = "CRITIQUE"
        details = f"""
        <div class="alert-box">
          <strong>🚨 {count} MSISDNs suspects identifiés</strong><br>
          Trafic IDD anormal · Activité nocturne · Contournement interconnect<br>
          <strong>Action requise :</strong> Notification aux forces de l'ordre
        </div>
        <div class="kpi-row">
          <div class="kpi">
            <div class="kpi-label">SIM Box Suspects</div>
            <div class="kpi-value alert">{count:,}</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Score IA Max</div>
            <div class="kpi-value alert">
              {max((x.get('score',0) for x in sb[:10]),default=0):.0f}/100
            </div>
          </div>
        </div>
        <p style="color:#475569;font-size:13px">
          Un dossier d'investigation complet (rapport C05) est disponible dans
          NOCTYRA360™, prêt pour transmission aux autorités judiciaires.
        </p>"""

    elif anomaly_type == "aml":
        count   = len(aml)
        color   = "#D97706"
        icon    = "💳"
        title   = f"Activité AML Suspecte — {count} Transactions"
        level   = "URGENT"
        details = f"""
        <div class="alert-box gold">
          <strong>💳 {count} transactions suspectes détectées</strong><br>
          Structuring · Circular transfers · Velocity anormale<br>
          <strong>Action requise :</strong> SAR à soumettre à la Banque Centrale
        </div>
        <div class="kpi-row">
          <div class="kpi">
            <div class="kpi-label">Transactions AML</div>
            <div class="kpi-value alert">{count:,}</div>
          </div>
        </div>"""

    else:
        gap  = finding.get("gap") or {}
        efr  = gap.get("tax_gap_local") or gap.get("tax_gap") or 0
        color = "#DC2626"
        icon  = "⚠️"
        title = f"EFR Gap Critique — {fmt(efr)}"
        level = "CRITIQUE"
        details = f"""
        <div class="alert-box">
          <strong>⚠️ Gap fiscal critique détecté</strong><br>
          EFR Gap : <strong>{fmt(efr)}</strong> non déclaré<br>
          <strong>Action requise :</strong> Notification DGI immédiate
        </div>"""

    subject = f"[NOCTYRA360™] 🚨 {level} — {anomaly_type.upper()} — {op} — {period}"

    body = f"""
    <div class="title" style="color:{color}">{icon} Alerte {level} : {title}</div>
    <div class="section">
      <div class="section-title">Contexte</div>
      <div class="info-row">
        <div class="info-label">Opérateur</div>
        <div class="info-value">{op}</div>
      </div>
      <div class="info-row">
        <div class="info-label">Pays</div>
        <div class="info-value">{country}</div>
      </div>
      <div class="info-row">
        <div class="info-label">Période</div>
        <div class="info-value">{period}</div>
      </div>
      <div class="info-row">
        <div class="info-label">Détecté le</div>
        <div class="info-value">{datetime.now().strftime('%d/%m/%Y %H:%M')} UTC</div>
      </div>
    </div>
    {details}
    <div style="text-align:center;margin:24px 0">
      <a class="btn" style="background:{color}" href="http://localhost:8000">
        🔍 Voir dans NOCTYRA360™
      </a>
    </div>
    <p style="color:#94A3B8;font-size:11px">
      Cette alerte a été générée automatiquement par NOCTYRA360™.
      Niveau : {level} · Détection IA · Certification SHA-256
    </p>
    """

    html = _base_template(f"Alerte {level}", color, icon, body)
    return subject, html

# ══════════════════════════════════════════════════════════════
# ENVOI EMAIL
# ══════════════════════════════════════════════════════════════

async def send_email_async(to: List[str], subject: str, html: str,
                            attachment_path: str = "") -> bool:
    """Envoyer un email HTML de façon asynchrone."""
    cfg = load_email_config()
    if not cfg.get("enabled"):
        log.info(f"  📧 Email désactivé — aurait envoyé à: {to}")
        log.info(f"     Sujet: {subject}")
        return True  # Pas d'erreur — juste désactivé

    try:
        import aiosmtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{cfg['from_name']} <{cfg['from_email']}>"
        msg["To"]      = ", ".join(to)

        msg.attach(MIMEText(html, "html", "utf-8"))

        # Pièce jointe PDF si fournie
        if attachment_path and Path(attachment_path).exists():
            with open(attachment_path, "rb") as f:
                part = MIMEBase("application", "pdf")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                fname = Path(attachment_path).name
                part.add_header("Content-Disposition",
                                f'attachment; filename="{fname}"')
                msg.attach(part)

        await aiosmtplib.send(
            msg,
            hostname    = cfg["smtp_host"],
            port        = cfg["smtp_port"],
            username    = cfg["smtp_user"],
            password    = cfg["smtp_password"],
            start_tls   = cfg.get("smtp_tls", True),
        )
        log.info(f"  📧 Email envoyé → {to} | {subject[:50]}")
        return True

    except Exception as e:
        log.error(f"  ❌ Email erreur: {e}")
        return False

def send_email(to: List[str], subject: str, html: str,
               attachment_path: str = "") -> bool:
    """Version synchrone pour usage hors async."""
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(
            send_email_async(to, subject, html, attachment_path)
        )
        loop.close()
        return result
    except Exception as e:
        log.error(f"  ❌ send_email: {e}")
        return False

# ══════════════════════════════════════════════════════════════
# NOTIFICATIONS AUTOMATIQUES
# ══════════════════════════════════════════════════════════════

def notify_report_ready(finding: dict, anomalies: dict,
                         reports: dict) -> None:
    """Notifier quand un rapport est prêt."""
    cfg         = load_email_config()
    recipients  = cfg.get("recipients",{}).get("report_ready",[])
    if not recipients:
        return
    subject, html = template_report_ready(finding, reports, cfg)
    pdf_path = reports.get("pdf","")
    import threading
    t = threading.Thread(
        target=send_email,
        args=(recipients, subject, html, pdf_path),
        daemon=True
    )
    t.start()
    log.info(f"  📧 Notification rapport → {recipients}")

def notify_anomaly(finding: dict, anomalies: dict,
                   anomaly_type: str = "critical") -> None:
    """Notifier une anomalie critique."""
    cfg = load_email_config()
    thr = cfg.get("thresholds", {})
    rec = cfg.get("recipients", {})

    sb  = anomalies.get("sim_box", [])
    aml = anomalies.get("aml", [])
    gap = finding.get("gap") or {}
    efr = gap.get("tax_gap_local") or gap.get("tax_gap") or 0
    rev = finding.get("total_revenue") or 1

    notifications = []

    # SIM Box
    if len(sb) >= thr.get("simbox_count_alert", 100):
        to = rec.get("anomaly_simbox", rec.get("anomaly_critical", []))
        if to:
            notifications.append(("simbox", to))

    # AML
    if len(aml) >= thr.get("aml_count_alert", 50):
        to = rec.get("anomaly_aml", rec.get("anomaly_critical", []))
        if to:
            notifications.append(("aml", to))

    # EFR Gap critique
    gap_pct = (efr / rev * 100) if rev > 0 else 0
    if gap_pct >= thr.get("efr_gap_alert_pct", 5.0):
        to = rec.get("anomaly_critical", [])
        if to:
            notifications.append(("efr", to))

    import threading
    for atype, to in notifications:
        subject, html = template_anomaly_critical(finding, anomalies, atype, cfg)
        t = threading.Thread(
            target=send_email, args=(to, subject, html),
            daemon=True
        )
        t.start()
        log.info(f"  🚨 Alerte {atype} → {to}")

def notify_system_error(error: str, context: str = "") -> None:
    """Notifier une erreur système."""
    cfg = load_email_config()
    to  = cfg.get("recipients",{}).get("system_error",[])
    if not to:
        return
    subject = f"[NOCTYRA360™] ❌ Erreur système — {context}"
    html    = _base_template(
        "Erreur Système", "#DC2626", "❌",
        f"""<div class="title" style="color:#DC2626">❌ Erreur Système Détectée</div>
        <div class="alert-box">
          <strong>Contexte :</strong> {context}<br><br>
          <strong>Erreur :</strong><br>
          <code style="font-size:12px">{error[:500]}</code>
        </div>
        <p style="color:#64748B;font-size:12px">
          Vérifier les logs du serveur NOCTYRA360™ pour plus de détails.
        </p>"""
    )
    import threading
    threading.Thread(target=send_email, args=(to, subject, html),
                     daemon=True).start()

# ══════════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== TEST NOTIFICATIONS ===\n")
    cfg = load_email_config()
    print(f"Email activé : {cfg.get('enabled')}")
    print(f"SMTP         : {cfg.get('smtp_host')}:{cfg.get('smtp_port')}")
    print(f"Expéditeur   : {cfg.get('from_email')}")
    print(f"\nDestinataires:")
    for k,v in cfg.get("recipients",{}).items():
        print(f"  {k:25} → {v}")
    print(f"\nSeuils d'alerte:")
    for k,v in cfg.get("thresholds",{}).items():
        print(f"  {k:30} = {v}")
    print("\n✅ Module notifications prêt")
    print("\nPour activer : modifier config/email_config.json")
    print('  → "enabled": true')
    print('  → Remplir smtp_user / smtp_password')
