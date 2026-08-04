# ADR 0003 — Toute l'inférence côté backend, et retrait de COOP/COEP

- **Statut** : accepté
- **Date** : 2026-08-05

## Contexte

La version précédente portait un pipeline d'inférence complet dans le
navigateur : session ONNX Runtime Web, cascade WebGPU → WASM, letterbox, décodage
de sortie YOLO, NMS, tracker à centroïdes, galerie de ré-identification, et un
benchmark client. L'argument de vente était « aucune image ne quitte votre
machine ».

Le coût réel : deux implémentations du comptage à maintenir en accord, un modèle
de plusieurs dizaines de Mo servi au navigateur, des performances dépendant du
GPU et du pilote du visiteur, et l'obligation de servir la page avec
`Cross-Origin-Embedder-Policy: require-corp` pour obtenir `SharedArrayBuffer`.

## Décision

L'inférence est **exclusivement côté serveur**. Le navigateur envoie une vidéo ou
des frames JPEG, reçoit une timeline, la rejoue. Interdits explicites :
`onnxruntime-web`, WebGPU/WASM, tout « mode local » ou repli navigateur.

Conséquence directe : **COOP/COEP `require-corp` est retiré.** Le besoin de
`SharedArrayBuffer` disparaît avec ONNX Runtime Web. COEP casse le chargement de
ressources qui ne portent pas les bons en-têtes, sans rien apporter ici. Les
en-têtes conservés sont `Cross-Origin-Opener-Policy: same-origin` et
`Cross-Origin-Resource-Policy: same-origin`, qui isolent sans rien casser.

## Conséquences

- **Les images quittent la machine.** C'est le prix du choix, et il doit être
  **écrit dans l'interface** — infobulle du sélecteur de source et de la zone de
  dépôt. Une promesse de confidentialité retirée en silence serait un mensonge.
- Un seul comptage existe, en Python, testé. Le frontend garde une copie
  **minimale** de la géométrie (`sideOfLine`, `pointInPolygon`,
  `distanceToSegment`) qui sert au dessin et au test de sélection à la souris, et
  **qui ne compte rien** ; un test vérifie qu'elle donne le même signe que la
  convention backend, sinon les flèches de sens affichées mentiraient.
- Le serveur devient une ressource finie : bornes de concurrence, baux de
  modèles, plafond de résidence mémoire, limitation de débit.
- Le déploiement de production sert le build frontend **depuis le backend**
  (`TRAFFIC_STATIC_DIR`) : un seul origin, donc aucun CORS à ouvrir pour l'usage
  normal.
