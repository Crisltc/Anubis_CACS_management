"""
TOUS les modèles du Hub, en quatre sections : projets/kanban, stock,
import de BOM, bibliothèque/wiki.

Trois règles à garder en tête en lisant ce fichier :

* le stock n'est PAS un champ, c'est la SOMME d'un registre de mouvements —
  une sortie d'atelier est donc juste par construction, sans compteur à
  resynchroniser et sans dérive possible ;
* on ARCHIVE, on ne supprime pas : l'historique est pluriannuel ;
* les auteurs sont des prénoms (chaînes), pas des comptes — cohérent avec
  l'authentification par mot de passe partagé (middleware.py).
"""
import re
from decimal import Decimal

from django.db import models
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils.text import Truncator, slugify

# Type commun à toutes les quantités : Decimal exact, JAMAIS de float — pour
# qu'additionner des milliers de mouvements ne fasse pas dériver un stock.
QTY = dict(max_digits=12, decimal_places=2)
ZERO = Decimal("0")


class SluggedModel(models.Model):
    """Base des modèles dont le slug se déduit d'un titre à la création.
    Mutualise le seul `save()` qui se répétait entre Project et WikiPage."""
    SLUG_FROM = "name"
    slug = models.SlugField(unique=True, blank=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(type(self), getattr(self, self.SLUG_FROM),
                                    exclude_pk=self.pk)
        super().save(*args, **kwargs)


def unique_slug(model, title, exclude_pk=None):
    """
    Slug libre déduit d'un titre.

    Deux titres DIFFÉRENTS peuvent donner le même slug — « Fusée ANUBIS » et
    « Fusee ANUBIS » donnent tous deux « fusee-anubis », et en français les
    accents rendent le cas courant. Sans suffixe, le second enregistrement
    plante en IntegrityError au lieu d'afficher quelque chose. On suffixe
    donc, et un titre qui ne laisse aucun caractère slugifiable (emoji seuls)
    retombe sur un nom générique plutôt que sur un slug vide.
    """
    base = slugify(title) or "sans-titre"
    others = model.objects.exclude(pk=exclude_pk) if exclude_pk \
        else model.objects.all()
    slug, n = base, 2
    while others.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


# =============================================================================
# Projets, cartes, kanban, fil d'activité
# =============================================================================
class Project(SluggedModel):
    """Un projet de l'asso : une fusée, un drone, un banc de test…"""
    STATUS = [("actif", "Actif"), ("archive", "Archivé")]

    name = models.CharField("nom", max_length=120, unique=True)
    description = models.TextField("description (Markdown)", blank=True)
    team = models.TextField(
        "équipe", blank=True,
        help_text="Un nom par ligne, ou séparés par des virgules.")
    campaign_year = models.CharField(
        "campagne", max_length=20, blank=True,
        help_text="Ex. « 2026-2027 » — sert au classement des archives.")
    status = models.CharField(max_length=10, choices=STATUS, default="actif")
    created = models.DateTimeField(auto_now_add=True)

    # --- Géométrie, pour la marge statique (pôle méca) ---------------------
    # Le Hub ne calcule PAS l'aérodynamique : OpenRocket le fait déjà et le
    # fait mieux. On y recopie le centre de poussée, et le Hub s'occupe de ce
    # qui se mesure à l'atelier — les masses réellement pesées.
    diameter_mm = models.DecimalField("calibre (mm)", max_digits=7,
                                      decimal_places=1, null=True, blank=True)
    cp_mm = models.DecimalField(
        "centre de poussée (mm depuis la pointe)", max_digits=8,
        decimal_places=1, null=True, blank=True,
        help_text="Relevé dans OpenRocket — le Hub ne le calcule pas.")
    min_margin = models.DecimalField(
        "marge statique minimale (calibres)", max_digits=4, decimal_places=2,
        default=Decimal("1.5"),
        help_text="Seuil de l'asso — vérifier le cahier des charges de la "
                  "campagne en vigueur, il fait foi.")

    class Meta:
        ordering = ["status", "-created"]   # actifs d'abord, récents d'abord

    def get_absolute_url(self):
        return reverse("project_detail", args=[self.slug])

    def members(self):
        """L'équipe saisie librement, découpée en noms (lignes ou virgules)."""
        return [m.strip() for m in re.split(r"[\n,]", self.team) if m.strip()]

    def mass_balance(self):
        """Le centrage de CETTE fusée — voir compute_mass_balance()."""
        return compute_mass_balance(list(self.mass_items.all()),
                                    self.cp_mm, self.diameter_mm)

    def __str__(self):
        return self.name


# Les trois pôles travaillent sur LE MÊME projet : une fusée a un séquenceur
# (élec), une coiffe (méca) et un firmware (soft). Le pôle est donc un
# attribut de l'élément, pas un Hub séparé — sans quoi le pôle méca ne verrait
# pas que la case électronique a pris 200 g.
POLES = [("elec", "Élec"), ("meca", "Méca"), ("soft", "Soft")]

# Un cycle de vie PAR pôle : router un PCB et usiner une pièce ne sont pas la
# même étape. L'ordre de chaque liste EST l'ordre du rail — ne jamais trier.
LIFECYCLES = {
    "elec": [
        ("conception", "Conception"), ("routage", "Routage"),
        ("fabrication", "Fabrication"), ("assemblage", "Assemblage"),
        ("test", "Test"), ("integration", "Intégration"),
        ("vol", "Vol"), ("resultat", "Résultat"),
    ],
    "meca": [
        ("conception", "Conception"), ("cao", "CAO"),
        ("fabrication", "Usinage / impression"), ("assemblage", "Assemblage"),
        ("test", "Test"), ("integration", "Intégration"),
        ("vol", "Vol"), ("resultat", "Résultat"),
    ],
    "soft": [
        ("conception", "Conception"), ("developpement", "Développement"),
        ("revue", "Revue de code"), ("test_banc", "Test au banc"),
        ("integration", "Intégration"), ("vol", "Vol"),
        ("resultat", "Résultat"),
    ],
}

# Union ordonnée des clés : c'est ce que la BASE accepte comme valeur d'étape.
# Une même clé peut porter un libellé différent selon le pôle (« fabrication »
# = « Fabrication » côté élec, « Usinage / impression » côté méca) : on garde
# ici le premier rencontré, et c'est Board.status_label() — qui lit le rail du
# pôle — qui donne le bon mot à l'affichage.
_seen = {}
for _stages in LIFECYCLES.values():
    for _key, _label in _stages:
        _seen.setdefault(_key, _label)
ALL_STAGES = list(_seen.items())


class Board(models.Model):
    """
    Un élément d'un projet : une carte électronique (élec), une pièce
    mécanique (méca) ou un module logiciel (soft). Le modèle est commun —
    seuls le cycle de vie et le vocabulaire changent d'un pôle à l'autre.

    `status` est l'étape du rail affiché partout : il doit refléter la
    réalité physique.
    """
    # Étapes où « non applicable » a un sens (test raté → pas d'intégration,
    # pas de vol, pas de résultat). L'ordre porte la cascade, vers l'avant.
    # Communes aux trois pôles : la fusée vole — ou pas — pour tout le monde.
    NA_STAGES = ("integration", "vol", "resultat")
    # Le mot juste selon le pôle, pour les titres et les boutons.
    NOUNS = {"elec": "carte", "meca": "pièce", "soft": "module"}

    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name="boards")
    pole = models.CharField("pôle", max_length=4, choices=POLES, default="elec")
    name = models.CharField("nom", max_length=120)
    status = models.CharField("étape", max_length=15, choices=ALL_STAGES,
                              default="conception")
    manager = models.CharField("responsable", max_length=60, blank=True)
    target_date = models.DateField("date cible", null=True, blank=True)
    notes = models.TextField("notes (Markdown)", blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["project", "pole", "name"]
        unique_together = [("project", "name")]

    def get_absolute_url(self):
        return reverse("board_detail", args=[self.pk])

    def lifecycle(self):
        """Le rail de CE pôle — lu directement par le template `_rail.html`."""
        return LIFECYCLES[self.pole]

    def noun(self):
        return self.NOUNS[self.pole]

    def status_label(self):
        """Libellé de l'étape DANS le rail du pôle — à préférer partout à
        `get_status_display`, qui ignore le pôle et rendrait « Fabrication »
        pour une pièce méca en cours d'usinage."""
        return dict(self.lifecycle()).get(self.status, self.status)

    def lifecycle_position(self):
        """Index de l'étape courante : le template grise ce qui précède.
        Tolérant si l'étape n'appartient pas (ou plus) au pôle — changer le
        pôle d'un élément ne doit pas casser sa page."""
        keys = [s for s, _ in self.lifecycle()]
        return keys.index(self.status) if self.status in keys else 0

    def na_stages(self):
        """Étapes marquées non applicables — barrées sur le rail.
        Méthode du modèle plutôt que la même requête recopiée dans quatre
        vues : le template `_rail.html` la lit directement."""
        return list(self.stages.filter(non_applicable=True)
                    .values_list("stage", flat=True))

    def current_firmware(self):
        """Pôle soft : la version qui tourne est le DERNIER flash réussi du
        registre — jamais un champ à resynchroniser (même doctrine que le
        stock, qui est la somme de ses mouvements)."""
        return self.flashes.filter(ok=True).first()

    def __str__(self):
        return f"{self.project.name} / {self.name}"


class BoardStage(models.Model):
    """
    Contenu propre à UNE étape d'une carte : ses notes et son marquage
    « non applicable ». Les photos et avancements vivent dans les Post
    taggés `stage` — on réutilise le fil plutôt qu'un stockage parallèle.
    Une ligne par (carte, étape), créée À LA DEMANDE : on n'en pré-crée
    jamais huit.
    """
    board = models.ForeignKey(Board, on_delete=models.CASCADE,
                              related_name="stages")
    stage = models.CharField("étape", max_length=15, choices=ALL_STAGES)
    notes = models.TextField("notes (Markdown)", blank=True)
    non_applicable = models.BooleanField("non applicable", default=False)
    na_reason = models.CharField("raison", max_length=200, blank=True)

    class Meta:
        unique_together = [("board", "stage")]

    def __str__(self):
        return f"{self.board} · {self.get_stage_display()}"


class Task(models.Model):
    """Tâche du kanban. Volontairement minimaliste : ni sous-tâches ni
    dépendances — chaque champ en plus est un champ que personne ne remplira."""
    COLUMNS = [("todo", "À faire"), ("doing", "En cours"),
               ("blocked", "Bloqué"), ("done", "Fait")]

    board = models.ForeignKey(Board, on_delete=models.CASCADE,
                              related_name="tasks")
    title = models.CharField("titre", max_length=200)
    column = models.CharField(max_length=10, choices=COLUMNS, default="todo")
    assignee = models.CharField("qui", max_length=60, blank=True)
    target_date = models.DateField("pour le", null=True, blank=True)
    # Rang dans la colonne, entretenu par le glisser-déposer SortableJS.
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["column", "position", "id"]

    def __str__(self):
        return self.title


class Post(models.Model):
    """
    Publication du fil d'activité, avec photos. Rattachée SOIT à un projet
    (annonce générale), SOIT à une carte (avancement précis).
    `stage` non vide ⇒ le post appartient à la sous-page de cette étape et
    n'apparaît pas dans le fil général de la carte.
    """
    author = models.CharField("auteur", max_length=60)
    text_md = models.TextField("texte (Markdown)", blank=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                null=True, blank=True, related_name="posts")
    board = models.ForeignKey(Board, on_delete=models.CASCADE,
                              null=True, blank=True, related_name="posts")
    stage = models.CharField("étape", max_length=15, blank=True,
                             choices=ALL_STAGES)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]   # fil antéchronologique

    def target(self):
        """L'objet auquel le post est rattaché (affichage et redirection)."""
        return self.board or self.project

    def get_absolute_url(self):
        return self.target().get_absolute_url()

    def __str__(self):
        # L'extrait fait partie du __str__ pour que la page de recherche
        # affiche quelque chose d'utile sans template dédié aux posts.
        return f"{self.author} — {Truncator(self.text_md).words(14)}"


def photo_path(instance, filename):
    """Rangement disque : photos/<id du post>/<nom>.webp"""
    return f"photos/{instance.post_id}/{filename}"


class Photo(models.Model):
    """Photo d'un post, déjà recompressée en WebP par hub.images —
    l'original de 5 Mo n'est jamais stocké."""
    post = models.ForeignKey(Post, on_delete=models.CASCADE,
                             related_name="photos")
    image = models.FileField(upload_to=photo_path)   # WebP 1600 px max
    thumb = models.FileField(upload_to=photo_path)   # WebP 400 px max
    caption = models.CharField("légende", max_length=200, blank=True)


class Comment(models.Model):
    """Commentaire plat sous un post — pas de fils imbriqués."""
    post = models.ForeignKey(Post, on_delete=models.CASCADE,
                             related_name="comments")
    author = models.CharField("auteur", max_length=60)
    text = models.TextField("commentaire")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created"]   # chronologique sous le post


# =============================================================================
# Pôle méca : masse et centrage
#
# Même doctrine que le stock : la masse d'une fusée n'est pas un champ qu'on
# tient à jour, c'est la SOMME des pièces réellement pesées. Le problème que
# ça résout est celui de toutes les campagnes : « la CAO annonçait 3,2 kg, la
# vraie fusée en pèse 3,9 et le CG a reculé de 4 cm ».
# =============================================================================
def compute_mass_balance(items, cp_mm=None, diameter_mm=None):
    """
    (masse totale en g, CG en mm depuis la pointe, marge statique en calibres).

        CG    = Σ(mᵢ · xᵢ) / Σ(mᵢ)      ← moyenne PONDÉRÉE, pas une moyenne
        marge = (CP − CG) / calibre

    CG et marge valent None tant qu'il manque une donnée : on préfère
    afficher « — » qu'un chiffre inventé, sur lequel personne ne doit fonder
    une autorisation de vol.

    Fonction libre plutôt que méthode : le calcul ne dépend pas de la base,
    donc il se vérifie sans elle (voir tests.py).
    """
    total = sum((i.mass_g for i in items), ZERO)
    if not total:
        return ZERO, None, None
    cg = sum((i.mass_g * i.position_mm for i in items), ZERO) / total
    margin = None
    if cp_mm is not None and diameter_mm:
        margin = (cp_mm - cg) / diameter_mm
    return total, cg, margin


class MassItem(models.Model):
    """
    Une masse RÉELLEMENT PESÉE et sa position sur l'axe de la fusée.

    Attachée au projet (la fusée entière) et non à un pôle : la case
    électronique et le parachute pèsent aussi. Chaque pôle verse ses pièces
    au même budget — c'est tout l'intérêt d'un Hub partagé.
    """
    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name="mass_items")
    # Élément concerné, quand la pièce en a un (facultatif : le moteur ou le
    # lest n'appartiennent à aucun élément suivi).
    board = models.ForeignKey(Board, on_delete=models.SET_NULL, null=True,
                              blank=True, related_name="mass_items")
    name = models.CharField("désignation", max_length=120)
    mass_g = models.DecimalField("masse pesée (g)", max_digits=9,
                                 decimal_places=1)
    position_mm = models.DecimalField(
        "position du CG de la pièce (mm depuis la pointe)", max_digits=8,
        decimal_places=1,
        help_text="Toujours depuis la POINTE : une origine commune, sinon "
                  "le centrage est faux sans prévenir.")
    note = models.CharField("précision", max_length=200, blank=True)
    author = models.CharField("pesée par", max_length=60)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position_mm", "id"]   # de la pointe vers le culot
        verbose_name = "masse"

    def __str__(self):
        return f"{self.name} — {self.mass_g} g"


# =============================================================================
# Pôle soft : registre de flash
#
# Encore la même doctrine : la version qui tourne sur une carte n'est pas un
# champ, c'est la DERNIÈRE ligne réussie de son registre. Le problème résolu :
# « quelle version est sur le séquenceur, et est-ce bien celle qui a passé le
# test au banc ? » — une question qu'on ne veut pas se poser sur le pas de tir.
# =============================================================================
class Flash(models.Model):
    """Un flash : ce module logiciel, dans cette version, sur cette carte."""
    board = models.ForeignKey(Board, on_delete=models.CASCADE,
                              related_name="flashes")
    # Carte électronique effectivement flashée (facultatif : un flash de banc
    # de test ne vise pas toujours une carte suivie).
    target = models.ForeignKey(Board, on_delete=models.SET_NULL, null=True,
                               blank=True, related_name="flashed_with")
    version = models.CharField("version", max_length=40)
    git_ref = models.CharField("commit / tag", max_length=40, blank=True)
    # Un flash raté ne devient pas la version courante : sans ce drapeau, un
    # échec écraserait la dernière version connue comme bonne.
    ok = models.BooleanField("flash réussi", default=True)
    author = models.CharField("par", max_length=60)
    notes = models.CharField("contexte", max_length=200, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]
        verbose_name = "flash"

    def __str__(self):
        return f"{self.board.name} {self.version}"


# =============================================================================
# Stock : catalogue + registre de mouvements
#
# LA règle : le stock est la somme des mouvements d'un composant, jamais un
# champ. Une erreur se corrige en AJOUTANT un mouvement, jamais en réécrivant
# l'histoire. Pour lire une liste : Part.objects.with_stock() (une requête) —
# ne jamais boucler en appelant part.stock().
# =============================================================================
class Location(models.Model):
    """Un rangement physique : bac, tiroir, page de carnet, étagère.
    Volontairement PLAT : à 100-200 références « Armoire A / Bac 3 » suffit,
    et ça évite un modèle récursif à maintenir."""
    name = models.CharField("emplacement", max_length=80, unique=True)
    note = models.CharField("précision", max_length=120, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "emplacement"

    def __str__(self):
        return self.name


class PartQuerySet(models.QuerySet):
    def with_stock(self):
        """Annote CHAQUE composant de son stock, en une seule requête."""
        return self.annotate(stock=Coalesce(Sum("movements__delta"), ZERO))


class Part(models.Model):
    """
    Un composant du référentiel du pôle.

    Pas de quantité ici : elle vit dans les mouvements. Les champs
    fournisseur sont volontairement PLATS — un nom, une référence, un lien.
    Aucune API n'est appelée : on ouvre la page LCSC/Mouser dans un onglet.
    """
    CATEGORIES = [
        ("resistance", "Résistance"), ("condensateur", "Condensateur"),
        ("inductance", "Inductance"), ("diode", "Diode / LED"),
        ("transistor", "Transistor / MOSFET"), ("ci", "Circuit intégré"),
        ("connecteur", "Connecteur"), ("module", "Module"),
        ("mecanique", "Mécanique / visserie"), ("autre", "Autre"),
    ]

    name = models.CharField(
        "nom", max_length=140, unique=True,
        help_text="Convention : « RES 10k 0603 1% » pour les passifs, "
                  "le MPN pour les actifs.")
    category = models.CharField("catégorie", max_length=14,
                                choices=CATEGORIES, default="autre")
    value = models.CharField("valeur", max_length=40, blank=True)     # 10k, 100n
    package = models.CharField("boîtier", max_length=40, blank=True)  # 0603…
    mpn = models.CharField("réf fabricant (MPN)", max_length=120, blank=True)
    manufacturer = models.CharField("fabricant", max_length=80, blank=True)

    location = models.ForeignKey(Location, on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="parts")
    min_qty = models.DecimalField("seuil d'alerte", default=ZERO, **QTY)

    supplier = models.CharField("fournisseur", max_length=60, blank=True,
                                help_text="LCSC, Mouser, RS, Würth…")
    sku = models.CharField("réf fournisseur", max_length=60, blank=True)
    supplier_url = models.URLField("page produit", blank=True)
    # Quatre décimales : certains composants coûtent 0,0020 €.
    unit_price = models.DecimalField("prix unitaire (EUR)", null=True,
                                     blank=True, max_digits=10,
                                     decimal_places=4)
    datasheet_url = models.URLField("datasheet", blank=True)
    # Fichier en plus du lien : utile quand le PDF fournisseur disparaît.
    datasheet_pdf = models.FileField("datasheet (PDF)", upload_to="datasheets/",
                                     blank=True)
    # Photo réservée aux composants qu'on ne reconnaît pas au premier coup
    # d'œil — même pipeline WebP que les photos de posts, zéro code en plus.
    photo = models.FileField(upload_to="composants/", blank=True)
    notes = models.TextField("notes", blank=True)
    created = models.DateTimeField(auto_now_add=True)

    objects = PartQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        verbose_name = "composant"

    def get_absolute_url(self):
        return reverse("part_detail", args=[self.pk])

    def stock(self):
        """Stock d'UN composant. Pour une liste, utiliser .with_stock()."""
        return self.movements.aggregate(s=Coalesce(Sum("delta"), ZERO))["s"]

    def __str__(self):
        return self.name


class Movement(models.Model):
    """
    Une ligne du registre : + à l'entrée, − à la sortie. C'est la SEULE
    façon de faire bouger un stock, donc le stock ne peut pas être faux.
    """
    KINDS = [("entree", "Entrée"), ("sortie", "Sortie"),
             ("inventaire", "Correction d'inventaire")]

    part = models.ForeignKey(Part, on_delete=models.CASCADE,
                             related_name="movements")
    # Signé : +50 entrée, −3 sortie. Le signe porte le sens.
    delta = models.DecimalField("quantité (signée)", **QTY)
    kind = models.CharField("type", max_length=10, choices=KINDS,
                            default="sortie")
    author = models.CharField("par", max_length=60)
    reason = models.CharField("motif", max_length=200, blank=True)
    # Carte servie quand la sortie sert un assemblage précis (optionnel).
    board = models.ForeignKey(Board, on_delete=models.SET_NULL, null=True,
                              blank=True, related_name="movements")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]
        verbose_name = "mouvement"

    def __str__(self):
        return f"{self.delta:+} {self.part} ({self.author})"


# =============================================================================
# Import de BOM
#
# Une BOM vit dans BomImport/BomImportLine PENDANT le rapprochement ; une
# fois arbitrée elle devient des BomLine rattachées à la carte — et c'est
# elle qui sert au calcul de faisabilité.
# =============================================================================
class BomLine(models.Model):
    """Nomenclature validée : cette carte a besoin de N × ce composant."""
    board = models.ForeignKey(Board, on_delete=models.CASCADE,
                              related_name="bom_lines")
    # PROTECT : on ne supprime pas un composant utilisé par une nomenclature.
    part = models.ForeignKey(Part, on_delete=models.PROTECT,
                             related_name="bom_lines")
    qty = models.DecimalField("quantité par carte", default=Decimal("1"), **QTY)
    designators = models.CharField(max_length=300, blank=True)   # R1,R2,R7

    class Meta:
        ordering = ["designators", "id"]
        unique_together = [("board", "part")]

    def __str__(self):
        return f"{self.board} : {self.qty} × {self.part}"


class ColumnProfile(models.Model):
    """Mapping « entête du fichier → champ canonique », mémorisé pour être
    rejoué : la 2ᵉ BOM du même outil s'importe sans reconfigurer."""
    name = models.CharField("nom", max_length=80, unique=True)
    mapping = models.JSONField(default=dict)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class BomImport(models.Model):
    """Un import de BOM pour une carte, avec son état d'avancement."""
    STATUS = [("mapping", "Colonnes à mapper"),
              ("matching", "Rapprochement en cours"),
              ("done", "Nomenclature enregistrée")]

    board = models.ForeignKey(Board, on_delete=models.CASCADE,
                              related_name="bom_imports")
    filename = models.CharField(max_length=200)
    profile = models.ForeignKey(ColumnProfile, on_delete=models.SET_NULL,
                                null=True, blank=True)
    # Le brut est conservé tel quel : on peut re-mapper sans re-uploader.
    headers = models.JSONField(default=list)
    raw_rows = models.JSONField(default=list)
    status = models.CharField(max_length=10, choices=STATUS, default="mapping")
    created = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=60)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.filename} → {self.board}"


class BomImportLine(models.Model):
    """Une ligne de BOM après mapping : champs canoniques + verdict du
    moteur de rapprochement (voir matching.py). Tous les champs sont
    optionnels — une BOM réelle est trouée."""
    STATUS = [
        ("auto", "Validée automatiquement"),   # score ≥ 95
        ("review", "À arbitrer"),              # candidats ambigus
        ("nomatch", "Sans correspondance"),    # à créer au catalogue
        ("ignored", "Ignorée"),                # DNP ou choix utilisateur
    ]

    bom_import = models.ForeignKey(BomImport, on_delete=models.CASCADE,
                                   related_name="lines")
    row_index = models.PositiveIntegerField()
    designators = models.CharField(max_length=300, blank=True)
    qty = models.DecimalField(default=Decimal("1"), **QTY)   # par carte
    value = models.CharField(max_length=80, blank=True)
    package = models.CharField(max_length=40, blank=True)
    mpn = models.CharField(max_length=120, blank=True)
    manufacturer = models.CharField(max_length=120, blank=True)
    lcsc = models.CharField("réf fournisseur", max_length=40, blank=True)
    dnp = models.BooleanField("non monté (DNP)", default=False)

    status = models.CharField(max_length=10, choices=STATUS, default="review")
    matched_part = models.ForeignKey(Part, on_delete=models.SET_NULL,
                                     null=True, blank=True)
    matched_score = models.PositiveIntegerField(default=0)
    matched_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["row_index"]


class MatchCandidate(models.Model):
    """Proposition du moteur pour une ligne : score + raison LISIBLE
    (« MPN exact », « valeur + boîtier »). L'humain tranche."""
    line = models.ForeignKey(BomImportLine, on_delete=models.CASCADE,
                             related_name="candidates")
    part = models.ForeignKey(Part, on_delete=models.CASCADE)
    score = models.PositiveIntegerField()
    reason = models.CharField(max_length=200)

    class Meta:
        ordering = ["-score"]


# =============================================================================
# Bibliothèque de documents et wiki
# =============================================================================
class Document(models.Model):
    """Un rapport / compte rendu / post-mortem : PDF + métadonnées + texte."""
    TYPES = [
        ("rce", "Rapport RCE"), ("final", "Rapport final"),
        ("passation", "Passation"), ("procedure", "Procédure / Tuto"),
        ("datasheet", "Datasheets"), ("autre", "Autre"),
    ]

    title = models.CharField("titre", max_length=200)
    doc_type = models.CharField("type", max_length=12, choices=TYPES,
                                default="final")
    authors = models.CharField("auteur·e·s", max_length=200, blank=True)
    date = models.DateField("date du document", null=True, blank=True)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True,
                                blank=True, related_name="documents")
    pdf = models.FileField(upload_to="documents/")
    # Sources LaTeX zippées : recommandées — un PDF seul n'est pas modifiable
    # par la promo suivante.
    source_zip = models.FileField(upload_to="documents/", null=True, blank=True)
    thumb = models.FileField(upload_to="documents/", null=True, blank=True)
    # Texte intégral extrait à l'upload : c'est LUI qui rend les rapports
    # retrouvables par la recherche transversale.
    text_content = models.TextField(blank=True, editable=False)
    created = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=60)

    class Meta:
        ordering = ["-date", "-created"]

    def get_absolute_url(self):
        return reverse("document_detail", args=[self.pk])

    def __str__(self):
        return self.title


class WikiPage(SluggedModel):
    """Page de savoir vivant, éditable par tous, versionnée intégralement."""
    SLUG_FROM = "title"

    title = models.CharField("titre", max_length=200, unique=True)
    content_md = models.TextField("contenu (Markdown)", blank=True)
    # PDF optionnel affiché directement dans la page (iframe sur la vue média
    # protégée, servie inline) — pas besoin de le télécharger pour le lire.
    pdf = models.FileField("PDF intégré", upload_to="wiki/", blank=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def get_absolute_url(self):
        return reverse("wiki_page", args=[self.slug])

    def __str__(self):
        return self.title


class WikiRevision(models.Model):
    """Une révision = le TEXTE INTÉGRAL de la page à un instant donné.
    À ce volume c'est simple et incassable : pas de chaîne de diffs à
    reconstruire. « Restaurer » crée une nouvelle révision, il ne réécrit rien."""
    page = models.ForeignKey(WikiPage, on_delete=models.CASCADE,
                             related_name="revisions")
    content_md = models.TextField()
    author = models.CharField(max_length=60)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]
