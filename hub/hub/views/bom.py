"""
Import de BOM en trois écrans :

  1. UPLOAD    fichier + carte cible (+ profil de colonnes éventuel)
  2. MAPPING   colonne du fichier → champ canonique, mémorisable en profil
  3. ARBITRAGE auto repliées, ambiguës à trancher, absentes à créer

On ne peut pas enregistrer tant qu'il reste une ligne non arbitrée : une BOM
partielle fausserait silencieusement la faisabilité — exactement ce qu'on
s'interdit.
"""
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..matching import match_line
from ..models import (Board, BomImport, BomImportLine, BomLine, ColumnProfile,
                      Location, Part)
from ..parsing import CANONICAL_FIELDS, extract_lines, guess_mapping, read_table

# Statuts qui bloquent l'enregistrement de la nomenclature.
PENDING = ("review", "nomatch")


def import_list(request):
    """Historique des imports + point d'entrée d'un nouvel import."""
    return render(request, "bom/import_list.html", {
        "imports": BomImport.objects.select_related("board__project")[:50],
        "boards": Board.objects.select_related("project")
                               .filter(project__status="actif"),
        "profiles": ColumnProfile.objects.all(),
    })


@require_POST
def import_upload(request):
    """Écran 1 : lit le fichier, stocke le BRUT, passe au mapping."""
    board = get_object_or_404(Board, pk=request.POST.get("board"))
    f = request.FILES.get("file")
    if not f:
        messages.error(request, "Aucun fichier fourni.")
        return redirect("bom_import_list")
    try:
        headers, rows = read_table(f)
    except Exception as exc:  # noqa: BLE001 — fichier illisible ou exotique
        messages.error(request, f"Fichier illisible : {exc}")
        return redirect("bom_import_list")
    if not rows:
        messages.error(request, "Le fichier ne contient aucune ligne de données.")
        return redirect("bom_import_list")

    imp = BomImport.objects.create(
        board=board, filename=f.name, headers=headers, raw_rows=rows,
        created_by=request.session["prenom"],
        profile_id=request.POST.get("profile") or None)
    return redirect("bom_mapping", pk=imp.pk)


def mapping_view(request, pk):
    """Écran 2 : associer chaque colonne à un champ canonique."""
    imp = get_object_or_404(BomImport, pk=pk)
    if request.method == "POST":
        mapping = {h: request.POST.get(f"col_{i}", "ignore")
                   for i, h in enumerate(imp.headers)}
        name = request.POST.get("save_profile", "").strip()
        if name:
            imp.profile, _ = ColumnProfile.objects.update_or_create(
                name=name, defaults={"mapping": mapping})
        imp.save()
        for warning in _build_lines_and_match(imp, mapping):
            messages.warning(request, warning)
        return redirect("bom_review", pk=imp.pk)

    # Profil choisi à l'upload, sinon heuristiques d'entête.
    proposed = imp.profile.mapping if imp.profile else guess_mapping(imp.headers)
    # L'aperçu est construit ICI : un template Django n'indexe pas un dict
    # par variable.
    return render(request, "bom/mapping.html", {
        "imp": imp, "fields": CANONICAL_FIELDS,
        "columns": [{
            "header": h,
            "proposed": proposed.get(h, "ignore"),
            "sample": [v for v in (row.get(h, "") for row in imp.raw_rows[:4]) if v],
        } for h in imp.headers],
    })


def _build_lines_and_match(imp, mapping):
    """Extrait les lignes canoniques puis lance le moteur sur chacune.
    Renvoie les avertissements à afficher (divergences quantité/designators).

    `row_index + 2` dans le message : +1 pour la ligne d'entête, +1 parce que
    les tableurs comptent à partir de 1 — l'utilisateur retrouve ainsi la
    ligne exacte dans son fichier.
    """
    imp.lines.all().delete()
    warnings = []
    for data in extract_lines(imp.raw_rows, mapping):
        warning = data.pop("warning", "")
        if warning:
            warnings.append(f"Ligne {data['row_index'] + 2} : {warning}")
        match_line(BomImportLine.objects.create(bom_import=imp, **data))
    imp.status = "matching"
    imp.save()
    return warnings


def review_view(request, pk):
    """Écran 3 : l'arbitrage humain, cœur de « jamais de devinette silencieuse »."""
    imp = get_object_or_404(BomImport.objects.select_related("board"), pk=pk)
    grouped = {key: [] for key, _ in BomImportLine.STATUS}
    for line in (imp.lines.prefetch_related("candidates__part")
                          .select_related("matched_part")):
        grouped[line.status].append(line)
    return render(request, "bom/review.html", {
        "imp": imp, "grouped": grouped, "categories": Part.CATEGORIES,
        "locations": Location.objects.all(),
        "pending": any(grouped[s] for s in PENDING),
    })


@require_POST
def line_decide(request, line_pk):
    """
    Décision de l'utilisateur sur UNE ligne :
      action=ignore  → ligne écartée de la nomenclature
      action=create  → composant créé au catalogue puis associé
      (défaut)       → validation du candidat coché
    """
    line = get_object_or_404(BomImportLine, pk=line_pk)
    who = request.session["prenom"]
    action = request.POST.get("action", "")

    if action == "ignore":
        line.status, line.matched_reason = "ignored", f"écartée par {who}"
        line.save()
    elif action == "create":
        name = (request.POST.get("new_name", "").strip() or line.mpn
                or f"{line.value} {line.package}".strip())
        if Part.objects.filter(name=name).exists():
            messages.error(request, f"« {name} » existe déjà dans le catalogue.")
            return redirect("bom_review", pk=line.bom_import_id)
        # Créé avec 0 en stock : la quantité s'ajoutera à la première saisie.
        part = Part.objects.create(
            name=name, category=request.POST.get("category", "autre"),
            value=line.value, package=line.package, mpn=line.mpn,
            manufacturer=line.manufacturer, sku=line.lcsc,
            location_id=request.POST.get("location") or None,
            notes=f"Créé à l'import BOM {line.bom_import.filename}")
        line.status, line.matched_part = "auto", part
        line.matched_score, line.matched_reason = 100, f"créé par {who}"
        line.save()
        messages.success(request, f"« {part.name} » ajouté au catalogue.")
    else:
        cand = line.candidates.filter(part_id=request.POST.get("part")).first()
        if cand:
            line.status, line.matched_part = "auto", cand.part
            line.matched_score = cand.score
            line.matched_reason = f"{cand.reason} — validé par {who}"
            line.save()
    return redirect("bom_review", pk=line.bom_import_id)


@require_POST
def save_bom(request, pk):
    """Écrit la nomenclature de la carte. Un ré-import REMPLACE l'ancienne :
    une carte n'a qu'une BOM."""
    imp = get_object_or_404(BomImport, pk=pk)
    pending = imp.lines.filter(status__in=PENDING).count()
    if pending:
        messages.error(request,
                       f"{pending} ligne(s) encore à arbitrer avant d'enregistrer.")
        return redirect("bom_review", pk=imp.pk)

    board = imp.board
    with transaction.atomic():
        board.bom_lines.all().delete()
        # Fusion par composant : un même composant peut apparaître sur
        # plusieurs lignes du fichier (quantités additionnées).
        merged = {}
        for line in imp.lines.filter(status="auto"):
            if line.matched_part_id:
                e = merged.setdefault(line.matched_part_id,
                                      {"qty": Decimal("0"), "des": []})
                e["qty"] += line.qty
                if line.designators:
                    e["des"].append(line.designators)
        BomLine.objects.bulk_create([
            BomLine(board=board, part_id=pid, qty=v["qty"],
                    designators=", ".join(v["des"])[:300])
            for pid, v in merged.items()])
        imp.status = "done"
        imp.save()
    messages.success(request, f"Nomenclature enregistrée : {len(merged)} "
                     f"composant(s) pour « {board.name} ». La faisabilité est "
                     f"maintenant calculable.")
    return redirect("feasibility", board_pk=board.pk)
