# ADR 0060 — La définition d'analyse devient un réglage de l'utilisateur

- **Statut** : accepté
- **Date** : 2026-09-03
- **Achève**
  [ADR 0037](0037-le-plancher-du-detecteur-suit-le-curseur-quand-il-descend.md), qui a
  nommé cette cause sans pouvoir la corriger : le réglage n'existait ni dans la requête
  ni à l'écran.
- **Même doctrine qu'**
  [ADR 0036](0036-la-confiance-de-lecture-devient-un-reglage-de-l-utilisateur.md).

## Le symptôme

« On a du mal à détecter les motos. » L'utilisateur descend « Confiance véhicules », ne
voit rien changer, et n'a **aucun autre curseur à tourner**.

## Ce qui décide vraiment

Le commentaire de `core/settings.py` le disait déjà, à l'endroit où personne ne le
lit :

> Il se paie sur les véhicules **petits et lointains** : ce qui décide qu'un objet est
> détecté n'est pas sa taille dans la vidéo mais sa taille **dans l'entrée du réseau**.

`rect=True` est imposé par Ultralytics en prédiction (`engine/model.py`, l'override
`predict` bat le `rect: False` de `cfg/default.yaml`). Une source 16:9 entre donc en
**640×384**, et l'arithmétique de `LetterBox` donne, sur du 1920×1080 :

| imgsz | tenseur | aire | moto de 60 px | piéton de 30 px |
|---|---|---|---|---|
| 640 | 640×384 | ×1,00 | **20 px** | **10 px** |
| 960 | 960×544 | ×2,13 | 30 px | 15 px |
| 1280 | 1280×736 | ×3,83 | 40 px | 20 px |

Vingt pixels, c'est moins de trois cellules de la grille P3 (stride 8) et une aire très
en dessous du plancher « small » de COCO (32²).

**Corollaire mesuré, et contre-intuitif** : la taille dans le tenseur vaut
`fraction de l'image × imgsz`. **Filmer plus défini n'achète donc rien au détecteur**
tant qu'`imgsz` ne bouge pas — ce qu'ADR 0031 avait mesuré sans en donner la cause.

Confirmé sur du métrage réel avec `recall_bench.py`, 25 images d'un clip 720p, `yolov8n`
à 640 contre `yolo11x` à 1280 : rappel `car` **0,481**, avec les **27 manqués tous dans
le seau 32-64 px** et les **25 réussites toutes au-delà de 128 px**. Sur des voitures.
Les motos et les piétons sont plus petits encore.

## Le réglage ne vaut rien seul, et c'est mesuré

**La correction la plus importante de ce document.** Il a d'abord présenté la définition
d'analyse comme « le levier décisif ». Mesuré avec `recall_bench.py` sur une vidéo réelle
(720p, 30 images, 62 instances de vérité, `yolov8n` contre `yolo11x@1280`) :

| imgsz | « Confiance véhicules » | rappel |
|---|---|---|
| 640 | 0,35 *(défauts)* | 0,484 |
| 640 | 0,12 | **0,484** |
| 960 | 0,35 | **0,484** |
| 1280 | 0,35 | **0,484** |
| 960 | 0,20 | **0,790** |
| 1280 | 0,12 | 0,806 |

**Aucun des deux réglages ne rend quoi que ce soit seul.** Ensemble, le rappel passe de
0,484 à 0,790 — les manqués du seau 32-64 px tombent de 32 à 13.

La chaîne, vérifiée étage par étage :

- **à 640, l'objet n'est pas détecté du tout.** Baisser le seuil ne peut rien filtrer de
  moins : il n'y a rien. Le même `predict` sur une image du clip rend **1 boîte à 640, 2 à
  960, 5 à 1280** ;
- **à 960, il est détecté mais score entre 0,12 et 0,35.** Le curseur part dans le fichier
  de suivi sur `new_track_thresh` (ADR 0024) : sous lui, une détection **prolonge** une
  piste mais n'en **ouvre** jamais. Elle n'atteint donc jamais le domaine ;
- **l'écart entre les deux étages du banc le montre directement** : à imgsz 1280,
  `--stage detector` rend 0,806 et `--stage tracked` rend 0,484. Le détecteur trouve
  20 objets de plus, et le tracker les jette tous.

`fuse_score: false` a été testé sur ce cas et **ne rachète rien** (0,484 à imgsz 1280) :
le mur d'association de `test_naissance_de_piste.py` est réel mais n'est pas ce qui
bloque ici. C'est bien la porte de création de piste.

### Ce que le rappel seul cachait

Le paragraphe ci-dessus a d'abord conclu sur le rappel seul, et **c'est ce qui a failli
faire changer un défaut**. Un banc de rappel pousse toujours dans le même sens : baisser
un seuil l'augmente mécaniquement. `recall_bench.py` compte désormais aussi les
candidats non appariés :

| imgsz | conf | rappel `car` | précision `car` | F1 | effet de bord |
|---|---|---|---|---|---|
| 640 | 0,35 *(défauts)* | 0,484 | **1,000** | 0,652 | aucun |
| 960 | 0,35 | 0,484 | 1,000 | 0,652 | aucun |
| **960** | **0,20** | **0,790** | 0,860 | **0,824** | **17 `bus` inventés** |
| 960 | 0,12 | 0,790 | 0,583 | 0,671 | pire partout |

Trois choses qu'on ne voyait pas :

- **le compromis reste favorable** — F1 0,652 → 0,824. Le rappel gagne 63 % et la
  précision n'en perd que 14, parce que **le tracker filtre les détections instables** :
  mesuré au détecteur nu, la précision tombe à 0,707 au même réglage. C'est l'écart
  entre `--stage detector` et `--stage tracked`, et il joue ici en faveur du réglage ;
- **le modèle invente une classe.** À 0,20, 17 observations de `bus` sur un clip qui
  n'en contient aucun. Probablement **un** objet fantôme suivi pendant dix-sept images
  plutôt que dix-sept fantômes — le banc compte des observations, pas des véhicules —
  mais un compteur affichera un bus qui n'est jamais passé ;
- **0,12 est franchement mauvais** : même rappel qu'à 0,20, précision effondrée. Il
  existe donc un optimum, et il n'est pas au plus bas.

**Le défaut n'est pas changé.** Le gain est réel mais son effet de bord dépend de la
scène et des classes cochées, et il est mesuré sur 62 instances d'un seul clip. Le
réglage est exposé, documenté et chiffré ; le choix appartient à qui regarde sa vidéo.

**Réserves à ne pas taire** : 62 instances, sous le seuil de 200 que le banc exige
lui-même — la direction est nette, la valeur exacte ne l'est pas ; ce sont des
**voitures** et non des motos, plus petites encore ; et la « vérité » est un modèle
COCO, donc une partie des faux positifs peut être de vrais objets qu'elle a manqués.

## La décision

`inferenceImgsz` voyage dans la requête, `null` suivant le défaut du déploiement — la
convention exacte de `confidenceThreshold` et `plateConfidence`.

C'est un arbitrage de **scène**, pas de machine, et c'est ce qui le fait basculer côté
requête : un plan large sur un carrefour lointain a besoin de 960 là où une caméra à
trois mètres n'y gagnerait rien et paierait ×2,1.

### Un choix, jamais un curseur

Le côté doit être **multiple de 32**, le pas de la grille du réseau. Trois valeurs :
640, 960, 1280, plus « Serveur ». Un curseur continu inviterait à taper 500 — que le
schéma refuse par un 422, et que `pipeline_bench.py` arrondirait à 512 **en silence**.

`1920` n'est pas proposé bien que le serveur l'accepte. **La raison est le débit, pas la
VRAM** — ce paragraphe a d'abord annoncé une crête extrapolée de ~2,8 Gio, et la mesure
l'a démenti : à lot 1, l'allocation torch vaut 40 Mio à 960, 61 à 1280 et **121 à 1920**.
Ce qui ne passe pas, c'est le temps.

## Le coût, mesuré, et il n'est pas quadratique

Ce document a d'abord annoncé un coût suivant l'aire du tenseur. Mesuré sur la Quadro
P1000, carte chaude, `yolov8n` sur une source 1080p, `predict` de bout en bout :

| imgsz | ms/image | img/s | aire | **coût réel** |
|---|---|---|---|---|
| 640 | 19,1 | 52,3 | ×1,00 | ×1,00 |
| 960 | 24,6 | 40,7 | ×2,13 | **×1,29** |
| 1280 | 40,0 | 25,0 | ×3,83 | **×2,09** |
| 1920 | 74,9 | 13,4 | ×8,50 | **×3,92** |

Le coût croît en gros comme l'aire **à la puissance 0,65**, pas linéairement : la carte
est à p50 50 % d'utilisation à 640 (décision 37), donc un tenseur plus grand la remplit
mieux au lieu de coûter proportionnellement. 960 coûte **+29 %**, pas +113 %.

### Le réglage est affiché dans le récapitulatif

Toujours, sans avertissement. Ce n'est pas une conséquence à annoncer, c'est un fait :
ce réglage **rend deux jobs incomparables** sans qu'on le lise, et il était jusqu'ici une
variable d'environnement identique pour tout le monde.

### Un avertissement pour les petits objets

Le jumeau de celui des plaques, quand `motorcycle`, `bicycle` ou `person` est coché :

> Moto est le plus petit objet de COCO. Ce n'est pas leur taille dans la vidéo qui
> décide qu'ils sont détectés, c'est leur taille dans l'entrée du réseau : monter
> « Définition d'analyse », baisser « Confiance véhicules » ou resserrer le plan sont
> les trois gestes qui en récupèrent.

Une conséquence et trois gestes, jamais un interdit — `canAnalyse` reste le seul juge.

Deux précautions, chacune tenue par un test :

- **il ne recopie aucune dimension de tenseur.** Écrire « 640×384 » était tentant et
  deviendrait faux dès que la définition change. Même précaution que
  `PLATE_READABLE_MIN_SOURCE_HEIGHT`, qui n'affirme qu'une hauteur de source ;
- **le tri se fait sur le nom COCO** (`SMALL_CLASSES` dans `shared/lib/classes.ts`),
  jamais sur le libellé français. Deviner « ce nom ressemble à une moto » depuis une
  chaîne traduite cesserait d'être vrai au premier renommage.

## Ce que ce champ n'est pas

**Le seul champ d'`EngineSpec` qui ne soit pas un simple indice.** `start_ms` et
`max_lost_ms` sont des optimisations : un moteur qui les ignore produit les mêmes
chiffres, parce que le service et le domaine appliquent la règle de leur côté. Ici il
n'y a pas de règle équivalente en aval — un moteur qui ignore `imgsz` rend d'autres
détections, donc d'autres chiffres.

Cela ne casse pas la testabilité du projet : le `FakeEngine` de la CI ne produit aucune
image, donc la question ne se pose pas pour lui. Mais la propriété « un moteur peut
ignorer toute la spec » cesse d'être vraie, et c'est écrit à sa place.

## Conséquences

- **rien ne change par défaut** : `null` suit `TRAFFIC_INFERENCE_IMGSZ`, inchangé à 640 ;
- **le direct suit la requête aussi.** Les deux modes doivent détecter à la **même**
  résolution — c'est un invariant du projet — donc le flux lit `self._spec.imgsz` et non
  la constante du moteur, qui aurait justement fait diverger les deux ;
- **le coût suit l'aire du tenseur**, ×2,1 à 960 et ×3,8 à 1280. Contrepoids mesuré :
  la carte est à p50 50 % d'utilisation (décision 37), donc la première montée est
  partiellement gratuite. À `analysisSpeed = 1` sur une source 30 fps, tant que la
  cadence reste au-dessus de 30 img/s l'utilisateur ne perd littéralement rien ;
- **la VRAM est le vrai garde-fou** : ~707 Mio extrapolés à 960, ~1,3 Gio à 1280. Au
  besoin, descendre `TRAFFIC_INFERENCE_BATCH` à 2 — `settings.py` avertit déjà que
  l'échec est un OOM CUDA franc.

## Comment le vérifier

```bash
cd backend && uv run python scripts/recall_bench.py --videos <clip> --imgsz 640 --frames 300 --classes 0,2,3,5,7 --json out/i640.json
```

```bash
cd backend && uv run python scripts/recall_bench.py --videos <clip> --imgsz 960 --frames 300 --classes 0,2,3,5,7 --json out/i960.json --compare out/i640.json
```

Le rappel est **déterministe** : une course par palier suffit, et les 11 % de bruit de
cette machine ne s'y appliquent pas. C'est `missedByWidth` qui dit si le gain est là où
on l'attend — les manqués doivent quitter les seaux étroits.

Le **coût**, lui, se mesure sur `pipeline_bench.py --imgsz`, en courses alternées sur
carte chaude, et pas dans la même course : le débit n'est pas déterministe.
