#!/bin/bash
# NOCTYRA360™ — Installation PostgreSQL (WSL Ubuntu)
# Compatible Windows WSL — utilise sudo

echo "=== NOCTYRA360™ — PostgreSQL Setup ==="
echo "Environnement: Windows WSL Ubuntu"
echo ""

# ── ÉTAPE 1 : Installer les packages Python ───────────────────
echo "→ [1/5] Installation dépendances Python..."
pip3 install sqlalchemy psycopg2-binary --break-system-packages -q 2>/dev/null || \
pip install  sqlalchemy psycopg2-binary -q 2>/dev/null || \
pip3 install sqlalchemy psycopg2-binary -q 2>/dev/null

python3 -c "import sqlalchemy; print('  ✅ SQLAlchemy', sqlalchemy.__version__)" 2>/dev/null || \
    echo "  ❌ SQLAlchemy — installation manuelle requise"

# ── ÉTAPE 2 : Installer PostgreSQL avec sudo ──────────────────
echo ""
echo "→ [2/5] Installation PostgreSQL (sudo requis)..."
sudo apt-get install -y postgresql postgresql-contrib -q 2>/dev/null
if [ $? -ne 0 ]; then
    echo "  ⚠️  sudo apt-get échoué — essai avec apt..."
    sudo apt install -y postgresql postgresql-contrib -q 2>/dev/null
fi

# ── ÉTAPE 3 : Démarrer PostgreSQL ────────────────────────────
echo ""
echo "→ [3/5] Démarrage PostgreSQL..."
sudo service postgresql start 2>/dev/null || \
sudo systemctl start postgresql 2>/dev/null || \
sudo pg_ctlcluster 16 main start 2>/dev/null || \
sudo pg_ctlcluster 14 main start 2>/dev/null
sleep 3

# Vérifier que PostgreSQL tourne
if pg_isready -q 2>/dev/null; then
    echo "  ✅ PostgreSQL démarré"
else
    echo "  ⚠️  PostgreSQL — essai démarrage manuel..."
    sudo -u postgres pg_ctl start -D /var/lib/postgresql/16/main 2>/dev/null || \
    sudo -u postgres pg_ctl start -D /var/lib/postgresql/14/main 2>/dev/null
    sleep 2
fi

# ── ÉTAPE 4 : Créer utilisateur et base ──────────────────────
echo ""
echo "→ [4/5] Création base de données noctyra360db..."

# Configurer auth trust
PG_VER=$(ls /etc/postgresql/ 2>/dev/null | head -1)
if [ -n "$PG_VER" ]; then
    PG_HBA="/etc/postgresql/$PG_VER/main/pg_hba.conf"
    echo "  → Configuration auth: $PG_HBA"

    # Ajouter rule trust pour noctyra360 (en premier)
    grep -q "noctyra360db.*noctyra360.*trust" "$PG_HBA" 2>/dev/null || \
    echo "local   noctyra360db    noctyra360                              trust" | \
        sudo tee -a "$PG_HBA" > /dev/null

    # Changer postgres de peer à trust pour les commandes ci-dessous
    sudo sed -i \
        's/^local   all             postgres.*peer/local   all             postgres                                trust/' \
        "$PG_HBA" 2>/dev/null

    sudo service postgresql restart 2>/dev/null
    sleep 2
fi

# Créer user et database
psql -U postgres -c "CREATE USER noctyra360 WITH PASSWORD '' CREATEDB;" 2>/dev/null && \
    echo "  ✅ Utilisateur noctyra360 créé"
psql -U postgres -c "CREATE DATABASE noctyra360db OWNER noctyra360 ENCODING 'UTF8';" 2>/dev/null && \
    echo "  ✅ Base noctyra360db créée"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE noctyra360db TO noctyra360;" 2>/dev/null

# ── ÉTAPE 5 : Tester ─────────────────────────────────────────
echo ""
echo "→ [5/5] Test de connexion..."

python3 -c "
import sys
sys.path.insert(0, '.')
try:
    from core.database import DB_TYPE, init_db, db_get_stats
    print(f'  ✅ DB Type: {DB_TYPE}')
    init_db()
    stats = db_get_stats()
    print(f'  ✅ Base opérationnelle — {stats.get(\"total_findings\",0)} résultats stockés')
except Exception as e:
    print(f'  ❌ Erreur: {e}')
    import traceback; traceback.print_exc()
"

echo ""
echo "=== RÉSULTAT ==="
python3 -c "
import sys; sys.path.insert(0,'.')
from core.database import DB_TYPE
if DB_TYPE == 'postgresql':
    print('✅ PostgreSQL actif — données persistantes')
else:
    print('✅ SQLite actif (fallback) — données persistantes dans noctyra360.db')
    print('   → Pour PostgreSQL: relancer avec sudo ou installer manuellement')
"
echo ""
echo "Relancer maintenant : bash run.sh"
