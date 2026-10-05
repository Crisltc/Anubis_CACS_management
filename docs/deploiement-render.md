# Déployer le Hub sur Render, sans modifier le code

Render attend deux conventions que le Hub ne suit pas. On les contourne **par
la configuration**, pas en touchant au code :

| Convention Render | Ce que fait le Hub | Contournement |
|---|---|---|
| Écouter sur le port de `$PORT` | `entrypoint.sh` fixe `0.0.0.0:8000` | déclarer `PORT=8000` dans les variables Render |
| Lire la base dans `DATABASE_URL` | `settings.py` lit `DB_HOST`, `DB_USER`… | recopier les 5 champs affichés par Render |

Le reste passe tel quel : les migrations s'appliquent au démarrage, WhiteNoise
sert les statiques, et le Hub fait déjà confiance à `X-Forwarded-Proto` — donc
le HTTPS de Render est reconnu.

> **Validé avant rédaction.** L'image du Hub a été lancée seule, avec une base
> externe et l'hôte `hub-pecs.onrender.com` : `/sante/` répond 200 et la
> connexion renvoie 302. Aucune modification du code n'a été nécessaire.

---

## Avant de commencer : les limites du plan gratuit

À lire **maintenant**, pas après avoir tout monté.

- **Pas de disque persistant.** `/data/media` est effacé à chaque déploiement
  et à chaque redémarrage : **les photos d'atelier et les PDF de la
  bibliothèque disparaissent**. Les statiques, elles, sont régénérées au
  démarrage — aucun souci de ce côté. Pour une phase de test où l'on juge
  l'ergonomie, c'est acceptable ; pour l'usage réel, il faut le disque payant.
- **Le service s'endort** après une période sans visite : la première page
  ensuite met une bonne minute à venir. Prévenir les testeurs, sinon ils
  concluront que le site est cassé.
- **La base gratuite a une durée de vie limitée.** Vérifier le délai en
  vigueur sur la page tarifs de Render — au-delà, la base est supprimée.
- **`scripts/backup.sh` ne marche pas sur Render** : il s'appuie sur
  `docker compose exec`. Ici, c'est la sauvegarde de Render ou un `pg_dump`
  lancé depuis l'extérieur.

---

## Étape 1 — Créer la base PostgreSQL

Sur le tableau de bord Render : **New ▸ Postgres**.

- **Name** : `hub-pecs-db`
- **Region** : à noter, il faudra **la même** pour le service web (sans quoi
  le nom d'hôte interne ne résout pas)
- **Version** : 16
- **Plan** : Free

Une fois créée, ouvrir sa page et garder sous la main la section *Connections*.
Cinq valeurs vont servir : `Hostname`, `Port`, `Database`, `Username`,
`Password`. Prendre l'**hôte interne** (celui qui ne sort pas d'Internet), pas
l'externe : c'est plus rapide et ça évite d'exiger TLS.

---

## Étape 2 — Publier le service web

Deux routes. La **A** part de l'image déjà construite dans Docker Desktop —
c'est la plus proche de ce que tu as sous la main. La **B** laisse Render
construire depuis le dépôt Git ; c'est celle à privilégier une fois le projet
sur GitHub, parce que chaque `git push` redéploie tout seul.

### Route A — depuis l'image Docker Desktop

Render exécute du **linux/amd64**, et c'est justement l'architecture que
produit ta machine : l'image locale convient telle quelle. (Ce ne serait pas
le cas pour un Raspberry Pi, qui est en arm64.)

Se connecter au registre, puis étiqueter et pousser :

```powershell
docker login ghcr.io -u TON_PSEUDO_GITHUB
```

```powershell
docker tag aero-platform-v3-hub:latest ghcr.io/TON_PSEUDO/aero-hub:1.0.0
```

```powershell
docker push ghcr.io/TON_PSEUDO/aero-hub:1.0.0
```

Une commande par ligne : PowerShell 5.1 ne connaît pas `&&`.

Sur Render : **New ▸ Web Service ▸ Existing image**, et coller
`ghcr.io/TON_PSEUDO/aero-hub:1.0.0`. Si le paquet est privé, ajouter les
identifiants du registre dans *Settings ▸ Registry Credentials*.

> Étiqueter une **version** (`1.0.0`) et pas seulement `latest` : c'est ce qui
> permet de revenir en arrière quand une mise à jour casse quelque chose la
> veille d'une échéance.

### Route B — depuis le dépôt Git

Le dossier n'est pas encore un dépôt. Le créer et le pousser sur GitHub (le
`.gitignore` exclut déjà `.env`, donc les mots de passe ne partent pas).

Sur Render : **New ▸ Web Service**, connecter le dépôt, puis :

| Champ | Valeur |
|---|---|
| Language / Runtime | **Docker** |
| Root Directory | `hub` |
| Dockerfile Path | `./Dockerfile` |

Régler *Root Directory* sur `hub` évite d'avoir à corriger le chemin du
Dockerfile **et** le contexte de build : les deux suivent.

---

## Étape 3 — Les variables d'environnement

C'est l'étape qui décide si ça marche. Dans *Environment* du service web :

| Clé | Valeur | Pourquoi |
|---|---|---|
| `PORT` | `8000` | le Hub écoute 8000 en dur ; on l'annonce à Render |
| `DB_HOST` | *Hostname* de la base | |
| `DB_PORT` | `5432` | |
| `HUB_DB_NAME` | *Database* | |
| `DB_USER` | *Username* | |
| `DB_PASSWORD` | *Password* | |
| `HUB_SECRET_KEY` | une longue chaîne aléatoire | signe les sessions ; **ne plus jamais la changer** |
| `HUB_SHARED_PASSWORD` | mot de passe membre | à choisir, **pas** `pecs-dev` |
| `HUB_ADMIN_PASSWORD` | mot de passe admin | à choisir, **pas** `admin-dev` |
| `HUB_ALLOWED_HOSTS` | `hub-pecs.onrender.com` | l'URL exacte du service |
| `HUB_CSRF_ORIGINS` | `https://hub-pecs.onrender.com` | avec `https://` |

Générer la clé secrète :

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Les deux seules pannes probables

Elles ont été reproduites en local, voici leur signature exacte :

| Symptôme | Cause |
|---|---|
| **400** sur toutes les pages | l'URL du service manque dans `HUB_ALLOWED_HOSTS` |
| Les pages s'affichent mais **aucun formulaire ne passe** (403) | l'origine manque dans `HUB_CSRF_ORIGINS` |

La seconde est la traîtresse : le site a l'air de fonctionner, et personne ne
peut se connecter. Renseigner les deux supprime le problème.

L'URL n'est connue qu'après la première création du service. Il est donc
normal de déployer une fois, de relever l'URL, de compléter ces deux variables,
puis de laisser Render redéployer.

---

## Étape 4 — Vérifier

Régler *Health Check Path* sur `/sante/` dans les réglages du service : Render
saura ainsi si le Hub est réellement debout, et pas seulement démarré.

Puis, dans l'ordre :

1. `https://<ton-service>.onrender.com/sante/` doit afficher `ok` ;
2. la page de connexion doit s'afficher (sinon → **400**, voir plus haut) ;
3. se connecter avec un prénom et le mot de passe membre (sinon → **403**) ;
4. créer un projet, puis un élément : si l'enregistrement passe, la base est
   bien connectée et les migrations sont appliquées.

Les journaux du déploiement doivent montrer, dans cet ordre : l'attente de la
base, `migrate`, `collectstatic`, puis `Listening at: http://0.0.0.0:8000`.

---

## Ce qu'il faudra prévoir ensuite

Le plan gratuit convient à une phase de retours, pas à l'usage réel — à cause
du disque éphémère, qui fait disparaître photos et PDF. Trois suites
possibles :

- **rester sur Render** en payant l'instance et un disque persistant ;
- **un VPS + Caddy** : le `docker-compose.yml` fonctionne alors sans aucune
  adaptation, puisqu'il est déjà écrit pour un reverse proxy — voir le README ;
- **le Raspberry Pi du local** avec un tunnel, la cible d'origine du projet.
