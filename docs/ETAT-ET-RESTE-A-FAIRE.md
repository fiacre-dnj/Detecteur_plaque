# État du projet et reste à faire

> **À l'agent qui reprend ce travail dans une nouvelle discussion : lis ce fichier
> en premier, puis [`prompt/README.md`](../prompt/README.md).** Ce document dit où
> en est le code ; `prompt/` dit ce qu'il doit devenir.
>
> Dernière mise à jour : 2026-08-06, après le lot 14 — le dernier.

---

## 1. Résumé

Le plan d'exécution est [`prompt/12-PLAN-EXECUTION.md`](../prompt/12-PLAN-EXECUTION.md) :
**14 lots**. Treize sont terminés.

| Lot | Sujet | État |
|---|---|---|
| 0 | Socle du dépôt, licence AGPL, hooks, ADR 0001→0005 | ✅ |
| 1 | Socle backend : `core/`, Problem Details, `/api/v1/health` | ✅ |
| 2 | **Domaine du comptage** (le cœur) | ✅ |
| 3 | Orchestration, jobs, SSE, `FakeEngine` | ✅ |
| 4 | Persistance SQLite + Alembic, registre, exports CSV | ✅ |
| 5 | Catalogue de 20 modèles, registre LRU, Ultralytics, ANPR | ✅ |
| 6 | Sécurité, en-têtes, limite de corps, OpenAPI | ✅ |
| 7 | WebSocket temps réel | ✅ |
| 8 | **Benchmark serveur** | ✅ |
| 9 | Socle frontend + **système de design** | ✅ |
| 10 | Source, lecteur vidéo, éditeur de géométrie | ✅ |
| 11 | Analyse, relecture de timeline, résultats, registre | ✅ |
| 12 | Modèles, réglages, temps réel, benchmark, historique, presets | ✅ |
| 13 | Docker, CI, docs finales, `CLAUDE.md` réécrit | ✅ |
| 14 | Durcissement, les 56 pièges de `prompt/13` | ✅ |

**Chiffres vérifiés :** 846 tests backend (1 ignoré), 343 tests frontend, `ruff` +
`mypy --strict` + `oxlint` + `tsc -b` + `bun run build` verts, 15 hooks de
pré-commit actifs.

### Ce que le lot 14 a trouvé

La liste de sécurité de `prompt/06` §6 a rendu trois écarts, la relecture des 56
pièges en a rendu six. Les trois qui comptent :

- **`input_ttl_minutes` n'était jamais appliqué.** La configuration promettait que
  la vidéo déposée partait au bout d'une heure ; elle survivait vingt-quatre fois
  plus longtemps. `delete_input()` existait, était correct, et n'avait aucun
  appelant. Les tests de purge comptaient des jobs sans jamais regarder le disque.
- **Le bail de modèle n'excluait rien** (invariant 9). `leases` comptait les usages
  concurrents sans les empêcher : une analyse différée et une session temps réel
  sur le même modèle partageaient l'instance et mélangeaient leurs états de suivi.
- **Le NMS ne dédupliquait pas entre classes** (piège 5). Le commentaire affirmait
  le contraire ; `agnostic_nms` n'était passé nulle part.

Les trois avaient en commun d'être **silencieux** : aucune erreur, aucun journal,
des chiffres plausibles. Et deux d'entre eux étaient documentés comme résolus par
un commentaire qui décrivait un mécanisme inexistant.

**L'application est fonctionnelle de bout en bout** : dépôt d'un fichier, édition
de géométrie au canvas, analyse serveur suivie en SSE, relecture synchronisée,
comptage en direct sur le flux caméra, benchmark, historique, presets.

---

## 2. Où reprendre exactement

```bash
git branch --show-current
git status --short
```

Les 14 lots sont écrits. Il ne reste que des vérifications qui demandent une
machine en état et un humain devant l'écran — voir §4.

---

## 3. Ce qui marche réellement aujourd'hui

Vérifié contre le vrai serveur, pas supposé.

### Différé

- déposer une vidéo (`POST /api/v1/jobs`), suivre la progression en SSE, obtenir
  le résultat en `json.gz`, consulter le registre paginé, exporter en CSV ;
- annuler une analyse en cours (arrêt **entre deux images**, bail rendu) ;
- un job **survit au redémarrage** du service ;
- rouvrir une analyse de l'historique **avec sa géométrie** (`/jobs/{id}/config`),
  ou la relancer — ce qui crée un **nouveau** job et ne mute jamais l'ancien.

### Direct

Vérifié avec un vrai YOLOv8n sur le WebSocket réel :

- `ready` renvoie `frameWidth: null` avant la première image, puis les dimensions
  réellement décodées dans chaque `frameResult` ;
- une session de six frames rend `frameIndex: 5` — le serveur dérive ses propres
  index ;
- la place de session est rendue à la fermeture : une seconde session s'ouvre ;
- un `init` sans ligne ferme en **1008** avec la raison, tronquée à 123 octets
  comme la RFC 6455 l'exige ;
- l'origine `http://localhost:5173.evil.com` est refusée au handshake.

**La panne silencieuse a été reproduite volontairement** : une ligne dont le `x`
va jusqu'à 1180 dans une image de 960 de large est acceptée sans un mot. Le
serveur ne peut pas la détecter puisqu'il ne connaît pas la résolution que le
client croit envoyer. C'est ce qui justifie `scaleRequestGeometry`, son test, et
le refus de compter en cas d'écart de dimensions.

### Presets

Vérifié contre le vrai serveur : création `201`, homonyme `409`, lecture en
`640×360` rendant `x=50 y=200` avec `scaled: true`, suppression `204` puis `404`.
La migration Alembic s'applique au démarrage.

### Benchmark

Mesuré sur un vrai YOLOv8n, chiffres de cette machine :

- premier run : `loadMs` **28 466** (téléchargement inclus, attribué au chargement
  et non fondu dans l'inférence), médiane 215 ms, p95 268 ms ;
- second run, poids sur disque : `loadMs` **55**, médiane **94,7 ms** ;
- après chaque run, `GET /api/v1/models` rend `loadedIds: []` — la libération
  fonctionne contre le registre réel ;
- **limite assumée** : l'échantillon embarqué est synthétique, donc `detections`
  vaut **0** pour tous les modèles. Les *temps* sont valables ; la colonne
  « détections » ne devient informative qu'avec `imageSource=job`. Embarquer une
  photo de trafic réelle mettrait des plaques réelles dans le dépôt, et truquer le
  compte serait pire que de le laisser à zéro.

### Ce qui n'a **pas** pu être vérifié

- **L'image Docker n'a jamais été construite avec succès sur cette machine.** Le
  disque `C:` est plein (0 octet libre au moment du lot 13) et BuildKit échoue sur
  une erreur d'entrée/sortie qui ne mentionne jamais l'espace disque. Le
  `Dockerfile` et le `docker-compose.yml` sont écrits et leur YAML est validé,
  mais **le `docker compose up` du critère d'acceptation du lot 13 reste à
  prouver**. Le job `image` de la CI le fera au premier passage — il construit,
  démarre, attend le healthcheck et vérifie que `/` et `/historique` rendent bien
  l'interface.
- **La boucle direct avec une vraie webcam** dans un navigateur. Le protocole a
  été exercé de bout en bout par un client Python qui parle exactement la même
  séquence, mais la capture `canvas.toBlob` et le `getUserMedia` réels ne l'ont
  pas été.
- **La CI n'a jamais tourné** : `.github/workflows/ci.yml` est écrit mais aucun
  push n'a encore déclenché GitHub Actions.

---

## 4. Tâches restantes

Les 14 lots sont écrits. Ce qui reste ne demande pas d'écrire du code, mais une
machine en état et un humain devant l'écran.

- [ ] **Construire l'image et faire tourner `docker compose up`.** C'est le critère
      d'acceptation du lot 13, et il n'a pas pu être honoré : voir §3. Le job
      `image` de la CI le fera au premier passage.
- [ ] **Comparer un comptage réel à un comptage humain sur 30 s**
      ([`prompt/10`](../prompt/10-TESTS-QUALITE-CI.md) §4) et écrire le résultat.
      C'est la seule vérification qui dise si l'application compte *juste*, et
      aucun test automatique ne peut la remplacer.
- [ ] Les autres vérifications manuelles de `prompt/10` §4 : déplacer une ligne
      après une analyse, reculer dans la vidéo, couper le backend en pleine
      analyse, enchaîner caméra → fichier → caméra.
- [ ] Faire tourner la CI une première fois (aucun push n'a encore déclenché
      GitHub Actions).

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
  `models_registry/infrastructure/inference_probe.py`. Seul `models_registry` peut
  toucher son propre registre, et `tests/test_architecture.py` a refusé la
  première version.
- **Les schémas de requête d'analyse vivent dans `counting/application/`**, pas
  dans `jobs/api/`. Le mode différé et le mode direct valident tous les deux la
  même configuration ; le test d'architecture a refusé que `realtime` fouille dans
  l'`api` de `jobs`, et il avait raison — c'est ce partage qui garantit qu'un même
  tracé donne les mêmes chiffres dans les deux modes.
- **Le benchmark et les presets exigent la persistance**, contrairement aux jobs
  qui ont un dépôt en mémoire réel. Sans base, la route répond 503 avec la raison.
- `BenchmarkService.wait_for_idle()` existe pour les tests autant que pour
  l'arrêt du service. La première version des tests sondait le statut dans une
  boucle bornée en nombre d'itérations : elle passait à nu et **échouait sous
  `--cov`**. Un test dont le verdict dépend de la vitesse de la machine ne prouve
  rien ; attendre la tâche est déterministe.
- **La géométrie d'un preset est stockée en JSON**, pas dans des tables filles.
  C'est le seul endroit du projet où ce choix est fait, et il tient à l'usage : on
  requête les franchissements d'un job, on ne requête jamais les sommets d'un
  preset — ils sont écrits et relus en bloc.
- **Une seule image Docker** sert le backend et le frontend, plutôt que deux
  services derrière un reverse proxy. Ce n'est pas la disposition la plus
  orthodoxe ; elle supprime le CORS à ouvrir, le tamponnage SSE du proxy et le
  relais WebSocket — les trois pannes de déploiement habituelles.

### Deux bugs que seule l'exécution réelle a trouvés

Ils méritent d'être connus, parce qu'ils disent quelque chose sur les limites de
cette architecture :

- **`CONFIG_DIR` cherchait le YAML du tracker dans `backend/src/config/`** au lieu
  de `backend/config/`. **Toutes** les analyses réelles échouaient. Rien ne l'a vu :
  les 500 tests de comptage injectent un `FakeEngine` et n'atteignent jamais
  `UltralyticsEngine`. C'est le bénéfice de l'architecture et son prix.
- **Le champ `request` du multipart était envoyé en `Blob`** avec un type
  `application/json`, donc traité par FastAPI comme un second *fichier*, refusé en
  422. Trouvé en postant au vrai serveur ; le commentaire de code qui affirmait le
  contraire était faux.

---

## 6. Pièges d'environnement de cette machine

- **`uv` n'est pas sur le `PATH` par défaut.** Il vit dans
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_*\`. En Git Bash :
  ```bash
  export PATH="$PATH:/c/Users/$USER/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe"
  ```
  Sans cela, le hook pre-commit `mypy-backend` échoue sur « Executable `uv` not
  found » alors que mypy passe parfaitement quand on l'appelle à la main.
- Le Python du système est un **3.14.6** : il ne peut pas faire tourner ce
  backend. Toujours `uv run`.
- **Aucun GPU** : `device = cpu`, `half = false`, et les mesures de benchmark sont
  des mesures CPU — à interpréter comme telles.
- **Le disque `C:` est régulièrement plein.** Au lot 13 il ne restait aucun octet
  libre, ce qui a fait échouer le build Docker sur une erreur BuildKit
  (`input/output error`) qui ne mentionne jamais l'espace disque, puis a tué le
  démon. Vérifier `df -h /c` **avant** de conclure à un défaut du `Dockerfile`.
- Un **ancien service** occupait le port 8000 (reconnaissable à son en-tête
  `cross-origin-embedder-policy: require-corp`, signature de la version à
  inférence navigateur). Arrêté le 2026-08-05 ; s'il revient, il fait échouer
  `uvicorn --port 8000` et le proxy Vite parle à la mauvaise application.
- Les fichiers écrits sous Windows arrivent en CRLF ; le hook
  `mixed-line-ending --fix=lf` les normalise et **fait échouer le premier
  `git commit`**. Réindexer et recommiter suffit.
- Sous Windows, `rm -rf backend/data` échoue si le service tourne (fichier SQLite
  verrouillé). Arrêter uvicorn d'abord.
- `git commit -F` attend un **fichier**, pas un here-string PowerShell : passer un
  `@'…'@` produit un « No such file or directory » qui affiche tout le message.

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
bun run lint && bun run typecheck && bun test && bun run build

# Dépôt entier
uvx pre-commit run --all-files
```

Bout en bout, en développement :

```bash
cd backend && uv run uvicorn traffic_analysis.main:app --reload --port 8000
cd frontend && bun run dev        # http://localhost:5173
```

Attendre que le backend annonce « Application startup complete » **avant** de
tester le proxy : sinon Vite reçoit un refus de connexion et le diagnostic part
dans la mauvaise direction.

Ou tout d'un coup :

```bash
docker compose up                 # http://localhost:8000
```
