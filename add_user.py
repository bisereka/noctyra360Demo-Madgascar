#!/usr/bin/env python3
"""
NOCTYRA360™ — Outil d'ajout d'utilisateurs
Connect Now USA LLC

Usage :
  python3 add_user.py
  python3 add_user.py --username dgi_marie --password MonPW123! --role dgi --name "Marie Dupont"

Rôles disponibles : admin · dgi · artec · ministere · auditeur
"""

import sys, os, argparse
sys.path.insert(0, os.path.dirname(__file__))

from core.auth import add_user, authenticate_user, USERS, ROLES

# ── Couleurs terminal ──────────────────────────────────────────
G = "\033[92m"   # vert
R = "\033[91m"   # rouge
Y = "\033[93m"   # jaune
B = "\033[94m"   # bleu
W = "\033[0m"    # reset
BOLD = "\033[1m"

def print_roles():
    """Afficher les rôles disponibles."""
    print(f"\n{BOLD}Rôles disponibles :{W}")
    for code, rc in ROLES.items():
        reports = len(rc["reports"]) if rc["reports"] != ["all"] else 46
        menus   = len(rc["menus"])   if rc["menus"]   != ["all"] else 14
        print(f"  {rc['icon']} {Y}{code:12}{W} — {rc['label']}")
        print(f"    {rc['org']} | {reports} rapports | upload={rc['can_upload']}")

def print_users():
    """Afficher les utilisateurs existants."""
    print(f"\n{BOLD}Utilisateurs actuels :{W}")
    for u, data in USERS.items():
        role_info = ROLES.get(data.get("role",""), {})
        status = f"{G}✅ Actif{W}" if data.get("active",True) else f"{R}❌ Inactif{W}"
        print(f"  {role_info.get('icon','👤')} {Y}{u:15}{W} | "
              f"rôle={data.get('role'):12} | "
              f"{data.get('full_name',''):30} | {status}")

def interactive_mode():
    """Mode interactif — poser les questions."""
    print(f"\n{BOLD}{'='*50}{W}")
    print(f"{BOLD}  NOCTYRA360™ — Ajout d'utilisateur{W}")
    print(f"{BOLD}{'='*50}{W}")

    print_roles()
    print_users()

    print(f"\n{BOLD}--- Nouvel utilisateur ---{W}")

    # Identifiant
    while True:
        username = input(f"\n  {B}Identifiant{W} (ex: dgi_marie): ").strip().lower()
        if not username:
            print(f"  {R}❌ Identifiant requis{W}")
            continue
        if username in USERS:
            print(f"  {R}❌ '{username}' existe déjà{W}")
            print(f"     Utilisateurs existants: {list(USERS.keys())}")
            continue
        if not username.replace("_","").replace("-","").isalnum():
            print(f"  {R}❌ Identifiant: lettres, chiffres, _ et - uniquement{W}")
            continue
        break

    # Mot de passe
    import getpass
    while True:
        password = getpass.getpass(f"  {B}Mot de passe{W} (min 8 caractères): ")
        if len(password) < 8:
            print(f"  {R}❌ Minimum 8 caractères{W}")
            continue
        confirm = getpass.getpass(f"  {B}Confirmer mot de passe{W}: ")
        if password != confirm:
            print(f"  {R}❌ Les mots de passe ne correspondent pas{W}")
            continue
        break

    # Rôle
    roles_list = list(ROLES.keys())
    while True:
        role = input(f"\n  {B}Rôle{W} ({'/'.join(roles_list)}): ").strip().lower()
        if role not in ROLES:
            print(f"  {R}❌ Rôle invalide. Choisir parmi: {roles_list}{W}")
            continue
        break

    # Nom complet
    full_name = input(f"  {B}Nom complet{W} (ex: Marie Dupont — DGI): ").strip()
    if not full_name:
        full_name = f"{username} — {ROLES[role]['org']}"

    # Email
    email = input(f"  {B}Email{W} (optionnel): ").strip()

    # Confirmation
    rc = ROLES[role]
    print(f"\n{BOLD}--- Récapitulatif ---{W}")
    print(f"  Identifiant : {Y}{username}{W}")
    print(f"  Rôle        : {rc['icon']} {rc['label']}")
    print(f"  Organisation: {rc['org']}")
    print(f"  Nom complet : {full_name}")
    print(f"  Email       : {email or '—'}")
    print(f"  Rapports    : {len(rc['reports']) if rc['reports'] != ['all'] else 46}")
    print(f"  Upload CDR  : {'✅ Oui' if rc['can_upload'] else '❌ Non'}")

    confirm = input(f"\n  {B}Créer cet utilisateur ? (oui/non){W}: ").strip().lower()
    if confirm not in ("oui","o","y","yes"):
        print(f"\n  {Y}❌ Annulé{W}")
        return

    # Créer l'utilisateur
    ok = add_user(username, password, role, full_name, email)
    if ok:
        print(f"\n  {G}✅ Utilisateur '{username}' créé avec succès !{W}")
        print(f"\n  {BOLD}Identifiants de connexion :{W}")
        print(f"  URL         : http://[IP-SERVEUR]:8000/login")
        print(f"  Identifiant : {Y}{username}{W}")
        print(f"  Mot de passe: [celui que vous venez de saisir]")
        print(f"\n  {Y}⚠️  Communiquer ces identifiants de façon sécurisée{W}")
    else:
        print(f"\n  {R}❌ Erreur lors de la création{W}")

def args_mode(args):
    """Mode arguments — depuis la ligne de commande."""
    if args.list:
        print_roles()
        print_users()
        return

    if not all([args.username, args.password, args.role, args.name]):
        print(f"{R}❌ --username, --password, --role et --name sont requis{W}")
        sys.exit(1)

    if args.role not in ROLES:
        print(f"{R}❌ Rôle invalide: {args.role}{W}")
        print(f"   Rôles disponibles: {list(ROLES.keys())}")
        sys.exit(1)

    if args.username in USERS:
        print(f"{R}❌ Utilisateur '{args.username}' existe déjà{W}")
        sys.exit(1)

    if len(args.password) < 8:
        print(f"{R}❌ Mot de passe trop court (minimum 8 caractères){W}")
        sys.exit(1)

    ok = add_user(args.username, args.password, args.role,
                  args.name, args.email or "")
    if ok:
        rc = ROLES[args.role]
        print(f"{G}✅ Utilisateur créé :{W}")
        print(f"   Identifiant : {args.username}")
        print(f"   Rôle        : {rc['icon']} {rc['label']}")
        print(f"   Login       : http://[IP]:8000/login")
    else:
        print(f"{R}❌ Erreur création utilisateur{W}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="NOCTYRA360™ — Gestion des utilisateurs"
    )
    parser.add_argument("--username", help="Identifiant de connexion")
    parser.add_argument("--password", help="Mot de passe")
    parser.add_argument("--role",     help="Rôle: admin/dgi/artec/ministere/auditeur")
    parser.add_argument("--name",     help="Nom complet")
    parser.add_argument("--email",    help="Adresse email (optionnel)")
    parser.add_argument("--list",     action="store_true",
                        help="Lister les utilisateurs et rôles")

    args = parser.parse_args()

    # Si aucun argument → mode interactif
    if not any(vars(args).values()):
        interactive_mode()
    else:
        args_mode(args)
