#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# NOCTYRA360™ — Guide LUKS Chiffrement Disque
# ⚠️  À exécuter AVANT l'installation du système
#     ou sur un disque/partition supplémentaire
# ═══════════════════════════════════════════════════════════════

cat << 'GUIDEEOF'
╔══════════════════════════════════════════════════════════════╗
║     NOCTYRA360™ — LUKS Chiffrement Disque                   ║
║     Connect Now USA LLC                                      ║
╚══════════════════════════════════════════════════════════════╝

LUKS (Linux Unified Key Setup) chiffre le disque entier.
Si le serveur est volé → données illisibles sans le mot de passe.

═══════════════════════════════════════════════════════════════
OPTION A — Chiffrement lors de l'installation Ubuntu
═══════════════════════════════════════════════════════════════

1. Démarrer l'installeur Ubuntu Server 22.04
2. À l'étape "Guided storage configuration"
   → Cocher "Set up this disk as an LVM group"
   → Cocher "Encrypt the LVM group with LUKS"
3. Saisir une passphrase forte (minimum 20 caractères)
   Exemple : N360-Madison-2026-SecureServer!
4. Confirmer et continuer l'installation
5. Au redémarrage → saisir la passphrase

RECOMMANDÉ pour les nouveaux serveurs.

═══════════════════════════════════════════════════════════════
OPTION B — Chiffrer un disque/partition supplémentaire
═══════════════════════════════════════════════════════════════
(Pour les données NOCTYRA360 sur un disque séparé)

ATTENTION : Cette opération EFFACE toutes les données du disque.

# 1. Identifier le disque
lsblk
# Exemple : /dev/sdb

# 2. Chiffrer le disque
sudo cryptsetup luksFormat /dev/sdb
# → Saisir YES en majuscules
# → Saisir passphrase forte (2x)

# 3. Ouvrir le volume chiffré
sudo cryptsetup open /dev/sdb noctyra360_data

# 4. Formater
sudo mkfs.ext4 /dev/mapper/noctyra360_data

# 5. Monter
sudo mkdir -p /opt/noctyra360
sudo mount /dev/mapper/noctyra360_data /opt/noctyra360

# 6. Montage automatique au démarrage
# Obtenir l'UUID du disque chiffré
sudo blkid /dev/sdb
# Ajouter dans /etc/crypttab :
echo "noctyra360_data UUID=VOTRE-UUID none luks" | sudo tee -a /etc/crypttab
# Ajouter dans /etc/fstab :
echo "/dev/mapper/noctyra360_data /opt/noctyra360 ext4 defaults 0 2" | sudo tee -a /etc/fstab

═══════════════════════════════════════════════════════════════
OPTION C — Chiffrement dossier (EncFS — sans reformater)
═══════════════════════════════════════════════════════════════
(Plus simple — chiffre seulement les données NOCTYRA360)

sudo apt-get install -y encfs

# Créer dossier chiffré
mkdir -p /opt/.noctyra360_enc /opt/noctyra360
encfs /opt/.noctyra360_enc /opt/noctyra360
# → Choisir "p" (mode paranoïa)
# → Saisir passphrase

# Monter automatiquement via script
cat > /opt/mount_noctyra360.sh << 'MOUNTEOF'
#!/bin/bash
echo "Passphrase NOCTYRA360 :"
encfs /opt/.noctyra360_enc /opt/noctyra360
MOUNTEOF
chmod +x /opt/mount_noctyra360.sh

═══════════════════════════════════════════════════════════════
RECOMMANDATIONS PASSPHRASE
═══════════════════════════════════════════════════════════════

✅ Minimum 20 caractères
✅ Majuscules + minuscules + chiffres + symboles
✅ Exemple : N360-CAR-MDG-2026-Ultra!Secure#Server

✅ Stocker la passphrase :
   → Coffre-fort physique
   → Gestionnaire de mots de passe (Bitwarden, 1Password)
   → Jamais en clair sur le serveur
   → Jamais dans un email

⚠️  Si passphrase perdue → données IRRÉCUPÉRABLES
⚠️  Tester la passphrase avant mise en production

GUIDEEOF
