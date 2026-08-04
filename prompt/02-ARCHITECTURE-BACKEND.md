# 02 — Architecture backend : par feature, hexagonale à l'intérieur

## 1. Le principe en une phrase

**Découpage vertical par feature** (une feature = un dossier autonome qui
contient son domaine, son application, son infrastructure et son transport), et
**découpage horizontal hexagonal à l'intérieur de chaque feature** (domaine pur
au centre, ports en Protocol, adaptateurs en périphérie).

Pourquoi les deux : un découpage purement horizontal (`domain/`, `services/`,
`repositories/` globaux) fait grossir quatre dossiers en parallèle et rend une
feature impossible à lire ou supprimer d'un bloc. Un découpage purement vertical
sans hexagone ré-introduit `ultralytics` et `SQLAlchemy` au milieu de la logique
de comptage, et la CI redevient dépendante d'un GPU.

## 2. Arborescence

```
backend/
├── pyproject.toml
├── .python-version
├── alembic.ini
├── migrations/                       # Alembic
├── config/
│   └── botsort_reid.yaml             # tracker Ultralytics (with_reid: true)
├── scripts/
│   └── fetch_plate_model.py
├── src/traffic_analysis/
│   ├── main.py                       # point d'entrée uvicorn (app = create_app())
│   ├── app_factory.py                # create_app(settings, overrides…)
│   ├── container.py                  # composition racine (DI)
│   │
│   ├── core/                         # socle transverse — AUCUNE feature ici
│   │   ├── settings.py               # Settings (pydantic-settings), get_settings()
│   │   ├── logging.py                # structlog + dictConfig, request_id
│   │   ├── errors.py                 # AppError et sa hiérarchie + Problem Details
│   │   ├── middleware/
│   │   │   ├── request_id.py
│   │   │   ├── security_headers.py
│   │   │   ├── body_size_limit.py
│   │   │   └── access_log.py
│   │   ├── openapi.py                # personnalisation OpenAPI (voir prompt/06)
│   │   ├── pagination.py             # Page[T], LimitOffsetParams
│   │   ├── schemas.py                # CamelModel, ProblemDetails, HealthSchema
│   │   ├── clock.py                  # Clock protocol + SystemClock (testabilité)
│   │   └── db/
│   │       ├── engine.py             # create_async_engine, PRAGMA WAL
│   │       ├── session.py            # async_sessionmaker, get_session (Depends)
│   │       ├── base.py               # DeclarativeBase, mixins timestamps
│   │       └── unit_of_work.py       # UnitOfWork (async context manager)
│   │
│   ├── features/
│   │   ├── counting/                 # LE cœur métier
│   │   │   ├── domain/               # pur : ni FastAPI, ni ultralytics, ni SQLAlchemy
│   │   │   │   ├── geometry.py
│   │   │   │   ├── models.py
│   │   │   │   ├── tracking_session.py
│   │   │   │   ├── line_counter.py
│   │   │   │   ├── zone_counter.py
│   │   │   │   ├── reid.py
│   │   │   │   └── speed.py
│   │   │   ├── application/
│   │   │   │   ├── ports.py          # DetectionTrackingEngine, PlateDetector, TrackingStream
│   │   │   │   ├── dto.py            # AnalysisJobConfig, AnalysisResultData, Progress
│   │   │   │   ├── analysis_service.py
│   │   │   │   └── serializers.py    # domaine → dict camelCase du fil
│   │   │   ├── infrastructure/
│   │   │   │   └── (rien : les adaptateurs vision vivent dans la feature models)
│   │   │   └── tests/
│   │   ├── jobs/                     # cycle de vie d'une analyse différée
│   │   │   ├── domain/               # JobStatus, machine à états, JobRecord
│   │   │   ├── application/          # JobManager, JobRepository (port), ProgressHub
│   │   │   ├── infrastructure/       # SqlAlchemyJobRepository, ResultStore (json.gz)
│   │   │   ├── api/                  # routes_jobs.py, routes_job_events.py, schemas.py
│   │   │   └── tests/
│   │   ├── models_registry/          # catalogue, poids, LRU, ANPR, moteur ultralytics
│   │   │   ├── domain/               # ModelDescriptor, catalogue, ModelTier
│   │   │   ├── application/          # ModelService (lease, warmup, catalogue+état)
│   │   │   ├── infrastructure/       # ModelRegistry, UltralyticsEngine, OnnxPlateDetector, WeightsDownloader
│   │   │   ├── api/                  # routes_models.py
│   │   │   └── tests/
│   │   ├── benchmark/                # mesure des modèles côté serveur
│   │   │   ├── domain/ application/ infrastructure/ api/ tests/
│   │   ├── realtime/                 # WebSocket webcam
│   │   │   ├── application/          # RealtimeSessionService
│   │   │   ├── api/                  # routes_realtime.py, protocol.py
│   │   │   └── tests/
│   │   ├── presets/                  # géométries enregistrées
│   │   │   ├── domain/ application/ infrastructure/ api/ tests/
│   │   └── health/
│   │       └── api/routes_health.py
│   │
│   └── api/
│       └── router.py                 # APIRouter racine /api/v1 qui monte les features
└── tests/
    ├── conftest.py                   # fixtures d'application (app, client, db)
    ├── support/                      # FakeEngine, FakePlateDetector, builders
    └── e2e/                          # scénarios bout en bout (job complet)
```

### Règle de dépendance (à vérifier en CI)
```
api → application → domain
infrastructure → application (ports) → domain
core ← tout le monde ;  core → rien des features
feature A ↛ feature B   (sauf par un port explicite, jamais par import direct)
```
Outiller la règle : un test `tests/test_architecture.py` qui parcourt les
modules avec `ast` et échoue si `features/*/domain/**` importe `fastapi`,
`sqlalchemy`, `ultralytics`, `cv2` (numpy est autorisé dans le domaine : les
descripteurs de ré-identification sont du calcul, pas de l'infrastructure).

## 3. Les patterns imposés, et pourquoi

| Pattern | Où | Ce qu'il achète |
|---|---|---|
| **Ports & Adapters** (`typing.Protocol`) | `features/*/application/ports.py` | La CI n'a besoin ni de GPU, ni de poids, ni d'ultralytics : les tests injectent un `FakeEngine`. C'est la décision qui rend le domaine testable |
| **Application Service** | `analysis_service.py` | Un seul module connaît l'*ordre* du pipeline. Le domaine ignore d'où viennent les frames, le moteur ignore ce qu'on en compte |
| **Repository** + **Unit of Work** | `jobs`, `presets`, `benchmark` | La persistance est remplaçable (SQLite → Postgres) sans toucher aux routes. L'UoW garantit qu'un job et ses agrégats sont écrits ou rien |
| **Registry + cache LRU** | `models_registry` | Un modèle résident coûte des centaines de Mo ; le plafond et l'éviction sont une règle métier, pas un détail |
| **Lease** (context manager) | `ModelRegistry.lease()` | Deux `track()` simultanés sur la **même** instance partagent l'état de suivi et **mélangent deux vidéos**. Le bail réserve l'instance pour la durée d'un run |
| **Machine à états explicite** | `jobs/domain/status.py` | `queued → running → done \| error \| cancelled`, transitions validées. Un statut qui saute une étape lève, au lieu de produire un résultat incohérent |
| **Observer / pub-sub** | `ProgressHub` | Diffusion de la progression à N abonnés SSE sans que le service d'analyse connaisse le transport |
| **DTO + Mapper** | `dto.py`, `serializers.py`, `schemas.py` | Le domaine n'est jamais sérialisé directement : un renommage de champ métier ne casse pas le contrat HTTP, et inversement |
| **Factory** | `create_app()` | Les tests construisent une application isolée avec moteur factice ; la production laisse la factory assembler le vrai |
| **Strategy** | `DetectionTrackingEngine` | Ultralytics aujourd'hui, un autre moteur demain, sans toucher au comptage |
| **Clock injectable** | `core/clock.py` | Un test qui dépend de `time.time()` est un test instable |

Patterns **interdits** ici : Singleton global mutable (l'état vit dans le
conteneur, pas dans un module), Service Locator (on injecte, on ne cherche pas),
héritage profond (composition), `BaseService` générique abstrait (une classe
mère sans comportement partagé réel ne fait que masquer le graphe d'appel).

## 4. Injection de dépendances

Un **conteneur de composition** explicite, construit une fois au démarrage :

```python
# container.py
@dataclass(slots=True)
class Container:
    settings: Settings
    engine_factory: Callable[[], DetectionTrackingEngine]
    plate_detector: PlateDetector | None
    model_service: ModelService
    job_manager: JobManager
    benchmark_service: BenchmarkService
    session_factory: async_sessionmaker[AsyncSession]

def build_container(settings: Settings, **overrides: object) -> Container: ...
```

- Le conteneur est posé sur `app.state.container` par `create_app()`.
- Les routes ne lisent **jamais** `app.state` directement : elles passent par
  des dépendances typées, `Annotated[JobManager, Depends(get_job_manager)]`,
  déclarées dans `core/deps.py`. Une route testable est une route dont on peut
  remplacer les dépendances avec `app.dependency_overrides`.
- Une session de base de données par requête, fournie par
  `Depends(get_session)`, jamais créée dans un service.

```python
JobManagerDep = Annotated[JobManager, Depends(get_job_manager)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
```

## 5. Asynchrone et travail bloquant — la règle qui évite le gel

L'inférence est **bloquante et longue** (secondes à minutes). Une seule règle :

> Tout ce qui touche à OpenCV, à PyTorch ou au disque en volume s'exécute dans
> un thread worker via `anyio.to_thread.run_sync`. La boucle asyncio ne fait que
> du transport, de l'orchestration et de la base.

Corollaires :
- Le callback de progression est appelé **depuis le thread worker** : il ne
  touche l'état partagé qu'en repassant par la boucle
  (`loop.call_soon_threadsafe`). Un état muté depuis deux threads est un bug qui
  ne se reproduit qu'en charge.
- L'annulation d'un job passe par un `threading.Event` lu par le worker à chaque
  frame (`is_cancelled()`), pas par `task.cancel()` : on n'annule pas un
  `track()` en cours, on lui demande de s'arrêter proprement.
- Les tâches de fond (`cleanup_loop`, préchauffage) sont créées dans le
  `lifespan` **et gardées dans un `set`** : une tâche asyncio sans référence
  forte peut être ramassée par le GC en pleine exécution.
- `max_concurrent_jobs` est un `asyncio.Semaphore` : un GPU = une analyse à la
  fois, les suivantes attendent en file. Le job est accepté (202) même si
  l'exécution attend — l'utilisateur doit voir « en file d'attente », pas un 503.

## 6. Erreurs et journalisation

### Hiérarchie
```python
class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"          # stable, machine-readable
    detail: str                            # message français, lisible

class NotFoundError(AppError):      status_code = 404; code = "not_found"
class ConflictError(AppError):      status_code = 409; code = "conflict"
class ValidationAppError(AppError):  status_code = 422; code = "validation_error"
class PayloadTooLargeError(AppError): status_code = 413; code = "payload_too_large"
class UnavailableError(AppError):   status_code = 503; code = "unavailable"
class UnknownModelError(NotFoundError): code = "unknown_model"
class JobNotFoundError(NotFoundError):  code = "job_not_found"
```

Un unique `exception_handler(AppError)` les traduit en **Problem Details
(RFC 9457)** : `{ "type", "title", "status", "detail", "code", "instance",
"requestId" }`, `Content-Type: application/problem+json`. Un handler
`RequestValidationError` fait de même en ajoutant `errors[]`. Un handler
`Exception` journalise la trace complète et rend un 500 **sans fuite** de
message interne.

Interdits : `raise HTTPException` dans une couche application ou domaine (le
domaine ne connaît pas HTTP) ; `except Exception: pass` ; un `print`.

### Journalisation
`structlog`, sortie console en dev, **JSON en production**. Chaque log porte
`request_id` (middleware, en-tête `X-Request-ID` accepté en entrée et renvoyé),
et pour les analyses `job_id` et `model_id`. Journaliser : début/fin de job avec
durée et FPS, chargement et éviction de modèle, session temps réel
ouverte/fermée, toute exception. Ne **jamais** journaliser le contenu d'une
frame ni un chemin d'upload complet en production.

## 7. Conventions Python senior

- `from __future__ import annotations` en tête de chaque module.
- **Dataclasses `frozen=True, slots=True`** pour les objets de domaine
  immuables ; `slots=True` seul pour l'état vivant. Le gain n'est pas
  cosmétique : une timeline de 54 000 frames × N pistes rend l'empreinte
  mémoire visible.
- Typage complet, `mypy --strict` sur `src`. La seule tolérance est
  `infrastructure/*` (bibliothèques non typées) : `disallow_untyped_calls =
  false`, `warn_return_any = false`. Le domaine et l'application restent
  strictement typés — c'est là qu'est la logique.
- **Aucun `Any` qui traverse une frontière** : un adaptateur peut recevoir
  `Any` d'ultralytics, il rend un type du domaine.
- Nommage : modules et fonctions `snake_case`, classes `PascalCase`, constantes
  `UPPER_SNAKE`, privé préfixé `_`. Les noms sont en anglais ; les docstrings et
  commentaires en **français**.
- Une fonction fait une chose ; au-delà de ~40 lignes ou de 3 niveaux
  d'imbrication, extraire. Les fonctions du domaine sont **pures** dès que c'est
  possible (entrée → sortie, pas d'effet de bord, pas d'horloge implicite).
- Docstring **utile** : elle dit *pourquoi*, pas *quoi*. « Compte les
  franchissements » n'apporte rien ; « le côté est mis à jour même sur rejet,
  sinon la piste regarde dans le mauvais sens et le franchissement suivant
  compte à l'envers » est ce qu'on veut lire.
- `ruff` avec `select = ["E","F","I","UP","B","SIM","C4","RUF","ANN","ASYNC","S","T20","PTH","RET","ARG"]`,
  `line-length = 100`, et `ignore = ["RUF001","RUF002","RUF003"]` (les
  apostrophes typographiques et les guillemets « » du français sont du texte
  voulu, pas des homoglyphes accidentels).
- `S` (bandit) activé : il attrape `assert` en production, les chemins
  temporaires prévisibles, `subprocess` sans liste d'arguments. Les `assert` des
  tests sont exclus via `per-file-ignores`.

## 8. Points d'extension à laisser prêts (documentés, pas implémentés)

1. **Authentification** : la factory doit accepter une liste de dépendances
   globales (`dependencies=[Depends(verify_api_key)]` commenté), et le schéma de
   sécurité OpenAPI est déjà déclaré (voir [`06`](06-SECURITE-CORS-SWAGGER.md)).
2. **File externe** : `JobManager` dépend d'un port `JobQueue`. L'implémentation
   asyncio actuelle est une des deux possibles ; Redis/RQ viendrait sans toucher
   aux routes.
3. **Postgres** : aucun SQL brut spécifique à SQLite hors du `PRAGMA` de
   `engine.py`, aucun type SQLite-only. Migrer = changer l'URL et régénérer les
   migrations.
4. **OCR de plaque** : `PlateDetector` rend des boîtes ; un port
   `PlateReader` (image + boîte → texte + score) est déclaré et non implémenté.
5. **RTSP / multi-caméra** : `TrackingStream` est déjà l'abstraction correcte.
