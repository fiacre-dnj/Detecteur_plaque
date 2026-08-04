# 01 — Stack, outillage et arborescence racine

## 1. Arborescence du dépôt

```
.
├── backend/                  # service FastAPI (uv)
├── frontend/                 # SPA React (bun)
├── prompt/                   # ce prompt
├── docs/
│   ├── ARCHITECTURE.md       # schéma + décisions
│   ├── adr/                  # Architecture Decision Records numérotés
│   └── API.md                # export lisible du contrat
├── .github/workflows/ci.yml
├── docker-compose.yml
├── .editorconfig
├── .gitattributes
├── .gitignore
├── CHANGELOG.md              # Keep a Changelog + SemVer
├── CONTRIBUTING.md           # renvoie vers prompt/11
├── README.md                 # démarrage en 5 commandes
└── CLAUDE.md                 # instructions agent, écrit en dernier
```

Deux racines de projet indépendantes, deux outillages, **aucun monorepo tool**
(pas de nx/turbo) : le couplage est un contrat HTTP, pas un graphe de build.

## 2. Backend

| Élément | Choix | Version |
|---|---|---|
| Langage | Python | **3.12** (`.python-version` = `3.12`) |
| Gestion d'env & deps | **uv** | ≥ 0.5 |
| Framework | FastAPI | ≥ 0.115 |
| Serveur ASGI | uvicorn[standard] | ≥ 0.30 |
| Validation / config | pydantic 2, pydantic-settings | ≥ 2.7 / ≥ 2.3 |
| Vision | ultralytics | ≥ 8.4, < 9 |
| Assignation trackers | **lap** | ≥ 0.5 |
| Images | opencv-python-headless, numpy | ≥ 4.9 / ≥ 1.26 |
| Upload multipart | python-multipart | ≥ 0.0.9 |
| ORM | **SQLAlchemy** (async) + aiosqlite | ≥ 2.0 / ≥ 0.20 |
| Migrations | **Alembic** | ≥ 1.13 |
| Journalisation | structlog | ≥ 24 |
| Limitation de débit | slowapi | ≥ 0.1.9 |
| Tests | pytest, pytest-asyncio, httpx | ≥ 8 / ≥ 0.23 / ≥ 0.27 |
| Lint / format | **ruff** | ≥ 0.5 |
| Types | **mypy --strict** | ≥ 1.10 |

### `lap` n'est pas optionnel
Ultralytics ne la tire pas, mais BoT-SORT/ByteTrack en ont besoin pour
l'assignation linéaire. Sans elle, `model.track()` échoue **à l'exécution**
avec `No module named 'lap'` — et aucun test à moteur factice ne peut le voir.
Elle est donc une dépendance de production explicite.

### Pourquoi Python 3.12 et pas 3.14
`torch` ne publie sur PyPI que des wheels cp310→cp313, et aucune variante CUDA
pour 3.14. En 3.14, `uv sync` échoue ou tente une compilation depuis les
sources, et Ultralytics ne démarre pas. Conséquences à écrire dans le projet :

- `backend/.python-version` contient `3.12` ;
- `pyproject.toml` déclare `requires-python = ">=3.12,<3.13"` — la borne haute
  est volontaire : elle transforme « ça plante à l'import de torch » en « uv
  refuse de résoudre », ce qui est diagnosticable ;
- une **ADR** (`docs/adr/0001-python-312.md`) explique la contrainte, sa date et
  la condition de sortie (« quand torch publiera des wheels cp314, relever la
  borne et relancer la CI »).

### Environnement virtuel
```bash
cd backend
uv sync                    # crée .venv dédié — jamais le Python global
uv run uvicorn traffic_analysis.main:app --reload --port 8000
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run alembic upgrade head
```
`torch` pèse ~2,5 Go installé. Si le disque du dépôt est juste :
`export UV_PROJECT_ENVIRONMENT=~/.venvs/traffic-backend` (l'environnement reste
dédié au backend).

### Variables d'environnement (préfixe `TRAFFIC_`)

Fichier `backend/.env.example` **committé**, `.env` ignoré.

```dotenv
TRAFFIC_ENV=development              # development | staging | production
TRAFFIC_HOST=127.0.0.1
TRAFFIC_PORT=8000
TRAFFIC_LOG_LEVEL=INFO
TRAFFIC_LOG_FORMAT=console           # console | json (json en prod)

# CORS — liste explicite, jamais "*" (voir prompt/06)
TRAFFIC_CORS_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]
TRAFFIC_CORS_ORIGIN_REGEX=
TRAFFIC_TRUSTED_HOSTS=["localhost","127.0.0.1"]

# Persistance
TRAFFIC_DATABASE_URL=sqlite+aiosqlite:///./data/traffic.db
TRAFFIC_DATA_DIR=./data              # résultats volumineux (json.gz), uploads

# Modèles
TRAFFIC_WEIGHTS_DIR=./.weights
TRAFFIC_DEVICE=auto                  # auto | cpu | 0 | cuda:0
TRAFFIC_HALF=true
TRAFFIC_DEFAULT_MODEL_ID=yolov8n
TRAFFIC_WARMUP=true
TRAFFIC_MAX_LOADED_MODELS=2
TRAFFIC_PLATE_MODEL_PATH=            # vide = <weights>/license-plate.onnx
TRAFFIC_PLATE_CONFIDENCE=0.25

# Bornes d'exécution
TRAFFIC_MAX_CONCURRENT_JOBS=1
TRAFFIC_MAX_REALTIME_SESSIONS=1
TRAFFIC_MAX_UPLOAD_MB=800
TRAFFIC_JOB_TTL_MINUTES=1440
TRAFFIC_RATE_LIMIT=60/minute

# Documentation
TRAFFIC_DOCS_ENABLED=true            # false en production
TRAFFIC_STATIC_DIR=                  # build frontend servi par le backend
```

Règles : **aucun secret ni valeur d'environnement en dur dans le code**, un seul
objet `Settings` (pydantic-settings) chargé une fois et injecté ; interdiction de
lire `os.environ` ailleurs.

## 3. Frontend

| Élément | Choix |
|---|---|
| Runtime / gestionnaire | **bun** (npm/pnpm fonctionnent, mais les scripts et le lockfile sont bun) |
| Framework | **React 19** |
| Build | **Vite** (dernière majeure stable) |
| Styles | **Tailwind CSS v4** via `@tailwindcss/vite` (pas de `tailwind.config.js` : configuration CSS-first avec `@theme`) |
| Icônes | **lucide-react** (uniquement — pas d'autre pack) |
| Routage | **react-router** v7 (`createBrowserRouter`, routes paresseuses) |
| État serveur | **@tanstack/react-query** v5 |
| Types | TypeScript strict |
| Lint | **oxlint** (rapide, config `.oxlintrc.json`) |
| Format | **prettier** (ou `oxfmt` si disponible) |
| Tests | **`bun test`** pour les modules purs + **@testing-library/react** pour les composants critiques |
| Optimisation | **babel-plugin-react-compiler** activé |

Interdits explicites : `onnxruntime-web`, `axios` (le `fetch` natif suffit et
notre client est une seule couche), `moment`, `lodash` (utilitaires natifs),
`redux` (React Query + état local suffisent), une seconde bibliothèque d'icônes,
une bibliothèque de graphiques (l'histogramme de flux est du SVG maison, ~40
lignes, et évite 100 ko de bundle).

### Scripts (`frontend/package.json`)
```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "lint": "oxlint",
    "format": "prettier --write src",
    "typecheck": "tsc -b",
    "test": "bun test",
    "test:watch": "bun test --watch",
    "analyze": "vite build --mode analyze"
  }
}
```

### TypeScript — options non négociables
`strict`, `noUncheckedIndexedAccess`, `verbatimModuleSyntax`,
`erasableSyntaxOnly`, `noUnusedLocals`, `noUnusedParameters`,
`noFallthroughCasesInSwitch`, `exactOptionalPropertyTypes`.

Conséquences pratiques : imports de types via `import type`, **pas de `enum`**
(utiliser des unions littérales ou `as const`), **pas de propriétés de
paramètres de constructeur** (les champs de classe s'écrivent explicitement),
un paramètre inutilisé fait échouer le build.

### L'alias `@/*` est déclaré dans **trois** fichiers qui doivent rester d'accord
1. `tsconfig.app.json` → `paths` (pour `tsc -b`) ;
2. `vite.config.ts` → `resolve.alias` (pour le bundler) ;
3. `tsconfig.json` racine → `paths` (c'est **le seul** que `bun test` lit ; le
   fichier solution est ignoré par `tsc -b`).

Ajouter `"types": ["@types/bun"]` dans `tsconfig.app.json` pour que les imports
`bun:test` des specs placées sous `src/` typecheckent.

### `vite.config.ts` — points obligatoires
- plugins : `react()`, `tailwindcss()`, react-compiler ;
- `server.port` lit `process.env.PORT` (l'outillage qui assigne un port doit
  obtenir le serveur qu'il attend) ;
- **proxy `/api` → backend** (`process.env.BACKEND_URL || http://127.0.0.1:8000`),
  avec `ws: true` pour le WebSocket temps réel. On passe par le proxy plutôt
  qu'en cross-origin pour rester **same-origin** : ni CORS, ni CORP à négocier
  en développement, et le SSE traverse sans réglage ;
- **piège Vite** : le repli SPA répond `index.html` en **HTTP 200** pour une
  route inconnue. Sans le proxy, `/api/health` renverrait donc du HTML avec un
  200 et serait parsé comme un JSON cassé au lieu d'être rapporté comme
  « backend absent ». Le client HTTP doit **vérifier le `content-type`** et
  lever une erreur explicite si c'est `text/html` ;
- `build.rollupOptions.output.manualChunks` : isoler `react`/`react-dom`,
  `react-router`, `@tanstack/react-query` dans un chunk `vendor` ;
- `build.chunkSizeWarningLimit` laissé au défaut : un dépassement est un signal,
  pas une nuisance à museler.

## 4. Docker

- `backend/Dockerfile` **multi-étapes** : étape `builder` avec uv qui produit
  `/app/.venv`, étape finale `python:3.12-slim` qui copie l'environnement,
  utilisateur non-root, `HEALTHCHECK` sur `/api/v1/health/live`, variables par
  défaut en production (`TRAFFIC_DOCS_ENABLED=false`,
  `TRAFFIC_LOG_FORMAT=json`).
- `frontend/Dockerfile` : étape bun qui `bun run build`, puis image finale
  servie **par le backend** (`TRAFFIC_STATIC_DIR=/app/static`) — un seul
  origin en production, donc aucun CORS à ouvrir pour l'usage normal.
- `docker-compose.yml` : service `backend` (volumes `./data`, `./.weights`),
  service `frontend-build` en profil `build`. `deploy.resources` documenté pour
  le GPU (`--gpus all` en commentaire, car le compose GPU dépend de l'hôte).

## 5. Qualité — points d'entrée uniques

| Intention | Backend | Frontend |
|---|---|---|
| Lancer | `uv run uvicorn traffic_analysis.main:app --reload` | `bun run dev` |
| Tester | `uv run pytest` | `bun run test` |
| Typer | `uv run mypy src` | `bun run typecheck` |
| Linter | `uv run ruff check .` | `bun run lint` |
| Formater | `uv run ruff format .` | `bun run format` |

`.pre-commit-config.yaml` à la racine : ruff (check + format), mypy sur
`backend/src`, oxlint et `tsc -b` sur le frontend, `check-added-large-files`
(limite 5 Mo — c'est ce qui empêche un `.pt` d'entrer dans l'historique),
`end-of-file-fixer`, `check-merge-conflict`.

## 6. `.gitignore` — l'essentiel

```gitignore
# Python
.venv/            __pycache__/      *.py[cod]
.mypy_cache/      .ruff_cache/      .pytest_cache/
# Données et poids : JAMAIS dans git (voir prompt/11)
.weights/         *.pt              *.onnx            *.engine
data/             backend/data/     *.db              *.db-wal   *.db-shm
# Frontend
node_modules/     dist/             .vite/
# Divers
.env              .env.*            !.env.example
frontend/public/demo/*.mp4
```

> **Différence assumée avec l'ancienne version du projet** : les `.onnx`
> **étaient** committés (~700 Mo d'historique). Le nouveau projet ne committe
> aucun poids : ils sont téléchargés à la demande par le registre de modèles, et
> le modèle de plaques est récupéré par un script documenté
> (`backend/scripts/fetch_plate_model.py`) avec vérification de somme SHA-256.
