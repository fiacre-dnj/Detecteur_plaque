# Démarrer le projet

(Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned) ; (& c:\Users\User\Documents\dev\Detecteur_plaque\backend\.venv\Scripts\Activate.ps1)

Les commandes à coller, dans l'ordre. Pour le *pourquoi* de chaque choix, voir
[`README.md`](README.md) ; ce fichier-ci ne fait que dérouler.

---

## 0. Une seule fois : mettre `uv` sur le `PATH`

**C'est l'erreur que tout le monde rencontre en premier sur cette machine.** `uv`
a été installé par winget, qui ne l'ajoute pas au `PATH` :

```
uv: The term 'uv' is not recognized as a name of a cmdlet, function, script file,
or executable program.
```

### Le correctif définitif (PowerShell, à faire une fois)

```powershell
[Environment]::SetEnvironmentVariable(
  "PATH",
  [Environment]::GetEnvironmentVariable("PATH", "User") + ";C:\Users\f.dauphin\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe",
  "User"
)
```

Puis **fermez et rouvrez le terminal** — une variable d'environnement n'est lue
qu'au démarrage du processus. Vérification :

```powershell
uv --version
```

Cela règle aussi un agacement discret : le hook de pré-commit `mypy` appelle
`uv run` et échoue sur « Executable `uv` not found », alors que `mypy` passe
parfaitement quand on l'appelle à la main.

### Le dépannage ponctuel (ne vaut que pour le terminal courant)

PowerShell :

```powershell
$env:PATH = "C:\Users\f.dauphin\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe;$env:PATH"
```

Git Bash :

```bash
export PATH="$PATH:/c/Users/$USER/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe"
```

> **Ne jamais appeler un `python` du `PATH` pour ce projet.** Celui du système est
> un 3.14 ; le backend exige un 3.12, et `uv` le provisionne lui-même.

---

## 1. Le backend — terminal 1

```powershell
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn traffic_analysis.main:app --reload --port 8000
```

**Attendez la ligne « Application startup complete »** avant de démarrer le
frontend. Sinon le proxy de Vite reçoit un refus de connexion, et le diagnostic
part dans la mauvaise direction.

`uv sync` et `alembic upgrade head` ne sont nécessaires qu'au premier lancement,
ou après un `git pull` qui touche aux dépendances ou aux migrations.

---

## 2. Le frontend — terminal 2

```powershell
cd frontend
bun install
bun run dev
```

Puis ouvrez **<http://localhost:5173>**.

**C'est cette adresse-là, pas le 8000.** En développement, Vite sert l'interface
et relaie `/api` vers le backend, WebSocket compris. Le port 8000 ne sert que
l'API.

| | |
|---|---|
| Interface | <http://localhost:5173> |
| Documentation de l'API | <http://127.0.0.1:8000/api/docs> |
| État du service | <http://127.0.0.1:8000/api/v1/health> |

---

## 3. Avant la première analyse

### Les poids ne sont pas dans le dépôt

Le premier usage d'un modèle le télécharge — 6 Mo pour `yolov8n`, jusqu'à 137 Mo
pour les plus gros. L'interface l'annonce avant de le faire. Pour éviter que cela
arrive au milieu d'une analyse :

```powershell
cd backend
uv run python scripts/fetch_weights.py --tiers nano
```

Ou davantage, si vous comptez comparer les modèles :

```powershell
uv run python scripts/fetch_weights.py --tiers nano,medium,large,xlarge
```

Le modèle de lecture de plaques est optionnel et se récupère à part
(`scripts/fetch_plate_model.py`, avec vérification de son empreinte SHA-256). Son
absence **n'empêche pas** le service de démarrer : l'option ANPR est simplement
signalée indisponible.

### La vidéo de démonstration est absente

Volontairement : une scène de trafic contient des plaques réelles. Déposez un MP4
à `frontend/public/demo/traffic.mp4`, ou choisissez simplement un fichier depuis
votre disque. En son absence, l'interface indique le chemin attendu au lieu
d'échouer en silence.

---

## 4. Vérifier avant de committer

```powershell
# Backend
cd backend
uv run ruff check . ; uv run ruff format --check . ; uv run mypy src ; uv run pytest

# Frontend
cd ../frontend
bun run lint ; bun run typecheck ; bun test ; bun run build

# Dépôt entier
uvx pre-commit run --all-files
```

Les hooks de pré-commit rejouent ces vérifications de toute façon.

**Le premier `git commit` échoue souvent**, et c'est normal : le hook
`mixed-line-ending` convertit les fins de ligne CRLF que Windows a écrites. Il
modifie les fichiers, donc il refuse le commit. Réindexez et recommittez :

```powershell
git add -A
git commit -m "..."
```

---

## 5. Tout servir d'un coup (Docker)

```powershell
docker compose up
```

Une seule image sert le backend **et** l'interface sur <http://localhost:8000> —
une seule adresse, aucun réglage de CORS.

> **À vérifier avant de compter dessus.** Ce chemin n'a **jamais pu être
> construit** sur cette machine : le disque `C:` s'est rempli à chaque tentative,
> et BuildKit échoue sur une erreur d'entrée/sortie qui ne mentionne jamais
> l'espace disque. Il faut environ **5 Go libres**. Vérifiez avec
> `Get-PSDrive C` avant de conclure à un défaut du `Dockerfile`, et faites au
> besoin un `docker system prune -af` après un redémarrage de Docker Desktop.

---

## Quand quelque chose ne marche pas

| Symptôme | Cause |
|---|---|
| `uv: The term 'uv' is not recognized` | §0 de ce fichier |
| Le proxy Vite refuse la connexion | Le backend n'a pas fini de démarrer — attendez « Application startup complete » |
| `uvicorn --port 8000` échoue | Un service occupe déjà le port. Un ancien service de ce projet traîne parfois ; il se reconnaît à son en-tête `cross-origin-embedder-policy: require-corp` |
| Le premier `git commit` échoue | Le hook de fins de ligne — réindexez et recommittez |
| Le build Docker échoue en `input/output error` | Disque plein, pas le `Dockerfile` |
| `rm -rf backend/data` échoue | Le fichier SQLite est verrouillé : arrêtez uvicorn d'abord |

Le reste des pièges de cette machine est dans
[`docs/ETAT-ET-RESTE-A-FAIRE.md`](docs/ETAT-ET-RESTE-A-FAIRE.md) §6.
