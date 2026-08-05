# Architecture

> Ce document grandit lot par lot. Les sections marquées « à venir » seront
> écrites quand le code correspondant existera : ce fichier documente ce qui est,
> pas ce qui est prévu. L'intention vit dans [`prompt/`](../prompt/).

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
backend/    service FastAPI, environnement uv dédié, Python 3.12
frontend/   SPA React 19 + Vite + Tailwind v4, environnement bun
prompt/     la spécification normative du projet
docs/       ce fichier, l'API en version lisible, les ADR
yolo/       poids .onnx d'une version antérieure — INUTILISÉS, ignorés par git
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
| `torch` CPU par défaut, extra `gpu` | Pas de GPU ici ; 250 Mo au lieu de 2,5 Go | [0005](adr/0005-torch-cpu-par-defaut.md) |
| `DESIGN.md` source des jetons, accent vert fonctionnel | Le chrome achromatique laisse la couleur au canvas, où elle encode une donnée | [0004](adr/0004-systeme-de-design.md) |

## Modèle de données

À venir — Lot 4. Voir [`prompt/07-PERSISTANCE-SQLITE.md`](../prompt/07-PERSISTANCE-SQLITE.md).

## Tailles de bundle

Budget : chunk d'entrée **< 200 ko gzip**. Un dépassement est un sujet de revue,
pas un avertissement à museler.

Mesuré au lot 9 (`bun run build`) :

| Chunk | Brut | gzip |
|---|---|---|
| `vendor` (react, react-dom, react-router, react-query) | 304,1 ko | **96,6 ko** |
| `index` (coquille, client HTTP, routeur) | 22,3 ko | **7,8 ko** |
| `index.css` (Tailwind + jetons) | 17,9 ko | 4,3 ko |
| `counting-studio` (route paresseuse) | 5,4 ko | 2,3 ko |
| `job-history` / `benchmark` (routes paresseuses) | < 1 ko | < 0,5 ko |

**Entrée = vendor + index = 104,4 ko gzip**, soit environ la moitié du budget.
Les trois écrans sont des chunks séparés : un visiteur qui n'ouvre que le Studio
ne télécharge ni l'historique ni le benchmark.
