"""
Pipeline photo : les photos de téléphone (5 Mo et plus) sont recompressées à
l'upload et l'original est JETÉ. Résultat ~150-300 Ko par photo — des années
d'historique tiennent sur la carte SD d'un Raspberry Pi.
"""
import io

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_SIZE = 1600     # côté max de l'image principale
THUMB_SIZE = 400    # côté max de la miniature
QUALITY = 80        # indiscernable pour des photos d'atelier


def _to_webp(img, max_side):
    """Redimensionne (thumbnail conserve le ratio et n'agrandit jamais)."""
    img = img.copy()
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=QUALITY)
    return ContentFile(buf.getvalue())


def process_photo(uploaded_file):
    """Fichier uploadé → (WebP 1600 px, WebP 400 px)."""
    img = Image.open(uploaded_file)
    # Rotation EXIF : sans elle, toute photo prise en portrait s'affiche couchée.
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return _to_webp(img, MAX_SIZE), _to_webp(img, THUMB_SIZE)
