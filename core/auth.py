"""
NOCTYRA360™ — Authentification & Contrôle d'accès par rôle
Connect Now USA LLC — Confidentiel

Rôles : admin · dgi · artec · ministere · auditeur
JWT tokens · bcrypt passwords · RBAC complet
"""

import os, json, hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict
try:
    from jose import JWTError, jwt
except ImportError:
    # Fallback si python-jose pas encore installé
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install",
        "python-jose[cryptography]", "--break-system-packages", "-q"],
        capture_output=True)
    from jose import JWTError, jwt
from passlib.context import CryptContext

# ── Configuration JWT ──────────────────────────────────────────
SECRET_KEY  = os.environ.get(
    "N360_SECRET_KEY",
    "N360-Connect-Now-USA-2026-SecretKey-!@#$%"
)
ALGORITHM   = "HS256"
TOKEN_HOURS = 8   # Token expire après 8 heures

pwd_ctx = CryptContext(schemes=["sha256_crypt", "bcrypt"], deprecated="auto")

# ══════════════════════════════════════════════════════════════
# DÉFINITION DES RÔLES ET PERMISSIONS
# ══════════════════════════════════════════════════════════════

ROLES = {

    "admin": {
        "label":    "Administrateur Système",
        "org":      "Connect Now USA LLC",
        "color":    "#C9A227",
        "icon":     "🔑",
        "menus":    ["all"],        # Accès total
        "reports":  ["all"],
        "can_upload": True,
        "can_download": True,
        "can_configure": True,
        "can_see_sha256": True,
        "can_see_audit": True,
        "description": "Accès complet à toutes les fonctionnalités"
    },

    "dgi": {
        "label":    "Direction Générale des Impôts",
        "org":      "DGI",
        "color":    "#3B82F6",
        "icon":     "🏛️",
        "menus":    [
            "dashboard", "cdr_ingestion", "mobile_money",
            "report_catalog", "query_engine"
        ],
        "reports":  [
            "A01","A02","A03","A04",     # Gouvernement
            "B01","B02","B03","B05",     # Opérateurs
            "C01","C02","C03","C06",     # Légal/EFR
            "D06","D08","D09",           # Intelligence finance
            "F03","F04",                 # Certification
            "M12A","M12B"               # Supervision
        ],
        "can_upload": True,
        "can_download": True,
        "can_configure": False,
        "can_see_sha256": True,
        "can_see_audit": False,
        "description": "Rapports fiscaux, déclarations opérateurs, EFR Gap"
    },

    "artec": {
        "label":    "Autorité de Régulation",
        "org":      "ARTEC / ARCEP",
        "color":    "#10B981",
        "icon":     "📡",
        "menus":    [
            "dashboard", "cdr_ingestion", "sim_box",
            "imei_terminals", "report_catalog", "supervision"
        ],
        "reports":  [
            "A03",                       # Scorecard opérateurs
            "B01","B02","B04","B06",     # Analyse opérateurs + interconnect
            "C04","C05",                 # Evidence + SIM Box légal
            "D01","D02","D03","D05",     # Fraude réseau
            "D07","D10",                 # OTT + Fraud ring
            "F01","F02","F03",           # Technique + Audit
            "M12A","M12B","M12C"        # Supervision totale
        ],
        "can_upload": True,
        "can_download": True,
        "can_configure": False,
        "can_see_sha256": True,
        "can_see_audit": True,
        "description": "Conformité réseau, SIM Box, qualité de service, régulation"
    },

    "ministere": {
        "label":    "Ministère des Finances",
        "org":      "Gouvernement",
        "color":    "#8B5CF6",
        "icon":     "⚖️",
        "menus":    [
            "dashboard", "report_catalog"
        ],
        "reports":  [
            "A01","A02","A04","A05",     # Briefs ministériels
            "E01","E06",                 # Investisseur + Budget
            "G01","G02"                  # Régional
        ],
        "can_upload": False,
        "can_download": True,
        "can_configure": False,
        "can_see_sha256": False,
        "can_see_audit": False,
        "description": "Vue exécutive: EFR Gap, impact budget, briefs présidentiels"
    },

    "auditeur": {
        "label":    "Auditeur Indépendant",
        "org":      "Audit Externe",
        "color":    "#F97316",
        "icon":     "🔍",
        "menus":    [
            "dashboard", "report_catalog", "query_engine"
        ],
        "reports":  [
            "A01","A02","A03",           # Résumés
            "B01","B02","B03",           # Analyse opérateurs
            "F01","F02","F03","F04",     # Technique complet
            "M12A","M12B","M12C"        # Supervision
        ],
        "can_upload": False,
        "can_download": True,
        "can_configure": False,
        "can_see_sha256": True,
        "can_see_audit": True,
        "description": "Lecture seule: rapports techniques et d'audit ISO 27001"
    },
}

# ══════════════════════════════════════════════════════════════
# UTILISATEURS PAR DÉFAUT
# ══════════════════════════════════════════════════════════════

def _hash(pw: str) -> str:
    return pwd_ctx.hash(pw)

DEFAULT_USERS = {
    "admin": {
        "username": "admin",
        "hashed_password": _hash("N360Admin2026!"),
        "role": "admin",
        "full_name": "Administrateur NOCTYRA360™",
        "email": "admin@noctyra360.com",
        "active": True,
    },
    "dgi": {
        "username": "dgi",
        "hashed_password": _hash("DGI_N360_2026!"),
        "role": "dgi",
        "full_name": "Direction Générale des Impôts",
        "email": "dgi@gouvernement.mg",
        "active": True,
    },
    "artec": {
        "username": "artec",
        "hashed_password": _hash("ARTEC_N360_2026!"),
        "role": "artec",
        "full_name": "ARTEC — Autorité de Régulation",
        "email": "artec@artec.mg",
        "active": True,
    },
    "ministere": {
        "username": "ministere",
        "hashed_password": _hash("MIN_N360_2026!"),
        "role": "ministere",
        "full_name": "Ministère des Finances",
        "email": "ministre@finances.gov.mg",
        "active": True,
    },
    "auditeur": {
        "username": "auditeur",
        "hashed_password": _hash("AUDIT_N360_2026!"),
        "role": "auditeur",
        "full_name": "Auditeur Indépendant",
        "email": "audit@noctyra360.com",
        "active": True,
    },
}

# Fichier pour stocker les utilisateurs (permet ajout futur)
USERS_FILE = os.path.join(os.path.dirname(__file__), "..", "config", "users.json")

def _load_users() -> dict:
    """Charger les utilisateurs depuis le fichier ou utiliser les défauts."""
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return DEFAULT_USERS

def _save_users(users: dict):
    """Sauvegarder les utilisateurs."""
    try:
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        with open(USERS_FILE, "w") as f:
            json.dump(users, f, indent=2)
    except Exception as e:
        print(f"  ⚠️  Sauvegarde users: {e}")

USERS = _load_users()

# ── Fonctions auth ─────────────────────────────────────────────

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_ctx.verify(plain, hashed)
    except Exception:
        return False

def authenticate_user(username: str, password: str) -> Optional[dict]:
    """Vérifier credentials et retourner l'utilisateur si valide."""
    user = USERS.get(username.lower())
    if not user:
        return None
    if not user.get("active", True):
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return user

def create_token(username: str, role: str) -> str:
    """Créer un JWT token."""
    expire = datetime.utcnow() + timedelta(hours=TOKEN_HOURS)
    data = {
        "sub":      username,
        "role":     role,
        "exp":      expire,
        "iat":      datetime.utcnow(),
        "platform": "NOCTYRA360"
    }
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> Optional[dict]:
    """Décoder et valider un JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        role     = payload.get("role")
        if not username or not role:
            return None
        return {"username": username, "role": role}
    except JWTError:
        return None

def get_role_config(role: str) -> dict:
    """Retourner la configuration du rôle."""
    return ROLES.get(role, ROLES["auditeur"])

def can_access_report(role: str, report_code: str) -> bool:
    """Vérifier si un rôle peut accéder à un rapport."""
    rc = get_role_config(role)
    allowed = rc.get("reports", [])
    if "all" in allowed:
        return True
    return report_code in allowed

def can_access_menu(role: str, menu: str) -> bool:
    """Vérifier si un rôle peut voir un menu."""
    rc = get_role_config(role)
    menus = rc.get("menus", [])
    return "all" in menus or menu in menus

def get_user_profile(username: str) -> dict:
    """Profil complet d'un utilisateur pour le frontend."""
    user = USERS.get(username, {})
    role = user.get("role", "auditeur")
    rc   = get_role_config(role)
    return {
        "username":       username,
        "full_name":      user.get("full_name", username),
        "role":           role,
        "role_label":     rc["label"],
        "org":            rc["org"],
        "color":          rc["color"],
        "icon":           rc["icon"],
        "menus":          rc["menus"],
        "reports":        rc["reports"],
        "can_upload":     rc["can_upload"],
        "can_download":   rc["can_download"],
        "can_configure":  rc["can_configure"],
        "can_see_sha256": rc["can_see_sha256"],
        "can_see_audit":  rc["can_see_audit"],
        "description":    rc["description"],
    }

def add_user(username: str, password: str, role: str,
             full_name: str, email: str = "") -> bool:
    """Ajouter un nouvel utilisateur."""
    if role not in ROLES:
        return False
    USERS[username.lower()] = {
        "username":        username.lower(),
        "hashed_password": _hash(password),
        "role":            role,
        "full_name":       full_name,
        "email":           email,
        "active":          True,
    }
    _save_users(USERS)
    return True

if __name__ == "__main__":
    print("=== TEST AUTH ===")
    # Test login
    for username, password in [
        ("admin",     "N360Admin2026!"),
        ("dgi",       "DGI_N360_2026!"),
        ("artec",     "ARTEC_N360_2026!"),
        ("ministere", "MIN_N360_2026!"),
        ("auditeur",  "AUDIT_N360_2026!"),
        ("hacker",    "wrongpassword"),
    ]:
        user = authenticate_user(username, password)
        if user:
            token = create_token(username, user["role"])
            decoded = decode_token(token)
            profile = get_user_profile(username)
            print(f"  ✅ {username:12} | rôle={user['role']:10} | "
                  f"rapports={len(profile['reports'])} | "
                  f"upload={profile['can_upload']}")
        else:
            print(f"  ❌ {username:12} — accès refusé")
