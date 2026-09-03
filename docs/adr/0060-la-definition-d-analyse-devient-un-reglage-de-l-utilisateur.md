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

`1920` n'est pas proposé bien que le serveur l'accepte : la crête VRAM extrapolée
(~2,8 Gio depuis les 332 Mio mesurés à 640) ne tient pas confortablement en lot sur les
4 Gio de cette carte.

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
