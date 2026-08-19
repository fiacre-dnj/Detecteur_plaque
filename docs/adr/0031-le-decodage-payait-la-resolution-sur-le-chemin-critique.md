# ADR 0031 — La résolution ne coûtait qu'une chose : le décodage, et il attendait le GPU

- **Statut** : accepté
- **Date** : 2026-08-19
- **Complète** : [ADR 0013](0013-le-cout-du-pipeline-de-comptage.md), dont il reprend
  le banc et l'annonce du « prochain budget », et
  [ADR 0030](0030-le-detecteur-de-plaques-payait-une-inference-par-vehicule.md), dont
  il ne touche pas les deux étages de plaques.

## Contexte

« Plus la vidéo a une forte résolution, plus l'analyse perd des images par
seconde. » Le constat était juste et sa cause inconnue : ADR 0013 avait mesuré le
pipeline sur **trois vidéos 720p**, donc à résolution constante, et son partage ne
pouvait rien dire de ce qui se passe à 1440p ou en 4K.

**Et le banc qui devait répondre ne démarrait plus.** `scripts/pipeline_bench.py`
appelait `resolved_tracker_config(gmc_method)` avec un seul argument depuis
qu'[ADR 0024](0024-le-detecteur-descend-sous-le-seuil-de-l-utilisateur.md) lui avait
ajouté le seuil de la requête : `TypeError` avant la première image. Un outil de
mesure cassé n'est pas un outil dégradé, c'est l'absence de mesure — et sans mesure,
toute optimisation est un pari. Il est réparé, et il sait désormais faire trois
choses qu'il ne savait pas : mesurer une **échelle de résolution**, mesurer les
**deux étages de plaques**, et compter le **volume de travail** qu'ils reçoivent.

## La mesure

Une même scène réencodée à quatre paliers (`--ladder 720,1080,1440,2160`), donc à
**contenu identique** : c'est ce qui rend les comptages comparables et permet
d'attribuer un écart de cadence à un écart de coût plutôt qu'à un écart de scène.
`yolov8n`, GPU Quadro P1000, 120 images mesurées après 15 de rodage, sans ANPR.

| palier | img/s | ms/image | décodage | inférence | prétraitement | comptage |
|---|---|---|---|---|---|---|
| 720p  | 58,5 | 17,1 | **3,2** (18,8 %) | 8,01 | 2,3 | 2 véhicules |
| 1080p | 47,0 | 21,3 | **6,9** (32,6 %) | 8,00 | 2,8 | 2 |
| 1440p | 35,4 | 28,3 | **12,6** (44,5 %) | 8,01 | 3,2 | 2 |
| 2160p | 27,0 | 37,1 | **21,7** (58,6 %) | 8,00 | 3,0 | 2 |

Trois choses se lisent d'un coup :

- **l'inférence ne bouge pas d'un dixième de milliseconde.** L'entrée du réseau vaut
  640 quelle que soit la source (`inference_imgsz`), donc une 4K est réduite à la même
  taille qu'une 720p avant d'atteindre la carte. La résolution n'achète **rien** au
  détecteur de véhicules — elle n'achète que des plaques (voir plus bas) ;
- **le prétraitement non plus**, ou presque : 2,3 → 3,0 ms du 720p au 4K. Le
  letterbox d'une image 4K vers 640 est bon marché, et ce n'était pas l'intuition ;
- **tout le reste est le décodage**, qui suit le nombre de pixels. Le poste est obtenu
  *par différence* dans le banc, donc il ne prouve rien tout seul : chronométré
  séparément sur le même fichier 4K, `read()` seul coûte **20,9 ms** contre 21,7
  annoncées par différence. La colonne **est** le décodage.

De 720p à 2160p, la cadence tombe de 2,17× et **la totalité de la perte est du
décodage**, c'est-à-dire du travail CPU exécuté pendant que la carte attend.

## Décision — un fil de décodage, un lot d'avance, un seul chemin

`iter_video` avait deux chemins et ils partageaient ce défaut : le décodage de l'image
suivante attendait l'inférence de la précédente. Le chargeur d'Ultralytics décode dans
la boucle du prédicteur ; le chemin « avec borne de début » décodait lui-même, image
par image, **sans lot du tout**.

Il n'y a plus qu'un chemin : `decode_ahead` décode dans un fil séparé et rend des
**lots d'images consécutives**, que `model.track(source=[…])` traite en un appel. Le
plafond devient `max(décodage, GPU)` au lieu de leur somme.

| palier | avant | après | gain | décodage |
|---|---|---|---|---|
| 720p  | 58,5 | **64,0** | 1,09× | 3,2 → 1,2 ms |
| 1080p | 47,0 | **58,4** | **1,24×** | 6,9 → 1,2 ms |
| 1440p | 35,4 | **59,0** | **1,67×** | 12,6 → 1,6 ms |
| 2160p | 27,0 | **39,7** | **1,47×** | 21,7 → 7,8 ms |

**Comptage identique sur les quatre paliers**, et la cadence est devenue **plate de
720p à 1440p** (64,0 / 58,4 / 59,0 img/s — l'écart tient dans les ±20 % de variation
thermique que cette machine impose à toute mesure, ADR 0013).

Avec ANPR **et** OCR actives, sur la même scène :

| palier | avant | après | plaques publiées |
|---|---|---|---|
| 720p  | 20,25 | 20,00 | 0 → 0 |
| 2160p | 16,25 | **20,89** (1,29×) | `8254S` → `8254S` |

Le 720p ne gagne rien, et c'est attendu : l'étage de plaques y coûte 32 ms, les 2 ms
de décodage économisées se perdent dans le bruit. Le point qui compte est l'autre —
**720p et 2160p tournent désormais à la même cadence**, la résolution ne se paie plus.

Le lot mérite une justification propre. Vérifié dans la roue installée
(`ultralytics/trackers/track.py`, 8.4.115) : hors mode `stream`, Ultralytics ne crée
**qu'un** tracker et l'applique aux résultats dans l'ordre d'entrée. Le lot reste donc
neutre pour le suivi — c'est ce que le commentaire du moteur affirmait déjà pour
`batch=4`, et cela vaut identiquement pour une liste d'images. Le chemin avec borne de
début, qui n'avait aucun lot, en gagne un au passage.

## Ce que la vérification a montré

- **compteurs identiques** aux quatre paliers, plaque publiée identique, et
  `nearMisses` inchangés — le signal qui monte avant tout total quand le suivi se
  dégrade ;
- **l'inférence reste à 8,00 ms**, ce qui prouve que la forme d'entrée n'a pas changé :
  une liste d'images de même taille garde `rect=True`, donc 640×384 et non 640×640 —
  ce dernier aurait coûté ~1,7× ;
- **contre le vrai serveur**, ANPR et OCR actives, fenêtre de 8 s d'une 4K : 421 images,
  4 véhicules, plaque `8254S` publiée, exactement ce que le banc annonce ;
- **une annulation en vol rend la main en 0,30 s.** C'est le mode de panne propre au
  fil : le consommateur cesse de lire au milieu, et un `put` sans expiration
  laisserait le fil vivant sur un décodeur ouvert. Le producteur redemande donc la
  permission de continuer à chaque expiration, et un test le vérifie avec une file
  volontairement pleine.

## Ce qui a été essayé et rejeté, avec la mesure

Ne pas re-proposer ces pistes sans lire ce qui suit.

**L'accélération matérielle du décodage par OpenCV** (`CAP_PROP_HW_ACCELERATION =
VIDEO_ACCELERATION_ANY`). Elle est **acceptée** — la propriété relue vaut 2, donc
D3D11 — et elle est **2,3× plus lente** : 13,70 ms contre 5,87 par image sur le vrai
H.264 1080p du dépôt. La cause est le rapatriement : la surface décodée vit en mémoire
graphique et doit revenir en mémoire système, puis être convertie, pour qu'OpenCV rende
un tableau BGR. Le NVDEC ne gagnerait ici qu'en restant sur la carte jusqu'à
l'inférence, ce qu'aucun chemin d'OpenCV ne permet.

**Borner les threads du décodeur FFmpeg** (`CAP_PROP_N_THREADS`). Sans effet : 5,49 ms
à 4 threads, 5,51 à 8, contre 5,87 par défaut (12) — soit le bruit de mesure.

**Faire le letterbox dans le fil de décodage.** C'était le troisième levier prévu, et
la mesure l'a écarté avant écriture : le prétraitement vaut 2,3 ms en 720p et 3,0 ms
en 4K, donc il **n'est pas la taxe de résolution**. Pire, il est passé à 3,2–4,9 ms
*après* le fil de décodage — la contention CPU entre les deux — et y déplacer du
travail supplémentaire aggraverait exactement le palier où le décodage est déjà le
facteur limitant. Le gain plafonnait à 3 ms et le risque était une conversion de
repère de boîtes.

## Ce que cela ne corrige pas

**À 2160p, le décodage reste le facteur limitant** : 21 ms contre ~16 ms pour toute la
chaîne GPU, d'où les 7,8 ms qui dépassent encore. Deux précisions avant d'en conclure
quoi que ce soit :

- **le palier 4K de l'échelle est un fichier `mp4v`**, pas du H.264 : la roue OpenCV de
  cette machine n'embarque pas d'encodeur H.264 (`libopenh264` absent), donc le banc
  réencode en MPEG-4 partie 2, un format **sans découpage en tranches**, donc sans
  parallélisme d'images à l'intérieur du décodeur. Un vrai fichier 4K H.264 décode sur
  douze threads et serait probablement recouvert en entier. Le dépôt n'en contient
  aucun : la question reste ouverte et **mesurable dès qu'un tel fichier existe** ;
- le levier suivant, s'il en faut un, est un second fil de décodage sur des positions
  entrelacées, ou une bibliothèque de décodage matériel sans rapatriement. Les deux
  demandent une dépendance ou une complexité qu'aucune mesure ne justifie encore.

**La résolution reste productive pour les plaques, et le banc le chiffre désormais.**
Sur la même scène, avec OCR :

| palier | vignettes OCR par image | plaques publiées | coût de l'étage de plaques |
|---|---|---|---|
| 720p  | **0,00** | 0 | 32,3 ms |
| 2160p | 0,01 | 1 (`8254S`) | **20,6 ms** |

En 720p l'OCR ne tourne **jamais** : les plaques sont sous le plancher de lecture de
64 px (invariant 12). En 4K elle tourne, publie — et **l'étage de plaques coûte moins
cher**, parce qu'un vote acquis arrête le détecteur (`stop_when_confident`, ADR 0010).
La haute résolution n'est donc pas seulement une taxe : elle est ce qui rend l'ANPR
utile, et son surcoût de décodage est précisément ce que le présent ADR supprime.

## Conséquences

- le décodage ne dépend plus du chargeur d'Ultralytics : `probe`, le déplacement
  vérifié et le pas d'analyse vivent dans `_iter_decoded`, une fonction **pure et sans
  fil**, donc testable par la CI — qui n'a ni GPU ni poids mais a OpenCV. Quatorze
  tests neufs y verrouillent l'index, le déplacement, la fin de fil et la propagation
  d'erreur ;
- **il n'y a plus qu'un appel à `model.track()` en différé**, contre deux, et
  `test_engine_arguments.py` le compte exprès : chaque nouveau chemin doit d'abord
  prouver qu'il porte `agnostic_nms`, `classes` et `persist` ;
- la file est bornée en **octets** (`DECODE_BUDGET_BYTES`, 128 Mo) et non en images :
  une image 4K pèse neuf fois une image 720p, donc « quatre images d'avance » ne veut
  pas dire la même chose d'un cas à l'autre ;
- **`TRAFFIC_INFERENCE_THREADS` devient un réglage plus intéressant qu'avant** : le
  prétraitement et le fil de décodage se disputent désormais les mêmes cœurs, ce qui
  explique une partie du gain non réalisé en 720p et 1080p. Le banc le chiffre chez
  l'exploitant ; le dépôt ne fige rien ;
- `build_counting_stack` est extrait de `build_container` : le banc assemble
  l'`AnalysisService` par **le même** code que le service. Recopier ce câblage — une
  quinzaine de réglages — aurait produit au premier oubli un rapport décrivant un
  pipeline que personne n'exécute.
