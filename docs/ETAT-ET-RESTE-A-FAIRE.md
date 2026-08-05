# État du projet et reste à faire

> **À l'agent qui reprend ce travail dans une nouvelle discussion : lis ce fichier
> en premier, puis [`prompt/README.md`](../prompt/README.md).** Ce document dit où
> en est le code ; `prompt/` dit ce qu'il doit devenir.
>
> Dernière mise à jour : 2026-08-05, après le lot 8.

---

## 1. Résumé en dix lignes

Le plan d'exécution est [`prompt/12-PLAN-EXECUTION.md`](../prompt/12-PLAN-EXECUTION.md) :
**14 lots**. Huit sont terminés :

| Lot | Sujet | État |
|---|---|---|
| 0 | Socle du dépôt, licence AGPL, hooks, ADR 0001→0005 | ✅ |
| 1 | Socle backend : `core/`, Problem Details, `/api/v1/health` | ✅ |
| 2 | **Domaine du comptage** (le cœur) | ✅ |
| 3 | Orchestration, jobs, SSE, `FakeEngine` | ✅ |
| 4 | Persistance SQLite + Alembic, registre, exports CSV | ✅ |
| 5 | Catalogue de 20 modèles, registre LRU, Ultralytics, ANPR | ✅ |
| 6 | Sécurité, en-têtes, limite de corps, OpenAPI | ✅ |
| 7 | WebSocket temps réel | ⬜ |
| 8 | **Benchmark serveur** | ✅ |
| 9 | Socle frontend + **système de design** | ✅ |
| 10 | Source, lecteur vidéo, éditeur de géométrie | ⬜ |
| 11 | Analyse, relecture de timeline, résultats, registre | ⬜ |
| 12 | Modèles, réglages, temps réel, benchmark, historique, presets | ⬜ |
| 13 | Docker, CI, docs finales, `CLAUDE.md` réécrit | ⬜ |
| 14 | Durcissement, les 56 pièges de `prompt/13` | ⬜ |

**Chiffres vérifiés :** 681 tests backend (1 ignoré), 7 tests frontend, couverture
97 % sur `features/counting/domain` et 94 % sur `features/benchmark`, `ruff` +
`mypy --strict` + `oxlint` + `tsc -b` + `bun run build` verts, 15 hooks de
pré-commit installés et actifs.

---

## 2. Où reprendre exactement

```bash
git branch --show-current          # → feat/backend-benchmark
git status --short                 # → propre
```

La branche `feat/backend-benchmark` porte le **lot 8 terminé** et est prête à
fusionner dans `main`. Le lot suivant conseillé est le **lot 7** (WebSocket temps
réel), puis les lots 10 à 12 (le frontend réel, le plus gros morceau).

`main` est propre et déployable.

### Deux détails que ce document donnait faux avant le lot 8

- Les migrations Alembic vivent dans **`backend/migrations/`**, pas
  `backend/alembic/`. Les commandes `uv run alembic …` sont justes ; seul le
  chemin ne l'était pas.
- La branche `feat/backend-benchmark` existait déjà en local mais **derrière
  `main`** d'un commit (elle ne portait pas `e682c60`). Elle a été rebasée sur
  `main` avant de commencer.

---

## 3. Ce qui marche réellement aujourd'hui

Testé de bout en bout, pas supposé :

- déposer une vidéo (`POST /api/v1/jobs`), suivre la progression en SSE, obtenir
  le résultat complet en `json.gz`, consulter le registre paginé, exporter en CSV ;
- annuler une analyse en cours (arrêt **entre deux images**, donc le bail du
  modèle est rendu) ;
- un job **survit au redémarrage** du service (vérifié en reconstruisant une
  seconde application sur la même base) ;
- le catalogue des 20 modèles avec, pour chacun, s'il est téléchargé et s'il est
  résident ;
- **mesurer les modèles sur cette machine** (`POST /api/v1/benchmark`), suivre en
  SSE, relire le dernier run — vérifié de bout en bout sur un **vrai YOLOv8n**, et
  les chiffres réels de cette machine sont instructifs :
  - premier run : `loadMs` **28 466** (téléchargement des poids inclus, attribué au
    chargement et non fondu dans l'inférence), médiane 215 ms, p95 268 ms ;
  - second run, poids sur le disque : `loadMs` **55**, médiane **94,7 ms** ;
  - après chaque run, `GET /api/v1/models` rend `loadedIds: []` — la libération
    fonctionne contre le registre réel, donc vingt modèles ne s'accumulent pas ;
  - **limite assumée** : l'échantillon embarqué est synthétique, donc
    `detections` y vaut **0** pour tous les modèles. Les *temps* sont valables ;
    la colonne « détections » ne devient informative qu'avec `imageSource=job`.
    Embarquer une photo de trafic réelle mettrait des plaques réelles dans le
    dépôt, et truquer le compte serait pire que de le laisser à zéro ;
- `/api/docs` documenté, fermable par `TRAFFIC_DOCS_ENABLED=false` ;
- la coquille frontend s'affiche, le badge dit « Serveur injoignable » avec une
  action « Réessayer » quand le backend est arrêté, le proxy Vite transmet `/api`.

**Ce qui ne marche pas encore** : les trois écrans du frontend sont des **états
vides explicites**. Ils affichent le vrai état du serveur et disent quoi faire,
mais on ne peut pas encore déposer de vidéo *depuis l'interface*, ni tracer une
ligne, ni voir des compteurs. Tout cela passe par l'API, pas par l'écran.

---

## 4. Tâches restantes, dans l'ordre conseillé

### Lot 7 — WebSocket temps réel

Spécification : [`prompt/05-API-ET-CONTRAT.md`](../prompt/05-API-ET-CONTRAT.md) §7.

- [ ] `features/realtime/api/protocol.py` : `init` → `ready` → (`frame` texte +
      JPEG binaire) → `frameResult`.
- [ ] **Vérification de l'`Origin` du handshake** contre `cors_origins` : un
      WebSocket n'est pas protégé par la politique de même origine.
- [ ] Fermeture `1008` sur init invalide, `1011` sur erreur interne, `1013` si une
      session est déjà active (**avant** `accept()`).
- [ ] Sémaphore de session (`max_realtime_sessions`).
- [ ] Décodage JPEG et `track()` dans un **thread worker**.
- [ ] Le message `ready` renvoie les **dimensions réellement reçues** : c'est le
      filet contre une géométrie non mise à l'échelle, qui compterait 25 % à côté
      sans aucune erreur visible.
- [ ] `finally` qui ferme le stream et **rend le bail** du modèle.
- [ ] Tests : init invalide, une frame → un `frameResult`, seconde session
      refusée, origine refusée.

Réutiliser : `AnalysisSession` (la **même** session que le mode différé),
`UltralyticsStream`, `FakeStream` de `tests/support/engine.py`.

### Lot 10 — Source, lecteur vidéo, éditeur de géométrie

Spécification : [`prompt/09-FRONTEND-UX-FONCTIONNALITES.md`](../prompt/09-FRONTEND-UX-FONCTIONNALITES.md) §2.

- [ ] `features/media-source` : dépôt de fichier (glisser-déposer + clic), vidéo
      de démonstration, caméra. **`video.srcObject = null` à l'arrêt du flux**,
      sinon le fichier suivant ne se charge jamais, sans même un événement
      `error` (piège 36).
- [ ] `features/video-transport` : lecteur maison — **pas la barre `controls`
      native**, qui recouvre exactement la zone où l'on trace les lignes.
      Réappliquer `playbackRate` sur `loadedmetadata` (le navigateur le remet à 1),
      écouter `ended` (ce n'est pas `pause`), **jamais `loop`**, masquer la
      timeline quand `duration` n'est pas fini.
- [ ] `shared/lib/geometry.ts` : `sideOfLine`, `pointInPolygon`,
      `distanceToSegment`. Copie **minimale** du backend, pour le dessin et le
      test de sélection à la souris — **elle ne compte rien**, et un test doit
      vérifier que `sideOfLine` donne le **même signe** que la convention backend,
      sinon les flèches de sens affichées mentent.
- [ ] `entities/geometry` : types + reducer d'édition + **signature de géométrie**
      (`ax,ay,bx,by,zoneId` par ligne, sommets par zone) pour le bandeau
      « résultat obsolète ».
- [ ] `features/geometry-editor` : canvas en superposition. Ordre de dessin de
      `prompt/09` §2.4 (le masque even-odd d'abord, les lignes après les boîtes).
      Tout est stocké en **pixels source**, converti au dessin.
- [ ] Tracé de zone : clic par sommet, fermeture par **double-clic *et* clic sur
      le premier sommet**, `Échap` annule. Le brouillon vit dans un **`ref`**, pas
      dans un `state` : un double-clic livre deux `pointerdown` et le `dblclick`
      dans un seul rendu, donc lire le state lirait une liste périmée (piège 42).
- [ ] Glisser sans saut (décalage de préhension conservé), `touch-none`,
      `setPointerCapture`.

### Lot 11 — Analyse, relecture, résultats

Spécification : `prompt/09` §2.8 et §3.

- [ ] `features/analysis-job` : dépôt avec **progression d'envoi** (l'unique
      `XMLHttpRequest` du projet, `fetch` n'expose pas la progression d'envoi),
      SSE **+ sondage de secours toutes les 3 s**, annulation.
- [ ] `features/timeline-replay` : `frameIndexAt` en **recherche binaire** (54 000
      lignes, appelé à chaque rafraîchissement), `statsAt`, `toTrackedVehicles`,
      `flowBuckets`. Suivi par **`requestAnimationFrame`**, pas par `timeupdate`
      (qui ne se déclenche que ~4 fois par seconde et fait traîner les boîtes).
- [ ] **Reculer dans la vidéo doit faire *baisser* les compteurs** : `statsAt`
      rejoue les événements jusqu'à `timeMs`, et l'occupation de zone est remise à
      zéro (c'est une lecture instantanée, pas un cumul).
- [ ] `features/results-dashboard` : cartes, répartition par type, détail par
      ligne (`↑ p · ↓ n`) et par zone, histogramme SVG maison à tranches
      adaptatives (chargé paresseusement).
- [ ] `features/vehicle-registry` : tableau virtualisé maison au-delà de 200
      lignes, 12 lignes puis « Afficher les N restants », exports.
- [ ] Bandeau « résultat obsolète » quand la signature de géométrie a changé.

### Lot 12 — Modèles, réglages, pages secondaires

- [ ] `features/model-picker` : groupes par palier à entêtes **collantes**,
      navigation clavier **à plat** (les groupes sont purement visuels), trois
      états *au catalogue* / *téléchargé* / *résident*, mention « premier usage :
      téléchargement ~N Mo ».
- [ ] Panneaux Détection / Comptage / Affichage, avec le **diagnostic live** —
      « le compte est faux » n'est diagnosticable que si l'on voit si un véhicule
      manquant n'a jamais été détecté, l'a été faiblement, n'était pas confirmé,
      ou a été masqué par une zone.
- [ ] `features/realtime-counting` : capture `toBlob("image/jpeg", 0.8)` réduite à
      **960 px**, **une frame en vol à la fois** (les autres sont abandonnées, pas
      mises en file), et **`scaleRequestGeometry` avec son test unitaire** — une
      ligne non mise à l'échelle compterait 25 % à côté sans aucune erreur visible.
- [ ] `features/benchmark` : tableau triable, dernier run rechargé à l'ouverture.
- [ ] `features/job-history` : ouvrir (recharge aussi la géométrie depuis
      `config_json`), relancer (**nouveau** job, jamais une mutation), supprimer.
- [ ] `features/geometry-presets` + routes backend `/presets` (pas encore écrites).

### Lot 13 — Livraison

- [ ] `backend/Dockerfile` multi-étapes, non-root, `HEALTHCHECK` sur
      `/api/v1/health/live`.
- [ ] `frontend/Dockerfile` → build servi **par le backend**
      (`TRAFFIC_STATIC_DIR`, déjà implémenté côté serveur).
- [ ] `docker-compose.yml` (volumes `./data`, `./.weights`).
- [ ] `.github/workflows/ci.yml` : 3 jobs, `fail-fast: false`, `--frozen`,
      **aucun téléchargement de poids en CI**.
- [ ] `docs/API.md`, README final, **`CLAUDE.md` réécrit** — il porte encore un
      avertissement disant qu'il décrit ce que le projet *doit* être ; au lot 13 il
      doit décrire ce qu'il *est*.

### Lot 14 — Durcissement

- [ ] Liste de contrôle de sécurité [`prompt/06`](../prompt/06-SECURITE-CORS-SWAGGER.md) §6.
- [ ] Vérifications manuelles [`prompt/10`](../prompt/10-TESTS-QUALITE-CI.md) §4,
      dont **comparer un comptage réel à un comptage humain sur 30 s** et écrire
      le résultat de la comparaison.
- [ ] Relire les **56 pièges** de [`prompt/13`](../prompt/13-PIEGES-CONNUS.md) un
      par un, en ajoutant un test là où c'est possible.

---

## 5. Décisions déjà prises — ne pas les rediscuter

Elles sont dans [`CLAUDE.md`](../CLAUDE.md) et dans [`docs/adr/`](adr/). Les cinq
qui reviennent le plus souvent :

1. **Analyse 100 % backend**, COOP/COEP `require-corp` retiré ([ADR 0003](adr/0003-analyse-100-pourcent-backend.md)).
2. **Aucun poids dans git** ; le dossier `yolo/` est inutilisable pour le suivi —
   un export ONNX ne porte pas le pipeline BoT-SORT + ReID + GMC dont
   `model.track()` a besoin ([ADR 0002](adr/0002-pas-de-poids-dans-git.md)).
3. **Python 3.12**, borne haute `<3.13` volontaire ([ADR 0001](adr/0001-python-312.md)).
4. **`torch-backend = "auto"`** dans `pyproject.toml` — remplace les extras
   cpu/gpu prévus au plan initial, qu'`uv` ne sait pas rendre par défaut. Le
   lockfile est universel, l'installation retient la variante de la machine
   (`2.13.0+cpu` ici) ([ADR 0005](adr/0005-torch-cpu-par-defaut.md)).
5. **`DESIGN.md` est la source des jetons visuels**, et l'accent vert est
   **strictement fonctionnel** — donc jamais une couleur de classe de véhicule,
   sinon « vert = compté » et « vert = camion » se contrediraient sur la même
   image ([ADR 0004](adr/0004-systeme-de-design.md)).

### Écarts assumés par rapport au plan initial

- `sse-starlette` écartée : le SSE est écrit à la main pour garder la main sur
  `X-Accel-Buffering`, le ping de maintien et l'envoi de l'état courant en premier.
- La règle d'architecture « une feature n'importe jamais une autre » a été
  **affinée** : une feature n'importe qu'une autre par sa couche `application`,
  son contrat publié. `jobs` a légitimement besoin de `counting` ; ce qui reste
  interdit, c'est de fouiller dans un `domain` ou une `infrastructure` voisine.
- `UtcDateTime` (`core/db/types.py`) remplace `DateTime(timezone=True)` : sur
  SQLite ce dernier relit des datetimes **naïfs**, ce qui casse silencieusement la
  purge TTL.
- **L'adaptateur de mesure du benchmark vit dans `models_registry`**, pas dans
  `benchmark/infrastructure/`. Le port `InferenceProbe` est publié par
  `benchmark/application/ports.py` et implémenté par
  `models_registry/infrastructure/inference_probe.py`. Ce n'est pas un caprice :
  seul `models_registry` peut toucher son propre registre, et
  `tests/test_architecture.py` a refusé la première version — qui logeait
  l'adaptateur côté benchmark et fouillait dans l'`infrastructure` voisine. Le
  test a fait son travail.
- **Le benchmark exige la persistance**, contrairement aux jobs qui ont un dépôt
  en mémoire réel. Un run est écrit ligne par ligne et rechargé à l'ouverture de
  la page : sans base, la route répond 503 avec la raison. Le dépôt en mémoire du
  benchmark est donc une **doublure de test** et vit dans `tests/support/`.
- `BenchmarkService.wait_for_idle()` existe pour les tests autant que pour
  l'arrêt du service. La première version des tests sondait le statut dans une
  boucle bornée en nombre d'itérations : elle passait à nu et **échouait sous
  `--cov`**. Un test dont le verdict dépend de la vitesse de la machine ne prouve
  rien ; attendre la tâche est déterministe.

---

## 6. Pièges d'environnement de cette machine

- **`uv` n'est pas sur le `PATH` par défaut.** Il vit dans
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_*\`. En Git Bash :
  ```bash
  export PATH="$PATH:/c/Users/$USER/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe"
  ```
- Le Python du système est un **3.14.6** : il ne peut pas faire tourner ce
  backend. Toujours `uv run`.
- **Aucun GPU** : `device = cpu`, `half = false`, et les mesures de benchmark sont
  des mesures CPU — à interpréter comme telles.
- Un **ancien service** occupait le port 8000 (reconnaissable à son en-tête
  `cross-origin-embedder-policy: require-corp`, signature de la version à
  inférence navigateur). Il a été arrêté le 2026-08-05 ; s'il revient, il fait
  échouer `uvicorn --port 8000` et le proxy Vite parle à la mauvaise application.
- Les fichiers écrits sous Windows arrivent en CRLF ; le hook
  `mixed-line-ending --fix=lf` les normalise et **fait échouer le premier
  `git commit`**. Réindexer et recommiter suffit.
- Sous Windows, `rm -rf backend/data` échoue si le service tourne (fichier SQLite
  verrouillé). Arrêter uvicorn d'abord.

---

## 7. Commandes de vérification

À passer avant chaque commit — les hooks les rejouent de toute façon.

```bash
# Backend
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head

# Frontend
cd ../frontend
bun run lint && bun run typecheck && bun run test && bun run build

# Dépôt entier
uvx pre-commit run --all-files
```

Bout en bout :

```bash
cd backend && uv run uvicorn traffic_analysis.main:app --reload --port 8000
cd frontend && bun run dev        # http://localhost:5173
```

Attendre que le backend annonce « Application startup complete » **avant** de
tester le proxy : sinon Vite reçoit un refus de connexion et le diagnostic part
dans la mauvaise direction (cela m'a coûté trois essais).
