# Image du Hub : python slim + wheels pip (toutes disponibles en arm64, donc
# build direct sur Raspberry Pi sans compilation).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Le bit exécutable se perd selon le système qui a fait le clone (Windows) :
# on le fixe dans l'image plutôt que de compter sur git.
RUN chmod +x entrypoint.sh

# /data = volume docker hub_media : médias (photos, PDF) + statiques collectés.
RUN mkdir -p /data/media /data/static

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
