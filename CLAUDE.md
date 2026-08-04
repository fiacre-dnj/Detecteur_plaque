# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **État : version du Lot 0.** Ce fichier décrit ce que le projet *doit* être,
> parce que le code n'existe pas encore. Il est réécrit au **Lot 13** pour
> documenter ce qui existe réellement. Tant que cet avertissement est là, la
> vérité est dans [`prompt/`](prompt/).

## `prompt/` est la spécification, pas de la documentation

Le dossier [`prompt/`](prompt/) (15 fichiers, à lire dans l'ordre depuis
[`prompt/README.md`](prompt/README.md)) **est** le cahier des charges. Quand il
écrit « obligatoire », « jamais » ou « exactement », il ne s'agit pas de style :
c'est une contrainte qui a coûté un bug dans une version antérieure de
l'application. [`prompt/13-PIEGES-CONNUS.md`](prompt/13-PIEGES-CONNUS.md) en tient
la liste (56 entrées) — **le relire avant de déboguer quoi que ce soit**.

Si une contrainte semble fausse : le dire avec la preuve, proposer l'alternative,
écrire une ADR. Ne jamais la contourner en silence.

Le plan d'exécution en 14 lots est
[`prompt/12-PLAN-EXECUTION.md`](prompt/12-PLAN-EXECUTION.md).

## Commandes

`uv` provisionne Python 3.12 lui-même : ne jamais invoquer un `python` du `PATH`
pour du code de ce projet.

```bash
# ── Backend (cd backend)
uv sync                          # ou: uv sync --extra gpu  sur machine NVIDIA
uv run uvicorn traffic_analysis.main:app --reload --port 8000
uv run pytest
uv run pytest tests/unit/counting/test_line_counter.py -k aller_retour   # un seul test
uv run pytest --cov=src --cov-report=term-missing
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "ajoute la table geometry_presets"
uv run python scripts/fetch_weights.py --tiers nano,medium,large,xlarge
uv run python scripts/fetch_plate_model.py

# ── Frontend (cd frontend)
bun install
bun run dev                      # proxy /api → 127.0.0.1:8000
bun run lint && bun run typecheck && bun run test && bun run build
bun test src/shared/lib/geometry.test.ts                                 # un seul fichier
bun test --watch

# ── Dépôt
uvx pre-commit run --all-files
```

## Architecture — la forme, et pourquoi elle est ainsi

### Backend : vertical par feature, hexagonal à l'intérieur

`backend/src/traffic_analysis/` contient `core/` (socle transverse, aucune
feature), `features/<nom>/` et `api/router.py`. Chaque feature porte son propre
`domain/` (pur), `application/` (ports + services), `infrastructure/`
(adaptateurs), `api/` (routes) et `tests/`.

Règle de dépendance, vérifiée par `backend/tests/test_architecture.py` :

```
api → application → domain
infrastructure → application (ports) → domain
core ← tout le monde ;  core → rien des features
feature A ↛ feature B   (sauf par un port explicite)
```

`features/*/domain/**` n'importe **jamais** `fastapi`, `sqlalchemy`,
`ultralytics` ni `cv2` (`numpy` est autorisé : un descripteur de
ré-identification est du calcul, pas de l'infrastructure). C'est ce qui permet à
la CI de tourner **sans GPU, sans poids et sans ultralytics**, en injectant un
`FakeEngine` — la décision qui rend tout le reste testable.

`features/counting/domain/` est le cœur : `geometry`, `models`, `line_counter`,
`zone_counter`, `reid`, `speed`, `tracking_session`. Sa spécification complète,
scénario de test par scénario de test, est
[`prompt/03-DOMAINE-COMPTAGE.md`](prompt/03-DOMAINE-COMPTAGE.md).

`features/models_registry/infrastructure/` est le **seul** endroit qui importe
`ultralytics`. C'est là que `Results`/`Boxes`/`xyxy` deviennent des
`TrackObservation` du domaine.

### Frontend : Feature-Sliced Design

`frontend/src/` : `app/` (câblage), `features/<capacité>/`, `entities/` (objets
métier partagés), `shared/` (socle). Aucun dossier `components/`, `hooks/` ou
`utils/` global — ce sont des sacs qui grossissent sans jamais se vider.

Règle de dépendance : `app → features → entities → shared`. Une feature
n'importe **jamais** une autre feature ; ce qui est commun descend dans
`entities/` ou `shared/`. Chaque feature expose un seul `index.ts`.

### Les deux côtés sont couplés par un contrat, pas par un build

Pas de monorepo tool. `frontend/src/shared/api/contracts.ts` est le miroir
**exact** des schémas pydantic ; une fixture JSON committée est parsée dans un
test typé, donc un renommage côté backend casse un test côté frontend. C'est
voulu.

## Invariants à ne jamais violer

Ces règles traversent tout le code. Chacune est un bug déjà payé.

1. **Le temps est du temps de scène.** Tout horodatage métier est
   `frame_index / fps × 1000`, jamais `time.time()`. Le seul usage légitime de
   l'horloge murale est la mesure de performance (FPS de traitement, durée d'un
   job). Introduire l'horloge murale dans un calcul métier casse les débits, les
   vitesses et les gates de ré-identification d'un coup.
2. **Les coordonnées sont en pixels de la vidéo source.** Jamais en pixels
   modèle, jamais en pixels CSS. Les conversions se font aux frontières
   (letterbox côté modèle, mise à l'échelle au dessin côté canvas).
3. **Un compteur affiché est dérivé, jamais accumulé en double.**
   `crossings == Σ by_line[*].total` et `total == positive + negative`. Deux
   compteurs indépendants finissent toujours par se contredire.
4. **On compte sous `identity_label`** (vote majoritaire de la galerie), jamais
   sous la lecture de la frame courante.
5. **Le badge ✓ dérive du tally**, jamais de la comptabilité interne d'une piste :
   un franchissement supprimé par le garde d'identité ne doit pas peindre ✓.
6. **La déduplication porte sur `(ligne, identité, sens)`**, pas sur la piste —
   une piste est détruite et recréée à chaque occlusion longue — et pas sur
   `(ligne, identité)`, sinon un aller-retour réel ne compte qu'une fois.
7. **`_release_lost` avant `_resolve_identities`.** Le tracker détruit une piste
   morte et crée sa remplaçante dans le *même* appel. Mesuré avec le mauvais
   ordre : 2 véhicules uniques et 0 ré-identification ; avec le bon : 1 et 1.
8. **La timeline stocke des `snapshot()`**, pris **après** la passe ANPR. La
   session mute la même instance de piste : stocker la référence vivante fait
   converger toutes les frames vers l'état final.
9. **Un bail (`lease`) par usage de modèle.** Deux `track()` simultanés sur la
   même instance partagent l'état de suivi et **mélangent deux vidéos** — des
   chiffres plausibles et complètement faux.
10. **Ne jamais déduire une caractéristique d'un modèle de son nom de fichier.**
    Le palier vit dans le catalogue.
11. **Tout ce qui touche OpenCV, PyTorch ou le disque en volume part dans un
    thread worker** (`anyio.to_thread.run_sync`). La boucle asyncio ne fait que
    du transport, de l'orchestration et de la base.
12. **Le code parle français à l'utilisateur, anglais au compilateur.**
    Identifiants et types en anglais ; docstrings, commentaires et copie
    d'interface en français.

## Décisions déjà prises — ne pas les rediscuter

1. **Analyse 100 % backend.** Aucune inférence navigateur, aucune dépendance
   `onnxruntime-web`, aucun mode local. Conséquence à énoncer dans l'UI : les
   images quittent la machine. Voir [ADR 0003](docs/adr/0003-analyse-100-pourcent-backend.md).
2. **Python 3.12 épinglé**, borne haute `<3.13` volontaire.
   Voir [ADR 0001](docs/adr/0001-python-312.md).
3. **Aucun poids dans git.** Voir [ADR 0002](docs/adr/0002-pas-de-poids-dans-git.md).
   Le dossier `yolo/` du dépôt contient des `.onnx` d'une version antérieure :
   **ils sont inutilisables** (un export ONNX ne porte pas le pipeline BoT-SORT +
   ReID + GMC dont `model.track()` a besoin) et ignorés par le code.
4. **`torch` en variante CPU par défaut**, `uv sync --extra gpu` sur machine
   NVIDIA. Voir [ADR 0005](docs/adr/0005-torch-cpu-par-defaut.md).
5. **Persistance SQLite + SQLAlchemy async + Alembic.** Jobs, agrégats,
   véhicules, événements et benchmarks survivent au redémarrage.
6. **`DESIGN.md` est la source de vérité des jetons visuels**, avec deux
   réconciliations arbitrées dans [ADR 0004](docs/adr/0004-systeme-de-design.md) :
   les valeurs de `DESIGN.md` remplacent le `bg-slate-950` de `prompt/09`, et
   l'accent vert est **strictement fonctionnel** — la couleur du canvas encode une
   donnée (ligne, zone, classe), donc le vert n'est jamais une couleur de classe.

## Pièges d'environnement de ce dépôt

- `uv` a été installé par winget et vit dans
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_*\`. S'il n'est pas
  trouvé, ajouter ce dossier au `PATH` du shell.
- Le Python du système est un **3.14.6** : il ne peut pas faire tourner ce
  backend. Toujours passer par `uv run`.
- **Aucun GPU sur cette machine.** `TRAFFIC_HALF=false`, et les mesures de
  benchmark sont des mesures CPU — à interpréter comme telles.
- Le frontend est passé de **pnpm à bun** : `bun.lock` est le lockfile committé.
- L'alias `@/*` doit être déclaré dans **trois** fichiers qui restent d'accord :
  `frontend/tsconfig.json` (le seul que `bun test` lit), `tsconfig.app.json`
  (pour `tsc -b`) et `vite.config.ts` (pour le bundler).
- La roue `ultralytics` embarque son propre paquet `tests` : les helpers vivent
  dans `backend/tests/support/`, importés en `from tests.support.engine import …`,
  et `conftest.py` ne contient que des fixtures.

## Git

Jamais de travail sur `main`. Une branche par lot, Conventional Commits avec
portée obligatoire, un commit qui compile et passe les tests même en
intermédiaire. Détails dans [CONTRIBUTING.md](CONTRIBUTING.md) et
[`prompt/11`](prompt/11-GIT-ET-CONVENTIONS.md).
