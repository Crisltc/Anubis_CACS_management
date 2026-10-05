"""
Vérifications de la logique non triviale — celle qui ment silencieusement si
elle casse. L'essentiel tourne SANS base de données (SimpleTestCase) : ce sont
des fonctions pures. Seuls les slugs, qui interrogent la table pour éviter une
collision, ont besoin d'une base (TestCase).

    docker compose exec hub python manage.py test

Ce qui n'est PAS testé ici est testé par l'usage : les vues sont des
formulaires HTML qu'on voit marcher ou pas.
"""
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from .templatetags.hub_tags import render_markdown
from .matching import norm_mpn, norm_package, norm_text, norm_value
from .models import (ALL_STAGES, LIFECYCLES, Board, MassItem, Project,
                     compute_mass_balance)
from .parsing import extract_lines, guess_mapping


class Normalisations(SimpleTestCase):
    """Les calibrations que le matériel réel exige (voir matching.py)."""

    def test_notation_r58(self):
        # « 4k7 » : le multiplicateur sert de virgule décimale.
        self.assertEqual(norm_value("4k7"), "4.7K")
        self.assertEqual(norm_value("10k"), "10K")
        self.assertEqual(norm_value("100nF"), "100N")
        self.assertEqual(norm_value("10 kΩ"), "10K")

    def test_suffixes_de_conditionnement(self):
        # Même composant, conditionnements différents → même clé.
        self.assertEqual(norm_mpn("BC547B-TR"), norm_mpn("BC547B"))
        self.assertEqual(norm_mpn("CC0603-100N/RL"), norm_mpn("CC0603 100N"))
        # …mais un grade de température différent reste différent : c'est
        # pour ça que le score 80 n'est jamais auto-validé.
        self.assertNotEqual(norm_mpn("LM358AD"), norm_mpn("LM358D"))

    def test_boitiers_de_cao(self):
        self.assertEqual(norm_package("R0603"), "0603")
        self.assertEqual(norm_package("C_0603_1608Metric"), "0603")

    def test_norm_text(self):
        self.assertEqual(norm_text(" bc 547-b "), "BC547B")
        self.assertEqual(norm_text(None), "")


class LectureDeBom(SimpleTestCase):
    """Les deux façons dont une BOM ment (voir parsing.py)."""

    def test_entetes_mpn_avant_fabricant(self):
        # « Manufacturer Part Number » est un MPN, pas un fabricant :
        # l'ordre des motifs doit tenir.
        m = guess_mapping(["Manufacturer Part Number", "Manufacturer",
                           "Designator", "Qty", "LCSC Part"])
        self.assertEqual(m["Manufacturer Part Number"], "mpn")
        self.assertEqual(m["Manufacturer"], "manufacturer")
        self.assertEqual(m["LCSC Part"], "lcsc")

    def test_quantite_des_designators_fait_foi(self):
        mapping = {"Designator": "designator", "Qty": "qty"}
        rows = [{"Designator": "R1,R2,R7", "Qty": "2"}]
        line = extract_lines(rows, mapping)[0]
        self.assertEqual(line["qty"], 3)          # 3 designators, pas 2
        self.assertIn("designators", line["warning"])   # divergence signalée

    def test_dnp_par_defaut_monte(self):
        mapping = {"Designator": "designator", "DNP": "dnp"}
        rows = [{"Designator": "C1", "DNP": ""},
                {"Designator": "C2", "DNP": "yes"},
                {"Designator": "C3", "DNP": "fitted"}]
        monte = [not line["dnp"] for line in extract_lines(rows, mapping)]
        self.assertEqual(monte, [True, False, True])


class CyclesDeVieParPole(SimpleTestCase):
    """Chaque pôle a son rail, mais la base accepte l'union des étapes."""

    def test_chaque_pole_a_son_rail(self):
        self.assertIn(("routage", "Routage"), LIFECYCLES["elec"])
        self.assertIn(("cao", "CAO"), LIFECYCLES["meca"])
        self.assertIn(("revue", "Revue de code"), LIFECYCLES["soft"])
        # Un PCB se route, une pièce s'usine : pas d'étape « routage » en méca.
        self.assertNotIn("routage", dict(LIFECYCLES["meca"]))

    def test_toutes_les_etapes_sont_stockables(self):
        # Sans ça, enregistrer une pièce en CAO lèverait une erreur de champ.
        connues = dict(ALL_STAGES)
        for pole, stages in LIFECYCLES.items():
            for key, _ in stages:
                self.assertIn(key, connues, f"{key} ({pole}) hors ALL_STAGES")

    def test_les_trois_poles_finissent_ensemble(self):
        # La fusée vole — ou pas — pour tout le monde : la cascade « non
        # applicable » doit valoir dans les trois rails.
        for stages in LIFECYCLES.values():
            keys = dict(stages)
            for stage in Board.NA_STAGES:
                self.assertIn(stage, keys)

    def test_libelle_selon_le_pole(self):
        # Même clé, deux métiers : « fabrication » n'est pas le même geste.
        elec = Board(pole="elec", status="fabrication")
        meca = Board(pole="meca", status="fabrication")
        self.assertEqual(elec.status_label(), "Fabrication")
        self.assertEqual(meca.status_label(), "Usinage / impression")

    def test_position_tolere_une_etape_hors_pole(self):
        # Passer une carte élec en méca laisse un statut « routage » orphelin :
        # la page doit s'afficher quand même, pas planter.
        orphelin = Board(pole="meca", status="routage")
        self.assertEqual(orphelin.lifecycle_position(), 0)


class MasseEtCentrage(SimpleTestCase):
    """Pôle méca : le CG est une moyenne PONDÉRÉE — l'erreur classique est
    d'en faire une moyenne simple, et elle ne se voit pas."""

    def _pesees(self, *masses):
        """Des pièces pesées, non sauvegardées : le calcul est pur."""
        return [MassItem(name=f"p{i}", mass_g=Decimal(m), position_mm=Decimal(x))
                for i, (m, x) in enumerate(masses)]

    def test_cg_est_pondere_par_les_masses(self):
        # 100 g à 0 mm et 300 g à 1000 mm → CG à 750 mm, PAS à 500.
        total, cg, _ = compute_mass_balance(self._pesees((100, 0), (300, 1000)))
        self.assertEqual(total, Decimal("400"))
        self.assertEqual(cg, Decimal("750"))

    def test_marge_statique(self):
        # CG 750, CP 900, calibre 100 → 1,5 calibre.
        _, _, margin = compute_mass_balance(
            self._pesees((100, 0), (300, 1000)),
            cp_mm=Decimal("900"), diameter_mm=Decimal("100"))
        self.assertEqual(margin, Decimal("1.5"))

    def test_marge_negative_si_cp_devant_le_cg(self):
        # CP en avant du CG = fusée instable : le signe doit le dire.
        _, _, margin = compute_mass_balance(
            self._pesees((100, 1000)),
            cp_mm=Decimal("500"), diameter_mm=Decimal("100"))
        self.assertLess(margin, 0)

    def test_rien_de_pese_ne_donne_aucun_chiffre(self):
        # Surtout pas de division par zéro, et pas de CG inventé.
        total, cg, margin = compute_mass_balance([])
        self.assertEqual(total, Decimal("0"))
        self.assertIsNone(cg)
        self.assertIsNone(margin)

    def test_pas_de_marge_sans_geometrie(self):
        # Sans CP ni calibre on affiche « — », jamais une valeur par défaut.
        _, cg, margin = compute_mass_balance(self._pesees((100, 500)))
        self.assertEqual(cg, Decimal("500"))
        self.assertIsNone(margin)


class RenduMarkdown(SimpleTestCase):
    """bleach est la SEULE barrière XSS du site."""

    def test_script_neutralise(self):
        html = render_markdown("Bonjour <script>alert(1)</script>")
        self.assertNotIn("<script>", html)

    def test_liens_croises(self):
        self.assertIn('href="/cartes/12/"', render_markdown("[[carte:12]]"))
        self.assertIn("mon libellé", render_markdown("[[carte:12|mon libellé]]"))
        # Sans préfixe connu : repli sur la recherche transversale.
        self.assertIn("/recherche/", render_markdown("[[alimentation]]"))


class Slugs(TestCase):
    """Deux titres différents peuvent viser le même slug — en français, les
    accents rendent le cas courant. Le second ne doit pas planter."""

    def test_collision_d_accents(self):
        a = Project.objects.create(name="Fusée ANUBIS")
        b = Project.objects.create(name="Fusee ANUBIS")
        self.assertEqual(a.slug, "fusee-anubis")
        self.assertEqual(b.slug, "fusee-anubis-2")

    def test_titre_sans_caractere_slugifiable(self):
        self.assertEqual(Project.objects.create(name="🚀").slug, "sans-titre")

    def test_le_slug_ne_bouge_pas_a_l_edition(self):
        # L'URL d'un projet est partagée sur Discord : elle doit survivre à
        # une correction de titre.
        p = Project.objects.create(name="Banc de test")
        p.name = "Banc de test v2"
        p.save()
        self.assertEqual(p.slug, "banc-de-test")
