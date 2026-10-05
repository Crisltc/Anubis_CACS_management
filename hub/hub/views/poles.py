"""
Ce qui est PROPRE aux pôles méca et soft.

Tout le reste — projets, kanban, fil, photos, stock, documents, wiki — est
déjà commun aux trois pôles : un pôle n'est pas un Hub séparé, c'est un
attribut des éléments d'un même projet. Il ne restait donc que deux manques
réels, et les deux appliquent la doctrine du stock (une somme / une dernière
ligne sur un registre qu'on ne réécrit pas) :

  MÉCA — masse & centrage : la masse d'une fusée est la SOMME des pièces
         réellement pesées, jamais un chiffre tenu à jour à la main.
  SOFT — registre de flash : la version qui tourne sur une carte est le
         DERNIER flash réussi, jamais un champ à resynchroniser.
"""
from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..middleware import require_admin
from ..models import Board, Flash, MassItem, Project
from . import _qty


# ---------------------------------------------------------------------------
# Méca : masse et centrage
# ---------------------------------------------------------------------------
def mass_balance(request, slug):
    """
    Budget de masse de la fusée : chaque pièce pesée, sa position depuis la
    pointe, et ce qui en découle — masse totale, CG, marge statique.

    Le Hub ne calcule pas l'aérodynamique : le centre de poussée est recopié
    d'OpenRocket. Ce que le Hub apporte, c'est la masse RÉELLE au lieu de
    celle de la CAO — la seule qui volera.
    """
    project = get_object_or_404(Project, slug=slug)

    if request.method == "POST":
        if request.POST.get("action") == "geometrie":
            project.diameter_mm = _qty(request.POST.get("diameter_mm"), None)
            project.cp_mm = _qty(request.POST.get("cp_mm"), None)
            project.min_margin = (_qty(request.POST.get("min_margin"))
                                  or project.min_margin)
            project.save()
            messages.success(request, "Géométrie enregistrée.")
        else:
            mass = _qty(request.POST.get("mass_g"))
            position = _qty(request.POST.get("position_mm"))
            # L'élément est filtré SUR CE PROJET : sans ça, un identifiant
            # posté à la main rattacherait une pesée à la fusée d'à côté.
            board = project.boards.filter(
                pk=request.POST.get("board") or 0).first()
            # Choisir un élément suffit : son nom devient la désignation. La
            # saisie libre reste possible pour tout ce qui n'est pas un
            # élément suivi (moteur, parachute, lest, colle…) et pour
            # préciser un élément (« Coiffe + porte-parachute »).
            name = request.POST.get("name", "").strip() or (
                board.name if board else "")
            if not name or mass is None or position is None:
                messages.error(request, "Choisis un élément ou saisis une "
                               "désignation, puis la masse et la position.")
            elif mass <= 0:
                messages.error(request, "Une masse pesée est strictement "
                               "positive.")
            else:
                MassItem.objects.create(
                    project=project, name=name, mass_g=mass,
                    position_mm=position, board=board,
                    note=request.POST.get("note", "").strip(),
                    author=request.session["prenom"])
                messages.success(request, f"« {name} » ajouté au budget de masse.")
        return redirect("mass_balance", slug=project.slug)

    total, cg, margin = project.mass_balance()
    return render(request, "projects/mass_balance.html", {
        "project": project,
        "items": project.mass_items.select_related("board"),
        "total_g": total, "cg": cg, "margin": margin,
        # Une marge insuffisante = fusée instable. On l'affiche en rouge et on
        # le dit ; c'est le cahier des charges de la campagne qui tranche.
        "unstable": margin is not None and margin < project.min_margin,
        # Annotés du nombre de pesées : le menu signale les éléments DÉJÀ
        # pesés, parce que compter deux fois la même pièce est l'erreur qui
        # fausse un budget de masse sans rien casser de visible.
        "boards": project.boards.annotate(n_masses=Count("mass_items")),
    })


@require_admin
@require_POST
def mass_item_delete(request, pk):
    """Retirer une pesée. Réservé admin : une ligne effacée déplace le CG de
    toute la fusée sans laisser de trace."""
    item = get_object_or_404(MassItem, pk=pk)
    slug = item.project.slug
    item.delete()
    messages.success(request, "Pesée retirée du budget de masse.")
    return redirect("mass_balance", slug=slug)


# ---------------------------------------------------------------------------
# Soft : registre de flash
# ---------------------------------------------------------------------------
def flash_log(request, pk):
    """
    Qui a flashé quelle version, sur quelle carte, quand, et est-ce que ça a
    marché. La version courante se lit en haut : c'est la dernière ligne
    réussie, donc elle ne peut pas mentir.
    """
    board = get_object_or_404(Board.objects.select_related("project"), pk=pk)

    if request.method == "POST":
        version = request.POST.get("version", "").strip()
        if not version:
            messages.error(request, "La version est obligatoire : c'est elle "
                           "qu'on cherchera après le vol.")
        else:
            Flash.objects.create(
                board=board, version=version,
                git_ref=request.POST.get("git_ref", "").strip(),
                target_id=request.POST.get("target") or None,
                ok=bool(request.POST.get("ok")),
                notes=request.POST.get("notes", "").strip(),
                author=request.session["prenom"])
            messages.success(request, f"Flash « {version} » enregistré.")
        return redirect("flash_log", pk=board.pk)

    return render(request, "projects/flash_log.html", {
        "board": board,
        "firmware": board.current_firmware(),
        "flashes": board.flashes.select_related("target")[:50],
        # Cibles proposées : les cartes ÉLEC du même projet — c'est sur
        # elles qu'un firmware se flashe.
        "targets": board.project.boards.filter(pole="elec"),
    })
