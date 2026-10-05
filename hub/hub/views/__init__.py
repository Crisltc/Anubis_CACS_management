"""
Aides partagées par les modules de vues.

Les cinq modules (core, projects, inventory, bom, library, poles) sont
indépendants les uns des autres ; ce qui est ici est le seul code qu'ils ont
en commun.
"""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import IntegrityError


def save_or_report(request, obj, what="Ce nom"):
    """
    Enregistre `obj`, ou explique pourquoi ça n'a pas marché.

    Les noms de projets, d'éléments, de composants et de pages de wiki sont
    uniques en base. Sans ce garde-fou, saisir un nom déjà pris renvoie une
    erreur 500 à la figure de l'utilisateur au lieu de lui dire simplement
    de choisir autre chose — et le cas arrive tout le temps quand plusieurs
    personnes remplissent le Hub le même soir.

    Renvoie True si l'enregistrement a réussi.
    """
    try:
        obj.save()
        return True
    except IntegrityError:
        messages.error(request, f"{what} est déjà pris. Choisis-en un autre.")
        return False


def _qty(raw, default=None):
    """Nombre saisi à la main — la virgule française est acceptée."""
    try:
        return Decimal(str(raw).replace(",", ".").strip())
    except (InvalidOperation, AttributeError, ValueError):
        return default
