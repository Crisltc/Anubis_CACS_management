"""Vues transverses : connexion, médias protégés, recherche, healthcheck."""
import mimetypes
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.postgres.search import SearchQuery, SearchVector
from django.db import connection
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render

from ..models import Board, Document, Part, Post, Project, WikiPage


# ---------------------------------------------------------------------------
# Connexion / déconnexion
# ---------------------------------------------------------------------------
def login_view(request):
    """
    Prénom + mot de passe. L'admin est testé EN PREMIER : un même prénom peut
    ouvrir une session membre ou admin selon le mot de passe donné.
    Le prénom est libre mais obligatoire — c'est lui qui signe tout.
    """
    if request.method == "POST":
        prenom = request.POST.get("prenom", "").strip()
        password = request.POST.get("password", "")
        admin = settings.HUB_ADMIN_PASSWORD
        member = settings.HUB_SHARED_PASSWORD
        if not prenom:
            messages.error(request,
                           "Le prénom est obligatoire : il signe tes contributions.")
        elif password and password in (admin, member):
            request.session["prenom"] = prenom
            request.session["is_admin"] = bool(admin) and password == admin
            return redirect(request.GET.get("suivant") or "dashboard")
        else:
            messages.error(request, "Mot de passe incorrect.")
    return render(request, "core/login.html")


def logout_view(request):
    request.session.flush()
    return redirect("login")


# ---------------------------------------------------------------------------
# Médias protégés
# ---------------------------------------------------------------------------
def protected_media(request, relpath):
    """
    Sert un fichier de MEDIA_ROOT après contrôle de session (le middleware a
    déjà refusé les non-connectés). Ici on empêche la traversée de chemin en
    comparant les chemins RÉSOLUS — un `..` ne suffit pas à sortir du dossier.
    À notre échelle, servir via Django suffit : pas besoin de X-Accel-Redirect.
    """
    root = Path(settings.MEDIA_ROOT).resolve()
    target = (root / relpath).resolve()
    if root not in target.parents or not target.is_file():
        raise Http404
    ctype, _ = mimetypes.guess_type(str(target))
    resp = FileResponse(open(target, "rb"),
                        content_type=ctype or "application/octet-stream")
    # `inline` : les PDF s'affichent dans le navigateur au lieu d'être
    # téléchargés — c'est ce qui fait marcher les visionneuses en <iframe>.
    resp["Content-Disposition"] = f'inline; filename="{target.name}"'
    return resp


# ---------------------------------------------------------------------------
# Recherche transversale
# ---------------------------------------------------------------------------
# (modèle, champs plein texte, titre de section). Chercher « alimentation »
# ramène aussi les RAPPORTS PDF qui en parlent : leur texte a été extrait à
# l'upload et vit dans Document.text_content.
FULLTEXT = [
    (Project, ("name", "description"), "Projets"),
    (Board, ("name", "notes"), "Cartes"),
    (Document, ("title", "authors", "text_content"), "Documents"),
    (WikiPage, ("title", "content_md"), "Wiki"),
    (Post, ("text_md",), "Publications"),
]


def search(request):
    """Une seule barre pour tout le Hub.

    Le SearchVector est construit À LA VOLÉE : à quelques milliers de lignes,
    stocker et indexer un vecteur matérialisé serait du luxe payé en
    complexité de schéma."""
    q = request.GET.get("q", "").strip()
    ctx = {"q": q, "parts": [], "groups": []}
    if q:
        # Composants : le catalogue est petit, `icontains` suffit largement.
        ctx["parts"] = (Part.objects.with_stock()
                        .filter(Q(name__icontains=q) | Q(mpn__icontains=q)
                                | Q(sku__icontains=q))
                        .select_related("location")[:10])
        sq = SearchQuery(q, config="french")
        ctx["groups"] = [
            (title, model.objects.annotate(
                sv=SearchVector(*fields, config="french")).filter(sv=sq)[:10])
            for model, fields, title in FULLTEXT
        ]
        # Évalué ici (et mis en cache par le queryset) plutôt que via cinq
        # tests recopiés dans le template.
        ctx["found"] = bool(ctx["parts"]) or any(i for _, i in ctx["groups"])
    return render(request, "core/search.html", ctx)


def health(request):
    """Supervision : 200 si Django ET la base répondent."""
    with connection.cursor() as cur:
        cur.execute("SELECT 1")
    return HttpResponse("ok")
