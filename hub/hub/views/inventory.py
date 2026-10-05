"""
Stock : catalogue, saisie en rafale, sortie rapide, faisabilité, achats.

On ne met JAMAIS un stock à jour à la main : on ajoute un mouvement et le
stock suit (c'est sa définition). Voir hub/models.py, section Stock.
"""
import csv
import io
from decimal import Decimal

from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..images import process_photo
from ..middleware import require_admin
from ..models import ZERO, Board, Location, Movement, Part, Project
from . import _qty, save_or_report

ONE = Decimal("1")
# Correspondance du mode « passifs » de la saisie en rafale.
PASSIVE_KINDS = {"RES": "resistance", "CAP": "condensateur",
                 "IND": "inductance"}


def _post_fields(request, obj, fields):
    """Recopie des champs texte du POST sur un objet (formulaires plats)."""
    for f in fields:
        setattr(obj, f, request.POST.get(f, "").strip())


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
def part_list(request):
    """Ce qu'on a, combien, où. Filtres en GET : l'URL reste partageable."""
    parts = Part.objects.with_stock().select_related("location")
    q = request.GET.get("q", "").strip()
    category = request.GET.get("categorie", "")
    location = request.GET.get("emplacement", "")
    if q:
        parts = parts.filter(Q(name__icontains=q) | Q(mpn__icontains=q)
                             | Q(sku__icontains=q))
    if category:
        parts = parts.filter(category=category)
    if location:
        parts = parts.filter(location_id=location)
    return render(request, "inventory/part_list.html", {
        "parts": parts,
        # Calcul en Python assumé : la liste est courte, et une annotation
        # conditionnelle coûterait plus en lisibilité qu'elle ne rapporte.
        "low": [p for p in parts if p.min_qty and p.stock < p.min_qty],
        "q": q, "categories": Part.CATEGORIES,
        "locations": Location.objects.all(),
        "current_category": category, "current_location": location,
    })


def part_detail(request, pk):
    part = get_object_or_404(Part.objects.with_stock(), pk=pk)
    return render(request, "inventory/part_detail.html", {
        "part": part,
        "movements": part.movements.select_related("board")[:50],
        "bom_lines": part.bom_lines.select_related("board__project"),
    })


def part_form(request, pk=None):
    """Création / correction d'un composant."""
    part = get_object_or_404(Part, pk=pk) if pk else None
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            messages.error(request, "Le nom du composant est obligatoire.")
        else:
            part = part or Part()
            part.name = name
            _post_fields(request, part,
                         ("category", "value", "package", "mpn",
                          "manufacturer", "supplier", "sku", "supplier_url",
                          "datasheet_url", "notes"))
            part.location_id = request.POST.get("location") or None
            part.min_qty = _qty(request.POST.get("min_qty"), ZERO) or ZERO
            part.unit_price = _qty(request.POST.get("unit_price"), None)
            if request.FILES.get("photo"):
                try:
                    main, _thumb = process_photo(request.FILES["photo"])
                    part.photo.save(f"{name[:50]}.webp", main, save=False)
                except Exception:  # noqa: BLE001 — fichier illisible
                    messages.warning(request, "Photo ignorée (pas une image ?).")
            if request.FILES.get("datasheet_pdf"):
                part.datasheet_pdf = request.FILES["datasheet_pdf"]
            if save_or_report(request, part, "Ce nom de composant"):
                messages.success(request, f"« {part.name} » enregistré.")
                return redirect(part)
    return render(request, "inventory/part_form.html", {
        "part": part, "categories": Part.CATEGORIES,
        "locations": Location.objects.all(),
    })


def locations(request):
    """Une liste, un champ d'ajout. Rien de plus."""
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if name:
            Location.objects.get_or_create(
                name=name, defaults={"note": request.POST.get("note", "")})
            messages.success(request, f"Emplacement « {name} » ajouté.")
        return redirect("locations")
    return render(request, "inventory/locations.html",
                  {"locations": Location.objects.annotate(n=Count("parts"))})


# ---------------------------------------------------------------------------
# Saisie en rafale — pensée pour la soirée de saisie initiale
# ---------------------------------------------------------------------------
def bulk_entry(request):
    """Un opérateur, un bac, des dizaines de références à enchaîner : mode,
    emplacement, catégorie et boîtier restent MÉMORISÉS d'une ligne à
    l'autre (session), puis valeur → quantité → Entrée."""
    return render(request, "inventory/bulk_entry.html", {
        "categories": Part.CATEGORIES,
        "locations": Location.objects.all(),
        "last": request.session.get("bulk_last", {}),
        "recent": Part.objects.with_stock().order_by("-created")[:8],
    })


@require_POST
def bulk_entry_submit(request):
    """Traite UNE ligne puis revient au formulaire (flux rafale)."""
    mode = request.POST.get("mode", "passif")
    qty = _qty(request.POST.get("qty"))
    if qty is None or qty <= 0:
        messages.error(request, "Quantité invalide.")
        return redirect("bulk_entry")

    field = (lambda name: request.POST.get(name, "").strip())
    # Choix rémanents pour la ligne suivante.
    request.session["bulk_last"] = {
        "mode": mode, "location": request.POST.get("location") or None,
        "category": field("category"), "package": field("package")}

    if mode == "passif":
        # Convention du pôle : « RES 10k 0603 1% ».
        kind, value, tol = field("kind") or "RES", field("value"), field("tolerance")
        if not value:
            messages.error(request, "La valeur est obligatoire en mode passif.")
            return redirect("bulk_entry")
        name = " ".join(x for x in [kind, value, field("package"),
                                    tol and f"{tol}%"] if x)
        defaults = {"category": PASSIVE_KINDS.get(kind, "autre"),
                    "value": value, "package": field("package")}
    else:
        # En mode actif, le MPN EST le nom.
        name = field("mpn")
        if not name:
            messages.error(request, "Le MPN est obligatoire en mode actif.")
            return redirect("bulk_entry")
        defaults = {"category": field("category") or "autre", "mpn": name,
                    "notes": field("description")}

    defaults.update({
        "location_id": request.POST.get("location") or None,
        "supplier": field("supplier"), "sku": field("sku"),
        "supplier_url": field("supplier_url"),
        "datasheet_url": field("datasheet_url"),
    })
    price = _qty(request.POST.get("price"), None)
    if price is not None:
        defaults["unit_price"] = price

    # Un composant déjà connu est RÉAPPROVISIONNÉ, jamais dupliqué.
    part, created = Part.objects.get_or_create(name=name, defaults=defaults)
    Movement.objects.create(
        part=part, delta=qty, kind="entree", author=request.session["prenom"],
        reason="Saisie initiale" if created else "Réapprovisionnement")
    messages.success(request, f"« {part.name} » "
                     f"{'créé' if created else 'complété'} : {qty:g} en entrée.")
    return redirect("bulk_entry")


# ---------------------------------------------------------------------------
# Sortie rapide — pensée téléphone, « deux taps »
# ---------------------------------------------------------------------------
def quick_out(request):
    q = request.GET.get("q", "").strip()
    results = []
    if q:
        results = (Part.objects.with_stock().filter(name__icontains=q)
                   .select_related("location")[:15])
        if not results:   # repli sur le MPN si le nom ne donne rien
            results = Part.objects.with_stock().filter(mpn__icontains=q)[:15]
    return render(request, "inventory/quick_out.html", {
        "q": q, "results": results,
        # Peuple le menu « projet → carte » du motif (optgroups natifs, 0 JS).
        "projects": Project.objects.filter(status="actif")
                                   .prefetch_related("boards"),
    })


@require_POST
def quick_out_submit(request):
    """Sortie d'atelier : UN mouvement négatif, et le stock est à jour."""
    part = get_object_or_404(Part, pk=request.POST.get("part_id"))
    qty = _qty(request.POST.get("qty"))
    if qty is None or qty <= 0:
        messages.error(request, "Quantité invalide.")
        return redirect(request.POST.get("back") or "quick_out")

    stock = part.stock()
    if qty > stock:
        # Un stock négatif est une erreur de saisie, pas un état physique.
        # Le message ORIENTE vers la correction au lieu de bloquer sèchement.
        messages.error(request,
                       f"Il ne reste que {stock:g} × « {part.name} » : sortie "
                       f"refusée. Si le bac en contient plus, corrige "
                       f"l'inventaire sur sa fiche.")
        return redirect(part)

    Movement.objects.create(
        part=part, delta=-qty, kind="sortie",
        author=request.session["prenom"],
        reason=request.POST.get("why", "").strip(),
        board_id=request.POST.get("board") or None)
    messages.success(request, f"Sortie de {qty:g} × « {part.name} » "
                     f"enregistrée. Stock restant : {part.stock():g}.")
    return redirect(request.POST.get("back") or "quick_out")


@require_POST
def stock_adjust(request, pk):
    """Correction d'inventaire : on ajoute le mouvement qui amène le stock au
    compte réel. L'écart reste visible — l'historique ne se réécrit pas."""
    part = get_object_or_404(Part, pk=pk)
    counted = _qty(request.POST.get("counted"))
    if counted is None or counted < 0:
        messages.error(request, "Quantité comptée invalide.")
        return redirect(part)
    delta = counted - part.stock()
    if delta:
        Movement.objects.create(
            part=part, delta=delta, kind="inventaire",
            author=request.session["prenom"],
            reason=request.POST.get("why", "").strip() or "Inventaire")
        messages.success(request, f"Inventaire : ajustement de {delta:+g}.")
    else:
        messages.success(request, "Inventaire conforme, rien à ajuster.")
    return redirect(part)


@require_admin
def movement_delete(request, pk):
    """Annuler une faute de frappe (admin) — la seule exception assumée à
    « l'historique ne se réécrit jamais »."""
    mv = get_object_or_404(Movement, pk=pk)
    part_pk = mv.part_id
    mv.delete()
    messages.success(request, "Mouvement supprimé.")
    return redirect("part_detail", pk=part_pk)


# ---------------------------------------------------------------------------
# Faisabilité, liste d'achat, sortie d'assemblage
# ---------------------------------------------------------------------------
def _rows(board, n):
    """Pour chaque ligne de nomenclature : requis, dispo, manque.
    Cœur de calcul PARTAGÉ par les trois vues ci-dessous — un seul endroit
    où la règle vit, donc les trois écrans ne peuvent pas diverger."""
    lines = (board.bom_lines.select_related("part", "part__location")
             .annotate(stock=Coalesce(Sum("part__movements__delta"), ZERO)))
    return [{"line": line, "part": line.part,
             "required": line.qty * n, "available": line.stock,
             "missing": max(line.qty * n - line.stock, ZERO)}
            for line in lines]


def _n(source):
    """Nombre d'exemplaires demandé (GET ou POST), au moins 1."""
    return _qty(source.get("n", "1"), ONE) or ONE


def feasibility(request, board_pk):
    """« Peut-on assembler N exemplaires de cette carte ? »"""
    board = get_object_or_404(Board.objects.select_related("project"),
                              pk=board_pk)
    n = _n(request.GET)
    rows = _rows(board, n)
    return render(request, "inventory/feasibility.html", {
        "board": board, "n": n, "rows": rows,
        "total_missing": sum(1 for r in rows if r["missing"]),
    })


def shortage_csv(request, board_pk):
    """Liste d'achat des manquants. Le lien permet d'ouvrir la fiche produit
    et de remplir le panier à la main : AUCUNE API fournisseur n'est appelée."""
    board = get_object_or_404(Board, pk=board_pk)
    n = _n(request.GET)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Fournisseur", "Réf fournisseur", "Quantité", "Composant",
                "PU (EUR)", "Lien"])
    for r in _rows(board, n):
        if r["missing"]:
            p = r["part"]
            w.writerow([p.supplier or "à sourcer", p.sku, f"{r['missing']:g}",
                        p.name, p.unit_price or "", p.supplier_url])
    resp = HttpResponse(out.getvalue(), content_type="text/csv")
    resp["Content-Disposition"] = \
        f'attachment; filename="achats_{board.name}_{n:g}x.csv"'
    return resp


@require_POST
def consume_bom(request, board_pk):
    """
    Sortie d'assemblage : un mouvement négatif par ligne. C'est ce qui
    remplace la réservation — on ne bloque rien à l'avance, on décompte au
    moment où la carte est RÉELLEMENT montée.
    Le contrôle préalable garantit le tout-ou-rien : jamais de décompte partiel.
    """
    board = get_object_or_404(Board, pk=board_pk)
    n = _n(request.POST)
    rows = _rows(board, n)
    blocking = [r for r in rows if r["missing"]]
    if blocking:
        messages.error(request, f"{len(blocking)} composant(s) en quantité "
                       f"insuffisante : sortie annulée, rien n'a été décompté.")
        return redirect("feasibility", board_pk=board.pk)
    Movement.objects.bulk_create([
        Movement(part=r["part"], delta=-r["required"], kind="sortie",
                 author=request.session["prenom"], board=board,
                 reason=f"Assemblage {board.name} ×{n:g}")
        for r in rows])
    messages.success(request, f"{len(rows)} composant(s) sortis du stock pour "
                     f"{n:g} × « {board.name} ».")
    return redirect("feasibility", board_pk=board.pk)
