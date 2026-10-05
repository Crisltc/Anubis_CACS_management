"""
Tableau de bord, projets, cartes, sous-pages d'étape, kanban, fil d'activité.

Style volontairement « vues fonctions + templates » : le plus lisible pour un
successeur qui découvre Django. htmx n'intervient QUE pour les commentaires ;
partout ailleurs, POST/redirect classique.
"""
import json

from django.contrib import messages
from django.db.models import Prefetch, Sum
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..images import process_photo
from ..middleware import require_admin
from ..models import (ZERO, Board, BoardStage, Comment, Part, Photo, Post,
                      Project, Task)
from . import save_or_report


# ---------------------------------------------------------------------------
# Tableau de bord
# ---------------------------------------------------------------------------
def dashboard(request):
    """Projets actifs et l'état de leurs éléments, puis les dernières nouvelles.

    `?pole=` restreint l'affichage à un pôle. C'est un FILTRE, pas un Hub
    séparé : les trois pôles travaillent sur les mêmes projets, et un méca
    doit pouvoir aller voir où en est le séquenceur."""
    pole = request.GET.get("pole", "")
    boards = Board.objects.filter(pole=pole) if pole else Board.objects.all()
    posts = Post.objects.select_related("project", "board")
    if pole:
        posts = posts.filter(board__pole=pole)
    return render(request, "projects/dashboard.html", {
        "projects": Project.objects.filter(status="actif").prefetch_related(
            Prefetch("boards", queryset=boards)),
        "archived": Project.objects.filter(status="archive"),
        "latest_posts": posts.prefetch_related("photos")[:8],
        "pole": pole,
    })


# ---------------------------------------------------------------------------
# Projets
# ---------------------------------------------------------------------------
def project_detail(request, slug):
    project = get_object_or_404(Project, slug=slug)
    # Groupés par pôle : une fusée mélange cartes, pièces et modules, et on
    # veut voir d'un coup d'œil ce que chaque pôle a en cours.
    boards = list(project.boards.all())
    return render(request, "projects/project_detail.html", {
        "project": project,
        "posts": project.posts.prefetch_related("photos", "comments"),
        "by_pole": [(key, label, [b for b in boards if b.pole == key])
                    for key, label in Board.POLES],
    })


def project_form(request, slug=None):
    """Création ET édition (un seul template, un seul chemin de code)."""
    # En création, une instance NON sauvegardée (même motif que board_form) :
    # le template lit project.STATUS et les valeurs par défaut sans variable
    # de contexte en plus. `project.pk` distingue création et édition.
    project = get_object_or_404(Project, slug=slug) if slug else Project()
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            messages.error(request, "Le nom du projet est obligatoire.")
        else:
            project.name = name
            for f in ("description", "team", "campaign_year"):
                setattr(project, f, request.POST.get(f, ""))
            # Le statut ne se change qu'en admin. Masquer le champ côté
            # template NE SUFFIT PAS : sans ce test, poster le formulaire
            # complet contournerait la restriction du bouton Archiver.
            if request.session.get("is_admin"):
                project.status = request.POST.get("status", project.status)
            if save_or_report(request, project, "Ce nom de projet"):
                messages.success(request, f"Projet « {project.name} » enregistré.")
                return redirect(project)
    return render(request, "projects/project_form.html",
                  {"project": project, "parts": Part.objects.all()})


@require_admin
@require_POST
def project_archive_toggle(request, slug):
    """Bascule actif ↔ archivé. Réservée à l'admin : ça change ce que toute
    l'équipe voit par défaut sur le tableau de bord."""
    project = get_object_or_404(Project, slug=slug)
    project.status = "actif" if project.status == "archive" else "archive"
    project.save()
    messages.success(request, f"« {project.name} » "
                     f"{'réactivé' if project.status == 'actif' else 'archivé'}.")
    return redirect(project)


@require_admin
def project_delete(request, slug):
    """Suppression définitive. L'usage normal est l'ARCHIVAGE, qui préserve
    l'historique pluriannuel."""
    project = get_object_or_404(Project, slug=slug)
    if request.method == "POST":
        project.delete()
        messages.success(request, "Projet supprimé définitivement.")
        return redirect("dashboard")
    return render(request, "confirm_delete.html", {"obj": project})


# ---------------------------------------------------------------------------
# Cartes
# ---------------------------------------------------------------------------
def board_detail(request, pk):
    """La page la plus dense du site : rail, fiche, nomenclature, kanban, fil."""
    board = get_object_or_404(Board.objects.select_related("project"), pk=pk)
    # Kanban prêt à itérer : (clé, libellé, tâches) dans l'ordre des colonnes.
    by_col = {key: [] for key, _ in Task.COLUMNS}
    for task in board.tasks.all():
        by_col[task.column].append(task)
    # Encart nomenclature : combien de composants, combien manquent pour UN
    # exemplaire. Une requête, aucun appel réseau.
    bom = (board.bom_lines.select_related("part")
           .annotate(stock=Coalesce(Sum("part__movements__delta"), ZERO)))
    return render(request, "projects/board_detail.html", {
        "board": board,
        "posts": board.posts.filter(stage="")
                            .prefetch_related("photos", "comments"),
        "kanban_columns": [(k, label, by_col[k]) for k, label in Task.COLUMNS],
        "bom_count": len(bom),
        "bom_missing": sum(1 for line in bom if line.qty > line.stock),
        # Pôle soft : la version qui tourne, c'est-à-dire le dernier flash
        # réussi. None tant que personne n'a rien flashé.
        "firmware": board.current_firmware() if board.pole == "soft" else None,
    })


def board_stage(request, pk, stage):
    """
    Sous-page d'une étape : ses notes, son applicabilité, son fil. Permet de
    REMONTER dans l'historique — chaque étape a sa page, quelle que soit
    l'étape où la carte se trouve réellement.
    """
    board = get_object_or_404(Board.objects.select_related("project"), pk=pk)
    labels = dict(board.lifecycle())
    if stage not in labels:
        raise Http404("Étape inconnue")
    # Créée à la demande : on ne pré-crée jamais les huit lignes.
    stage_obj, _ = BoardStage.objects.get_or_create(board=board, stage=stage)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "notes":
            stage_obj.notes = request.POST.get("notes", "")
            stage_obj.save()
            messages.success(request, "Notes de l'étape enregistrées.")
        elif action == "na" and stage in Board.NA_STAGES:
            stage_obj.non_applicable = bool(request.POST.get("non_applicable"))
            stage_obj.na_reason = request.POST.get("na_reason", "").strip()
            stage_obj.save()
            if stage_obj.non_applicable:
                _cascade_na(board, stage, labels)
            messages.success(request, "Applicabilité de l'étape mise à jour.")
        return redirect("board_stage", pk=board.pk, stage=stage)

    return render(request, "projects/board_stage.html", {
        "board": board, "stage": stage, "label": labels[stage],
        "stage_obj": stage_obj,
        "posts": board.posts.filter(stage=stage)
                            .prefetch_related("photos", "comments"),
        "can_na": stage in Board.NA_STAGES,
        "bom_count": board.bom_lines.count(),
    })


def _cascade_na(board, stage, labels):
    """
    Si l'intégration n'a pas lieu, le vol et le résultat non plus.
    La cascade ne va que VERS L'AVANT, et ne réécrit jamais une étape déjà
    marquée (sa raison propre est préservée). Réactiver une étape ne réactive
    PAS les suivantes : elles ont pu être marquées pour d'autres motifs,
    c'est à l'humain de trancher.
    """
    for later in Board.NA_STAGES[Board.NA_STAGES.index(stage) + 1:]:
        obj, _ = BoardStage.objects.get_or_create(board=board, stage=later)
        if not obj.non_applicable:
            obj.non_applicable = True
            obj.na_reason = f"cascade depuis « {labels[stage]} »"
            obj.save()


def board_form(request, project_slug=None, pk=None):
    """Création (sous un projet) ou édition d'une carte."""
    # En création, une instance NON sauvegardée : le template dispose ainsi
    # de board.lifecycle et des valeurs par défaut du modèle sans variable de
    # contexte supplémentaire. `board.pk` distingue création et édition.
    board = get_object_or_404(Board, pk=pk) if pk else None
    project = board.project if board else get_object_or_404(Project,
                                                            slug=project_slug)
    board = board or Board(project=project)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            messages.error(request, "Le nom de la carte est obligatoire.")
        else:
            board.name = name
            board.pole = request.POST.get("pole", board.pole)
            for f in ("status", "manager", "notes"):
                setattr(board, f, request.POST.get(f, ""))
            # Changer de pôle change le rail : une étape qui n'existe pas
            # dans le nouveau pôle (« routage » côté méca) est ramenée au
            # début plutôt que de laisser un statut orphelin en base.
            if board.status not in dict(board.lifecycle()):
                board.status = board.lifecycle()[0][0]
            board.target_date = request.POST.get("target_date") or None
            if save_or_report(request, board,
                              f"Ce nom d'élément (projet {project.name})"):
                messages.success(request, f"« {board.name} » enregistré.")
                return redirect(board)
    return render(request, "projects/board_form.html",
                  {"board": board, "project": project})


# ---------------------------------------------------------------------------
# Kanban
# ---------------------------------------------------------------------------
@require_POST
def task_create(request, board_pk):
    """Ajout rapide depuis le pied d'une colonne."""
    board = get_object_or_404(Board, pk=board_pk)
    title = request.POST.get("title", "").strip()
    if title:
        column = request.POST.get("column", "todo")
        Task.objects.create(board=board, title=title, column=column,
                            position=board.tasks.filter(column=column).count(),
                            assignee=request.POST.get("assignee", ""))
    return redirect(board)


@require_POST
def task_move(request, board_pk):
    """
    Persistance du glisser-déposer. Le client envoie l'ÉTAT COMPLET du
    tableau — {"todo": [3, 7], "doing": [5], …} — et on le réécrit tel quel :
    trivialement idempotent, bien plus robuste que des deltas. Un id inconnu
    (tâche supprimée pendant le drag) est ignoré grâce à .filter().update().
    """
    try:
        state = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("JSON invalide")
    valid = {key for key, _ in Task.COLUMNS}
    for column, ids in state.items():
        if column in valid:
            for position, task_id in enumerate(ids):
                Task.objects.filter(board_id=board_pk, pk=task_id).update(
                    column=column, position=position)
    return JsonResponse({"ok": True})


@require_POST
def task_delete(request, pk):
    task = get_object_or_404(Task, pk=pk)
    task.delete()
    return redirect("board_detail", pk=task.board_id)


# ---------------------------------------------------------------------------
# Fil d'activité
# ---------------------------------------------------------------------------
@require_POST
def post_create(request):
    """
    Publication depuis une page projet, une page carte ou une sous-page
    d'étape. Un post doit contenir du texte OU au moins une photo.
    """
    text = request.POST.get("text_md", "").strip()
    files = request.FILES.getlist("photos")
    if not text and not files:
        messages.error(request, "Un post doit contenir du texte ou une photo.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    post = Post(author=request.session["prenom"], text_md=text)
    if request.POST.get("board_id"):
        post.board = get_object_or_404(Board, pk=request.POST["board_id"])
        stage = request.POST.get("stage", "")
        post.stage = stage if stage in dict(post.board.lifecycle()) else ""
    elif request.POST.get("project_id"):
        post.project = get_object_or_404(Project, pk=request.POST["project_id"])
    else:
        return HttpResponseBadRequest("Post sans rattachement")
    post.save()

    for f in files:
        try:
            main, thumb = process_photo(f)
        except Exception:  # noqa: BLE001 — illisible : on saute, sans échouer
            messages.warning(request, f"Fichier ignoré (pas une image ?) : {f.name}")
            continue
        base = f.name.rsplit(".", 1)[0][:60]
        photo = Photo(post=post)
        photo.image.save(f"{base}.webp", main, save=False)
        photo.thumb.save(f"{base}_min.webp", thumb, save=False)
        photo.save()

    messages.success(request, "Publication enregistrée.")
    if post.stage:
        return redirect("board_stage", pk=post.board_id, stage=post.stage)
    return redirect(post.target())


@require_POST
def comment_create(request, post_pk):
    """Le SEUL endroit avec htmx : renvoie le fragment de liste, qui remplace
    #comments-<pk> sans recharger la page."""
    post = get_object_or_404(Post, pk=post_pk)
    text = request.POST.get("text", "").strip()
    if text:
        Comment.objects.create(post=post, author=request.session["prenom"],
                               text=text)
    return render(request, "projects/_comments.html", {"post": post})


@require_admin
def post_delete(request, pk):
    """Suppression d'un post — ses photos partent du disque avec lui."""
    post = get_object_or_404(Post, pk=pk)
    target = post.target()
    for photo in post.photos.all():
        photo.image.delete(save=False)
        photo.thumb.delete(save=False)
    post.delete()
    messages.success(request, "Publication supprimée.")
    return redirect(target)
