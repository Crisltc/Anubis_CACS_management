#!/bin/sh
# Démarrage du conteneur : migrations, statiques, gunicorn.
# Les migrations s'appliquent automatiquement → mise à jour = git pull +
# `docker compose up -d --build`, rien d'autre à faire.
set -e
echo "Attente de la base de données…"
# Boucle BORNÉE (~60 s) : une attente infinie muette donne un conteneur qui
# « démarre » sans jamais servir et cache la vraie panne (mot de passe faux,
# base absente). Au bout de 30 essais on laisse l'erreur partir au journal.
i=0
until python manage.py migrate --noinput >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then
    echo "Base injoignable après 60 s — dernière erreur :" >&2
    python manage.py migrate --noinput   # sans filtre : la trace est visible
    exit 1
  fi
  sleep 2
done
python manage.py collectstatic --noinput
exec gunicorn wsgi:application --bind 0.0.0.0:8000 \
  --workers 1 --timeout 60 --access-logfile - --error-logfile -
