# 07 — Persistance : SQLite + SQLAlchemy 2.0 (async) + Alembic

## 1. Ce qui va en base, ce qui va sur disque

| Donnée | Où | Pourquoi |
|---|---|---|
| Job (métadonnées, statut, progression, config) | **Base** | Interrogeable, survit au redémarrage |
| Statistiques agrégées d'un job | **Base** (colonnes + JSON) | Historique et comparaison sans lire un gros fichier |
| Registre des véhicules, franchissements, entrées de zone | **Base** | Filtres, tri, export CSV, requêtes analytiques |
| **Timeline** (frames × pistes) | **Disque** : `data/jobs/<id>/result.json.gz` | 54 000 lignes × N pistes : c'est un blob de relecture, pas une donnée relationnelle |
| Vidéo déposée | **Disque** : `data/jobs/<id>/input.mp4` | Supprimée à la purge TTL |
| Presets de géométrie | **Base** | Petits, réutilisables |
| Runs de benchmark | **Base** | Comparaison dans le temps |

Règle : **la base est la source de vérité de l'état**, le fichier est la source
de vérité du détail de relecture. Un job dont le fichier a disparu est marqué
`result_missing` plutôt que de renvoyer un 500.

## 2. Moteur et session

```python
# core/db/engine.py
engine = create_async_engine(
    settings.database_url,           # sqlite+aiosqlite:///./data/traffic.db
    echo=settings.env == "development" and settings.log_level == "DEBUG",
    pool_pre_ping=True,
    connect_args={"timeout": 30},    # attente du verrou d'écriture SQLite
)

@event.listens_for(engine.sync_engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")     # lecteurs concurrents pendant une écriture
    cursor.execute("PRAGMA foreign_keys=ON")      # SQLite les ignore par défaut !
    cursor.execute("PRAGMA synchronous=NORMAL")   # WAL + NORMAL : bon compromis
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()
```

Trois pièges SQLite à ne pas répéter :
1. **`PRAGMA foreign_keys` est désactivé par défaut** : sans lui, les cascades ne
   s'appliquent pas et les orphelins s'accumulent silencieusement.
2. **Un seul écrivain à la fois.** WAL rend les lectures concurrentes possibles,
   mais deux écritures se sérialisent. Les écritures massives (des milliers de
   franchissements) passent donc par **une transaction unique en fin de job**,
   pas une par événement.
3. `sessionmaker(expire_on_commit=False)` : sans cela, lire un attribut après un
   commit déclenche un rechargement… qui, en async, lève `MissingGreenlet`.

```python
SessionFactory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session          # le commit est explicite, dans l'UoW ou le service
```

## 3. Modèle de données

```python
class Base(DeclarativeBase):
    pass

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=…, onupdate=…)
```

### `jobs`
| Colonne | Type | Notes |
|---|---|---|
| `id` | `str` (uuid4 hex) | PK |
| `status` | `str` | enum applicative, index |
| `model_id` | `str` | index |
| `file_name` | `str` | nom d'origine, **assaini** |
| `file_size_bytes` | `int` | |
| `config_json` | `JSON` | la `AnalysisRequestSchema` telle que reçue — rejouer une analyse à l'identique doit être possible |
| `progress`, `processed_frames`, `total_frames`, `processing_fps` | | |
| `error` | `str \| None` | message utilisateur, jamais une trace |
| `video_width/height/fps/frame_count/duration_ms` | | renseignés après `probe` |
| `stats_json` | `JSON \| None` | le bloc `stats` complet |
| `unique_vehicles`, `crossings_total`, `reid_hits` | `int` | **dénormalisés** pour trier l'historique sans ouvrir le JSON |
| `result_path` | `str \| None` | relatif à `DATA_DIR` |
| `started_at`, `finished_at` | `datetime \| None` | |
| `created_at`, `updated_at` | | |

### `job_vehicles` (le registre)
`id` PK, `job_id` FK cascade, `global_id`, `label`, `first_seen_ms`,
`last_seen_ms`, `reid_count`, `avg_speed_px_s`, `avg_speed_kmh`,
`best_plate_score`, `zones_visited_json`.
Index unique `(job_id, global_id)`, index `(job_id, label)`.

### `job_crossings`
`id` PK, `job_id` FK cascade, `line_id`, `global_id`, `track_id`, `label`,
`direction` (`+1/-1`), `timestamp_ms`, `frame_index`.
Index `(job_id, line_id)`, `(job_id, timestamp_ms)`.

### `job_zone_events`
`id` PK, `job_id` FK cascade, `zone_id`, `global_id`, `label`, `timestamp_ms`,
`frame_index`. Index `(job_id, zone_id)`.

### `geometry_presets`
`id` PK, `name` (unique), `description`, `source_width`, `source_height`,
`lines_json`, `zones_json`, `mask_outside_zones`, `created_at`, `updated_at`.
Les dimensions sont stockées parce qu'une géométrie n'a de sens que pour une
résolution donnée : le frontend propose une **mise à l'échelle** si la vidéo
courante a une autre taille, et le dit.

### `benchmark_runs` / `benchmark_entries`
`runs` : `id`, `status`, `device`, `ultralytics_version`, `frames`,
`image_hash`, `confidence`, `iou`, `created_at`, `finished_at`, `error`.
`entries` : `run_id` FK cascade, `model_id`, `tier`, `load_ms`,
`inference_median_ms`, `inference_p95_ms`, `preprocess_ms`, `postprocess_ms`,
`detections`, `released`, `error`.

## 4. Repositories et Unit of Work

```python
class JobRepository(Protocol):
    async def add(self, job: JobEntity) -> None
    async def get(self, job_id: str) -> JobEntity | None
    async def list(self, filters: JobFilters, page: LimitOffset) -> Page[JobEntity]
    async def update_progress(self, job_id: str, progress: Progress) -> None
    async def set_status(self, job_id: str, status: JobStatus, error: str | None = None) -> None
    async def save_result_aggregates(self, job_id: str, data: AnalysisResultData) -> None
    async def delete(self, job_id: str) -> None
```

- Les repositories rendent et acceptent des **entités de domaine/DTO**, jamais
  des modèles ORM : un modèle ORM qui remonte jusqu'à une route emporte une
  session et des chargements paresseux dans un contexte async où ils explosent.
- `save_result_aggregates` fait **une seule transaction** avec des inserts en
  lot (`session.execute(insert(JobCrossing), [dict, dict, …])`) : 5 000
  franchissements insérés un par un prennent des minutes en SQLite.
- **La progression n'écrit pas en base à chaque frame.** Elle vit en mémoire
  (`ProgressHub`) et n'est persistée qu'à intervalle (toutes les ~2 s) et aux
  transitions d'état. Sinon une analyse à 25 fps déclenche 25 écritures par
  seconde sur un moteur mono-écrivain.
- `UnitOfWork` : un `async with uow:` qui commit à la sortie normale, rollback
  sur exception, et expose les repositories. Le service ne commit jamais
  lui-même.

## 5. Alembic

- `alembic.ini` + `migrations/env.py` configurés en **async**
  (`connection.run_sync(context.run_migrations)`).
- `target_metadata = Base.metadata`, `compare_type=True`,
  `render_as_batch=True` — **indispensable** pour SQLite : il ne sait pas
  `ALTER COLUMN`, et sans le mode batch toute évolution de colonne échoue.
- Une migration = un changement, message impératif :
  `alembic revision --autogenerate -m "ajoute la table geometry_presets"`.
- **Migration relue à la main** systématiquement : l'autogénération manque les
  renommages (elle produit drop+create, donc une perte de données).
- `alembic upgrade head` est exécuté **au démarrage en développement** et
  **jamais automatiquement en production** (une commande de déploiement
  explicite, pour ne pas migrer trois répliques en parallèle).
- Un test de migration : `upgrade head` puis `downgrade base` sur une base
  temporaire — une migration non réversible doit être un choix conscient.

## 6. Rétention et purge

- `TRAFFIC_JOB_TTL_MINUTES` (défaut 1440) : une tâche de fond
  (`cleanup_loop`, réveil toutes les 60 s) supprime les jobs **terminaux** plus
  vieux que le TTL : lignes en base (cascade) **et** répertoire sur disque.
- La vidéo d'entrée peut être supprimée **plus tôt** que le résultat
  (`TRAFFIC_INPUT_TTL_MINUTES`, défaut 60) : c'est la donnée la plus lourde et la
  plus sensible, et elle n'est plus nécessaire une fois le résultat produit.
- La purge est **idempotente** et journalisée. Un fichier déjà absent n'est pas
  une erreur.
- `VACUUM` déclenché après une purge massive (> 100 jobs supprimés) : SQLite ne
  rend pas l'espace disque tout seul.
- Une route `DELETE /api/v1/jobs/{id}` fait la même chose à la demande.

## 7. Cohérence — les règles à ne pas contourner

1. **La base ne recalcule rien.** `crossings_total` est écrit depuis
   `Σ by_line.total` calculé par le domaine. On ne réimplémente pas le comptage
   en SQL : une seconde implémentation divergerait.
2. **Un job `done` est immuable.** Aucune route ne modifie ses agrégats. Relancer
   une analyse crée un **nouveau** job, ce qui rend les comparaisons possibles.
3. **Les événements sont ordonnés par `timestamp_ms`** à l'insertion : la
   relecture côté frontend fait une recherche par balayage croissant et suppose
   cet ordre.
4. **Aucune contrainte d'unicité sur `job_crossings`** : deux franchissements
   légitimes de la même identité sur la même ligne dans **deux sens** doivent
   coexister. La déduplication est une règle de domaine, déjà appliquée en amont
   — la reproduire en contrainte SQL casserait le cas de l'aller-retour.
5. Les dates sont **UTC et timezone-aware** (`datetime.now(UTC)`). SQLite stocke
   des chaînes : un mélange naïf/aware produit des comparaisons fausses.

## 8. Tests de persistance

- Base **SQLite en fichier temporaire** (pas `:memory:` : les connexions
  multiples d'un moteur async ne partagent pas une base mémoire), créée par une
  fixture, migrée avec Alembic, détruite après.
- Tests : création → progression → terminal ; agrégats insérés en lot et relus ;
  cascade de suppression (supprimer un job supprime ses véhicules) ; purge TTL ;
  pagination et filtres ; `foreign_keys` réellement actif (insérer un
  `job_crossings` orphelin doit échouer).
