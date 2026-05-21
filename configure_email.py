#!/usr/bin/env python3
"""
NOCTYRA360™ — Configuration Email
Connect Now USA LLC

Usage :
  python3 configure_email.py           # Mode interactif
  python3 configure_email.py --test    # Tester la config actuelle
  python3 configure_email.py --show    # Voir la config actuelle
"""
import sys, os, argparse, getpass
sys.path.insert(0, os.path.dirname(__file__))
from core.notifications import (
    load_email_config, save_email_config,
    send_email, template_report_ready, _base_template
)

G="\033[92m"; R="\033[91m"; Y="\033[93m"; B="\033[94m"; W="\033[0m"; BOLD="\033[1m"

SMTP_PRESETS = {
    "1": {"name":"Gmail",       "host":"smtp.gmail.com",        "port":587, "tls":True},
    "2": {"name":"Outlook",     "host":"smtp-mail.outlook.com", "port":587, "tls":True},
    "3": {"name":"Yahoo",       "host":"smtp.mail.yahoo.com",   "port":587, "tls":True},
    "4": {"name":"OVH",         "host":"ssl0.ovh.net",          "port":587, "tls":True},
    "5": {"name":"SMTP Custom", "host":"",                      "port":587, "tls":True},
}

def show_config():
    cfg = load_email_config()
    print(f"\n{BOLD}=== Configuration Email NOCTYRA360™ ==={W}")
    print(f"  Activé    : {'🟢 Oui' if cfg.get('enabled') else '🔴 Non (emails simulés)'}")
    print(f"  SMTP      : {cfg.get('smtp_host')}:{cfg.get('smtp_port')}")
    print(f"  Compte    : {cfg.get('smtp_user')}")
    print(f"  Expéditeur: {cfg.get('from_name')}")
    print(f"\n{BOLD}  Destinataires :{W}")
    for k,v in cfg.get("recipients",{}).items():
        print(f"    {Y}{k:25}{W} → {', '.join(v) if v else '(aucun)'}")
    print(f"\n{BOLD}  Seuils d'alerte :{W}")
    thr = cfg.get("thresholds",{})
    print(f"    EFR Gap alerte si gap > {thr.get('efr_gap_alert_pct',5)}% du revenue")
    print(f"    SIM Box alerte si > {thr.get('simbox_count_alert',100)} suspects")
    print(f"    AML alerte si > {thr.get('aml_count_alert',50)} transactions")
    print(f"    Compliance alerte si < {thr.get('compliance_low_alert',70)}%\n")

def interactive_setup():
    print(f"\n{BOLD}{'='*55}{W}")
    print(f"{BOLD}  NOCTYRA360™ — Configuration Email{W}")
    print(f"{BOLD}{'='*55}{W}")
    show_config()

    cfg = load_email_config()

    print(f"{BOLD}--- Configuration SMTP ---{W}")
    print(f"\n  Choisir le fournisseur email:")
    for k,v in SMTP_PRESETS.items():
        print(f"    {Y}{k}{W}. {v['name']} ({v['host']}:{v['port']})")

    choice = input(f"\n  Choix (1-5): ").strip()
    preset = SMTP_PRESETS.get(choice, SMTP_PRESETS["1"])

    if choice == "5":
        host = input(f"  Hôte SMTP : ").strip()
        port = input(f"  Port SMTP (587): ").strip() or "587"
        preset["host"] = host
        preset["port"] = int(port)

    cfg["smtp_host"] = preset["host"]
    cfg["smtp_port"] = preset["port"]
    cfg["smtp_tls"]  = preset["tls"]
    print(f"  {G}✅ SMTP : {preset['host']}:{preset['port']}{W}")

    print(f"\n{BOLD}--- Compte email expéditeur ---{W}")
    print(f"  {Y}Note Gmail:{W} Utiliser un 'Mot de passe d'application'")
    print(f"  Google Account → Sécurité → Vérification 2 étapes → Mots de passe app\n")

    user = input(f"  Adresse email : ").strip()
    pwd  = getpass.getpass(f"  Mot de passe (ou App Password) : ")
    name = input(f"  Nom affiché (NOCTYRA360™ Connect Now USA) : ").strip()

    cfg["smtp_user"]    = user
    cfg["smtp_password"]= pwd
    cfg["from_email"]   = user
    cfg["from_name"]    = name or "NOCTYRA360™ — Connect Now USA LLC"

    print(f"\n{BOLD}--- Destinataires ---{W}")
    print(f"  Saisir les adresses email séparées par des virgules\n")

    rec = cfg.get("recipients", {})
    for key, label in [
        ("report_ready",    "Rapport prêt (DGI, ARTEC)"),
        ("anomaly_critical","Anomalie critique (DGI, Superviseur)"),
        ("anomaly_simbox",  "SIM Box détecté (Police, ARTEC)"),
        ("anomaly_aml",     "AML détecté (Banque Centrale, DGI)"),
        ("system_error",    "Erreur système (Admin technique)"),
    ]:
        current = ", ".join(rec.get(key, []))
        val = input(f"  {Y}{label}{W}\n  [{current}] : ").strip()
        if val:
            rec[key] = [e.strip() for e in val.split(",") if e.strip()]
    cfg["recipients"] = rec

    print(f"\n{BOLD}--- Seuils d'alerte ---{W}")
    thr = cfg.get("thresholds", {})
    v = input(f"  EFR Gap alerte si gap > ?% du revenue [{thr.get('efr_gap_alert_pct',5)}] : ").strip()
    if v: thr["efr_gap_alert_pct"] = float(v)
    v = input(f"  SIM Box alerte si > ? suspects [{thr.get('simbox_count_alert',100)}] : ").strip()
    if v: thr["simbox_count_alert"] = int(v)
    v = input(f"  AML alerte si > ? transactions [{thr.get('aml_count_alert',50)}] : ").strip()
    if v: thr["aml_count_alert"] = int(v)
    cfg["thresholds"] = thr

    enable = input(f"\n  {BOLD}Activer les notifications maintenant ? (oui/non){W} : ").strip().lower()
    cfg["enabled"] = enable in ("oui","o","y","yes")

    save_email_config(cfg)
    print(f"\n{G}✅ Configuration sauvegardée{W}")

    if cfg["enabled"]:
        test_addr = input(f"  Envoyer un email de test à quelle adresse ? : ").strip()
        if test_addr:
            print(f"  Envoi test vers {test_addr}...")
            ok = send_email(
                [test_addr],
                "[NOCTYRA360™] ✅ Test configuration email",
                _base_template("Test Email","#1E8449","✅",
                    "<div style='font-size:16px;font-weight:700'>✅ Email configuré avec succès !</div>"
                    "<p>NOCTYRA360™ enverra automatiquement les notifications.</p>"
                )
            )
            if ok:
                print(f"  {G}✅ Email de test envoyé !{W}")
            else:
                print(f"  {R}❌ Echec — vérifier SMTP et mot de passe{W}")

def test_send():
    cfg = load_email_config()
    if not cfg.get("enabled"):
        print(f"{Y}⚠️  Email non activé — mode simulation{W}")
        print(f"   Lancer python3 configure_email.py pour configurer")
        return
    addr = input(f"Adresse email de test : ").strip()
    if not addr: return
    ok = send_email([addr], "[TEST] NOCTYRA360™",
        _base_template("Test","#C9A227","✅","<p>Test OK</p>"))
    print(f"{G}✅ Envoyé !{W}" if ok else f"{R}❌ Echec{W}")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--show",  action="store_true", help="Voir la configuration")
    p.add_argument("--test",  action="store_true", help="Tester l'envoi")
    args = p.parse_args()
    if args.show:   show_config()
    elif args.test: test_send()
    else:           interactive_setup()
