# CLAUDE.md

Guide pour Claude Code (claude.ai/code) dans ce dépôt.

> Ce fichier décrit **ce qui existe**. Les 14 lots sont écrits ; l'application
> compte des véhicules de bout en bout, en différé comme en direct.
> [`prompt/`](prompt/) reste la spécification normative — quand les deux
> divergent, ce fichier a raison sur l'état du code et `prompt/` sur ce qui était
> demandé.

## Ce que fait l'application

Détection, suivi, ré-identification et comptage de véhicules sur une vidéo ou un
flux caméra. Toute l'inférence est côté serveur ; le navigateur pilote, dessine la
géométrie de comptage et rejoue le résultat.

Deux modes partagent **le même** code de comptage — la même `AnalysisSession`, les
mêmes schémas de requête, les mêmes sérialiseurs — et c'est ce qui garantit qu'un
même tracé donne les mêmes chiffres dans les deux :

- **différé** : dépôt d'un fichier, analyse asynchrone suivie en SSE, résultat
  complet relu et rejoué sur la vidéo locale. Le flux SSE porte aussi un
  **aperçu** échantillonné (`event: preview`, ~5 Hz) : la vidéo locale se cale
  sur l'image analysée et le navigateur y dessine les boîtes, les compteurs et
  les franchissements du serveur **pendant** l'analyse
  ([ADR 0006](docs/adr/0006-apercu-live-des-analyses.md)) ;
- **direct** : frames JPEG sur WebSocket, une image en vol à la fois.

## `prompt/` est la spécification, pas de la documentation

Le dossier [`prompt/`](prompt/) (15 fichiers, à lire dans l'ordre depuis
[`prompt/README.md`](prompt/README.md)) **est** le cahier des charges. Quand il
écrit « obligatoire », « jamais » ou « exactement », c'est une contrainte qui a
coûté un bug dans une version antérieure.
[`prompt/13-PIEGES-CONNUS.md`](prompt/13-PIEGES-CONNUS.md) en tient la liste (56
entrées) — **le relire avant de déboguer quoi que ce soit**.

Si une contrainte semble fausse : le dire avec la preuve, proposer l'alternative,
écrire une ADR. Ne jamais la contourner en silence.

## Commandes

`uv` provisionne Python 3.12 lui-même : ne jamais invoquer un `python` du `PATH`
pour du code de ce projet.

```bash
# ── Tout servir (backend + interface, un seul origin)
docker compose up                # http://localhost:8000

# ── Backend (cd backend)
uv sync
uv run uvicorn traffic_analysis.main:app --reload --port 8000
uv run pytest                                                            # 860 tests
uv run pytest tests/unit/counting/test_line_counter.py -k aller_retour   # un seul
uv run pytest --cov=src --cov-report=term-missing
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "ajoute la table X"
uv run python scripts/fetch_weights.py --tiers nano,medium,large,xlarge
uv run python scripts/fetch_plate_model.py

# ── Frontend (cd frontend)
bun install
bun run dev                      # proxy /api → 127.0.0.1:8000, WebSocket compris
bun run lint && bun run typecheck && bun test && bun run build           # 372 tests
bun test src/features/realtime-counting/model/scale.test.ts              # un seul

# ── Dépôt
uvx pre-commit run --all-files
```

**Il n'y a pas d'extra `gpu`.** `pyproject.toml` déclare
`[tool.uv] torch-backend = "auto"` : `uv sync` prend la roue CPU ici et la roue
CUDA sur une machine NVIDIA. Pour forcer : `UV_TORCH_BACKEND=cpu uv sync`.

## Architecture

### Backend — vertical par feature, hexagonal à l'intérieur

`backend/src/traffic_analysis/` : `core/` (socle transverse, aucune feature),
`features/<nom>/` et `api/router.py`. Sept features : `counting`, `jobs`,
`models_registry`, `realtime`, `benchmark`, `presets`, `health`. Chacune porte son
`domain/` (pur), `application/` (ports + services), `infrastructure/`
(adaptateurs) et `api/` (routes).

Règle de dépendance, **outillée** par `backend/tests/test_architecture.py` — il a
rejeté du code trois fois pendant l'écriture des lots 7 et 8, et il avait raison à
chaque fois :

```
api → application → domain
infrastructure → application (ports) → domain
core ← tout le monde ;  core → rien des features
feature A → feature B  UNIQUEMENT par son `application`
```

`features/*/domain/**` n'importe jamais `fastapi`, `sqlalchemy`, `ultralytics`,
`cv2` ni `pydantic` (`numpy` est autorisé : un descripteur de ré-identification
est du calcul). C'est ce qui permet à la CI de tourner **sans GPU, sans poids et
sans ultralytics**, en injectant un `FakeEngine`.

Cette architecture a un prix, payé deux fois : un bug de chemin de configuration
du tracker et une erreur d'encodage multipart ont traversé 500 tests verts, parce
que le moteur factice ne les atteint jamais. **Vérifier contre le vrai serveur
avant de déclarer une fonctionnalité terminée.**

`features/counting/domain/` est le cœur : `geometry`, `models`, `line_counter`,
`zone_counter`, `reid`, `speed`, `tracking_session`. Sa spécification est
[`prompt/03-DOMAINE-COMPTAGE.md`](prompt/03-DOMAINE-COMPTAGE.md).

`features/models_registry/infrastructure/` est le **seul** endroit qui importe
`ultralytics`.

`counting/application/dto.py` et `request_schema.py` sont le contrat publié de la
feature `counting` : `jobs`, `realtime` et `benchmark` importent de là, jamais du
domaine.

### Frontend — Feature-Sliced Design

`frontend/src/` : `app/` (câblage), `features/<capacité>/` (13), `entities/`,
`shared/`. Aucun dossier `components/`, `hooks/` ou `utils/` global.

```
app → features → entities → shared
```

Une feature n'importe **jamais** une autre feature. Quand deux en ont besoin, le
câblage passe par `StudioPage` — c'est pourquoi `GeometryPanel` reçoit un
`onOpenPresets` plutôt que la modale elle-même.

### Le contrat, pas un build

Pas de monorepo tool. `frontend/src/shared/api/contracts.ts` est le miroir
**exact** des schémas pydantic ; une fixture JSON committée est parsée dans un
test typé, donc un renommage côté backend casse un test côté frontend.

### Livraison

Une seule image (`backend/Dockerfile`, trois étapes) sert le backend **et** le
build du frontend, sur un seul origin. Cela supprime le CORS à ouvrir, le
tamponnage SSE du proxy et le relais WebSocket — les trois pannes de déploiement
habituelles. Un **seul worker** uvicorn : l'état en mémoire (`ProgressHub`, baux
de modèles, compteur de sessions) n'est pas partagé entre processus.

## Invariants à ne jamais violer

Chacun est un bug déjà payé.

1. **Le temps est du temps de scène.** Tout horodatage métier est
   `frame_index / fps × 1000`, jamais `time.time()`. Le seul usage légitime de
   l'horloge murale est la mesure de performance. En direct, le client compte
   depuis le début de session — un flux caméra n'a pas d'index de frame.
2. **Les coordonnées sont en pixels de la vidéo source.** Jamais en pixels
   modèle, jamais en pixels CSS. Les conversions se font aux frontières.
3. **Un compteur affiché est dérivé, jamais accumulé en double.**
   `crossings == Σ by_line[*].total` et `total == positive + negative`.
4. **On compte sous `identity_label`** (vote majoritaire de la galerie), jamais
   sous la lecture de la frame courante.
5. **Le badge ✓ dérive du tally**, jamais de la comptabilité interne d'une piste.
6. **La déduplication porte sur `(ligne, identité, sens)`** — pas sur la piste,
   détruite à chaque occlusion longue, et pas sur `(ligne, identité)`, sinon un
   aller-retour réel ne compte qu'une fois.
7. **`_release_lost` avant `_resolve_identities`.** Mesuré avec le mauvais ordre :
   2 véhicules uniques et 0 ré-identification ; avec le bon : 1 et 1.
8. **La timeline stocke des `snapshot()`**, pris **après** la passe ANPR.
9. **Un bail (`lease`) par usage de modèle.** Deux `track()` simultanés sur la
   même instance mélangent deux vidéos — des chiffres plausibles et faux.
10. **Ne jamais déduire une caractéristique d'un modèle de son nom de fichier.**
11. **Tout ce qui touche OpenCV, PyTorch ou le disque en volume part dans un
    thread worker** (`anyio.to_thread.run_sync`).
12. **Le code parle français à l'utilisateur, anglais au compilateur.**
    Identifiants et types en anglais ; docstrings, commentaires et copie
    d'interface en français.

### Les deux pannes silencieuses

Elles méritent leur propre section parce qu'elles ne lèvent **rien** : pas
d'exception, pas de journal, et des chiffres qui restent plausibles.

13. **La géométrie du direct est mise à l'échelle d'envoi.** Le client réduit ses
    frames à 960 px ; une ligne tracée sur du 1280 px appliquée à une image de 960
    est comptée **25 % à côté**. Le serveur ne peut pas le détecter — il ne connaît
    pas la résolution que le client croit envoyer — donc il renvoie les dimensions
    reçues, et le client compare et **refuse de compter** en cas d'écart.
    `pixelsPerMeter` est mis à l'échelle lui aussi : c'est un rapport pixels/mètre.
    Voir `frontend/src/features/realtime-counting/model/scale.ts`.
14. **L'aperçu d'un job porte les dimensions décodées par le serveur.** Le client
    les compare à celles de sa balise `<video>` et **suspend le dessin** en cas de
    désaccord — SAR non carré, rotation portée par les métadonnées. Le serveur ne
    peut pas détecter cet écart : il ne sait pas ce que le navigateur affiche. Des
    boîtes décalées se lisent comme un défaut de détection, jamais comme un défaut
    de repère.
15. **Un preset porte la résolution pour laquelle il a été tracé.** Le serveur le
    convertit à la lecture et **l'annonce** par `scaled`. Une conversion
    silencieuse serait pire que pas de conversion : une géométrie qui bouge sans
    prévenir se lit comme un bug.

## Décisions déjà prises — ne pas les rediscuter

1. **Analyse 100 % backend.** Aucune inférence navigateur.
   [ADR 0003](docs/adr/0003-analyse-100-pourcent-backend.md).
2. **Python 3.12 épinglé**, borne haute `<3.13`.
   [ADR 0001](docs/adr/0001-python-312.md).
3. **Aucun poids dans git.** [ADR 0002](docs/adr/0002-pas-de-poids-dans-git.md).
   Le dossier `yolo/` contient des `.onnx` d'une version antérieure :
   **inutilisables** (un export ONNX ne porte pas le pipeline BoT-SORT + ReID +
   GMC) et ignorés par le code.
4. **`torch` en variante automatique** selon le matériel, pas d'extra.
   [ADR 0005](docs/adr/0005-torch-cpu-par-defaut.md).
5. **Persistance SQLite + SQLAlchemy async + Alembic.** Sept tables. La timeline
   complète, elle, part dans un `json.gz` sur disque : plusieurs centaines de Mo
   n'ont rien à faire dans une base mono-écrivain que personne ne requête.
6. **`DESIGN.md` est la source de vérité des jetons visuels**, avec deux
   arbitrages dans [ADR 0004](docs/adr/0004-systeme-de-design.md) : les valeurs de
   `DESIGN.md` remplacent le `bg-slate-950` de `prompt/09`, et l'accent vert est
   **strictement fonctionnel** — la couleur du canvas encode une donnée, donc le
   vert n'est jamais une couleur de classe.

## Pièges d'environnement de cette machine

- `uv` a été installé par winget et vit dans
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_*\`. **Il n'est pas sur le
  `PATH` du shell Bash ni de PowerShell** : les hooks pre-commit qui appellent
  `uv run` échouent alors avec « Executable `uv` not found ». Ajouter ce dossier au
  `PATH` avant de committer.
- Le Python du système est un **3.14** : il ne peut pas faire tourner ce backend.
  Toujours passer par `uv run`.
- **Aucun GPU.** `TRAFFIC_HALF=false`, et les mesures de benchmark sont des mesures
  CPU — à interpréter comme telles.
- Le frontend est passé de pnpm à **bun** ; `bun.lock` est le lockfile committé.
  La version est épinglée en **trois** endroits qui doivent rester d'accord :
  `frontend/package.json` (`packageManager`), l'image `oven/bun` des deux
  Dockerfiles, et `bun-version` dans la CI.
- L'alias `@/*` est déclaré dans **trois** fichiers : `frontend/tsconfig.json` (le
  seul que `bun test` lit), `tsconfig.app.json` (pour `tsc -b`) et
  `vite.config.ts`.
- La roue `ultralytics` embarque son propre paquet `tests` : les helpers vivent
  dans `backend/tests/support/`, importés en `from tests.support.engine import …`,
  et `conftest.py` ne contient que des fixtures.
- Le hook `mixed-line-ending` **corrige** les fins de ligne au premier passage et
  fait donc échouer le premier `git commit` : ré-ajouter et recommitter.
- Le disque `C:` de cette machine est régulièrement **plein**, ce qui fait échouer
  les builds Docker avec une erreur d'entrée/sortie de BuildKit qui ne mentionne
  jamais l'espace disque. Vérifier `df -h` avant de conclure à un défaut du
  `Dockerfile`.

## Tests

| | Backend | Frontend |
|---|---|---|
| Nombre | 859 (1 skip) | 372 |
| Lanceur | pytest, `asyncio_mode = "auto"` | `bun test` (**pas** vitest) |
| Isolation | base SQLite sous `tmp_path`, moteur factice | — |

`filterwarnings = ["error", …]` : un avertissement fait échouer la suite.

**Ne jamais borner l'attente d'un test par un nombre d'itérations.** Des tests de
benchmark passaient nus et échouaient sous `--cov` pour cette raison : un test dont
le verdict dépend de la vitesse de la machine ne prouve rien. Attendre la tâche
réelle (`await service.wait_for_idle()`), ou une échéance en temps.

## Git

Jamais de travail sur `main`. Une branche par lot, Conventional Commits avec
portée obligatoire, un commit qui compile et passe les tests même en
intermédiaire. Détails dans [CONTRIBUTING.md](CONTRIBUTING.md) et
[`prompt/11`](prompt/11-GIT-ET-CONVENTIONS.md).
