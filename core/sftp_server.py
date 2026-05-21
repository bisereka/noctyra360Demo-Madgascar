"""
NOCTYRA360™ — Serveur SFTP intégré
Connect Now USA LLC — Confidentiel

Architecture :
  - Serveur SFTP écoute sur le port 2222
  - Chaque opérateur a son propre compte SFTP
  - Dossier isolé par opérateur : /uploads/telma/, /uploads/orange/, etc.
  - Watchdog détecte tout nouveau fichier → déclenche traitement automatique
  - Résultats sauvegardés en base de données
"""

import os, sys, time, threading, logging, json, shutil
from pathlib import Path
from datetime import datetime

# ── Logging ────────────────────────────────────────────────────
log = logging.getLogger("N360.SFTP")
logging.basicConfig(
    level=logging.INFO,
    format="  %(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)

BASE_DIR    = Path(__file__).parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
CONFIG_DIR  = BASE_DIR / "config"
SFTP_PORT   = int(os.environ.get("N360_SFTP_PORT", 2222))
SFTP_HOST   = os.environ.get("N360_SFTP_HOST", "0.0.0.0")

# ══════════════════════════════════════════════════════════════
# CONFIGURATION DES COMPTES SFTP PAR OPÉRATEUR
# ══════════════════════════════════════════════════════════════

SFTP_ACCOUNTS_FILE = CONFIG_DIR / "sftp_accounts.json"

DEFAULT_ACCOUNTS = {
    "telma": {
        "password":  "Telma_N360_2026!",
        "operator":  "Telma",
        "country":   "Madagascar",
        "currency":  "MGA",
        "is_momo":   False,
        "folder":    "telma",
        "active":    True,
    },
    "orange_mdg": {
        "password":  "Orange_MDG_N360!",
        "operator":  "Orange Madagascar",
        "country":   "Madagascar",
        "currency":  "MGA",
        "is_momo":   False,
        "folder":    "orange_mdg",
        "active":    True,
    },
    "mvola": {
        "password":  "MVola_N360_2026!",
        "operator":  "MVola",
        "country":   "Madagascar",
        "currency":  "MGA",
        "is_momo":   True,
        "folder":    "mvola",
        "active":    True,
    },
    "orange_car": {
        "password":  "Orange_CAR_N360!",
        "operator":  "Orange CAR",
        "country":   "Centrafrique",
        "currency":  "XAF",
        "is_momo":   False,
        "folder":    "orange_car",
        "active":    True,
    },
    "telecel_car": {
        "password":  "Telecel_N360_2026!",
        "operator":  "Telecel CAR",
        "country":   "Centrafrique",
        "currency":  "XAF",
        "is_momo":   False,
        "folder":    "telecel_car",
        "active":    True,
    },
    "vodacom_moz": {
        "password":  "Vodacom_MOZ_N360!",
        "operator":  "Vodacom Mozambique",
        "country":   "Mozambique",
        "currency":  "MZN",
        "is_momo":   False,
        "folder":    "vodacom_moz",
        "active":    True,
    },
}

def load_accounts() -> dict:
    try:
        if SFTP_ACCOUNTS_FILE.exists():
            return json.loads(SFTP_ACCOUNTS_FILE.read_text())
    except Exception:
        pass
    return DEFAULT_ACCOUNTS

def save_accounts(accounts: dict):
    CONFIG_DIR.mkdir(exist_ok=True)
    SFTP_ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2))

def create_operator_folders():
    """Créer les dossiers SFTP pour chaque opérateur."""
    accounts = load_accounts()
    for username, acc in accounts.items():
        folder = UPLOADS_DIR / acc["folder"]
        folder.mkdir(parents=True, exist_ok=True)
        done = folder / ".processed"
        done.mkdir(exist_ok=True)
        log.info(f"  📁 Dossier SFTP: uploads/{acc['folder']}/ → {acc['operator']}")

# ══════════════════════════════════════════════════════════════
# SERVEUR SFTP (basé sur paramiko)
# ══════════════════════════════════════════════════════════════

try:
    import paramiko
    PARAMIKO_OK = True
except ImportError:
    PARAMIKO_OK = False
    log.warning("paramiko non disponible — serveur SFTP désactivé")

if PARAMIKO_OK:

    class N360SFTPInterface(paramiko.SFTPServerInterface):
        """Interface SFTP — chaque opérateur voit seulement son dossier."""

        def __init__(self, server, *args, **kwargs):
            self.operator_folder = server.operator_folder
            super().__init__(server, *args, **kwargs)

        def _real_path(self, path):
            """Résoudre le chemin vers le dossier de l'opérateur."""
            path = path.lstrip("/")
            real = self.operator_folder / path
            # Sécurité : pas de path traversal
            try:
                real.resolve().relative_to(self.operator_folder.resolve())
            except ValueError:
                return self.operator_folder
            return real

        def list_folder(self, path):
            real = self._real_path(path)
            if not real.exists():
                return paramiko.SFTP_NO_SUCH_FILE
            out = []
            for f in real.iterdir():
                if f.name.startswith('.'):
                    continue
                attr = paramiko.SFTPAttributes.from_stat(f.stat())
                attr.filename = f.name
                out.append(attr)
            return out

        def stat(self, path):
            real = self._real_path(path)
            if not real.exists():
                return paramiko.SFTP_NO_SUCH_FILE
            return paramiko.SFTPAttributes.from_stat(real.stat())

        def lstat(self, path):
            return self.stat(path)

        def open(self, path, flags, attr):
            real = self._real_path(path)
            real.parent.mkdir(parents=True, exist_ok=True)
            mode = "wb" if flags & os.O_WRONLY else "rb"
            try:
                f = open(real, mode)
                fobj = paramiko.SFTPHandle(flags)
                fobj.filename = str(real)
                fobj.readfile = f
                fobj.writefile = f
                return fobj
            except Exception as e:
                log.error(f"SFTP open error: {e}")
                return paramiko.SFTP_FAILURE

        def remove(self, path): return paramiko.SFTP_OP_UNSUPPORTED
        def rename(self, o, n):  return paramiko.SFTP_OP_UNSUPPORTED
        def mkdir(self, path, attr): return paramiko.SFTP_OP_UNSUPPORTED
        def rmdir(self, path): return paramiko.SFTP_OP_UNSUPPORTED

    class N360SFTPServer(paramiko.ServerInterface):
        """Authentification SSH/SFTP par opérateur."""

        def __init__(self):
            self.operator_folder = UPLOADS_DIR
            self.operator_info   = {}
            self.event = threading.Event()

        def check_auth_password(self, username, password):
            accounts = load_accounts()
            acc = accounts.get(username)
            if acc and acc.get("active") and acc.get("password") == password:
                self.operator_info   = acc
                self.operator_folder = UPLOADS_DIR / acc["folder"]
                self.operator_folder.mkdir(parents=True, exist_ok=True)
                log.info(f"  🔐 SFTP Login: {username} → {acc['operator']}")
                return paramiko.AUTH_SUCCESSFUL
            log.warning(f"  ❌ SFTP Login échoué: {username}")
            return paramiko.AUTH_FAILED

        def check_channel_request(self, kind, chanid):
            if kind == "session":
                return paramiko.OPEN_SUCCEEDED
            return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

        def check_channel_subsystem_request(self, channel, name):
            return name == "sftp"

    def generate_host_key():
        """Générer ou charger la clé SSH du serveur."""
        key_path = CONFIG_DIR / "sftp_host_key"
        if key_path.exists():
            return paramiko.RSAKey.from_private_key_file(str(key_path))
        log.info("  🔑 Génération clé SSH serveur...")
        key = paramiko.RSAKey.generate(2048)
        CONFIG_DIR.mkdir(exist_ok=True)
        key.write_private_key_file(str(key_path))
        return key

    def run_sftp_server():
        """Lancer le serveur SFTP en arrière-plan."""
        import socket
        host_key = generate_host_key()
        create_operator_folders()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
        try:
            sock.bind((SFTP_HOST, SFTP_PORT))
        except OSError as e:
            log.error(f"  ❌ SFTP port {SFTP_PORT} indisponible: {e}")
            log.info(f"  ℹ️  Essayer: N360_SFTP_PORT=2223 bash run.sh")
            return
        sock.listen(10)
        sock.settimeout(1.0)
        log.info(f"  📡 Serveur SFTP démarré sur port {SFTP_PORT}")
        log.info(f"     Connexion: sftp -P {SFTP_PORT} telma@[IP-SERVEUR]")

        while True:
            try:
                conn, addr = sock.accept()
            except socket.timeout:
                continue
            except Exception:
                break
            t = threading.Thread(
                target=_handle_sftp_client,
                args=(conn, addr, host_key),
                daemon=True
            )
            t.start()

    def _handle_sftp_client(conn, addr, host_key):
        """Gérer une connexion SFTP."""
        try:
            transport = paramiko.Transport(conn)
            transport.add_server_key(host_key)
            server = N360SFTPServer()
            transport.set_subsystem_handler(
                "sftp", paramiko.SFTPServer, N360SFTPInterface
            )
            transport.start_server(server=server)
            channel = transport.accept(60)
            if channel:
                server.event.wait(30)
            transport.close()
        except Exception as e:
            log.debug(f"SFTP client error: {e}")
        finally:
            conn.close()

# ══════════════════════════════════════════════════════════════
# WATCHDOG — Détection et traitement automatique des fichiers
# ══════════════════════════════════════════════════════════════

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_OK = True
except ImportError:
    WATCHDOG_OK = False

if WATCHDOG_OK:

    class CDRFileHandler(FileSystemEventHandler):
        """Détecte les nouveaux fichiers CDR et déclenche le traitement."""

        def __init__(self, process_callback):
            self.callback  = process_callback
            self.accounts  = load_accounts()
            self._pending  = {}   # éviter double-trigger
            super().__init__()

        def on_created(self, event):
            if event.is_directory:
                return
            path = Path(event.src_path)
            # Ignorer les fichiers cachés et dossiers .processed
            if path.name.startswith('.') or '.processed' in str(path):
                return
            # Extensions CDR acceptées
            if path.suffix.lower() not in ('.csv','.txt','.log','.asn1','.gz'):
                return
            # Anti-doublon : attendre 2 secondes
            key = str(path)
            if key in self._pending:
                return
            self._pending[key] = True
            log.info(f"  📥 Nouveau fichier détecté: {path.name}")
            # Attendre que le fichier soit complètement transféré
            threading.Timer(3.0, self._process_after_delay, args=[path]).start()

        def _process_after_delay(self, path: Path):
            """Traiter après que le fichier est stable."""
            self._pending.pop(str(path), None)
            if not path.exists():
                return
            # Vérifier taille stable (upload terminé)
            size1 = path.stat().st_size
            time.sleep(2)
            if not path.exists():
                return
            size2 = path.stat().st_size
            if size1 != size2:
                # Upload encore en cours → réessayer
                threading.Timer(3.0, self._process_after_delay, args=[path]).start()
                return

            # Identifier l'opérateur depuis le dossier parent
            operator_info = self._get_operator_info(path)
            log.info(f"  🚀 Traitement automatique: {path.name}")
            log.info(f"     Opérateur: {operator_info.get('operator','?')}")
            log.info(f"     Pays: {operator_info.get('country','?')}")

            try:
                self.callback(path, operator_info)
                # Déplacer vers .processed après succès
                done_dir = path.parent / ".processed"
                done_dir.mkdir(exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = done_dir / f"{ts}_{path.name}"
                shutil.move(str(path), str(dest))
                log.info(f"  ✅ Traité → {dest.name}")
            except Exception as e:
                log.error(f"  ❌ Erreur traitement {path.name}: {e}")
                # Déplacer vers .errors
                err_dir = path.parent / ".errors"
                err_dir.mkdir(exist_ok=True)
                shutil.move(str(path), str(err_dir / path.name))

        def _get_operator_info(self, path: Path) -> dict:
            """Déterminer l'opérateur depuis le chemin du fichier."""
            # Chercher dans les comptes SFTP
            folder_name = path.parent.name
            for username, acc in self.accounts.items():
                if acc.get("folder") == folder_name:
                    return acc
            # Fallback : détecter depuis le nom du fichier
            fname = path.name.lower()
            if "telma"   in fname: return {"operator":"Telma","country":"Madagascar","currency":"MGA","is_momo":False}
            if "mvola"   in fname: return {"operator":"MVola","country":"Madagascar","currency":"MGA","is_momo":True}
            if "orange"  in fname: return {"operator":"Orange","country":"Madagascar","currency":"MGA","is_momo":False}
            if "vodacom" in fname: return {"operator":"Vodacom","country":"Mozambique","currency":"MZN","is_momo":False}
            if "telecel" in fname: return {"operator":"Telecel","country":"Centrafrique","currency":"XAF","is_momo":False}
            # Défaut depuis config active
            return {"operator":"Opérateur","country":"","currency":"XAF","is_momo":False}

    def start_watchdog(process_callback):
        """Démarrer la surveillance des dossiers SFTP."""
        create_operator_folders()
        handler  = CDRFileHandler(process_callback)
        observer = Observer()
        observer.schedule(handler, str(UPLOADS_DIR), recursive=True)
        observer.start()
        log.info(f"  👁️  Watchdog actif: surveillance {UPLOADS_DIR}/")
        log.info(f"      Dossiers surveillés:")
        accounts = load_accounts()
        for acc in accounts.values():
            if acc.get("active"):
                log.info(f"      → uploads/{acc['folder']}/ ({acc['operator']})")
        return observer

# ══════════════════════════════════════════════════════════════
# GESTION DES COMPTES SFTP
# ══════════════════════════════════════════════════════════════

def add_sftp_account(username: str, password: str, operator: str,
                     country: str, currency: str, is_momo: bool = False) -> bool:
    """Ajouter un compte SFTP pour un opérateur."""
    accounts = load_accounts()
    folder = username.lower().replace(" ","_")
    accounts[username.lower()] = {
        "password": password,
        "operator": operator,
        "country":  country,
        "currency": currency,
        "is_momo":  is_momo,
        "folder":   folder,
        "active":   True,
    }
    save_accounts(accounts)
    # Créer le dossier
    (UPLOADS_DIR / folder).mkdir(parents=True, exist_ok=True)
    log.info(f"  ✅ Compte SFTP créé: {username} → {operator}")
    return True

def list_sftp_accounts() -> list:
    """Lister tous les comptes SFTP."""
    accounts = load_accounts()
    return [{
        "username": u,
        "operator": a["operator"],
        "country":  a["country"],
        "currency": a["currency"],
        "is_momo":  a["is_momo"],
        "folder":   a["folder"],
        "active":   a.get("active", True),
    } for u, a in accounts.items()]

def get_processed_files(operator_folder: str = "") -> list:
    """Lister les fichiers déjà traités."""
    results = []
    search_dirs = []
    if operator_folder:
        search_dirs = [UPLOADS_DIR / operator_folder / ".processed"]
    else:
        for acc in load_accounts().values():
            search_dirs.append(UPLOADS_DIR / acc["folder"] / ".processed")

    for d in search_dirs:
        if d.exists():
            for f in sorted(d.iterdir(), reverse=True)[:20]:
                if not f.name.startswith('.'):
                    results.append({
                        "filename": f.name,
                        "size":     f.stat().st_size,
                        "processed_at": datetime.fromtimestamp(
                            f.stat().st_mtime).isoformat(),
                    })
    return results

if __name__ == "__main__":
    print("=== TEST SFTP CONFIG ===")
    create_operator_folders()
    accounts = list_sftp_accounts()
    print(f"\n  {len(accounts)} comptes SFTP configurés:")
    for a in accounts:
        status = "✅" if a["active"] else "❌"
        momo   = " (MoMo)" if a["is_momo"] else ""
        print(f"  {status} {a['username']:15} → {a['operator']}{momo} | {a['country']} | {a['currency']}")
        print(f"     Dossier: uploads/{a['folder']}/")

    print(f"\n  Pour déposer un CDR (exemple Telma):")
    print(f"  sftp -P 2222 telma@[IP-SERVEUR]")
    print(f"  sftp> put telma_avril_2026.csv")
    print(f"\n  ✅ SFTP prêt")
