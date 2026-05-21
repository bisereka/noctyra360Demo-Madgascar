#!/usr/bin/env python3
"""
NOCTYRA360™ — Gestion des comptes SFTP opérateurs
Connect Now USA LLC

Usage :
  python3 manage_sftp.py --list
  python3 manage_sftp.py --add --username telecel_new --password "PW!" --operator "Telecel" --country "CAR" --currency XAF
  python3 manage_sftp.py --test --username telma
"""
import sys, os, argparse
sys.path.insert(0, os.path.dirname(__file__))
from core.sftp_server import (
    load_accounts, add_sftp_account, list_sftp_accounts,
    create_operator_folders, get_processed_files,
    SFTP_PORT, UPLOADS_DIR
)

G="\033[92m"; R="\033[91m"; Y="\033[93m"; B="\033[94m"; W="\033[0m"; BOLD="\033[1m"

def cmd_list():
    accounts = list_sftp_accounts()
    print(f"\n{BOLD}=== Comptes SFTP NOCTYRA360™ ==={W}")
    print(f"Port SFTP : {Y}{SFTP_PORT}{W}")
    print(f"Dossier   : {UPLOADS_DIR}\n")
    for a in accounts:
        status = f"{G}✅ Actif{W}" if a["active"] else f"{R}❌ Inactif{W}"
        momo   = f" {Y}(MoMo){W}" if a["is_momo"] else ""
        print(f"  {Y}{a['username']:18}{W} → {BOLD}{a['operator']}{W}{momo}")
        print(f"    Pays    : {a['country']} | Devise: {a['currency']}")
        print(f"    Dossier : uploads/{a['folder']}/")
        print(f"    Statut  : {status}")
        # Fichiers en attente
        folder = UPLOADS_DIR / a["folder"]
        if folder.exists():
            pending = [f for f in folder.iterdir()
                      if f.is_file() and not f.name.startswith('.')]
            if pending:
                print(f"    {Y}⏳ {len(pending)} fichier(s) en attente{W}")
        print()

    print(f"{BOLD}--- Connexion opérateur (exemples) ---{W}")
    print(f"  Linux/Mac : {B}sftp -P {SFTP_PORT} telma@[IP-SERVEUR]{W}")
    print(f"  Windows   : {B}WinSCP → SFTP → IP:{SFTP_PORT} → identifiant/mdp{W}")
    print(f"  FileZilla : {B}Site Manager → SFTP → Port {SFTP_PORT}{W}\n")

def cmd_add(args):
    if not all([args.username, args.password, args.operator, args.country, args.currency]):
        print(f"{R}❌ Requis: --username --password --operator --country --currency{W}")
        sys.exit(1)
    ok = add_sftp_account(
        args.username, args.password, args.operator,
        args.country,  args.currency,
        is_momo=args.momo or False
    )
    if ok:
        print(f"{G}✅ Compte SFTP créé: {args.username} → {args.operator}{W}")
        print(f"   Dossier: uploads/{args.username.lower()}/")
        print(f"   Connexion: sftp -P {SFTP_PORT} {args.username}@[IP]")
    else:
        print(f"{R}❌ Erreur création{W}")

def cmd_processed(args):
    files = get_processed_files(args.operator or "")
    print(f"\n{BOLD}Fichiers traités ({len(files)}){W}")
    for f in files[:20]:
        kb = round(f["size"]/1024,1)
        print(f"  ✅ {f['filename']:40} {kb:8.1f} KB  {f['processed_at'][:19]}")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="NOCTYRA360™ — Gestion SFTP")
    p.add_argument("--list",      action="store_true")
    p.add_argument("--add",       action="store_true")
    p.add_argument("--processed", action="store_true")
    p.add_argument("--username",  help="Identifiant SFTP")
    p.add_argument("--password",  help="Mot de passe")
    p.add_argument("--operator",  help="Nom opérateur")
    p.add_argument("--country",   help="Pays")
    p.add_argument("--currency",  help="Devise (MGA/XAF/MZN)")
    p.add_argument("--momo",      action="store_true", help="Mobile Money")
    args = p.parse_args()

    if args.add:         cmd_add(args)
    elif args.processed: cmd_processed(args)
    else:                cmd_list()
