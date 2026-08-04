# Prompt de reconstruction — application de comptage de véhicules

Ce dossier **est le prompt**. Il décrit, de bout en bout, l'application à
construire depuis un dépôt vide : un service d'analyse vidéo qui compte des
véhicules (détection + suivi + ré-identification + franchissement de lignes),
lit les plaques en option (ANPR) et permet de comparer plusieurs modèles YOLO,
avec **toute l'inférence côté backend Python** et un frontend React qui pilote,
visualise et rejoue.

> **À l'agent qui exécute ce prompt** : lis les fichiers dans l'ordre, puis
> suis [`12-PLAN-EXECUTION.md`](12-PLAN-EXECUTION.md). Ce dossier est
> normatif : quand un fichier dit « obligatoire », « jamais », « exactement »,
> ce n'est pas une préférence de style, c'est une contrainte qui a coûté un bug
> dans la version précédente de l'application. Si tu penses qu'une contrainte
> est fausse, dis-le explicitement avant de l'ignorer.

## Ordre de lecture

| # | Fichier | Ce qu'il fixe |
|---|---|---|
| 00 | [`00-CONTEXTE-ET-PERIMETRE.md`](00-CONTEXTE-ET-PERIMETRE.md) | Le produit, le vocabulaire, le périmètre, ce qui est explicitement hors périmètre |
| 01 | [`01-STACK-ET-OUTILLAGE.md`](01-STACK-ET-OUTILLAGE.md) | Versions, gestionnaires de paquets, scripts, arborescence racine, Docker |
| 02 | [`02-ARCHITECTURE-BACKEND.md`](02-ARCHITECTURE-BACKEND.md) | Architecture par feature + hexagonale, design patterns, injection de dépendances, conventions Python senior |
| 03 | [`03-DOMAINE-COMPTAGE.md`](03-DOMAINE-COMPTAGE.md) | **Le cœur** : géométrie, suivi, comptage, zones, ré-identification, vitesse. Chaque règle et sa raison d'être |
| 04 | [`04-MODELES-YOLO-ET-BENCHMARK.md`](04-MODELES-YOLO-ET-BENCHMARK.md) | Catalogue de modèles, registre + LRU, poids, ANPR, benchmark serveur |
| 05 | [`05-API-ET-CONTRAT.md`](05-API-ET-CONTRAT.md) | Tous les endpoints, schémas, SSE, WebSocket, format d'erreur |
| 06 | [`06-SECURITE-CORS-SWAGGER.md`](06-SECURITE-CORS-SWAGGER.md) | CORS avancé, en-têtes de sécurité, limitation de débit, OpenAPI/Swagger avancé |
| 07 | [`07-PERSISTANCE-SQLITE.md`](07-PERSISTANCE-SQLITE.md) | SQLAlchemy 2.0 async, modèle de données, Alembic, repositories, rétention |
| 08 | [`08-ARCHITECTURE-FRONTEND.md`](08-ARCHITECTURE-FRONTEND.md) | Feature-Sliced Design React, patterns, état serveur, lazy loading, conventions TS senior |
| 09 | [`09-FRONTEND-UX-FONCTIONNALITES.md`](09-FRONTEND-UX-FONCTIONNALITES.md) | Écran par écran, composant par composant, interactions et copies FR |
| 10 | [`10-TESTS-QUALITE-CI.md`](10-TESTS-QUALITE-CI.md) | Stratégie de test des deux côtés, lint/types, CI, critères de couverture |
| 11 | [`11-GIT-ET-CONVENTIONS.md`](11-GIT-ET-CONVENTIONS.md) | Branches, Conventional Commits, granularité, PR, hooks, ce qui ne doit jamais être committé |
| 12 | [`12-PLAN-EXECUTION.md`](12-PLAN-EXECUTION.md) | Le plan en 14 lots, avec définition de « terminé » et le commit attendu par lot |
| 13 | [`13-PIEGES-CONNUS.md`](13-PIEGES-CONNUS.md) | Les pièges déjà payés — à relire avant de déboguer quoi que ce soit |

## Les cinq décisions déjà prises (ne pas les rediscuter)

1. **Analyse 100 % backend.** Aucune inférence dans le navigateur, aucune
   dépendance `onnxruntime-web`, aucun « mode navigateur ». Le frontend envoie
   une vidéo ou des frames, reçoit une timeline, la rejoue.
2. **Python 3.12 épinglé**, pas 3.14. PyPI ne publie pas de wheels `cp314`
   pour `torch` (cp310→cp313 seulement) et aucune roue CUDA pour 3.14 :
   Ultralytics ne s'installe pas. Voir [`01`](01-STACK-ET-OUTILLAGE.md#pourquoi-python-312-et-pas-314).
3. **Persistance SQLite + SQLAlchemy** (async, avec Alembic). Les jobs, les
   résultats agrégés, les véhicules, les événements et les benchmarks
   survivent au redémarrage. Voir [`07`](07-PERSISTANCE-SQLITE.md).
4. **Fonctionnalités portées** : comptage vidéo complet, ANPR, benchmark des
   modèles, large catalogue YOLO (familles v8 / 11 / 12 / 26, tailles n → x).
5. **Architecture par feature** des deux côtés, code clean, français pour
   l'UI et la documentation.

## Règles transverses valables partout

- **Le temps est du temps de scène.** Tous les horodatages métier sont des
  millisecondes de la timeline média (`frame_index / fps × 1000`), jamais
  l'horloge murale. Toute la justesse des débits, des vitesses et des gates de
  ré-identification en dépend.
- **Les coordonnées sont en pixels de la vidéo source.** Jamais en pixels
  modèle, jamais en pixels CSS. Les conversions se font aux frontières
  (letterbox côté modèle, mise à l'échelle au dessin côté canvas).
- **Un compteur affiché est dérivé, jamais accumulé en double.** Le total
  d'une page se recalcule depuis le détail ; deux compteurs indépendants
  finissent toujours par se contredire.
- **Le code parle français à l'utilisateur, anglais au compilateur.**
  Identifiants et types en anglais, docstrings/commentaires et copies d'UI en
  français.
- **Pas de code mort, pas de « au cas où ».** Une abstraction n'existe que si
  elle a au moins deux implémentations réelles ou un test qui l'exige.
