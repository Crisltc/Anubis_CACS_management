"""
TOUTES les routes du Hub dans un seul fichier : le plus rapide moyen de
savoir ce qui existe, pour qui reprend le projet.
🔒 = réservé admin (voir le décorateur require_admin dans middleware.py).
"""
from django.urls import path

from .views import bom, core, inventory, library, poles, projects

urlpatterns = [
    # --- Transverse ---------------------------------------------------------
    path("connexion/", core.login_view, name="login"),
    path("deconnexion/", core.logout_view, name="logout"),
    path("media/<path:relpath>", core.protected_media, name="media"),
    path("recherche/", core.search, name="search"),
    path("sante/", core.health, name="health"),

    # --- Projets, cartes, kanban, fil d'activité -----------------------------
    path("", projects.dashboard, name="dashboard"),
    path("projets/nouveau/", projects.project_form, name="project_create"),
    path("projets/<slug:slug>/", projects.project_detail, name="project_detail"),
    path("projets/<slug:slug>/modifier/", projects.project_form, name="project_edit"),
    path("projets/<slug:slug>/archiver/", projects.project_archive_toggle, name="project_archive_toggle"),   # 🔒
    path("projets/<slug:slug>/supprimer/", projects.project_delete, name="project_delete"),                  # 🔒
    path("projets/<slug:project_slug>/cartes/nouvelle/", projects.board_form, name="board_create"),
    path("cartes/<int:pk>/", projects.board_detail, name="board_detail"),
    path("cartes/<int:pk>/etape/<str:stage>/", projects.board_stage, name="board_stage"),
    path("cartes/<int:pk>/modifier/", projects.board_form, name="board_edit"),
    path("cartes/<int:board_pk>/taches/", projects.task_create, name="task_create"),
    path("cartes/<int:board_pk>/taches/deplacer/", projects.task_move, name="task_move"),
    path("taches/<int:pk>/supprimer/", projects.task_delete, name="task_delete"),
    path("posts/publier/", projects.post_create, name="post_create"),
    path("posts/<int:post_pk>/commenter/", projects.comment_create, name="comment_create"),
    path("posts/<int:pk>/supprimer/", projects.post_delete, name="post_delete"),                              # 🔒

    # --- Pôle méca : masse & centrage · pôle soft : registre de flash -------
    path("projets/<slug:slug>/masse/", poles.mass_balance, name="mass_balance"),
    path("masse/<int:pk>/supprimer/", poles.mass_item_delete, name="mass_item_delete"),   # 🔒
    path("cartes/<int:pk>/flash/", poles.flash_log, name="flash_log"),

    # --- Stock ---------------------------------------------------------------
    path("stock/", inventory.part_list, name="part_list"),
    path("stock/composants/nouveau/", inventory.part_form, name="part_create"),
    path("stock/composants/<int:pk>/", inventory.part_detail, name="part_detail"),
    path("stock/composants/<int:pk>/modifier/", inventory.part_form, name="part_edit"),
    path("stock/composants/<int:pk>/inventaire/", inventory.stock_adjust, name="stock_adjust"),
    path("stock/mouvements/<int:pk>/supprimer/", inventory.movement_delete, name="movement_delete"),          # 🔒
    path("stock/emplacements/", inventory.locations, name="locations"),
    path("stock/saisie/", inventory.bulk_entry, name="bulk_entry"),
    path("stock/saisie/ajouter/", inventory.bulk_entry_submit, name="bulk_entry_submit"),
    path("stock/sortie/", inventory.quick_out, name="quick_out"),
    path("stock/sortie/valider/", inventory.quick_out_submit, name="quick_out_submit"),
    path("stock/faisabilite/<int:board_pk>/", inventory.feasibility, name="feasibility"),
    path("stock/faisabilite/<int:board_pk>/achats.csv", inventory.shortage_csv, name="shortage_csv"),
    path("stock/faisabilite/<int:board_pk>/sortir/", inventory.consume_bom, name="consume_bom"),

    # --- Import de BOM -------------------------------------------------------
    path("bom/", bom.import_list, name="bom_import_list"),
    path("bom/importer/", bom.import_upload, name="bom_import_upload"),
    path("bom/<int:pk>/colonnes/", bom.mapping_view, name="bom_mapping"),
    path("bom/<int:pk>/arbitrage/", bom.review_view, name="bom_review"),
    path("bom/<int:pk>/enregistrer/", bom.save_bom, name="bom_save"),
    path("bom/lignes/<int:line_pk>/decider/", bom.line_decide, name="bom_line_decide"),

    # --- Bibliothèque et wiki -------------------------------------------------
    path("documents/", library.document_list, name="document_list"),
    path("documents/ajouter/", library.document_upload, name="document_upload"),
    path("documents/<int:pk>/", library.document_detail, name="document_detail"),
    path("documents/<int:pk>/supprimer/", library.document_delete, name="document_delete"),                   # 🔒
    path("wiki/", library.wiki_index, name="wiki_index"),
    path("wiki/nouvelle/", library.wiki_edit, name="wiki_create"),
    path("wiki/<slug:slug>/", library.wiki_page, name="wiki_page"),
    path("wiki/<slug:slug>/modifier/", library.wiki_edit, name="wiki_edit"),
    path("wiki/<slug:slug>/historique/", library.wiki_history, name="wiki_history"),
    path("wiki/<slug:slug>/restaurer/<int:rev_pk>/", library.wiki_restore, name="wiki_restore"),
]
