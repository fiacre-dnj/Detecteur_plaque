# Image de production : le backend **et** le frontend, sur un seul origin.
#
# Une seule image plutôt que deux services derrière un reverse proxy. Ce n'est pas
# la disposition la plus orthodoxe, et elle se justifie par ce qu'elle supprime :
# aucun CORS à ouvrir, aucun réglage de proxy pour que le SSE traverse sans
# tamponnage, aucune configuration pour que le WebSocket soit relayé. Ces trois
# points sont la source habituelle des pannes de déploiement d'une application de
# ce genre, et servir le build depuis le backend les fait disparaître toutes les
# trois. Le code du montage existe déjà (`app_factory._mount_static`) : il ne manque
# que le `TRAFFIC_STATIC_DIR` que ce fichier pose.
#
# Trois étapes, dont deux ne survivent pas : le résultat n'embarque ni bun, ni
# node_modules, ni le compilateur qui a construit les roues Python.

# ── 1. Le frontend ───────────────────────────────────────────────────────────
# Version de bun épinglée : sans cela le build n'est pas reproductible, et une
# régression de l'outil arriverait par surprise un jour où l'on ne construit rien
# de nouveau.
FROM oven/bun:1.3-alpine AS frontend

WORKDIR /build

# Le manifeste et le lock d'abord : tant qu'ils ne changent pas, Docker réutilise
# la couche d'installation, qui est de loin la plus lente des deux.
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile

COPY frontend/ ./
# `bun run build` enchaîne `tsc -b` puis `vite build` : une erreur de typage fait
# donc échouer l'image. C'est voulu — livrer un bundle qui ne typecheck pas
# reviendrait à désactiver la vérification au moment où elle compte le plus.
RUN bun run build


# ── 2. Les dépendances Python ────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

# `UV_LINK_MODE=copy` parce que le cache de uv et le point de montage ne sont pas
# sur le même système de fichiers : le lien dur échouerait, et uv retomberait sur
# une copie en le signalant à chaque ligne.
#
# `UV_TORCH_BACKEND=cpu` choisit la roue CPU **explicitement**. La détection
# automatique ne voit aucun GPU pendant un build et prendrait déjà le CPU — mais
# par accident. Une image qui embarque CUDA pèse deux gigaoctets de plus pour du
# code qui ne s'en servira pas.
#
# Les commentaires sont au-dessus et non dans le bloc : une ligne de commentaire
# entre deux continuations `\` est avalée dans la valeur de la variable, et la
# panne qui suit est incompréhensible.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_TORCH_BACKEND=cpu

WORKDIR /app

# Les manifestes seuls d'abord, pour la même raison que côté frontend. La roue de
# torch pèse à elle seule plusieurs centaines de mégaoctets.
COPY backend/pyproject.toml backend/uv.lock ./
# `--no-install-project` : le projet lui-même n'est pas encore copié. Sans ce
# drapeau, uv échouerait à trouver `src/traffic_analysis`.
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
# `pyproject.toml` déclare `readme = "../README.md"`, hors du contexte de ce
# répertoire : hatchling échouerait à construire le paquet sans lui.
COPY README.md /README.md
RUN uv sync --frozen --no-dev


# ── 3. L'image servie ────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

# `opencv-python-headless` évite `libGL` et GTK, mais deux bibliothèques restent
# nécessaires sur une base slim, et l'absence de l'une ou l'autre ne se manifeste
# qu'au premier import — c'est-à-dire au premier job, pas au démarrage.
#   libglib2.0-0 : `libgthread-2.0.so.0`, dont OpenCV dépend même sans interface.
#   libgomp1     : OpenMP, exigé par torch et onnxruntime.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Non-root, avec un UID fixe. Fixe parce que les volumes montés héritent de ces
# droits : un UID attribué automatiquement changerait d'une reconstruction à
# l'autre, et le conteneur perdrait l'accès à ses propres données.
RUN groupadd --gid 1001 traffic \
    && useradd --uid 1001 --gid traffic --create-home --shell /usr/sbin/nologin traffic

WORKDIR /app

COPY --from=builder --chown=traffic:traffic /app/.venv /app/.venv
COPY --from=builder --chown=traffic:traffic /app/src /app/src
COPY --from=builder --chown=traffic:traffic /app/migrations /app/migrations
COPY --from=builder --chown=traffic:traffic /app/alembic.ini /app/pyproject.toml ./
COPY --from=builder --chown=traffic:traffic /app/config /app/config
COPY --from=builder --chown=traffic:traffic /app/scripts /app/scripts

# Le build du frontend, à l'emplacement que `TRAFFIC_STATIC_DIR` désigne.
COPY --from=frontend --chown=traffic:traffic /build/dist /app/static

# Créés et donnés à l'utilisateur **avant** le `USER` : un volume monté sur un
# répertoire inexistant est créé par Docker en root, et `/health/ready` — qui écrit
# réellement un fichier de test — rapporterait alors « degraded » sans que rien
# n'explique pourquoi.
RUN mkdir -p /app/data /app/.weights && chown -R traffic:traffic /app/data /app/.weights

# Les chemins sont **absolus**. Les défauts du projet (`./data`, `./.weights`) sont
# relatifs au répertoire courant, qui n'est plus garanti dès qu'on remplace la
# commande au lancement — et une base créée ailleurs qu'au point de montage se
# perdrait au premier redémarrage, silencieusement.
#
# Quatre slashes dans l'URL SQLite : trois donnent un chemin relatif, quatre un
# chemin absolu. La confusion est classique et rend une base vide à chaque
# démarrage sans qu'aucune erreur ne soit levée.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TRAFFIC_STATIC_DIR=/app/static \
    TRAFFIC_DATA_DIR=/app/data \
    TRAFFIC_WEIGHTS_DIR=/app/.weights \
    TRAFFIC_DATABASE_URL=sqlite+aiosqlite:////app/data/traffic.db \
    TRAFFIC_DEVICE=cpu \
    TRAFFIC_LOG_FORMAT=json

USER traffic

EXPOSE 8000

# En Python plutôt qu'en `curl` : cela évite d'installer un client HTTP dans
# l'image finale pour un seul usage. `/health/live` et non `/health/ready` —
# `live` dit « le processus répond », et c'est la question que pose un healthcheck
# de conteneur. `ready` écrit sur le disque, et le sonder toutes les trente
# secondes ferait des écritures pour rien.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=4)"]

# Un seul worker. Le service tient un état en mémoire — le `ProgressHub` du SSE,
# les baux de modèles, le compteur de sessions temps réel — qu'un second processus
# ne verrait pas : deux workers rendraient une progression sur deux et
# autoriseraient deux sessions « uniques » simultanées. La concurrence utile est
# déjà dans les threads worker (`anyio.to_thread`).
CMD ["uvicorn", "traffic_analysis.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
