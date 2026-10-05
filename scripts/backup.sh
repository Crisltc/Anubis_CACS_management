#!/usr/bin/env bash
# ============================================================================
# Sauvegarde nocturne — s'exécute SUR le serveur (cron), sans accès sortant.
#
# Produit dans $BACKUP_DIR une archive chiffrée avec la clé PUBLIQUE age du
# responsable (BACKUP_AGE_RECIPIENT du .env) :
#
#   aero-backup-AAAA-MM-JJ.tar.age
#     ├── hub.dump       (pg_dump -Fc : projets, stock, mouvements, wiki…)
#     ├── hub-media.tar  (photos WebP, PDF de la bibliothèque)
#     └── MANIFEST.txt   (date, tailles — pour vérification)
#
# La clé PRIVÉE n'est JAMAIS sur le serveur : même compromis, les archives
# restent illisibles.
#
# Installation (une fois) :
#   sudo apt-get install -y age
#   crontab -e →  17 3 * * * /srv/aero/aero-platform-V3/scripts/backup.sh \
#                              >> /srv/aero/backups/backup.log 2>&1
# ============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-/srv/aero/backups}"
COMPOSE="docker compose --project-directory ${REPO_DIR}"

set -a; source "${REPO_DIR}/.env"; set +a
: "${BACKUP_AGE_RECIPIENT:?BACKUP_AGE_RECIPIENT manquant dans .env}"

# Nom du volume docker : compose préfixe du nom de projet, qui est le nom du
# dossier mis en minuscules et débarrassé des caractères hors [a-z0-9_-].
PROJECT="$(basename "${REPO_DIR}" | tr 'A-Z' 'a-z' | tr -cd 'a-z0-9_-')"
VOLUME="${PROJECT}_hub_media"

STAMP="$(date +%F)"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
mkdir -p "${BACKUP_DIR}"

echo "[$(date -Is)] Début de la sauvegarde ${STAMP}"

# --- 1. Dump PostgreSQL (format custom : compressé, restauration sélective) --
${COMPOSE} exec -T db pg_dump -U "${DB_USER}" -Fc "${HUB_DB_NAME:-hub}" \
  > "${WORK}/hub.dump"

# --- 2. Médias (photos, PDF, datasheets) ------------------------------------
docker run --rm -v "${VOLUME}":/data:ro -v "${WORK}":/out \
  alpine tar -cf /out/hub-media.tar -C /data media 2>/dev/null \
  || echo "  (volume ${VOLUME} vide — normal sur une installation neuve)"

# --- 3. Manifeste ------------------------------------------------------------
{ echo "date=${STAMP}"; echo "host=$(hostname)"; ls -l "${WORK}"; } \
  > "${WORK}/MANIFEST.txt"

# --- 4. Archive unique + chiffrement age ------------------------------------
OUT="${BACKUP_DIR}/aero-backup-${STAMP}.tar.age"
tar -cf - -C "${WORK}" . | age -r "${BACKUP_AGE_RECIPIENT}" -o "${OUT}"
echo "aero-backup-${STAMP}.tar.age" > "${BACKUP_DIR}/latest.txt"

# --- 5. Rotation locale ------------------------------------------------------
find "${BACKUP_DIR}" -name 'aero-backup-*.tar.age' \
  -mtime "+${BACKUP_KEEP_DAYS:-14}" -delete

echo "[$(date -Is)] OK — $(du -h "${OUT}" | cut -f1) → ${OUT}"
