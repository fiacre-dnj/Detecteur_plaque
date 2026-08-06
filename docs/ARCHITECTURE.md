# Architecture

> Ce fichier documente **ce qui existe**. L'intention, elle, vit dans
> [`prompt/`](../prompt/) — et quand les deux divergent, c'est ce fichier qui a
> raison sur l'état du code et `prompt/` qui a raison sur ce qui était demandé.
>
> Pour l'API route par route : [`API.md`](API.md).

## Vue d'ensemble

```
┌──────────────── navigateur ────────────────┐        ┌───── serveur Python ─────┐
│                                            │        │                          │
│  Studio (React)                            │        │  FastAPI /api/v1         │
│   ├─ source : fichier | démo | webcam      │        │   ├─ jobs   (SSE)        │
│   ├─ éditeur de géométrie (canvas)         │        │   ├─ realtime (WS)       │
│   ├─ lecteur maison                        │        │   ├─ models             │
│   └─ relecture de timeline + résultats     │        │   ├─ benchmark          │
│                                            │        │   └─ presets            │
└────────────────────────────────────────────┘        │                          │
        │  multipart (vidéo + config)                 │  AnalysisService         │
        │  SSE (progression)          ──────────────► │   ├─ UltralyticsEngine   │
        │  GET result.json.gz                         │   └─ AnalysisSession     │
        │  WS (frames JPEG ⇄ frameResult)             │        (domaine pur)     │
        ▼                                             │                          │
   rejoue la timeline sur                             │  SQLite (WAL) + disque   │
   la vidéo locale                                    └──────────────────────────┘
```

**Aucune inférence dans le navigateur.** Le frontend envoie, reçoit, rejoue. Voir
[ADR 0003](adr/0003-analyse-100-pourcent-backend.md).

## Découpage du dépôt

```
backend/            service FastAPI, environnement uv dédié, Python 3.12
  Dockerfile        l'image de production — elle contient AUSSI le frontend
frontend/           SPA React 19 + Vite + Tailwind v4, environnement bun
  Dockerfile        rechargement à chaud en conteneur ; jamais servi en production
docker-compose.yml  `docker compose up` → tout sur http://localhost:8000
.github/workflows/  la CI, trois jobs indépendants
prompt/             la spécification normative du projet
docs/               ce fichier, API.md, les ADR, l'état du projet
yolo/               poids .onnx d'une version antérieure — INUTILISÉS, ignorés par git
```

Deux racines de projet indépendantes, deux outillages, **aucun monorepo tool** :
le couplage entre les deux côtés est un contrat HTTP, pas un graphe de build. Le
contrat est matérialisé par `frontend/src/shared/api/contracts.ts`, miroir exact
des schémas pydantic, plus une fixture JSON committée parsée dans un test typé —
un renommage côté serveur casse donc un test côté client.

## Règles de dépendance

### Backend — vertical par feature, hexagonal à l'intérieur

```
api → application → domain
infrastructure → application (ports) → domain
core ← tout le monde ;  core → rien des features
feature A ↛ feature B   (sauf par un port explicite)
```

Un découpage purement horizontal (`domain/`, `services/`, `repositories/`
globaux) fait grossir quatre dossiers en parallèle et rend une feature impossible
à lire ou à supprimer d'un bloc. Un découpage purement vertical sans hexagone
ré-introduit `ultralytics` et `SQLAlchemy` au milieu de la logique de comptage, et
la CI redevient dépendante d'un GPU.

`features/*/domain/**` n'importe jamais `fastapi`, `sqlalchemy`, `ultralytics` ni
`cv2`. `numpy` est autorisé : un descripteur de ré-identification est du calcul,
pas de l'infrastructure. La règle est **outillée**, pas seulement écrite —
`backend/tests/test_architecture.py` parcourt les modules en `ast` et échoue.

### Frontend — Feature-Sliced Design

```
app → features → entities → shared
```

Une feature n'importe jamais une autre feature ; ce qui devient commun descend
dans `entities/` ou `shared/`. Chaque feature expose un seul `index.ts`.

## Décisions structurantes

| Décision | Raison courte | ADR |
|---|---|---|
| Inférence exclusivement serveur, COOP/COEP retiré | Une seule implémentation du comptage ; `SharedArrayBuffer` n'est plus nécessaire | [0003](adr/0003-analyse-100-pourcent-backend.md) |
| Python 3.12, borne haute `<3.13` | `torch` ne publie pas de roue `cp314` ; échouer à la résolution est diagnosticable | [0001](adr/0001-python-312.md) |
| Aucun poids dans git | ~700 Mo dans l'historique de la version précédente, définitifs | [0002](adr/0002-pas-de-poids-dans-git.md) |
| `torch` CPU par défaut (`torch-backend = "auto"`, pas d'extra) | Pas de GPU ici ; 250 Mo au lieu de 2,5 Go | [0005](adr/0005-torch-cpu-par-defaut.md) |
| `DESIGN.md` source des jetons, accent vert fonctionnel | Le chrome achromatique laisse la couleur au canvas, où elle encode une donnée | [0004](adr/0004-systeme-de-design.md) |

## Modèle de données

SQLite en mode WAL, SQLAlchemy async, migrations Alembic. Sept tables :

| Table | Contenu | Pourquoi en base |
|---|---|---|
| `jobs` | état, progression, configuration reçue | un job survit à un redémarrage |
| `job_vehicles` | le registre d'une analyse | requêté et paginé |
| `job_crossings` | les franchissements | requêtés par ligne et par instant |
| `job_zone_events` | les entrées de zone | idem |
| `benchmark_runs` / `benchmark_entries` | mesures et contexte matériel | comparables six mois plus tard |
| `geometry_presets` | géométries réutilisables | petites, et faites pour durer |

**Ce qui n'est pas en base** : la timeline complète d'une analyse, qui part dans un
`result.json.gz` sur disque. Plusieurs centaines de mégaoctets de snapshots
image par image n'ont rien à faire dans une base mono-écrivain, et personne ne les
requête — ils sont relus en bloc pour la relecture.

Trois décisions de persistance méritent d'être connues avant d'y toucher :

- **La progression n'écrit pas à chaque frame.** Elle vit en mémoire dans le
  `ProgressHub` et n'est persistée qu'à intervalle et aux transitions d'état. Une
  analyse à 25 images par seconde déclencherait sinon 25 écritures par seconde sur
  un moteur qui n'accepte qu'un écrivain.
- **`save_result_aggregates` fait une seule transaction** avec des insertions en
  lot : 5 000 franchissements insérés un par un prennent des minutes en SQLite.
- **Un modèle ORM ne sort jamais de son repository.** Il emporterait sa session et
  ses chargements paresseux dans un contexte async, où ils échouent sur un
  `MissingGreenlet` dont le message ne dit rien.

Les migrations sont jouées au démarrage **hors production** seulement : en
production, une migration est une décision de déploiement, pas un effet de bord
d'un redémarrage.

Le détail des colonnes est dans
[`prompt/07-PERSISTANCE-SQLITE.md`](../prompt/07-PERSISTANCE-SQLITE.md) et dans les
modèles ORM de chaque feature.

## Livraison

Une **seule image** sert le backend et l'interface (`backend/Dockerfile`, trois
étapes : build bun du frontend, résolution uv des dépendances, image d'exécution
non-root). Le backend monte le build du frontend sur `/` avec le repli SPA, après
le routeur d'API — donc `/api/**` gagne toujours.

Un seul origin, et c'est ce qui supprime les trois pannes de déploiement
habituelles de ce genre d'application : le CORS à ouvrir, le tamponnage du proxy
qui retient les événements SSE jusqu'à ce que son tampon soit plein, et le relais
WebSocket qu'il faut activer explicitement.

Un **seul worker** uvicorn, délibérément. Le service tient un état en mémoire — le
`ProgressHub`, les baux de modèles, le compteur de sessions temps réel — qu'un
second processus ne verrait pas : deux workers rendraient une progression sur deux
et autoriseraient deux sessions « uniques » simultanées. La concurrence utile est
ailleurs, dans les threads worker (`anyio.to_thread`) où part tout ce qui touche
OpenCV, PyTorch ou le disque en volume.

La CI (`.github/workflows/ci.yml`) a trois jobs indépendants — backend, frontend,
image — déclarés séparément pour qu'aucun échec n'annule les autres. Elle ne
télécharge **aucun poids** : les tests injectent un moteur factice, ce que le test
d'architecture rend possible en interdisant `ultralytics` hors de
`models_registry/infrastructure`.

## Tailles de bundle

Budget : chunk d'entrée **< 200 ko gzip**. Un dépassement est un sujet de revue,
pas un avertissement à museler.

Mesuré au lot 13, application complète (`bun run build`) :

| Chunk | Brut | gzip |
|---|---|---|
| `vendor` (react, react-dom, react-router, react-query) | 309,5 ko | **97,7 ko** |
| `index` (coquille, client HTTP, routeur) | 19,1 ko | **7,0 ko** |
| `index.css` (Tailwind + jetons) | 26,8 ko | 5,8 ko |
| `counting-studio` (route paresseuse) | 97,8 ko | 32,6 ko |
| `benchmark` (route paresseuse) | 12,0 ko | 4,7 ko |
| `job-history` (route paresseuse) | 9,2 ko | 3,5 ko |
| `geometry-presets` (modale paresseuse) | 7,1 ko | 2,8 ko |
| `FlowHistogram` (composant paresseux) | 2,4 ko | 1,3 ko |

**Entrée = vendor + index = 104,6 ko gzip**, soit un peu plus de la moitié du
budget — et **inchangée** depuis le lot 9 malgré tout ce qui a été ajouté depuis :
l'éditeur de géométrie, la relecture, le direct, le benchmark, l'historique et les
presets. C'est le découpage qui produit ce résultat, pas la modération : chaque
écran est un chunk que seul son visiteur télécharge.

Le Studio est de loin le plus lourd des chunks paresseux (32,6 ko gzip) parce
qu'il porte le canvas, le lecteur, la relecture et le direct. Il n'est chargé que
lorsqu'on l'ouvre — et c'est l'écran qu'on ouvre en premier, donc ce coût est réel
pour la plupart des visites. Le déplacer dans l'entrée ne changerait rien au total
et ferait payer le Studio à qui ne consulte que l'historique.
