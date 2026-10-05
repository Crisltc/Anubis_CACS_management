"""
Moteur de rapprochement BOM ↔ catalogue du pôle.

Échelle de scores — LE cœur du module, on ne devine jamais en silence :

    100  réf fournisseur (SKU) exacte             → validé automatiquement
     95  MPN exact                                → validé automatiquement
     80  MPN normalisé (suffixe conditionnement)  → À CONFIRMER par l'humain
     60  paramétrique valeur + boîtier (passifs)  → À CONFIRMER par l'humain

Pourquoi 80 n'est PAS auto-validé : deux MPN qui ne diffèrent que par le
conditionnement (-TR, R7…) sont le MÊME composant, mais deux qui diffèrent
par le grade de température ne le sont pas. La normalisation ne sait pas les
distinguer, l'humain si. On montre, il tranche.

Tout se joue sur la base locale : aucun appel réseau, donc aucun import ne
peut échouer parce qu'un service extérieur est en panne.

Les normalisations ci-dessous sont des CALIBRATIONS exigées par le matériel
réel (conditionnements fournisseurs, notation R58, boîtiers de CAO) — ce
n'est pas de la sur-ingénierie, ne pas les simplifier.
"""
import re

from .models import MatchCandidate, Part

AUTO_THRESHOLD = 95

# Suffixes de conditionnement usuels (bande, bobine, coupe) — à enrichir au
# fil des cas réels rencontrés.
PACKAGING_SUFFIXES = re.compile(
    r"[-_/,]?(TR|CT|TB|ND|R7|RL|E3|T1|T2|REEL|CUT|TAPE)$", re.IGNORECASE)

# Tailles impériales reconnues dans les noms de boîtier des CAO.
IMPERIAL_SIZES = re.compile(r"(0201|0402|0603|0805|1206|1210|2010|2512)")


# ---------------------------------------------------------------------------
# Normalisations
# ---------------------------------------------------------------------------
def norm_text(s):
    """Majuscules, séparateurs écrasés : « BC 547-B » → « BC547B »."""
    return re.sub(r"[\s\-_./]+", "", (s or "").upper())


def norm_mpn(mpn):
    """MPN sans suffixe de conditionnement, puis normalisation générique."""
    return norm_text(PACKAGING_SUFFIXES.sub("", (mpn or "").strip()))


def norm_value(v):
    """
    Valeur de passif → forme canonique : 10K, 4.7K, 100N, 22P…
    Gère 10k / 10K / 10 kΩ / 0.1uF / 100nF / µ→U, et la notation « 4k7 »
    (norme R58, où le multiplicateur sert de virgule décimale).
    """
    s = (v or "").strip().upper().replace("Μ", "U").replace("µ".upper(), "U")
    s = re.sub(r"(OHMS?|Ω|F(ARAD)?S?|H(ENRY)?S?)$", "", s)   # unités finales
    s = s.replace(" ", "")
    m = re.fullmatch(r"(\d+)([RKMUNP])(\d+)", s)             # 4k7 → 4.7K
    return f"{m.group(1)}.{m.group(3)}{m.group(2)}" if m else s


def norm_package(p):
    """Boîtier : retire le verbiage des CAO (R0603, C_0603_1608Metric → 0603)."""
    s = norm_text(p)
    m = IMPERIAL_SIZES.search(s)
    return m.group(1) if m else s


# ---------------------------------------------------------------------------
# Rapprochement d'une ligne
# ---------------------------------------------------------------------------
def match_line(line):
    """
    Calcule les candidats d'une BomImportLine, les écrit en base et fixe le
    statut de la ligne. Renvoie ce statut.
    """
    line.candidates.all().delete()
    candidates = []   # (score, Part, raison lisible)

    # Le catalogue tient en quelques centaines de lignes : on le charge UNE
    # fois et on compare en mémoire. Plus simple et plus rapide qu'une
    # requête par critère, et ça restera vrai bien au-delà de 200 composants.
    catalogue = list(Part.objects.all())

    # --- 1. Réf fournisseur exacte : la clé la plus fiable -----------------
    if line.lcsc:
        key = norm_text(line.lcsc)
        candidates += [(100, p, f"réf fournisseur exacte ({line.lcsc})")
                       for p in catalogue if p.sku and norm_text(p.sku) == key]

    # --- 2. MPN exact, puis MPN normalisé ----------------------------------
    if line.mpn:
        exact, loose = norm_text(line.mpn), norm_mpn(line.mpn)
        for p in catalogue:
            # Le MPN vit dans le champ dédié OU dans le nom : la convention
            # de saisie des composants actifs met le MPN en nom.
            for field in (p.mpn, p.name):
                if not field:
                    continue
                if norm_text(field) == exact:
                    candidates.append((95, p, "MPN exact"))
                    break
                if norm_mpn(field) == loose:
                    candidates.append(
                        (80, p, "MPN à un suffixe de conditionnement près"))
                    break

    # --- 3. Paramétrique passifs : valeur + boîtier ------------------------
    if line.value:
        nval, npkg = norm_value(line.value), norm_package(line.package)
        for p in catalogue:
            # À défaut de champs remplis, repli sur le nom « RES 10k 0603 ».
            haystack = norm_text(p.name)
            pval = norm_value(p.value) if p.value else ""
            ppkg = norm_package(p.package) if p.package else ""
            value_ok = (pval and pval == nval) or (nval and nval in haystack)
            pkg_ok = (not npkg) or (ppkg == npkg) or (npkg in haystack)
            if value_ok and pkg_ok:
                candidates.append((60, p, f"valeur {line.value}"
                                   + (f" + boîtier {npkg}" if npkg else "")))

    # --- Dédoublonnage : le meilleur score par composant -------------------
    best = {}
    for score, part, reason in candidates:
        if part.pk not in best or best[part.pk][0] < score:
            best[part.pk] = (score, part, reason)
    ranked = sorted(best.values(), key=lambda c: -c[0])

    MatchCandidate.objects.bulk_create([
        MatchCandidate(line=line, part=part, score=score, reason=reason)
        for score, part, reason in ranked[:6]])

    # --- Verdict ------------------------------------------------------------
    if line.dnp:
        line.status, line.matched_reason = "ignored", "DNP (non monté)"
    elif ranked and ranked[0][0] >= AUTO_THRESHOLD:
        score, part, reason = ranked[0]
        line.status, line.matched_part = "auto", part
        line.matched_score, line.matched_reason = score, reason
    else:
        line.status = "review" if ranked else "nomatch"
    line.save()
    return line.status
