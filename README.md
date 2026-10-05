# Anubis — Hub de management du CACS

**Anubis** est la plateforme web interne du **Cercle Aérospatial CentraleSupélec
(CACS)**. Elle sert à mieux manager les projets et à suivre l'avancement des
équipes : qui travaille sur quoi, à quelle étape en est chaque élément, ce qu'il
y a en stock, ce qui a été documenté et ce que la promotion suivante devra
reprendre.

> **État actuel : seul le PECS est couvert.** À ce stade, le site est adapté
> uniquement au **PECS (Pôle Espace CentraleSupélec)** du CACS. Les autres
> pôles du cercle (le sélecteur affiche déjà « HELICS — à venir ») ne sont pas
> encore pris en charge.

## Ce que ça apporte

- **Projets et avancement** : un projet (fusée, drone, banc de test…) regroupe
  des éléments (carte électronique, pièce mécanique, module logiciel), chacun
  avec son cycle de vie propre à son pôle, un kanban de tâches et un fil
  d'activité avec photos.
- **Les trois pôles sur un même projet** : élec, méca et soft partagent le même
  Hub au lieu de maintenir chacun leur outil.
- **Stock** : catalogue de composants dont la quantité est la somme des
  mouvements (donc jamais fausse), sortie rapide, saisie en rafale,
  faisabilité et liste d'achat.
- **BOM** : import de nomenclatures avec rapprochement automatique au catalogue.
- **Méca** : masse réellement pesée, centre de gravité et marge statique.
- **Soft** : registre de flash — quelle version tourne sur quelle carte.
- **Mémoire de l'asso** : bibliothèque de rapports avec recherche plein texte,
  et wiki versionné, pour que le savoir survive aux passations.

Django 5.2 + PostgreSQL, deux conteneurs Docker, prévu pour un petit serveur
(Raspberry Pi 4/5 ou VM Linux de 2 Go de RAM).

---

## Démarrer

```bash
cp .env.example .env    # puis REMPLIR (openssl rand -base64 48 pour les secrets)
docker compose up -d --build
```

Le Hub écoute sur `127.0.0.1:` + `HUB_PORT` (8081 par défaut). **Sur cette
machine le `.env` est réglé sur 8082**, parce que la pile V2 occupe encore
8081 ; en cas de doute, le port réel se lit avec :

```bash
docker compose port hub 8000
```
Aucun port n'est exposé publiquement : c'est au reverse proxy de l'asso
(Caddy / nginx / Traefik) de porter le HTTPS et de router le domaine dessus.

Mettre à jour :

```bash
git pull && docker compose up -d --build
```

Les migrations s'appliquent automatiquement au démarrage — il n'y a rien
d'autre à lancer.

Vérifier que ça tourne :

```bash
curl -s "localhost:$(docker compose port hub 8000 | cut -d: -f2)/sante/"
```

Lancer les tests :

```bash
docker compose exec hub python manage.py test
```

---

## Faire tester le Hub à l'asso

Docker Desktop fait tourner les conteneurs, mais il ne les met pas en ligne.
Il manque une seule brique : **quelque chose qui expose le port 8081 sur
Internet en HTTPS**. Pour une phase de test, lance un tunnel hors compose, par
exemple (URL en `https://…trycloudflare.com`, à ajouter au joker
`.trycloudflare.com` de `HUB_ALLOWED_HOSTS`) :

```bash
docker run --rm --network host cloudflare/cloudflared tunnel --url http://localhost:8081
```

Pas de compte, pas de port à ouvrir ; ta machine doit rester allumée et l'URL
change à chaque lancement.

### À faire AVANT de partager

1. **Changer les deux mots de passe** du `.env`. Le Hub n'a pas de comptes :
   qui a l'URL et le mot de passe peut tout faire — et le mot de passe admin
   permet de supprimer projets, mouvements et documents.
2. Vérifier ces deux lignes du `.env` — ce sont elles qui cassent en premier :

   ```
   HUB_ALLOWED_HOSTS=localhost,127.0.0.1,.trycloudflare.com
   HUB_CSRF_ORIGINS=http://localhost:8082,https://*.trycloudflare.com
   ```

   | Ce qui manque | Symptôme |
   |---|---|
   | l'hôte dans `HUB_ALLOWED_HOSTS` | **400** sur toutes les pages |
   | l'origine dans `HUB_CSRF_ORIGINS` | les pages s'affichent mais **aucun formulaire ne passe** (403) |

   Le second est le piège : le site a l'air de marcher, et personne ne peut
   se connecter. Renseigner les deux le supprime quel que soit le proxy.
3. Ne pas mettre de données sensibles pendant le test : l'URL est publique,
   juste imprévisible.

### Récolter les retours

Le Hub sait déjà le faire, inutile d'ouvrir un autre outil : crée une page de
wiki « Retours de test ». Elle est éditable par tout le monde, versionnée, et
chaque contribution est signée du prénom. Les remarques sur un projet précis
ont leur place dans le fil du projet, où l'on peut joindre une capture.

### Quand le test sera concluant

Le tunnel dépend de ta machine : ce n'est pas une hébergement durable. Deux
suites possibles, dans les deux cas le même `docker compose up -d --build` :

| Cible | Coût | Pour qui |
|---|---|---|
| **Raspberry Pi du local**, au bout d'un tunnel nommé | ~0 € | la cible prévue du projet — le Hub est dimensionné pour |
| **VPS** (Hetzner, OVH, Scaleway) + Caddy pour le HTTPS | ~4-5 €/mois | si le local n'a ni machine ni réseau fiable |

---

## Se connecter

Pas de comptes. Un **mot de passe partagé** ouvre la session, l'utilisateur
donne son **prénom**, et ce prénom signe tout (publications, commentaires,
mouvements de stock, révisions du wiki). Un **second mot de passe** (admin)
débloque les actions destructives : archiver ou supprimer un projet, supprimer
une publication, un mouvement ou un document.

---

## Un seul Hub, trois pôles

Les trois pôles ne sont **pas** trois Hubs séparés : une fusée a un séquenceur
(élec), une coiffe (méca) et un firmware (soft), et c'est le même projet. Le
pôle est donc un attribut de chaque élément, et le sélecteur de l'entête est
un **filtre** — sinon le pôle méca ne verrait jamais que la case électronique
a pris 200 g.

Ce qui change d'un pôle à l'autre :

| | Élec | Méca | Soft |
|---|---|---|---|
| L'élément s'appelle | une carte | une pièce | un module |
| Rail de cycle de vie | conception → **routage** → fabrication → assemblage → test → … | conception → **CAO** → **usinage** → assemblage → test → … | conception → **développement** → **revue** → **test au banc** → … |
| Second encart de sa page | nomenclature + faisabilité | nomenclature + faisabilité | **firmware en place** |
| Outil propre | import de BOM | **masse & centrage** | **registre de flash** |
| Couleur | bleu ciel | orange | violet |

Chaque pôle a sa couleur, en pastille **pleine** (`.chip.pole-elec/-meca/-soft`).
Les pastilles d'**étape** sont ambre et **contourées** : le contraste de forme
fait qu'on ne confond jamais les deux, même du coin de l'œil. Les trois teintes
dépassent 9:1 sur texte encre, dans les deux thèmes — vérifié au navigateur.

Tout le reste — kanban, fil d'activité et photos, stock et sorties, documents,
wiki, recherche — est **commun** et ne change pas selon le pôle.

Les trois rails se terminent par les mêmes étapes (intégration, vol, résultat)
et partagent donc la cascade « non applicable » : la fusée vole, ou pas, pour
tout le monde à la fois.

### Méca — masse & centrage

`Projet → Masse & centrage`. Chaque pièce est **pesée** puis inscrite avec sa
position depuis la pointe ; le Hub en tire la masse au décollage, le CG et la
marge statique.

La saisie part de l'**élément du projet** : le choisir suffit, son nom devient
la désignation — plus de « Coiffe » / « coiffe » / « Coife » qui se ressemblent
dans le tableau sans être la même pièce. La désignation libre reste là pour ce
qui n'est pas un élément suivi (moteur, parachute, lest) et pour préciser
(« Coiffe + porte-parachute »). Le menu marque les éléments **déjà pesés** :
compter deux fois la même pièce est l'erreur qui fausse un budget de masse
sans que rien n'ait l'air cassé.

Le Hub **ne fait pas d'aérodynamique** : le centre de poussée se recopie
d'OpenRocket, qui le fait déjà et mieux. Ce que le Hub apporte, c'est la masse
*réelle* plutôt que celle de la CAO — la seule qui volera. Le seuil de marge
minimale est un réglage du projet : **c'est le cahier des charges de la
campagne qui fait foi**, pas la valeur par défaut.

### Soft — registre de flash

`Carte soft → Registre de flash`. Une ligne par flash : version, commit, carte
visée, qui, et si ça a marché. Un flash **raté** reste au registre mais ne
devient pas la version courante — sinon un échec effacerait la dernière
version connue comme bonne.

---

## Les sept invariants

Ce sont les règles qui font que le système est juste. Une modification qui en
casse une produit un Hub subtilement faux.

| # | Règle | Où elle vit |
|---|---|---|
| **I1** | Le stock est `Σ(delta)` des mouvements, **jamais un champ** | `models.py` (Part / Movement) |
| **I2** | Le stock ne passe jamais sous zéro : une sortie trop grande est refusée | `views/inventory.py` (`quick_out_submit`) |
| **I3** | L'historique ne se réécrit pas, il se prolonge (inventaire, wiki, archivage) | `stock_adjust`, `wiki_restore` |
| **I4** | Pas de réservation : on décompte quand la carte est réellement montée | `consume_bom` |
| **I5** | L'import de BOM ne devine jamais en silence (auto ≥ 95, le reste s'arbitre) | `matching.py`, `views/bom.py` |
| **I6** | Aucun appel réseau sortant : un lien fournisseur, pas une API | partout |
| **I7** | Les auteurs sont des prénoms, pas des comptes | `middleware.py` |

Les deux ajouts des pôles méca et soft appliquent **le même I1** :

| | Ce n'est jamais un champ | C'est |
|---|---|---|
| Stock d'un composant | `Part.quantity` | `Σ(Movement.delta)` |
| Masse d'une fusée | un total tenu à la main | `Σ(MassItem.mass_g)` |
| Version sur une carte | `Board.firmware_version` | le dernier `Flash` réussi |

**Ne jamais ajouter un champ `Part.quantity` « pour la performance »** : ça
réintroduit exactement le bug que I1 élimine. Pour lire le stock d'une liste,
`Part.objects.with_stock()` (une seule requête).

---

## Où est quoi

```
docker-compose.yml       2 services, limites mémoire, healthcheck
.env.example             gabarit de configuration
scripts/                 backup.sh · restore.sh (chiffrement age)
hub/
├── Dockerfile  entrypoint.sh  requirements.txt
├── manage.py  settings.py  wsgi.py
└── hub/
    ├── models.py         TOUS les modèles (5 sections)
    ├── urls.py           TOUTES les routes
    ├── middleware.py     auth par mot de passe partagé + @require_admin
    ├── templatetags/hub_tags.py Markdown + [[liens croisés]] + bleach
    ├── matching.py       moteur de rapprochement BOM
    ├── parsing.py        lecture XLSX/CSV + heuristiques de colonnes
    ├── images.py         pipeline photo WebP
    ├── tests.py          les vérifications de la logique non triviale
    ├── static/hub.css    feuille unique, aucune dépendance CSS
    ├── views/            core · projects · inventory · bom · library · poles
    └── templates/        base.html + un dossier par domaine
```

Une seule app Django, des vues fonctions, zéro SPA, zéro build front-end
(htmx, SortableJS et EasyMDE sont chargés par CDN là où ils servent). Un
successeur peut modifier une page en l'ouvrant.

### Les briques mutualisées

Trois `include` portent tout ce qui se répétait :

| Fichier | Rôle |
|---|---|
| `templates/_rail.html` | le rail de cycle de vie, **un seul exemplaire** |
| `templates/_board_head.html` | fil d'Ariane + rail, pour les 5 pages d'un élément |
| `templates/projects/_posts.html` | formulaire de publication + fil |

Le rail affiché est celui **du pôle** de l'élément : `_rail.html` lit
`board.lifecycle` et `board.na_stages` directement sur le modèle — aucune vue
n'a à les passer au contexte. Ajouter un pôle = une entrée dans `LIFECYCLES`
(models.py), rien d'autre.

**L'étape réelle est visible sur les cinq pages d'un élément** (fiche,
sous-page d'étape, faisabilité, édition, registre de flash), parce qu'elles
incluent toutes `_board_head.html`. Le rail porte donc deux marques
distinctes :

| Classe | Sens | Rendu |
|---|---|---|
| `.now` | l'étape qu'on **regarde** | pastille encre |
| `.actual` | l'étape où l'élément est **vraiment** | souligné accent |

Elles se superposent partout sauf sur une sous-page d'étape — c'est là qu'est
tout l'intérêt : consulter « Conception » d'une pièce qui en est à la CAO ne
doit pas faire disparaître son étape réelle. La pastille du fil d'Ariane
(`Méca · CAO`) redit la même chose en clair et mène à cette étape en un clic.

⚠️ Le paramètre du rail s'appelle `viewed_stage`, pas `current` : `_rail.html`
est inclus dans des pages qui ont leurs propres variables, et un `current`
générique s'était déjà fait écraser en silence par le firmware courant de la
page de flash.

---

## Ce qu'il ne faut PAS « simplifier »

- **`bleach`** en fin de chaîne de rendu Markdown — la seule barrière XSS.
- **Les normalisations de `matching.py`** (suffixes de conditionnement,
  notation `4k7`, boîtiers impériaux) : ce sont des calibrations exigées par
  le matériel réel, pas de la sur-ingénierie.
- **PyMuPDF** : l'indexation plein texte des rapports *est* la promesse de la
  bibliothèque.
- **Le `start_period: 90s`** du healthcheck Postgres : sans lui, aucun
  démarrage à froid ne passe sur carte SD.
- **Le mode plein soleil** : c'est la condition pour que le site soit lisible
  dehors, le jour du lancement. Toute couleur ajoutée doit y rester ≥ 7:1
  (AAA) — se contenter de AA revient à ne rien lire sous le soleil.
- **La règle du stock non négatif** et le **tout-ou-rien de `consume_bom`**.
- **Le drapeau « flash réussi »** : sans lui, un flash raté devient la version
  officiellement en place.
- **`Board.status_label()`** plutôt que `get_status_display` : la même clé
  `fabrication` se dit « Fabrication » en élec et « Usinage / impression » en
  méca.

---

## Sauvegardes

Modèle en **tirage**, chiffré : le serveur produit une archive chiffrée avec
la clé **publique** `age` du responsable ; la clé **privée n'est jamais sur le
serveur**, donc même compromis les archives restent illisibles.

```bash
sudo apt-get install -y age
crontab -e   # 17 3 * * * /srv/aero/aero-platform-V3/scripts/backup.sh >> /srv/aero/backups/backup.log 2>&1
```

Restauration : `./scripts/restore.sh <archive.tar.age> <clé-privée-age>`.

**Le test de restauration complet par le nouvel admin fait partie de la
checklist de passation** — tant qu'il n'est pas passé, la passation n'est pas
finie. Le tirage de l'archive vers une machine extérieure (Actions, Drive,
alerte Discord) n'est volontairement pas fourni ici : il dépend de
l'infrastructure de l'asso, et se branche sur le `latest.txt` que
`backup.sh` écrit.

---

## Écarts assumés par rapport à la spécification V2

La spec listait sa propre dette (§ 16.2). Elle est corrigée ici plutôt que
recopiée :

| Dette V2 | V3 |
|---|---|
| Rail dupliqué dans 4 templates | un `include` unique |
| `na_stages` recalculé dans 4 vues | méthode `Board.na_stages()` |
| `login.html` recopiait le squelette de `base.html` | il l'étend (entête masquée hors session) |
| `bulk_entry.html` : deux formulaires jumeaux | un seul, modes basculés en CSS |
| `Document.visibility`, `WikiPage.visibility` déclarés, jamais utilisés | supprimés |
| Branche sqlite + repli `icontains` pour des tests inexistants | supprimée, et les tests existent |
| `BoardStage.updated`, `ColumnProfile.source_tool` jamais lus | supprimés |
| `scripts/check_changes.py` réimplémentait ce qu'il testait | remplacé par `hub/tests.py` |
| 3 migrations à rejouer | une seule, `0001_initial` (elle crée aussi la page wiki `faq`) |
| Pôles Méca et Soft en `<option disabled>` | ouverts, et filtre réel dans l'entête |

Autres différences volontaires :

- le fil d'une carte n'affiche que les publications **sans étape** (celles
  d'une étape vivent sur sa sous-page), comme le décrit la spec § 8.3 ;
- les URL sont résolues par `get_absolute_url` / `reverse` au lieu d'être
  écrites en dur (les liens `[[carte:12]]` suivent donc les routes) ;
- la recherche transversale est une seule boucle sur une table
  `(modèle, champs, titre)` au lieu de cinq blocs recopiés ;
- un nom déjà pris (projet, élément, composant, page de wiki) affiche un
  message au lieu d'une erreur 500, et deux titres qui donnent le même slug
  (« Fusée » / « Fusee ») sont départagés par un suffixe.
