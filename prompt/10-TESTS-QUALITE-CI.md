# 10 — Tests, qualité, intégration continue

## 1. Doctrine

> **La CI ne doit avoir besoin ni de GPU, ni de poids de modèle, ni
> d'ultralytics.** C'est la contrainte qui dicte l'architecture : le domaine est
> pur, les moteurs sont derrière des ports, et les tests injectent un
> `FakeEngine`. Si un test a besoin de télécharger 40 Mo, il est mal conçu.

Pyramide visée :
- **~70 % unitaires** : domaine (comptage, zones, ré-identification, vitesse,
  géométrie), fonctions pures du frontend.
- **~25 % intégration** : routes FastAPI avec moteur factice, persistance sur
  SQLite temporaire, SSE, WebSocket.
- **~5 % bout en bout** : un job complet du dépôt au résultat, sur une vidéo
  synthétique de quelques frames générée par le test.

Pas de couverture-fétiche, mais un plancher : **90 % sur `features/*/domain`**,
**80 % sur `features/*/application`**, aucun seuil sur `infrastructure` (c'est de
l'adaptation, testée par les tests d'intégration et par l'usage).

## 2. Backend — organisation

```
backend/tests/
├── conftest.py            # fixtures d'app, de client, de base
├── support/
│   ├── engine.py          # FakeEngine, FakeStream, scénarios de pistes
│   ├── plates.py          # FakePlateDetector
│   ├── builders.py        # make_line(), make_zone(), track_path(...)
│   └── video.py           # génère un .mp4 minimal avec cv2.VideoWriter
├── unit/    (par feature : counting/, models_registry/, jobs/…)
├── integration/
└── e2e/
```

### Le piège du nom `tests`
La roue `ultralytics` **embarque son propre paquet `tests`**. Un
`from tests.conftest import …` résout donc vers *ses* fichiers, pas les nôtres.
Conséquence normative : **les helpers vivent dans `tests/support/`**, importés
en `from tests.support.engine import FakeEngine`, et `conftest.py` ne contient
que des fixtures. Ajouter `consider_namespace_packages = false` et
`testpaths = ["tests"]` dans la configuration pytest.

### `FakeEngine` — le cœur du dispositif

```python
class FakeEngine:                       # satisfait DetectionTrackingEngine
    def __init__(self, info: VideoInfo, frames: list[list[TrackObservation]]): ...
    def probe(self, path: Path) -> VideoInfo: return self._info
    def iter_video(self, path, spec) -> Iterator[EngineFrame]:
        for i, tracks in enumerate(self._frames):
            yield EngineFrame(i, i / self._info.fps * 1000,
                              np.zeros((h, w, 3), np.uint8), tracks)
    def open_stream(self, spec) -> FakeStream: ...
```

Un helper `track_path(track_id, class_id, points, *, score=0.9, box_size=(80,60))`
fabrique une trajectoire, ce qui rend les scénarios lisibles :

```python
frames = compose(
    track_path(1, 2, straight_line((100, 300), (100, 700), steps=20)),   # traverse
    track_path(2, 7, straight_line((900, 700), (900, 300), steps=20)),   # sens inverse
)
```

Les images sont des `np.zeros` : les tests du domaine ne dépendent d'aucun
pixel — **sauf** ceux de la ré-identification, qui construisent des crops de
couleurs contrôlées pour vérifier les similarités.

### Fixtures d'application

```python
@pytest.fixture
async def app(tmp_path, fake_engine) -> FastAPI:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path/'t.db'}",
        data_dir=tmp_path/"data", warmup=False, docs_enabled=True,
        env="test", max_upload_mb=5,
    )
    application = create_app(settings, engine=fake_engine, plate_detector=FakePlateDetector())
    await run_migrations(settings)          # Alembic, pas create_all
    return application

@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

`warmup=False` dans les tests : un préchauffage chargerait un vrai modèle.
Les migrations Alembic (pas `Base.metadata.create_all`) : ainsi une migration
cassée est **vue par les tests**, ce qui est la moitié de leur intérêt.

### Tests d'intégration obligatoires
1. `POST /jobs` → 202, statut visible, SSE qui émet `progress` puis `end`,
   `GET /result` qui rend un JSON conforme.
2. `GET /result` sur un job `running` ⇒ **409**.
3. Upload de 1 octet de trop ⇒ **413** et **job supprimé** (aucun résidu sur
   disque ni en base).
4. Fichier vide ⇒ 422. Fichier non-vidéo ⇒ 415.
5. `modelId` inconnu ⇒ 422 avec la liste des ids valides.
6. Ligne référençant une zone inexistante ⇒ 422.
7. `DELETE /jobs/{id}` sur un job en cours ⇒ statut `cancelled`, sur un job
   terminé ⇒ artefacts purgés.
8. WebSocket : `init` invalide ⇒ 1008 ; une frame ⇒ un `frameResult` ; deuxième
   session ⇒ 1013 ; `Origin` non autorisée ⇒ refus.
9. En-têtes de sécurité présents sur une réponse quelconque (test paramétré sur
   le tableau de [`06`](06-SECURITE-CORS-SWAGGER.md)).
10. Préflight CORS : origine autorisée ⇒ en-têtes attendus ; origine inconnue ⇒
    pas d'`Access-Control-Allow-Origin`.
11. `GET /api/openapi.json` : `operationId` uniques, `summary` partout, au moins
    une réponse d'erreur documentée par route.
12. SSE **non tamponné** : le premier événement arrive avant la fin du job.

### Test d'architecture
`tests/test_architecture.py` parcourt les modules en `ast` et échoue si
`features/*/domain/**` importe `fastapi`, `sqlalchemy`, `ultralytics` ou `cv2`,
ou si une feature importe une autre feature ailleurs que par son `index`/port.
C'est ce test qui empêche l'architecture de se dissoudre en six mois.

### Test de non-régression des invariants comptables
Un test paramétré qui, pour chaque scénario de `support`, vérifie :
`stats.crossings == Σ by_line[*].total`,
`by_line[l].total == positive + negative`,
`Σ unique_by_class.values() == unique_vehicles`,
`Σ by_line[*].by_class.values() == crossings`.
Ces quatre égalités sont le filet le plus rentable du projet.

## 3. Frontend

- `bun test` sur les modules purs (liste dans
  [`09`](09-FRONTEND-UX-FONCTIONNALITES.md#7-tests-frontend-attendus)).
- Les specs vivent **à côté** de ce qu'elles couvrent
  (`shared/lib/geometry.test.ts`).
- Une **fixture de contrat** : un vrai `result.json` réduit, committé, parsé dans
  un test typé. Quand le backend renomme un champ, ce test casse — c'est le seul
  garde-fou automatique du contrat entre les deux dépôts.
- `@testing-library/react` limité à trois composants (sélecteur de modèle,
  lecteur, frontière d'erreur).
- **Pas de tests de canvas** : ils testeraient l'implémentation de dessin sans
  rien garantir. Le canvas est vérifié en lançant l'application, et la logique
  qu'il utilise (hit-testing, conversions) est extraite en fonctions pures
  testées.

## 4. Vérifications manuelles à scripter dans le README

Certaines choses ne se testent pas automatiquement et doivent être vérifiées à
la main, avec une liste écrite :
1. Analyser un vrai clip et comparer le total à un comptage humain sur 30 s.
2. Déplacer une ligne après analyse ⇒ bandeau « résultat obsolète ».
3. Reculer dans la vidéo ⇒ les compteurs baissent.
4. Couper le backend en pleine analyse ⇒ message clair, pas de page blanche.
5. Passer caméra → fichier → caméra ⇒ chaque source se charge (le piège
   `srcObject`).
6. Lancer le benchmark ⇒ la mémoire du serveur revient à son niveau initial
   après le run.

## 5. CI (`.github/workflows/ci.yml`)

Trois jobs parallèles, `fail-fast: false` (voir les deux côtés d'un coup) :

```yaml
backend:
  steps: [checkout, setup-uv (cache), uv sync --frozen,
          uv run ruff check ., uv run ruff format --check .,
          uv run mypy src, uv run alembic upgrade head (base temporaire),
          uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=…]
frontend:
  steps: [checkout, setup-bun (cache), bun install --frozen-lockfile,
          bun run lint, bun run typecheck, bun run test, bun run build,
          vérification du budget de chunk]
quality:
  steps: [gitleaks, uv pip audit (warn), bun audit (warn),
          vérification qu'aucun *.pt/*.onnx/*.mp4 n'entre dans le diff]
```

Règles :
- Lockfiles **committés** (`uv.lock`, `bun.lock`) et CI en mode `--frozen` : une
  build reproductible ou rien.
- **Aucun téléchargement de poids en CI.** Un test qui essaie doit échouer
  bruyamment (le `FakeEngine` est là pour ça).
- La CI est **obligatoire** avant merge ; branche protégée.
- Durée cible < 5 min. Si elle dérive, c'est qu'un test fait quelque chose qu'il
  ne devrait pas.

## 6. Hooks pre-commit

`.pre-commit-config.yaml` : `ruff --fix`, `ruff format`, `mypy` (backend
uniquement), `oxlint`, `tsc -b`, `check-added-large-files --maxkb=5000`,
`end-of-file-fixer`, `trailing-whitespace`, `check-merge-conflict`,
`detect-private-key`.

**Ne jamais utiliser `--no-verify`.** Si un hook bloque, la bonne réaction est de
corriger la cause : un hook contourné une fois le sera toujours.
