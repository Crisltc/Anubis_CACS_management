#!/usr/bin/env bash
# ============================================================================
# Restauration complète depuis une archive chiffrée.
#
#   ./scripts/restore.sh aero-backup-2026-08-20.tar.age cle-privee-age.txt
#
# À exécuter sur une machine où le dépôt est cloné et le .env rempli.
# ATTENTION : écrase la base et les médias existants.
#
# Le test de restauration complet par le nouvel admin fait partie de la
# checklist de passation : tant qu'il n'est pas passé, la passation n'est
# pas finie.
# ============================================================================
set -euo pipefail

ARCHIVE="${1:?usage: restore.sh <archive.tar.age> <clé-privée-age>}"
KEY="${2:?usage: restore.sh <archive.tar.age> <clé-privée-age>}"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="docker compose --project-directory ${REPO_DIR}"
set -a; source "${REPO_DIR}/.env"; set +a
DB="${HUB_DB_NAME:-hub}"
PROJECT="$(basename "${REPO_DIR}" | tr 'A-Z' 'a-z' | tr -cd 'a-z0-9_-')"

read -rp "Cette opération ÉCRASE les données actuelles. Taper OUI pour continuer : " CONFIRM
[[ "${CONFIRM}" == "OUI" ]] || { echo "Abandon."; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

echo "--- Déchiffrement et extraction"
age -d -i "${KEY}" "${ARCHIVE}" | tar -xf - -C "${WORK}"
ls -l "${WORK}"

echo "--- Démarrage de la base seule"
${COMPOSE} up -d db
until ${COMPOSE} exec -T db pg_isready -U "${DB_USER}" >/dev/null 2>&1; do sleep 2; done

echo "--- Restauration de la base (drop + create + pg_restore)"
${COMPOSE} exec -T db psql -U "${DB_USER}" -d postgres \
  -c "DROP DATABASE IF EXISTS ${DB};" \
  -c "CREATE DATABASE ${DB} OWNER ${DB_USER};"
${COMPOSE} exec -T db pg_restore -U "${DB_USER}" -d "${DB}" --no-owner \
  < "${WORK}/hub.dump"

echo "--- Restauration des médias"
if [[ -f "${WORK}/hub-media.tar" ]]; then
  docker run --rm -v "${PROJECT}_hub_media":/data -v "${WORK}":/in:ro \
    alpine tar -xf /in/hub-media.tar -C /data
fi

echo "--- Redémarrage complet"
${COMPOSE} up -d

echo
echo "Restauration terminée. Vérifie : un projet, une photo de fil, un PDF de"
echo "la bibliothèque, et le stock d'un composant du catalogue."
