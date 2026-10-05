"""
Authentification « maison » du Hub — et rien d'autre.

PAS de comptes individuels : un mot de passe partagé ouvre la session,
l'utilisateur donne son prénom, et ce prénom signe tout (posts, commentaires,
mouvements de stock, révisions du wiki). Un second mot de passe débloque les
actions destructives.

La session contient au maximum deux clés, pas une de plus :
    session["prenom"]   : str  → présent = connecté
    session["is_admin"] : bool → droits étendus
"""
from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

# Préfixes accessibles SANS session — tout le reste est protégé.
PUBLIC_PREFIXES = ("/connexion/", "/static/", "/sante/")


class SharedPasswordMiddleware:
    """Redirige vers la connexion toute requête sans session valide."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (not request.path.startswith(PUBLIC_PREFIXES)
                and not request.session.get("prenom")):
            # On mémorise la page demandée pour y revenir après connexion.
            return redirect(f"{reverse('login')}?suivant={request.path}")
        return self.get_response(request)


def require_admin(view):
    """Décorateur : réserve une vue aux sessions admin (suppressions…)."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.session.get("is_admin"):
            messages.error(request, "Action réservée à l'admin. "
                           "Reconnecte-toi avec le mot de passe admin.")
            return redirect("dashboard")
        return view(request, *args, **kwargs)
    return wrapper


def hub_context(request):
    """Context processor : ce que l'entête affiche sur TOUTES les pages —
    l'identité de session et la liste des pôles du sélecteur. Vit ici plutôt
    que dans un fichier à part, c'est la même notion que le middleware."""
    from .models import POLES
    return {"prenom": request.session.get("prenom"),
            "is_admin": request.session.get("is_admin", False),
            "poles": POLES}
