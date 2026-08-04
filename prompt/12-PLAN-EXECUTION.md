# 12 — Plan d'exécution en 14 lots

Chaque lot : une branche, une définition de « terminé » vérifiable, un ou
plusieurs commits atomiques. **L'ordre est choisi pour que chaque lot soit
démontrable** : on ne construit pas six semaines d'abstractions avant de voir un
véhicule compté.

Convention de lecture : `DoD` = definition of done, à vérifier avant de fermer le
lot.

---

## Lot 0 — Socle du dépôt
**Branche** `chore/repo-socle`

- `README.md` (démarrage en 5 commandes), `.editorconfig`, `.gitattributes`,
  `.gitignore` (voir [`01`](01-STACK-ET-OUTILLAGE.md#6-gitignore--lessentiel)),
  `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE` (AGPL-3.0, à cause d'Ultralytics),
  `.pre-commit-config.yaml`, `docs/adr/0001-python-312.md`,
  `docs/adr/0002-pas-de-poids-dans-git.md`,
  `docs/adr/0003-analyse-100-pourcent-backend.md`.

**DoD** : `pre-commit run --all-files` passe sur un dépôt vide de code.

---

## Lot 1 — Squelette backend qui répond
**Branche** `feat/backend-socle`

`pyproject.toml`, `.python-version`, `core/settings.py`, `core/logging.py`,
`core/errors.py` + handlers Problem Details, `core/schemas.py` (CamelModel),
`app_factory.py`, `main.py`, `features/health`, routeur racine `/api/v1`.

**DoD** : `uv run uvicorn …` démarre ; `GET /api/v1/health/live` rend
`{"status":"ok"}` ; une erreur volontaire rend un `application/problem+json` ;
`mypy --strict` et `ruff` verts ; les logs portent un `requestId`.

**Commits** : `chore(backend): initialise le projet uv en python 3.12` →
`feat(backend/core): configuration, journalisation et erreurs Problem Details` →
`feat(backend/api): expose /api/v1/health`.

---

## Lot 2 — Le domaine du comptage, sans aucune vision
**Branche** `feat/backend-domaine-comptage`

Tout [`03`](03-DOMAINE-COMPTAGE.md) : `geometry`, `models`, `line_counter`,
`zone_counter`, `reid`, `speed`, `tracking_session`, et **les tests d'abord**
(les scénarios sont donnés, écris-les avant l'implémentation : ils sont la
spécification).

**DoD** : tous les scénarios des tableaux de [`03`](03-DOMAINE-COMPTAGE.md)
passent ; les quatre invariants comptables de
[`10`](10-TESTS-QUALITE-CI.md#test-de-non-régression-des-invariants-comptables)
sont vérifiés par un test paramétré ; couverture ≥ 90 % sur `domain` ; le test
d'architecture interdit déjà `fastapi`/`ultralytics` dans `domain`.

C'est **le lot le plus important du projet**. Ne pas le bâcler pour arriver plus
vite à l'écran.

---

## Lot 3 — Orchestration + moteur factice + jobs en mémoire
**Branche** `feat/backend-jobs`

`application/ports.py`, `dto.py`, `analysis_service.py`, `serializers.py` ;
`features/jobs` (machine à états, `JobManager`, `ProgressHub`, `ResultStore`
`json.gz`) ; routes `POST /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/result`,
`DELETE /jobs/{id}`, SSE `GET /jobs/{id}/events` ; `tests/support/engine.py`.

**DoD** : le test d'intégration « dépôt → SSE → résultat » passe avec le
`FakeEngine` ; 409 sur résultat prématuré ; 413 sur upload trop gros avec purge ;
annulation effective en cours d'analyse ; le SSE envoie l'état courant en
premier et n'est pas tamponné.

---

## Lot 4 — Persistance SQLite
**Branche** `feat/backend-persistance`

Tout [`07`](07-PERSISTANCE-SQLITE.md) : moteur + PRAGMA, modèles ORM,
repositories, UoW, Alembic (migration initiale), branchement du `JobManager` sur
le repository, `GET /jobs` paginé, `GET /jobs/{id}/vehicles|crossings`,
export CSV, purge TTL.

**DoD** : un job survit au redémarrage du serveur ; `upgrade head` puis
`downgrade base` fonctionne ; insertion en lot d'un job à 5 000 franchissements
< 1 s ; cascade de suppression vérifiée ; `PRAGMA foreign_keys` réellement actif
(test) ; CSV lisible dans Excel (BOM + `;`).

---

## Lot 5 — Modèles, registre, Ultralytics, ANPR
**Branche** `feat/backend-modeles`

Tout [`04`](04-MODELES-YOLO-ET-BENCHMARK.md) sauf le benchmark :
catalogue, `ModelRegistry` (bail, LRU, warmup, device, half),
`UltralyticsEngine` + `UltralyticsStream`, `config/botsort_reid.yaml`,
`OnnxPlateDetector`, `scripts/fetch_plate_model.py`, `GET /models`,
`POST /models/{id}/preload`, `DELETE /models/{id}/loaded`, `/health` complet.

**DoD** : une **vraie** analyse locale sur un clip court produit des compteurs
plausibles (vérification manuelle documentée) ; deux analyses successives sur
deux modèles différents n'évincent pas une instance occupée ; l'absence du
modèle de plaques ne casse pas le démarrage ; aucun import d'`ultralytics` hors
`infrastructure` (test d'architecture).

---

## Lot 6 — Sécurité, CORS, Swagger
**Branche** `feat/backend-securite-docs`

Tout [`06`](06-SECURITE-CORS-SWAGGER.md) : middlewares dans le bon ordre, CORS
paramétré, en-têtes de sécurité, limite de corps, rate limiting, OpenAPI
personnalisé (tags, `operationId`, exemples, schémas de sécurité prêts), docs
désactivables.

**DoD** : les tests de [`10`](10-TESTS-QUALITE-CI.md) §2 items 9 à 11 passent ;
`/api/docs` est lisible et chaque route y a un résumé et un exemple ;
`TRAFFIC_DOCS_ENABLED=false` rend 404 sur les trois URL de doc.

---

## Lot 7 — Temps réel WebSocket
**Branche** `feat/backend-temps-reel`

`features/realtime` : protocole de [`05`](05-API-ET-CONTRAT.md) §7,
vérification d'`Origin`, sémaphore de session, décodage JPEG et suivi en thread
worker, message `ready` avec les dimensions reçues.

**DoD** : tests d'intégration WebSocket (init invalide, une frame → un
`frameResult`, seconde session refusée, origine refusée) ; fermeture propre qui
rend le bail du modèle.

---

## Lot 8 — Benchmark serveur
**Branche** `feat/backend-benchmark`

`features/benchmark` : protocole de mesure de
[`04`](04-MODELES-YOLO-ET-BENCHMARK.md) §6, persistance des runs, SSE,
annulation, `GET /benchmark/latest`.

**DoD** : un run sur 2 modèles factices produit des entrées cohérentes ; la
libération après mesure est observable (`loaded_ids()` revient à son état
initial) ; un modèle en échec n'interrompt pas le run.

---

## Lot 9 — Squelette frontend
**Branche** `feat/frontend-socle`

`package.json`, configuration Vite (proxy `/api`, alias dans les **trois**
fichiers, react-compiler, Tailwind v4), `index.css` avec `@theme`, `AppShell`,
routeur avec **routes paresseuses**, providers (React Query), `shared/api`
(`httpClient` avec la garde `content-type`, `problemDetails`, `queryKeys`),
`shared/ui` (Button, Slider, Toggle, Section, MetricCard, Skeleton, EmptyState,
ErrorBoundary), badge d'état backend.

**DoD** : `bun run dev` affiche la coquille ; le badge dit correctement
« injoignable » quand le backend est arrêté ; `bun run build` produit un chunk
d'entrée < 200 ko gzip ; `lint`, `typecheck`, `test` verts.

---

## Lot 10 — Source, lecteur, éditeur de géométrie
**Branche** `feat/frontend-scene-geometrie`

`features/media-source`, `features/video-transport`,
`features/geometry-editor`, `entities/geometry` (types + reducer + signature),
`shared/lib/geometry.ts` + ses tests.

**DoD** : dépôt d'un fichier, lecture, vitesses, pas-à-pas ; tracé d'une zone
(double-clic **et** clic sur le premier sommet ; `Échap`) ; glisser lignes et
zones sans saut ; masque even-odd visible ; passage caméra → fichier → caméra
fonctionnel (piège `srcObject`) ; tests purs de géométrie et du reducer verts.

---

## Lot 11 — Analyse serveur, relecture, résultats
**Branche** `feat/frontend-analyse-resultats`

`features/analysis-job` (dépôt avec progression d'upload, SSE + sondage de
secours, annulation), `features/timeline-replay` (`frameIndexAt`, `statsAt`,
`toTrackedVehicles`, `flowBuckets` + tests), `features/results-dashboard`,
`features/vehicle-registry` (paresseux, virtualisé), exports.

**DoD** : bout en bout démontrable — déposer un clip, voir la progression,
obtenir un résultat, le rejouer, reculer et voir les compteurs **baisser** ;
bandeau « résultat obsolète » après déplacement d'une ligne ; les quatre
invariants comptables sont vrais à l'écran ; export CSV correct.

---

## Lot 12 — Modèles, réglages, temps réel, benchmark, historique, presets
**Branche** `feat/frontend-modeles-et-pages`

`features/model-picker` (groupes, clavier, états téléchargé/résident),
panneaux de réglages et diagnostic, `features/realtime-counting` (capture,
`scaleRequestGeometry` + test, une frame en vol), `features/benchmark`,
`features/job-history`, `features/geometry-presets`.

**DoD** : la webcam compte en direct avec la géométrie **au bon endroit** ; le
benchmark affiche un tableau trié et recharge le dernier run ; l'historique
permet d'ouvrir et de relancer une analyse ; un preset se sauvegarde et se
recharge (avec mise à l'échelle si la résolution diffère).

---

## Lot 13 — Docker, CI, documentation finale
**Branche** `chore/livraison`

`backend/Dockerfile` multi-étapes, `frontend/Dockerfile`,
`docker-compose.yml`, `.github/workflows/ci.yml` (trois jobs),
`docs/ARCHITECTURE.md` (schéma + tailles de bundle + décisions),
`docs/API.md`, `README.md` final, `CLAUDE.md` **écrit en dernier** (il documente
ce qui existe, pas ce qui était prévu).

**DoD** : `docker compose up` sert l'application complète sur un seul origin ;
la CI est verte ; un nouveau venu démarre le projet en suivant le README sans
poser de question.

---

## Lot 14 — Durcissement et vérifications manuelles
**Branche** `chore/durcissement`

Passer la liste de contrôle de sécurité de
[`06`](06-SECURITE-CORS-SWAGGER.md) §6, la liste des vérifications manuelles de
[`10`](10-TESTS-QUALITE-CI.md) §4, relire [`13`](13-PIEGES-CONNUS.md) piège par
piège en vérifiant que chacun est effectivement évité (et ajouter un test là où
c'est possible).

**DoD** : chaque case cochée avec la preuve (sortie de commande, capture ou
test) ; les écarts assumés sont écrits dans une ADR.

---

## Règles valables pour tous les lots

1. **Test d'abord** quand le comportement est spécifié ici (c'est le cas de tout
   le domaine et de tout le contrat).
2. **Aucun `TODO` laissé sans une ligne dans `CHANGELOG.md` ou une issue.**
3. À la fin de chaque lot, rapporter honnêtement : ce qui marche, ce qui a été
   vérifié à la main, ce qui reste, ce qui a été volontairement omis. Ne jamais
   annoncer « terminé » pour un lot dont les tests ne passent pas.
4. Si une contrainte de ce prompt s'avère fausse à l'usage, le **dire** avec la
   preuve, proposer l'alternative, et écrire une ADR — mais ne pas la contourner
   en silence.
