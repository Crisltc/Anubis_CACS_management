"""
Bibliothèque de documents PDF et wiki.

L'upload d'un document déclenche l'extraction du texte intégral (recherche
plein texte) et la miniature de la première page. Les échecs sont TOLÉRÉS à
chaque étape : un PDF scanné sans texte reste consultable, il sera juste
moins bien indexé — on ne perd jamais un fichier.

Aucune compilation LaTeX côté serveur : les PDF arrivent déjà compilés.
"""
import pymupdf as fitz
from django.contrib import messages
from django.core.files.base import ContentFile
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..middleware import require_admin
from ..models import Document, Project, WikiPage, WikiRevision
from . import save_or_report

MAX_TEXT = 500_000    # borne du texte indexé, par document
THUMB_WIDTH = 400     # largeur de la miniature de première page


def _ingest_pdf(document):
    """Texte intégral + miniature. False si le fichier n'est pas un PDF."""
    try:
        pdf = fitz.open(document.pdf.path)
    except Exception:  # noqa: BLE001 — pas un PDF, ou corrompu
        return False
    document.text_content = "\n".join(p.get_text() for p in pdf)[:MAX_TEXT]
    try:
        page = pdf[0]
        zoom = THUMB_WIDTH / page.rect.width if page.rect.width else 1
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        document.thumb.save(f"thumb_{document.pk}.png",
                            ContentFile(pix.tobytes("png")), save=False)
    except Exception:  # noqa: BLE001 — pas de miniature, pas bloquant
        pass
    document.save()
    pdf.close()
    return True


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def document_list(request):
    """Bibliothèque filtrable par type et par projet (GET, URL partageable)."""
    docs = Document.objects.select_related("project")
    doc_type = request.GET.get("type", "")
    project = request.GET.get("projet", "")
    if doc_type:
        docs = docs.filter(doc_type=doc_type)
    if project:
        docs = docs.filter(project__slug=project)
    return render(request, "library/document_list.html", {
        "documents": docs, "types": Document.TYPES,
        "projects": Project.objects.all(),
        "current_type": doc_type, "current_project": project,
    })


def document_detail(request, pk):
    """Métadonnées + visionneuse : le PDF est servi `inline` par la vue média
    protégée, donc le lecteur intégré du navigateur l'affiche dans l'iframe."""
    return render(request, "library/document_detail.html",
                  {"doc": get_object_or_404(Document, pk=pk)})


def document_upload(request):
    if request.method == "POST":
        pdf = request.FILES.get("pdf")
        title = request.POST.get("title", "").strip()
        if not (pdf and title):
            messages.error(request, "Titre et fichier PDF sont obligatoires.")
            return redirect("document_upload")
        doc = Document(
            title=title, pdf=pdf,
            doc_type=request.POST.get("doc_type", "final"),
            authors=request.POST.get("authors", ""),
            date=request.POST.get("date") or None,
            project_id=request.POST.get("project") or None,
            source_zip=request.FILES.get("source_zip"),
            created_by=request.session["prenom"])
        doc.save()
        if not _ingest_pdf(doc):
            messages.warning(request, "Le fichier ne semble pas être un PDF "
                             "valide : il est enregistré mais ni indexé ni "
                             "prévisualisé.")
        messages.success(request, f"« {doc.title} » ajouté à la bibliothèque.")
        return redirect(doc)
    return render(request, "library/document_form.html", {
        "types": Document.TYPES, "projects": Project.objects.all()})


@require_admin
def document_delete(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if request.method == "POST":
        for f in (doc.pdf, doc.source_zip, doc.thumb):
            if f:
                f.delete(save=False)
        doc.delete()
        messages.success(request, "Document supprimé.")
        return redirect("document_list")
    return render(request, "confirm_delete.html", {"obj": doc})


# ---------------------------------------------------------------------------
# Wiki
# ---------------------------------------------------------------------------
def wiki_index(request):
    return render(request, "library/wiki_index.html",
                  {"pages": WikiPage.objects.all()})


def wiki_page(request, slug):
    return render(request, "library/wiki_page.html",
                  {"page": get_object_or_404(WikiPage, slug=slug)})


def wiki_edit(request, slug=None):
    """Création (slug absent) ou édition. Chaque sauvegarde archive une
    révision contenant le TEXTE INTÉGRAL : historique incassable."""
    page = get_object_or_404(WikiPage, slug=slug) if slug else None
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        content = request.POST.get("content_md", "")
        if not title:
            messages.error(request, "Le titre est obligatoire.")
        else:
            page = page or WikiPage()
            page.title, page.content_md = title, content
            if request.FILES.get("pdf"):
                page.pdf = request.FILES["pdf"]
            if save_or_report(request, page, "Ce titre de page"):
                WikiRevision.objects.create(page=page, content_md=content,
                                            author=request.session["prenom"])
                messages.success(request, "Page enregistrée.")
                return redirect(page)
    return render(request, "library/wiki_edit.html", {"page": page})


def wiki_history(request, slug):
    page = get_object_or_404(WikiPage, slug=slug)
    return render(request, "library/wiki_history.html",
                  {"page": page, "revisions": page.revisions.all()})


@require_POST
def wiki_restore(request, slug, rev_pk):
    """Restaure une ancienne révision en en créant une NOUVELLE :
    l'historique se prolonge, il ne se réécrit jamais."""
    page = get_object_or_404(WikiPage, slug=slug)
    rev = get_object_or_404(WikiRevision, pk=rev_pk, page=page)
    page.content_md = rev.content_md
    page.save()
    WikiRevision.objects.create(
        page=page, content_md=rev.content_md,
        author=f"{request.session['prenom']} (restauration)")
    messages.success(request, "Révision restaurée.")
    return redirect(page)
