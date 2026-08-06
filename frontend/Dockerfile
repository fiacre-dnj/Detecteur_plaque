# Le frontend **seul**, pour le développement en conteneur.
#
# À lire avec son contexte : en production, le frontend n'a pas d'image. Son build
# est copié dans celle du backend, qui le sert (`backend/Dockerfile`, étape
# `frontend`). C'est ce qui donne l'origin unique et supprime le CORS, le réglage
# de tamponnage SSE et le relais WebSocket.
#
# Cette image-ci existe pour l'autre besoin : travailler sur l'interface avec le
# rechargement à chaud, sans installer bun sur la machine. Elle n'est **jamais**
# servie à des utilisateurs — le serveur de développement de Vite n'est pas conçu
# pour cela et le dit lui-même.

FROM oven/bun:1.3-alpine

WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY . .

# `--host` est indispensable : sans lui Vite n'écoute que sur la boucle locale du
# conteneur, et le port publié ne mène nulle part. L'erreur est trompeuse — le port
# semble ouvert côté hôte et la connexion est simplement refusée.
#
# `BACKEND_URL` est lu par `vite.config.ts` pour le proxy `/api`, WebSocket compris
# (`ws: true`). Dans le compose il vaut `http://backend:8000`.
EXPOSE 5173
CMD ["bun", "run", "dev", "--host", "0.0.0.0"]
