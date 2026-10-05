"""
Rendu Markdown sécurisé + liens croisés [[...]].

Syntaxes reconnues dans les posts, le wiki et les descriptions de projet :
    [[projet:slug]]   [[carte:12]]   [[piece:345]]   [[doc:7]]
    [[texte libre]]   → recherche transversale sur ce texte

⚠️ L'ORDRE de la chaîne de rendu est critique : bleach passe EN DERNIER,
après le rendu Markdown. C'est la seule barrière XSS du site — ne jamais
la retirer ni la déplacer.
"""
import re

import bleach
import markdown as md
from django import template
from django.urls import reverse
from django.utils.safestring import mark_safe

# Balises/attributs survivant au nettoyage — tout le reste est retiré.
ALLOWED_TAGS = [
    "p", "br", "hr", "strong", "em", "code", "pre", "blockquote",
    "ul", "ol", "li", "h1", "h2", "h3", "h4", "a", "img", "table",
    "thead", "tbody", "tr", "th", "td", "del", "sup", "sub",
]
ALLOWED_ATTRS = {"a": ["href", "title"], "img": ["src", "alt", "title"]}

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")

# Préfixe → (nom de route, libellé par défaut). Les URL sont résolues par
# `reverse`, jamais écrites en dur : si une route bouge, les liens suivent.
TARGETS = {
    "projet": ("project_detail", "{}"),
    "carte": ("board_detail", "carte #{}"),
    "piece": ("part_detail", "composant #{}"),
    "doc": ("document_detail", "document #{}"),
}


def _wikilink_to_html(match):
    """Transforme un [[...]] en <a> selon son préfixe."""
    target = match.group(1).strip()
    label = (match.group(2) or "").strip()
    kind, _, ident = target.partition(":")
    route = TARGETS.get(kind.lower())
    if route and ident:
        url = reverse(route[0], args=[ident])
        default = route[1].format(ident)
    else:
        # Pas de préfixe connu → recherche transversale sur le texte.
        url, default = f"{reverse('search')}?q={target}", target
    return f'<a href="{url}">{label or default}</a>'


def render_markdown(text):
    """Markdown → HTML sûr, liens croisés résolus."""
    if not text:
        return ""
    text = WIKILINK_RE.sub(_wikilink_to_html, text)
    html = md.markdown(text, extensions=["tables", "fenced_code", "nl2br"])
    return mark_safe(bleach.clean(html, tags=ALLOWED_TAGS,
                                  attributes=ALLOWED_ATTRS))


register = template.Library()
register.filter("md", render_markdown)
