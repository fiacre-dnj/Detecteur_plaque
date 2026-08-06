# Comptage de véhicules

Détection, suivi, ré-identification et franchissement de lignes sur une vidéo ou
un flux webcam. **Toute l'inférence est côté serveur** (Python / Ultralytics) ; le
navigateur pilote l'analyse, dessine la géométrie de comptage et rejoue le
résultat.

- Comptage **par ligne et par sens**, dédupliqué par identité et par sens.
- Comptage **par zone** : entrées uniques et occupation instantanée.
- **Ré-identification longue durée** : un véhicule occulté puis revenu reste le
  même véhicule, ce qui distingue « véhicules uniques » de « passages ».
- **Lecture de plaques (ANPR)** en option, en passe secondaire sur chaque véhicule.
- **Benchmark serveur** de 20 modèles YOLO (familles v8 / 11 / 12 / 26,
  paliers nano → xlarge) mesurés sur *cette* machine.
- Historique persisté : un résultat se relit sans relancer l'analyse.

> **Les images quittent votre machine.** Elles sont envoyées au serveur, qui fait
> l'inférence. C'est une conséquence assumée de l'architecture
> ([ADR 0003](docs/adr/0003-analyse-100-pourcent-backend.md)) et l'interface le dit
> à l'endroit où l'on choisit une source.

## Démarrage — deux chemins

> Pressé ? [`RUN.md`](RUN.md) ne contient que les commandes, dans l'ordre, avec le
> dépannage des erreurs que cette machine produit.

### Pour utiliser l'application : une commande

```bash
docker compose up
# puis http://localhost:8000
```

Une seule image sert le backend **et** l'interface, sur un seul origin. C'est ce
qui supprime d'un coup les trois pannes de déploiement habituelles de ce genre
d'application : le CORS à ouvrir, le tamponnage du proxy qui retient les
événements SSE, et le relais WebSocket qu'il faut activer explicitement.

Le premier démarrage construit l'image, ce qui prend plusieurs minutes — la roue
CPU de PyTorch pèse à elle seule ~250 Mo. Les analyses, la base et les poids
téléchargés vivent dans deux volumes nommés et survivent à un `docker compose
down`.

Aucun poids n'est embarqué dans l'image ; le premier usage d'un modèle le
télécharge. Pour les récupérer d'avance :

```bash
docker compose exec app python scripts/fetch_weights.py --tiers nano
```

### Pour développer : cinq commandes

Prérequis : [`uv`](https://docs.astral.sh/uv/) et [`bun`](https://bun.sh) sur le
`PATH`. `uv` provisionne Python 3.12 lui-même — le Python du système n'est jamais
utilisé (voir [ADR 0001](docs/adr/0001-python-312.md)).

```bash
# 1. Backend : environnement dédié + migrations
cd backend && uv sync && uv run alembic upgrade head

# 2. Backend : démarrage
uv run uvicorn traffic_analysis.main:app --reload --port 8000

# 3. Frontend : dépendances
cd ../frontend && bun install

# 4. Frontend : démarrage (proxy /api → 127.0.0.1:8000)
bun run dev

# 5. Ouvrir http://localhost:5173
```

La documentation de l'API est sur <http://127.0.0.1:8000/api/docs>.

## Ce qu'il faut savoir avant le premier lancement

### Les poids ne sont pas dans le dépôt

Aucun `.pt` ni `.onnx` n'est committé ([ADR 0002](docs/adr/0002-pas-de-poids-dans-git.md)).
Le registre télécharge le modèle demandé au premier usage — jusqu'à ~137 Mo, ce
que l'interface annonce avant de le faire. Pour travailler hors ligne, ou pour
qu'un benchmark ne passe pas son temps à télécharger :

```bash
cd backend
# les 4 paliers demandés sur les 4 familles : 16 poids, ~800 Mo
uv run python scripts/fetch_weights.py --tiers nano,medium,large,xlarge
# ou une famille entière
uv run python scripts/fetch_weights.py --families yolo11 --tiers all
```

Le modèle de plaques est un `.onnx` récupéré séparément, avec vérification de sa
somme SHA-256 :

```bash
uv run python scripts/fetch_plate_model.py
```

Son absence **n'empêche pas le service de démarrer** : l'option ANPR est
simplement signalée indisponible dans `/api/v1/health` et désactivée dans l'UI.

### Le dossier `yolo/` n'est pas utilisé

Il contient des `.onnx` d'une version antérieure du projet. Un export ONNX ne
porte pas le pipeline natif d'Ultralytics (BoT-SORT + embeddings de
ré-identification + compensation de mouvement) dont `model.track()` a besoin :
ces fichiers **ne peuvent pas compter de véhicules**. Ils sont ignorés par git et
par le code. Les détecteurs véhicules sont des `.pt` natifs.

### `lap` est une dépendance de production, pas un extra

Ultralytics ne la tire pas, mais BoT-SORT et ByteTrack en ont besoin pour
l'assignation linéaire. Sans elle, `model.track()` échoue **à l'exécution** avec
`No module named 'lap'` — et aucun test à moteur factice ne peut le voir.

### GPU

`TRAFFIC_DEVICE=auto` résout `cuda` si `torch.cuda.is_available()`, sinon `cpu`.

**Il n'y a pas d'extra `gpu` à installer.** `pyproject.toml` déclare
`[tool.uv] torch-backend = "auto"` : un simple `uv sync` prend la roue CPU
(~250 Mo) sur une machine sans GPU et la roue CUDA correspondant au pilote détecté
sur une machine NVIDIA. Le lockfile porte les deux univers
([ADR 0005](docs/adr/0005-torch-cpu-par-defaut.md)). Pour forcer une variante —
build reproductible, ou machine dont le pilote n'est pas celui de la cible :

```bash
UV_TORCH_BACKEND=cpu uv sync      # ou cu124, cu126…
```

C'est ce que fait l'image Docker, qui force `cpu` pour ne pas embarquer deux
gigaoctets de CUDA inutilisé.

Sur CPU, les paliers `large` et `xlarge` demandent plusieurs centaines de
millisecondes par image, et l'ANPR ajoute une inférence par piste et par frame.

### Vidéo de démonstration

Déposez un clip à `frontend/public/demo/traffic.mp4` (ignoré par git : une scène
de trafic contient des plaques réelles). En son absence, l'interface indique le
chemin attendu au lieu d'échouer en silence.

## Configuration

Toutes les variables sont préfixées `TRAFFIC_` et documentées dans
`backend/.env.example`, qui est committé. `.env` est ignoré. Le code ne lit
`os.environ` nulle part : un unique objet `Settings` est chargé au démarrage et
injecté.

## Commandes

| Intention | Backend (`cd backend`) | Frontend (`cd frontend`) |
|---|---|---|
| Lancer | `uv run uvicorn traffic_analysis.main:app --reload` | `bun run dev` |
| Tester | `uv run pytest` | `bun run test` |
| Un seul test | `uv run pytest tests/unit/counting/test_line_counter.py -k aller_retour` | `bun test src/shared/lib/geometry.test.ts` |
| Typer | `uv run mypy src` | `bun run typecheck` |
| Linter | `uv run ruff check .` | `bun run lint` |
| Formater | `uv run ruff format .` | `bun run format` |
| Construire | — | `bun run build` |
| Migrer | `uv run alembic upgrade head` | — |

Et pour le dépôt entier :

| Intention | Commande |
|---|---|
| Tous les hooks | `uvx pre-commit run --all-files` |
| Servir l'application | `docker compose up` |
| Reconstruire l'image | `docker compose build app` |
| Interface en rechargement à chaud, en conteneur | `docker compose --profile dev up` |

## Vérifications manuelles

Certaines choses ne se testent pas automatiquement. À faire avant de considérer
une livraison terminée :

1. Analyser un vrai clip et comparer le total à un comptage humain sur 30 s.
2. Déplacer une ligne après une analyse ⇒ le bandeau « résultat obsolète » apparaît.
3. Reculer dans la vidéo ⇒ les compteurs **baissent**.
4. Couper le backend en pleine analyse ⇒ message clair, aucune page blanche.
5. Passer caméra → fichier → caméra ⇒ chaque source se charge.
6. Lancer le benchmark ⇒ la mémoire du serveur revient à son niveau initial.

## Architecture

- [`docs/ETAT-ET-RESTE-A-FAIRE.md`](docs/ETAT-ET-RESTE-A-FAIRE.md) — **où en est le
  code, ce qui reste à faire, et les pièges de cette machine**
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — schéma, décisions, tailles de bundle
- [`docs/API.md`](docs/API.md) — **ce que les routes veulent dire** ; la forme
  exacte est dans OpenAPI, généré depuis le code
- [`docs/adr/`](docs/adr/) — les décisions et leurs raisons
- [`prompt/`](prompt/) — **la spécification normative** du projet
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — branches, commits, revue

## Licence

**AGPL-3.0.** Ultralytics est sous AGPL, et ce service l'utilise pour de
l'inférence : la licence se propage. Ce n'est pas un détail juridique optionnel
pour un service exposé sur un réseau. Voir [`LICENSE`](LICENSE).
