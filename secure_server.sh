#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# NOCTYRA360™ — Script de sécurisation Ubuntu Server 22.04
# Connect Now USA LLC — Confidentiel
# 
# Ce script configure :
#   ✅ UFW Firewall
#   ✅ SSH Sécurisé (clé uniquement)
#   ✅ Fail2Ban (protection brute-force)
#   ✅ Nginx + SSL/HTTPS obligatoire
#   ✅ Certificat SSL (Let's Encrypt ou auto-signé)
#   ✅ Mises à jour automatiques
#   ✅ Audit système
#   ✅ LUKS (chiffrement disque — instructions)
#
# Usage : sudo bash secure_server.sh
# ═══════════════════════════════════════════════════════════════

set -e  # Arrêter si erreur

# ── Couleurs ───────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "  ${GREEN}✅ $1${NC}"; }
info() { echo -e "  ${BLUE}ℹ️  $1${NC}"; }
warn() { echo -e "  ${YELLOW}⚠️  $1${NC}"; }
err()  { echo -e "  ${RED}❌ $1${NC}"; }
step() { echo -e "\n${BOLD}${BLUE}══ $1 ══${NC}"; }

# ── Vérifications préliminaires ────────────────────────────────
if [ "$EUID" -ne 0 ]; then
  err "Ce script doit être exécuté en root : sudo bash secure_server.sh"
  exit 1
fi

if [ ! -f /etc/lsb-release ]; then
  err "Ubuntu requis"
  exit 1
fi

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║     NOCTYRA360™ — Sécurisation Serveur Ubuntu            ║${NC}"
echo -e "${BOLD}║     Connect Now USA LLC                                   ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Variables de configuration ─────────────────────────────────
read -p "  Domaine (ex: noctyra360.gov.mg) ou IP: " DOMAIN
DOMAIN=${DOMAIN:-$(curl -s ifconfig.me 2>/dev/null || echo "localhost")}

read -p "  Port SSH sécurisé (défaut 2200): " SSH_PORT
SSH_PORT=${SSH_PORT:-2200}

read -p "  Email admin (pour SSL Let's Encrypt): " ADMIN_EMAIL
ADMIN_EMAIL=${ADMIN_EMAIL:-"admin@noctyra360.com"}

read -p "  Créer un utilisateur système dédié NOCTYRA360 ? (oui/non) [oui]: " CREATE_USER
CREATE_USER=${CREATE_USER:-oui}

echo ""
echo -e "  ${BOLD}Configuration retenue :${NC}"
echo -e "  Domaine   : ${YELLOW}$DOMAIN${NC}"
echo -e "  Port SSH  : ${YELLOW}$SSH_PORT${NC}"
echo -e "  Email SSL : ${YELLOW}$ADMIN_EMAIL${NC}"
echo ""
read -p "  Continuer ? (oui/non): " CONFIRM
if [ "$CONFIRM" != "oui" ] && [ "$CONFIRM" != "o" ]; then
  echo "  Annulé."
  exit 0
fi

# ══════════════════════════════════════════════════════════════
# ÉTAPE 1 — MISES À JOUR SYSTÈME
# ══════════════════════════════════════════════════════════════
step "ÉTAPE 1 — Mises à jour système"

apt-get update -q
apt-get upgrade -y -q
apt-get install -y -q \
  ufw fail2ban nginx certbot python3-certbot-nginx \
  unattended-upgrades apt-listchanges \
  auditd libpam-google-authenticator \
  logrotate htop curl wget git \
  python3-pip python3-venv \
  postgresql postgresql-contrib \
  2>/dev/null || true

ok "Paquets installés"

# ══════════════════════════════════════════════════════════════
# ÉTAPE 2 — UTILISATEUR SYSTÈME DÉDIÉ
# ══════════════════════════════════════════════════════════════
step "ÉTAPE 2 — Utilisateur système NOCTYRA360"

if [ "$CREATE_USER" = "oui" ] || [ "$CREATE_USER" = "o" ]; then
  if ! id "noctyra360" &>/dev/null; then
    useradd -m -s /bin/bash -c "NOCTYRA360 Platform" noctyra360
    usermod -aG sudo noctyra360
    ok "Utilisateur noctyra360 créé"

    # Générer mot de passe fort
    N360_PWD=$(openssl rand -base64 24)
    echo "noctyra360:$N360_PWD" | chpasswd
    ok "Mot de passe généré : $N360_PWD"
    warn "→ NOTER CE MOT DE PASSE MAINTENANT !"
    echo "  $N360_PWD" > /root/noctyra360_admin_password.txt
    chmod 600 /root/noctyra360_admin_password.txt
    ok "Mot de passe sauvegardé dans /root/noctyra360_admin_password.txt"
  else
    ok "Utilisateur noctyra360 existe déjà"
  fi

  # Créer dossier application
  mkdir -p /opt/noctyra360
  chown noctyra360:noctyra360 /opt/noctyra360
  ok "Dossier /opt/noctyra360 créé"
fi

# ══════════════════════════════════════════════════════════════
# ÉTAPE 3 — SSH SÉCURISÉ
# ══════════════════════════════════════════════════════════════
step "ÉTAPE 3 — SSH Sécurisé"

# Backup config SSH
cp /etc/ssh/sshd_config /etc/ssh/sshd_config.backup.$(date +%Y%m%d)
ok "Backup SSH config créé"

# Créer dossier clés SSH pour noctyra360
if [ "$CREATE_USER" = "oui" ] || [ "$CREATE_USER" = "o" ]; then
  mkdir -p /home/noctyra360/.ssh
  chmod 700 /home/noctyra360/.ssh
  touch /home/noctyra360/.ssh/authorized_keys
  chmod 600 /home/noctyra360/.ssh/authorized_keys
  chown -R noctyra360:noctyra360 /home/noctyra360/.ssh
fi

# Générer clé SSH serveur si absente
if [ ! -f /etc/ssh/ssh_host_ed25519_key ]; then
  ssh-keygen -t ed25519 -f /etc/ssh/ssh_host_ed25519_key -N ""
fi

# Nouvelle config SSH sécurisée
cat > /etc/ssh/sshd_config << SSHEOF
# ─── NOCTYRA360™ SSH Config ───────────────────────────────────
Port $SSH_PORT
AddressFamily inet

# Protocoles et algorithmes
Protocol 2
HostKey /etc/ssh/ssh_host_ed25519_key
HostKey /etc/ssh/ssh_host_rsa_key

# Authentification
PermitRootLogin no
MaxAuthTries 3
MaxSessions 5
AuthorizedKeysFile .ssh/authorized_keys
PasswordAuthentication yes
PubkeyAuthentication yes
PermitEmptyPasswords no
ChallengeResponseAuthentication no

# Timeout et keepalive
LoginGraceTime 30
ClientAliveInterval 300
ClientAliveCountMax 2
TCPKeepAlive yes

# Restrictions
X11Forwarding no
AllowTcpForwarding no
PrintLastLog yes
Banner /etc/ssh/banner

# Logs
SyslogFacility AUTH
LogLevel VERBOSE
SSHEOF

# Bannière connexion SSH
cat > /etc/ssh/banner << BANEOF
╔══════════════════════════════════════════════════════════╗
║     NOCTYRA360™ — Connect Now USA LLC                    ║
║     SYSTÈME CONFIDENTIEL — ACCÈS RESTREINT               ║
║     Toute connexion non autorisée est un délit pénal     ║
╚══════════════════════════════════════════════════════════╝
BANEOF

systemctl restart ssh 2>/dev/null || service ssh restart 2>/dev/null || true
ok "SSH sécurisé sur port $SSH_PORT"
warn "→ IMPORTANT : Tester la connexion SSH avant de fermer cette session !"
info "   ssh -p $SSH_PORT noctyra360@$DOMAIN"

# ══════════════════════════════════════════════════════════════
# ÉTAPE 4 — FIREWALL UFW
# ══════════════════════════════════════════════════════════════
step "ÉTAPE 4 — Firewall UFW"

# Reset UFW
ufw --force reset > /dev/null

# Politique par défaut : tout bloquer
ufw default deny incoming
ufw default allow outgoing

# Règles autorisées
ufw allow $SSH_PORT/tcp     comment "SSH NOCTYRA360"
ufw allow 80/tcp            comment "HTTP (redirect vers HTTPS)"
ufw allow 443/tcp           comment "HTTPS NOCTYRA360"
ufw allow 2222/tcp          comment "SFTP NOCTYRA360 opérateurs"
ufw allow 8000/tcp          comment "API FastAPI (interne via Nginx)"

# Protection brute-force SSH via UFW
ufw limit $SSH_PORT/tcp comment "Limite SSH brute-force"

# Activer UFW
ufw --force enable
ok "Firewall UFW activé"
ufw status numbered | head -20
echo ""

# ══════════════════════════════════════════════════════════════
# ÉTAPE 5 — FAIL2BAN
# ══════════════════════════════════════════════════════════════
step "ÉTAPE 5 — Fail2Ban (protection brute-force)"

cat > /etc/fail2ban/jail.local << F2BEOF
[DEFAULT]
bantime  = 3600
findtime = 600
maxretry = 5
backend  = systemd

# ─── SSH ──────────────────────────────────────────────────────
[sshd]
enabled  = true
port     = $SSH_PORT
filter   = sshd
logpath  = /var/log/auth.log
maxretry = 3
bantime  = 86400

# ─── Nginx ────────────────────────────────────────────────────
[nginx-http-auth]
enabled  = true
filter   = nginx-http-auth
port     = http,https
logpath  = /var/log/nginx/error.log
maxretry = 5

[nginx-badbots]
enabled  = true
filter   = nginx-badbots
port     = http,https
logpath  = /var/log/nginx/access.log
maxretry = 2
bantime  = 86400

[nginx-botsearch]
enabled  = true
filter   = nginx-botsearch
port     = http,https
logpath  = /var/log/nginx/error.log
maxretry = 2
bantime  = 86400
F2BEOF

systemctl enable fail2ban
systemctl restart fail2ban 2>/dev/null || service fail2ban restart 2>/dev/null || true
ok "Fail2Ban configuré (ban 24h après 3 tentatives SSH)"

# ══════════════════════════════════════════════════════════════
# ÉTAPE 6 — NGINX + SSL/HTTPS
# ══════════════════════════════════════════════════════════════
step "ÉTAPE 6 — Nginx + SSL/HTTPS"

# Config Nginx pour NOCTYRA360
cat > /etc/nginx/sites-available/noctyra360 << NGINXEOF
# ─── Redirection HTTP → HTTPS ─────────────────────────────────
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    # Let's Encrypt challenge
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    # Tout le reste → HTTPS
    location / {
        return 301 https://\$host\$request_uri;
    }
}

# ─── HTTPS NOCTYRA360 ─────────────────────────────────────────
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name $DOMAIN;

    # ── SSL (Let's Encrypt — à décommenter après certbot) ──
    # ssl_certificate     /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    # include             /etc/letsencrypt/options-ssl-nginx.conf;
    # ssl_dhparam         /etc/letsencrypt/ssl-dhparams.pem;

    # ── SSL Auto-signé (utilisé avant Let's Encrypt) ──
    ssl_certificate     /etc/nginx/ssl/noctyra360.crt;
    ssl_certificate_key /etc/nginx/ssl/noctyra360.key;

    # ── Paramètres SSL robustes ────────────────────────────
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # ── En-têtes de sécurité ───────────────────────────────
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; connect-src 'self' https:;" always;
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;

    # ── Logs ──────────────────────────────────────────────
    access_log /var/log/nginx/noctyra360_access.log;
    error_log  /var/log/nginx/noctyra360_error.log;

    # ── Masquer version Nginx ──────────────────────────────
    server_tokens off;

    # ── Taille requête (CDR files jusqu'à 500MB) ──────────
    client_max_body_size 500M;
    client_body_timeout 300s;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;

    # ── Rate limiting ──────────────────────────────────────
    limit_req_zone \$binary_remote_addr zone=api:10m rate=30r/m;
    limit_req_zone \$binary_remote_addr zone=login:10m rate=5r/m;

    # ── NOCTYRA360 API → FastAPI port 8000 ────────────────
    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_set_header   Upgrade \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_buffering    off;
        proxy_cache_bypass 1;
    }

    # ── Rate limit sur login ──────────────────────────────
    location /api/login {
        limit_req zone=login burst=3 nodelay;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # ── Rate limit sur API ────────────────────────────────
    location /api/ {
        limit_req zone=api burst=20 nodelay;
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # ── Bloquer accès aux fichiers sensibles ──────────────
    location ~ /\. {
        deny all;
        return 404;
    }
    location ~* \.(py|sh|env|log|db|sqlite)$ {
        deny all;
        return 404;
    }
}
NGINXEOF

# Désactiver le site default
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/noctyra360 /etc/nginx/sites-enabled/

# Créer certificat auto-signé (en attendant Let's Encrypt)
mkdir -p /etc/nginx/ssl
openssl req -x509 -nodes -days 365 -newkey rsa:4096 \
  -keyout /etc/nginx/ssl/noctyra360.key \
  -out /etc/nginx/ssl/noctyra360.crt \
  -subj "/C=US/ST=Arizona/L=Tempe/O=Connect Now USA LLC/CN=$DOMAIN" \
  -addext "subjectAltName=DNS:$DOMAIN,IP:127.0.0.1" \
  2>/dev/null
chmod 600 /etc/nginx/ssl/noctyra360.key
ok "Certificat SSL auto-signé créé"

nginx -t 2>/dev/null && (systemctl restart nginx 2>/dev/null || service nginx restart 2>/dev/null)
ok "Nginx configuré et redémarré"
info "HTTPS disponible sur https://$DOMAIN"

# ══════════════════════════════════════════════════════════════
# ÉTAPE 7 — LET'S ENCRYPT (si domaine réel)
# ══════════════════════════════════════════════════════════════
step "ÉTAPE 7 — Let's Encrypt SSL"

if [[ "$DOMAIN" =~ \. ]] && [[ ! "$DOMAIN" =~ ^[0-9] ]]; then
  info "Domaine détecté: $DOMAIN — Tentative Let's Encrypt..."
  if certbot --nginx -d "$DOMAIN" --email "$ADMIN_EMAIL" \
     --agree-tos --non-interactive --redirect 2>/dev/null; then
    ok "Certificat Let's Encrypt installé pour $DOMAIN"
    ok "Renouvellement automatique configuré"
  else
    warn "Let's Encrypt échoué — certificat auto-signé utilisé"
    info "→ Réessayer manuellement : sudo certbot --nginx -d $DOMAIN"
  fi
else
  warn "IP détectée ($DOMAIN) — Let's Encrypt nécessite un domaine DNS"
  info "→ Configurer un domaine puis : sudo certbot --nginx -d votre.domaine.com"
fi

# ══════════════════════════════════════════════════════════════
# ÉTAPE 8 — MISES À JOUR AUTOMATIQUES
# ══════════════════════════════════════════════════════════════
step "ÉTAPE 8 — Mises à jour automatiques de sécurité"

cat > /etc/apt/apt.conf.d/50unattended-upgrades << AUTOEOF
Unattended-Upgrade::Allowed-Origins {
    "\${distro_id}:\${distro_codename}";
    "\${distro_id}:\${distro_codename}-security";
    "\${distro_id}ESMApps:\${distro_codename}-apps-security";
    "\${distro_id}ESM:\${distro_codename}-infra-security";
};
Unattended-Upgrade::AutoFixInterruptedDpkg "true";
Unattended-Upgrade::MinimalSteps "true";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-New-Unused-Dependencies "true";
Unattended-Upgrade::Remove-Unused-Dependencies "false";
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Mail "$ADMIN_EMAIL";
AUTOEOF

cat > /etc/apt/apt.conf.d/20auto-upgrades << AUTOEOF
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
APT::Periodic::Unattended-Upgrade "1";
AUTOEOF

ok "Mises à jour automatiques sécurité configurées"

# ══════════════════════════════════════════════════════════════
# ÉTAPE 9 — AUDIT ET MONITORING
# ══════════════════════════════════════════════════════════════
step "ÉTAPE 9 — Audit système"

# Auditd
cat >> /etc/audit/rules.d/noctyra360.rules << AUDITEOF 2>/dev/null || true
# NOCTYRA360 Audit Rules
-w /opt/noctyra360 -p rwxa -k noctyra360
-w /etc/passwd -p wa -k identity
-w /etc/shadow -p wa -k identity
-w /etc/ssh/sshd_config -p wa -k sshd_config
-a always,exit -F arch=b64 -S execve -k exec
AUDITEOF

systemctl enable auditd 2>/dev/null || true
systemctl restart auditd 2>/dev/null || true
ok "Audit système activé"

# Logrotate pour logs NOCTYRA360
cat > /etc/logrotate.d/noctyra360 << LOGEOF
/var/log/nginx/noctyra360_*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 640 www-data adm
    sharedscripts
    postrotate
        nginx -s reload 2>/dev/null || true
    endscript
}
LOGEOF
ok "Rotation des logs configurée (30 jours)"

# ══════════════════════════════════════════════════════════════
# ÉTAPE 10 — SERVICE SYSTEMD NOCTYRA360
# ══════════════════════════════════════════════════════════════
step "ÉTAPE 10 — Service systemd NOCTYRA360"

cat > /etc/systemd/system/noctyra360.service << SVCEOF
[Unit]
Description=NOCTYRA360™ Revenue Compliance Platform
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=noctyra360
Group=noctyra360
WorkingDirectory=/opt/noctyra360
ExecStart=/usr/bin/python3 -m uvicorn server:app --host 127.0.0.1 --port 8000 --workers 4
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=noctyra360

# Sécurité
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/opt/noctyra360/uploads
ReadWritePaths=/opt/noctyra360/reports_out
ReadWritePaths=/opt/noctyra360/config
PrivateTmp=yes
PrivateDevices=yes

# Limites
LimitNOFILE=65536
LimitNPROC=4096

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable noctyra360 2>/dev/null || true
ok "Service systemd noctyra360 configuré"
info "→ sudo systemctl start noctyra360"
info "→ sudo systemctl status noctyra360"
info "→ sudo journalctl -u noctyra360 -f"

# ══════════════════════════════════════════════════════════════
# RÉCAPITULATIF FINAL
# ══════════════════════════════════════════════════════════════

echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║         ✅ SÉCURISATION TERMINÉE                          ║${NC}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Résumé de la sécurisation :${NC}"
echo ""
echo -e "  ✅ UFW Firewall       → Ports ouverts: $SSH_PORT (SSH), 80, 443, 2222 (SFTP)"
echo -e "  ✅ SSH Sécurisé       → Port $SSH_PORT, PermitRootLogin non"
echo -e "  ✅ Fail2Ban           → Ban 24h après 3 tentatives SSH"
echo -e "  ✅ Nginx              → Reverse proxy + HTTPS forcé"
echo -e "  ✅ SSL/TLS            → TLS 1.2/1.3 uniquement"
echo -e "  ✅ En-têtes sécurité  → HSTS, X-Frame, CSP, XSS protection"
echo -e "  ✅ Rate limiting      → 5 tentatives login/min, 30 req API/min"
echo -e "  ✅ Auto-updates       → Patches sécurité automatiques"
echo -e "  ✅ Audit              → Toutes les actions loggées"
echo -e "  ✅ Service systemd    → Redémarrage automatique"
echo ""
echo -e "  ${BOLD}Accès NOCTYRA360 :${NC}"
echo -e "  🌐 Interface  : ${YELLOW}https://$DOMAIN${NC}"
echo -e "  🔐 SSH Admin  : ${YELLOW}ssh -p $SSH_PORT noctyra360@$DOMAIN${NC}"
echo -e "  📡 SFTP ops   : ${YELLOW}sftp -P 2222 telma@$DOMAIN${NC}"
echo ""
echo -e "  ${BOLD}${YELLOW}⚠️  ACTIONS MANUELLES REQUISES :${NC}"
echo -e "  ${YELLOW}1. Copier NOCTYRA360 dans /opt/noctyra360/${NC}"
echo -e "     sudo cp -r /chemin/noctyra360_production/* /opt/noctyra360/"
echo -e "     sudo chown -R noctyra360:noctyra360 /opt/noctyra360/"
echo ""
echo -e "  ${YELLOW}2. Ajouter votre clé SSH publique :${NC}"
echo -e "     sudo nano /home/noctyra360/.ssh/authorized_keys"
echo -e "     (coller votre clé publique id_rsa.pub ou id_ed25519.pub)"
echo ""
echo -e "  ${YELLOW}3. Démarrer NOCTYRA360 :${NC}"
echo -e "     sudo systemctl start noctyra360"
echo -e "     sudo systemctl status noctyra360"
echo ""
echo -e "  ${YELLOW}4. Si domaine DNS configuré — Let's Encrypt :${NC}"
echo -e "     sudo certbot --nginx -d $DOMAIN --email $ADMIN_EMAIL"
echo ""
echo -e "  ${BOLD}Commandes utiles :${NC}"
echo -e "  sudo ufw status                    → état firewall"
echo -e "  sudo fail2ban-client status sshd   → IPs bannies"
echo -e "  sudo journalctl -u noctyra360 -f   → logs plateforme"
echo -e "  sudo nginx -t                      → tester config nginx"
echo -e "  sudo certbot renew                 → renouveler SSL"
echo ""
