# 00 — Contexte, périmètre et vocabulaire

## 1. Ce que fait l'application, en une phrase

Elle **compte des véhicules** dans une vidéo (fichier déposé ou flux webcam),
en s'appuyant sur un modèle YOLO choisi par l'utilisateur, et rend un résultat
vérifiable : combien de véhicules distincts, combien de franchissements par
ligne et par sens, quelles identités, à quel instant, avec quelle vitesse, et
avec quelle plaque quand l'option ANPR est active.

## 2. Une seule vue métier

L'application n'est **pas** un tableau de bord multi-modules. Il n'y a pas de
navigation entre « module plaques », « module trafic », « module statistiques ».
Il y a **un atelier de comptage** (le *Studio*) où l'on choisit une source, on
dessine la géométrie, on lance l'analyse et on lit les résultats. Une page
secondaire d'**historique** (rendue possible par la persistance SQLite) et une
page de **benchmark** sont les seuls autres écrans, atteintes par des routes
paresseuses.

La **lecture de plaques est une option de la course de comptage**, pas un
module : elle rattache une plaque à un véhicule suivi.

## 3. Les deux modes de fonctionnement (tous les deux serveur)

| Mode | Transport | Usage | Sortie |
|---|---|---|---|
| **Différé (fichier)** | `POST /api/v1/jobs` (multipart) + SSE de progression + `GET .../result` | Un clip complet, analysé **image par image** par le serveur | Une *timeline* horodatée, des événements, un registre de véhicules, des stats |
| **Direct (webcam)** | WebSocket `/api/v1/realtime` | Comptage en direct sur la caméra locale | Un résultat **par frame** (pistes + événements + stats cumulées) |

Le navigateur ne calcule jamais de détection. En mode différé il **rejoue** la
timeline sur la vidéo locale ; en mode direct il **capture et envoie** des
frames JPEG et affiche ce qui revient.

Conséquence à énoncer dans l'UI : contrairement à la version précédente,
**les images quittent la machine** (elles vont au serveur). C'est le prix du
choix « analyse backend uniquement » et cela doit être écrit dans l'interface
(infobulle du sélecteur de source et de la zone de dépôt).

## 4. Fonctionnalités attendues (liste exhaustive)

### 4.1 Source et lecture
- Dépôt d'un **fichier vidéo** (glisser-déposer + sélecteur), **vidéo de
  démonstration** servie par le frontend, **webcam**.
- Lecteur vidéo **maison** (pas la barre `controls` native, qui recouvre
  exactement la zone où l'on trace les lignes) : lecture/pause, timeline,
  ±1 s / ±10 s, pas-à-pas image par image, vitesses 0,1× à 2×.
- La vidéo **ne boucle jamais**.

### 4.2 Géométrie de comptage
- **Lignes de comptage** multiples, nommées, colorées, déplaçables (corps et
  poignées A/B), optionnellement **liées à une zone**.
- **Zones polygonales** multiples, dessinées à la souris (clic par sommet,
  fermeture par double-clic ou par clic sur le premier sommet, `Échap` annule),
  sommets et corps déplaçables.
- Option **« ignorer hors zone »** : les zones deviennent la région d'intérêt,
  ce qui est en dehors n'est ni détecté, ni suivi, ni compté (visualisé par un
  assombrissement en règle *even-odd*).
- **Enregistrement et rechargement de presets de géométrie** (nouveau, permis
  par la persistance) : une intersection filmée deux fois se configure une
  seule fois.

### 4.3 Analyse et comptage
- Détection + suivi multi-objets côté serveur avec ReID d'apparence.
- Comptage **par ligne et par sens**, dédupliqué **par identité et par sens**.
- Comptage **par zone** : entrées uniques + occupation instantanée.
- **Ré-identification longue durée** : un véhicule occulté puis revenu reste le
  même véhicule (`uniqueVehicles` ≠ `crossings`).
- **Vote de classe majoritaire** : un véhicule est compté sous la classe que le
  détecteur lui a donnée le plus souvent, jamais sous la lecture d'une image.
- Quatre classes COCO comptées à l'identique : `car` (2), `motorcycle` (3),
  `bus` (5), `truck` (7).
- **Estimation de vitesse** par identité, en px/s, convertie en km/h
  **seulement** si l'utilisateur fournit une échelle px/m.
- **Pas d'analyse** (`frameStride`) réglable : 1 = toutes les images.
- **Annulation** d'un job en cours.

### 4.4 ANPR (option)
- Passe secondaire : recadrage de chaque véhicule suivi, puis modèle de plaques
  sur le crop. Les boîtes reviennent en coordonnées de l'image complète.
- Le meilleur score de plaque par identité est conservé et affiché dans le
  registre.
- Le seuil de confiance plaque est réglable.

### 4.5 Modèles
- **Catalogue large** : familles YOLOv8, YOLO11, YOLO12, YOLO26, tailles n/s/m/l/x
  (voir [`04`](04-MODELES-YOLO-ET-BENCHMARK.md) pour la liste exacte) + le
  modèle de plaques.
- Sélecteur groupé par palier (nano / small / medium / large / xlarge) avec
  entêtes collantes, navigation clavier, taille et note par modèle.
- **Benchmark serveur** : mesure réelle de chaque modèle sur la machine du
  serveur (médiane de N runs, chauffe écartée), progression en direct, résultats
  persistés et réaffichés au retour sur la page.
- Éviction LRU des modèles résidents, préchauffage du modèle par défaut.

### 4.6 Résultats et restitution
- Cartes de synthèse : véhicules uniques, franchissements, ré-identifications,
  débit estimé (/min), objets suivis, cadence de traitement.
- Répartition par type (uniques + passages) et **détail par ligne** (par sens)
  et **par zone** (entrées uniques + présents).
- **Histogramme de flux** par tranches adaptatives.
- **Registre des véhicules** : une ligne par identité — vu de/à, lignes
  franchies avec le sens, vitesse, nombre de ré-identifications, plaque.
- **Relecture synchronisée** : boîtes, trajectoires, badges et compteurs suivent
  la tête de lecture ; reculer dans la vidéo affiche les compteurs **de cet
  instant**, pas les totaux finaux.
- **Export** : JSON complet et **CSV** (registre des véhicules, franchissements).
- **Historique des analyses** persisté : relire un résultat sans relancer.

### 4.7 Diagnostic
- Panneau de réglages du comptage (seuils, gate d'association, `minHits`,
  durée de survie d'une piste, similarité de ré-identification) et **lecture
  live du diagnostic** : détections fortes / faibles, masquées par zone, pistes
  confirmées / provisoires. Une piste non confirmée est dessinée **en
  pointillés** avec un badge `…`.
- État du backend visible en permanence : joignable ou non, device (CPU/CUDA),
  version d'Ultralytics, modèles résidents.

## 5. Hors périmètre — explicitement

- **Aucune inférence navigateur.** Pas d'`onnxruntime-web`, pas de WebGPU/WASM,
  pas de repli local, pas de « garantie aucune image ne quitte la machine ».
- Pas d'authentification multi-utilisateurs (mais l'API doit être *prête* :
  point d'extension documenté, en-têtes et CORS déjà stricts).
- Pas d'OCR du texte de plaque (on **localise** la plaque, on ne lit pas les
  caractères) — point d'extension documenté.
- Pas de multi-caméra simultanée, pas de RTSP (point d'extension).
- Pas de déploiement Kubernetes : Docker + docker-compose suffisent.

## 6. Vocabulaire (à respecter dans le code et l'UI)

| Terme | Sens précis |
|---|---|
| **Détection** | Une boîte + un score + une classe sur une image |
| **Piste** (*track*) | Une suite de détections associées par le suivi, portant un `trackId` local au moteur |
| **Identité** (*globalId*) | Ce qui survit à la disparition d'une piste. Deux pistes successives du même véhicule partagent une identité |
| **Franchissement** (*crossing*) | Passage effectif d'une identité au travers du **segment** d'une ligne, avec un sens ±1 |
| **Entrée de zone** | Front dehors→dedans d'une identité, dédupliqué |
| **Occupation** | Nombre de pistes à l'intérieur d'une zone **à cet instant** (lecture, pas cumul) |
| **Temps de scène** | ms sur la timeline média. `frame_index / fps × 1000` |
| **Timeline** | La suite des frames analysées, chacune avec ses pistes figées |
| **Registre** | L'agrégat par identité sur toute la session |
| **Studio** | L'écran unique de comptage |
| **Palier** (*tier*) | nano / small / medium / large / xlarge |

## 7. Critères d'acceptation globaux du projet

1. `uv run pytest`, `uv run ruff check .`, `uv run mypy src` passent au vert.
2. `bun run lint`, `bun run typecheck`, `bun run test`, `bun run build` passent
   au vert.
3. Un clip de démonstration analysé en mode différé produit des compteurs
   cohérents : `crossings` = somme de `byLine[*].total`, et
   `byLine[*].total` = `positive + negative`.
4. Reculer dans la vidéo fait **baisser** les compteurs affichés.
5. Déplacer une ligne après une analyse affiche l'avertissement « résultat
   obsolète ».
6. Le backend arrêté ⇒ le frontend le dit clairement et désactive le bouton
   d'analyse, sans page blanche ni erreur console.
7. Aucun poids de modèle (`.pt`, `.onnx`) n'est présent dans l'historique git.
8. `/api/docs` documente chaque endpoint avec au moins un exemple de réponse.
