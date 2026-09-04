# Détecter les motos et les personnes

> Ce document raconte une enquête : **pourquoi l'application détectait mal les motos
> et les personnes**, ce que chaque étage de la chaîne fait réellement, ce qui a été
> mesuré, ce qui a été corrigé, et ce qui reste à mesurer.
>
> Il n'est pas normatif. [`prompt/`](prompt/) est le cahier des charges,
> [`CLAUDE.md`](CLAUDE.md) décrit l'état du code, et les sept ADR 0056 à 0062 portent
> chacune sa décision. Ce fichier-ci est ce qui les relie : le **mécanisme d'ensemble**,
> que ni une ADR ni un fichier de code ne peut donner seul.
>
> Chiffres du 2026-09-04, sur une **Quadro P1000** (Pascal `sm_61`, 4 Gio).

---

## Table

1. [Le symptôme, et pourquoi il était invérifiable](#1-le-symptôme)
2. [La chaîne : les neuf étages qu'une moto doit franchir](#2-la-chaîne)
3. [Les huit défauts trouvés](#3-les-huit-défauts)
4. [L'instrument : `recall_bench.py`](#4-linstrument)
5. [Ce que chaque réglage fait, et ce qu'il ne fait pas](#5-les-réglages)
6. [Ce qui a été mesuré et **réfuté**](#6-mesuré-et-réfuté)
7. [Les pièges de mesure de cette machine](#7-pièges-de-mesure)
8. [Que faire concrètement](#8-que-faire)
9. [Ce qui reste dû](#9-ce-qui-reste-dû)

---

## 1. Le symptôme

> « On a du mal à détecter les motos et les personnes. »

C'est la réclamation la plus difficile à trancher de ce projet, pour une raison
structurelle : **rien ne la mesurait**. L'application publie des compteurs — combien de
véhicules, combien de passages — et un compteur ne sait pas dire ce qu'il a **manqué**.
Un `motorcycle: 0` se lit de deux façons opposées :

- il n'y avait pas de moto ;
- il y en avait et la chaîne les a perdues.

Les deux affichaient le même chiffre et appellent des gestes contraires. Le tiroir
« Comptage » portait six chiffres de diagnostic, **tous globaux** : ils somment les
quatre classes cochées, donc ils ne distinguent pas « 3 000 voitures et zéro moto » de
« tout va bien ».

**Première conclusion de l'enquête, avant tout correctif : il fallait un banc.** Voir
[§4](#4-linstrument).

**Deuxième conclusion, et elle est structurelle** : le symptôme n'a pas *une* cause. Il
en a **huit**, à sept étages différents de la chaîne, et elles se cumulent. Quatre
d'entre elles suppriment un petit objet **en silence** — sans exception, sans journal,
sous des chiffres qui restent plausibles.

---

## 2. La chaîne

Voici, dans l'ordre, ce qu'une moto doit franchir pour apparaître dans un compteur.
**Chaque étage peut la faire disparaître, et sept des neuf le font sans rien dire.**

```
  ┌─ 1. DÉCODAGE ────────────────────────────────────────────────────┐
  │  OpenCV rend une image en pixels de la SOURCE (invariant 2).     │
  │  Fil séparé, lots d'images consécutives (ADR 0031).              │
  │  → une moto de 60 px sur du 1080p fait ici 60 px.                │
  └──────────────────────────────────────────────────────────────────┘
                                 ↓
  ┌─ 2. LETTERBOX / imgsz ───────────────────────── ⚠ DÉFAUT 3 ─────┐
  │  Ultralytics redimensionne à `imgsz`. `rect=True` étant imposé   │
  │  en prédiction, une source 16:9 entre en 640×384.                │
  │  → la même moto n'en fait plus que 20 px.                        │
  │  C'EST ICI que la taille d'un objet est décidée, pas dans la     │
  │  vidéo. Filmer plus défini n'achète RIEN si `imgsz` ne bouge pas. │
  └──────────────────────────────────────────────────────────────────┘
                                 ↓
  ┌─ 3. INFÉRENCE ───────────────────────────────────────────────────┐
  │  Le réseau rend des boîtes candidates avec un score par classe.  │
  │  La grille la plus fine (P3) a un pas de 8 px : un objet de      │
  │  20 px couvre 2,5 cellules. C'est le plancher physique.          │
  │  Sur cette carte, `half=False` (Pascal : le fp16 est plus lent). │
  └──────────────────────────────────────────────────────────────────┘
                                 ↓
  ┌─ 4. NMS ────────────────────────────────────── ⚠ DÉFAUT 2 ─────┐
  │  Supprime les boîtes qui se recouvrent trop (« Seuil IoU »).     │
  │  Était AGNOSTIQUE : toutes les classes dans un seul bassin, donc │
  │  la moins sûre disparaît. Un pilote supprimait sa moto.          │
  └──────────────────────────────────────────────────────────────────┘
                                 ↓
  ┌─ 5. PLANCHER PAR CLASSE ─────────────────────── ✚ ADR 0062 ─────┐
  │  Nouveau. Retire chaque boîte sous le plancher de SA classe.     │
  │  Après le NMS (sinon il travaillerait sur un jeu amputé) et      │
  │  avant le tracker (sinon une piste serait déjà ouverte).         │
  └──────────────────────────────────────────────────────────────────┘
                                 ↓
  ┌─ 6. TRACKER (BoT-SORT / BYTE) ───────────────── ⚠ DÉFAUTS 4·6 ──┐
  │  DEUX bandes de confiance, et c'est le point le moins intuitif : │
  │    · bande HAUTE (≥ `new_track_thresh`) → OUVRE une piste ;      │
  │    · bande BASSE (`track_low_thresh` → haute) → PROLONGE une     │
  │      piste existante, JAMAIS n'en ouvre une (ADR 0024).          │
  │  → une détection supplémentaire sous le curseur n'atteint jamais  │
  │    le comptage. C'est pourquoi monter `imgsz` seul ne rend rien.  │
  │  Survie d'une piste perdue : `track_buffer`, en IMAGES ANALYSÉES.│
  └──────────────────────────────────────────────────────────────────┘
                                 ↓
  ┌─ 7. `_drop_contained` (domaine) ─────────────── ⚠ DÉFAUT 1 ─────┐
  │  Jette toute boîte dont 90 % de l'aire tombe dans une autre.     │
  │  Mesure = intersection / min(aire) → structurellement            │
  │  asymétrique : c'est TOUJOURS le plus petit qui part.            │
  │  Était aveugle à la classe. Pilote dans sa moto : 1,000.         │
  └──────────────────────────────────────────────────────────────────┘
                                 ↓
  ┌─ 8. CONFIRMATION (`min_hits`) ───────────────────────────────────┐
  │  Une piste n'est un véhicule qu'après N images. Un scintillement │
  │  d'une image n'est pas un véhicule — c'est voulu, et c'est ce    │
  │  que `unconfirmed_tracks` mesure enfin (ADR 0059).               │
  └──────────────────────────────────────────────────────────────────┘
                                 ↓
  ┌─ 9. COMPTAGE ────────────────────────────────── ⚠ DÉFAUT 8 ─────┐
  │  Bande morte autour du trait (ADR 0018), date interpolée de      │
  │  l'intersection (ADR 0038), vote de classe sur la vie du         │
  │  véhicule (invariant 4).                                        │
  │  Le franchissement portait l'étiquette de l'INSTANT, pas le vote.│
  └──────────────────────────────────────────────────────────────────┘
```

### Pourquoi cette forme est le vrai sujet

Trois propriétés de cette chaîne expliquent tout le reste de ce document :

1. **Les étages ne sont pas indépendants.** Corriger le NMS seul ne rendait *rien* : un
   pilote qui survivait au NMS était réeffacé par `_drop_contained` à l'étage suivant.
   Les défauts 1 et 2 vont ensemble, et livrer l'un sans l'autre aurait fait conclure
   que la piste était morte ;
2. **Les étages 4 à 7 filtrent tous « à la baisse ».** Aucun ne peut ajouter un objet.
   Une chaîne de sept filtres où chacun retire 10 % en retire la moitié ;
3. **La plupart n'ont aucun témoin.** `_drop_contained` tourne **avant**
   `_count_scores`, donc une observation supprimée n'entre dans aucun des six chiffres
   du diagnostic. Personne ne pouvait le voir depuis l'interface.

---

## 3. Les huit défauts

Chacun a été **vérifié en exécutant le vrai code**, jamais en lisant. Chacun porte son
ADR, son test de verrouillage, et le chiffre qui l'a établi.

### Défaut 1 — `_drop_contained` effaçait les petits objets · [ADR 0056](docs/adr/0056-la-suppression-des-boites-incluses-effacait-les-petits-objets.md)

**Le mécanisme.** La fonction jette, avant le suivi, toute boîte dont 90 % de l'aire
tombe dans une autre. Sa mesure est `intersection / min(aire)`, donc **asymétrique par
construction** : un camion ne peut jamais être « contenu » dans une moto, mais une moto
l'est toujours dans un camion.

Sa docstring justifiait le seuil ainsi : *« le cas cible atteint 1,0, tandis qu'une
**voiture** roulant devant un camion peut être à 0,8 »*. Le seuil avait donc été calibré
sur la seule classe qui échappe au problème.

**Mesuré sur le vrai domaine**, trois géométries réalistes :

| cas | containment |
|---|---|
| pilote dans la boîte de sa moto | **1,000** |
| piéton devant un bus | **1,000** |
| moto devant un camion | **1,000** |

Et c'est toujours le plus petit qui part — c'est-à-dire exactement les deux classes
qu'on peine à détecter.

**Conséquences mesurées en bout de chaîne :**

- une moto suivie 5 images devant un camion ne laisse **aucune** trace :
  `high_detections = 5`, comptée nulle part ;
- une moto qui franchit à l'intérieur de la boîte d'un camion rend `crossings = 0`
  contre `1` pour le témoin ;
- une moto englobée 3,3 s sans que le tracker la perde ressort en **deux** véhicules.
  Le même mécanisme **sous-compte et double-compte**.

Sur les archives de ce dépôt — qui ne contiennent **ni moto ni personne**, donc en borne
basse : `containedOut = 1 610` pour `18 044` observations suivies, soit **8,2 %**.

**Le correctif.** La suppression est bornée aux objets **physiquement exclusifs entre
eux**, par `class_group` (`counting/domain/models.py:229`) :

```
{person}  ·  {bicycle, motorcycle}  ·  {car, bus, truck, train}
```

Quatre points qui ne se devinent pas :

- **la garde porte sur le GROUPE, jamais sur l'égalité de label.** Le détecteur ne nomme
  pas toujours la cabine comme le semi : `first.label != second.label` rouvrirait le
  piège d'origine sur une cabine `car` dans un semi `truck` ;
- **trois groupes et pas deux.** `CountCategory` range déjà en `vehicle` / `person` et ne
  peut pas répondre : elle met les deux-roues avec les voitures. Or un scooter sort
  régulièrement sous `bicycle` **ou** `motorcycle` — vrai doublon — sans être un doublon
  de la voiture derrière lui ;
- **le repli d'un label inconnu est `motor_vehicle`**, donc le comportement d'avant. Deux
  boîtes de **même** label tombent de toute façon dans le même groupe : le cas cible est
  protégé par construction, pas par la table ;
- **la garde est placée AVANT le test géométrique.** Que deux objets puissent être le même
  objet physique ne dépend pas de l'endroit où ils se trouvent.

**Effet sur les comptages** : ils changent par construction, dans **un seul sens**, et
**strictement pas du tout** sur une sélection qui ne contient que des véhicules à moteur.

---

### Défaut 2 — le NMS agnostique supprimait la moto sous son pilote · [ADR 0057](docs/adr/0057-le-nms-agnostique-supprimait-la-moto-sous-son-pilote.md)

**Le mécanisme.** Dans `nms.py` d'Ultralytics :

```python
c = x[:, 5:6] * (0 if agnostic else max_wh)   # decalage par classe
```

Sans agnostique, chaque classe est décalée dans un espace de coordonnées disjoint, donc
deux boîtes de classes différentes ne se « voient » jamais. `agnostic_nms=True` annule ce
décalage : **toutes les classes entrent dans un seul bassin**, et la moins sûre disparaît
dès que le recouvrement dépasse le « Seuil IoU ».

**Vérifié sur la vraie fonction**, deux boîtes à IoU 0,667 :

| entrée | sortie |
|---|---|
| `person 0.55` + `motorcycle 0.48` | la **moto** disparaît |
| `person 0.40` + `motorcycle 0.62` | la **personne** disparaît |

C'est **symétrique** : le réglage ne favorise personne, il détruit le moins sûr des deux.

**La prémisse était falsifiée.** Le commentaire qui justifiait le réglage invoquait
« nos **quatre** classes mutuellement exclusives ». `git log -S` date ce commentaire du
**2026-08-06** et l'ajout de `person` au catalogue du **2026-08-12** : la prémisse est
devenue fausse six jours après avoir été écrite, et personne ne pouvait le voir.

**Le mécanisme est certain, sa fréquence ne l'est pas.** Sur une géométrie réaliste
pilote/moto, l'IoU vaut **0,407** — sous le seuil par défaut de 0,45. Corollaire
contre-intuitif à retenir : **baisser le « Seuil IoU » aggrave ce cas**, le monter le
soigne. C'est l'inverse du réflexe.

**Le correctif.** Le NMS reste agnostique **dans** un groupe et ne compare jamais deux
groupes. `nms_class_groups` (`counting/application/ports.py:98`) partitionne, et un
`DetectionPredictor` dérivé appelle `non_max_suppression` **une fois par groupe**.

Cinq points, et le premier est le piège de toute l'ADR :

- **le groupe est la CATÉGORIE, surtout pas `class_group`.** Les deux tables se
  ressemblent, et les confondre est l'erreur naturelle — j'ai écrit la première version
  avec `class_group` et **mon propre test l'a rejetée**. Les deux questions sont
  différentes :

  | | question posée | pilote / moto | deux voitures à IoU 0,6 |
  |---|---|---|---|
  | `class_group` (containment) | l'un peut-il être **dans** l'autre ? | **oui** (1,000) | oui |
  | `category_of` (NMS) | ces boîtes **coïncidentes** sont-elles le même objet ? | **non** | oui |

  Avec `class_group`, la sélection par défaut `car·motorcycle·bus·truck` se scinderait en
  deux groupes (la moto est `two_wheeler`), donc **deux appels au NMS** là où il en faut
  un : la propriété « no-op au défaut » serait détruite.
  `TestDeuxTablesQuiNeSeConfondentPas` verrouille l'écart ;
- **le défaut ne change pas d'un bit** : `car`/`motorcycle`/`bus`/`truck` sont tous
  `vehicle`, donc une seule partie, donc un seul appel. Un test compare les tenseurs par
  `torch.equal` ;
- **deux mécanismes d'installation, et un seul suffit.** `predict()` ne construit son
  prédicteur qu'une fois par instance, **et le préchauffage appelle `model.predict()` au
  démarrage** : passer `predictor=` serait donc ignoré pour toute la vie du processus.
  `install_group_aware_nms` échange la **classe de l'instance déjà construite**. C'est
  pire qu'ADR 0035 — là-bas la première analyse obéissait, ici aucune ;
- **ne pas « corriger » en posant `model.predictor = None`** : `track()`
  ré-enregistrerait le tracker, `model.callbacks` **empile**, et `tracker.update()`
  tournerait deux fois par image. Chiffres plausibles, complètement faux ;
- **chaque groupe reçoit un `clone`** : `non_max_suppression` fait
  `prediction[..., :4] = xywh2xyxy(...)` sur une **vue**, donc elle convertit en place.
  Un second appel reconvertirait des xyxy en xyxy.

---

### Défaut 3 — la définition d'analyse décidait tout, et n'était pas réglable · [ADR 0060](docs/adr/0060-la-definition-d-analyse-devient-un-reglage-de-l-utilisateur.md)

**Le mécanisme.** Ce qui décide qu'un objet est détecté n'est pas sa taille dans la vidéo
mais **sa taille dans l'entrée du réseau**. `rect=True` étant imposé par Ultralytics en
prédiction, une source 16:9 entre en `imgsz` × `imgsz × 0,5625` :

| `imgsz` | tenseur sur du 1920×1080 | une moto de 60 px y fait |
|---|---|---|
| 640 | 640×384 | **20 px** |
| 960 | 960×544 | 30 px |
| 1280 | 1280×736 | 40 px |
| 1920 | 1920×1088 | 60 px |

Le commentaire de `core/settings.py` le disait déjà, à un endroit que personne ne lit.
ADR 0037 avait nommé cette cause **sans pouvoir la corriger** : le réglage n'existait ni
dans la requête ni à l'écran, seulement dans `TRAFFIC_INFERENCE_IMGSZ`.

**Corollaire contre-intuitif et important** : **filmer plus défini n'achète rien au
détecteur** tant qu'`imgsz` ne bouge pas — la taille dans le tenseur vaut
`fraction de l'image × imgsz`, donc elle ne dépend que du **cadrage**, jamais de la
définition du fichier. ADR 0031 avait mesuré ce fait sans en donner la cause.

**Mesuré, `predict` sur la même image** : 1 boîte à 640, **2** à 960, **5** à 1280.

**Le coût ne suit PAS l'aire**, et c'est la mesure qui a corrigé ma propre erreur — j'avais
écrit « coût ≈ carré du rapport » :

| `imgsz` | temps / image | rapport de temps | rapport d'aire |
|---|---|---|---|
| 640 | 19,1 ms | ×1,00 | ×1,00 |
| 960 | 24,6 ms | **×1,29** | ×2,13 |
| 1280 | 40,0 ms | **×2,09** | ×3,83 |
| 1920 | 74,9 ms | **×3,92** | ×8,44 |

Le coût croît comme l'**aire^0,65**. La raison : la carte est à p50 50 % d'utilisation à
640, donc un tenseur plus grand la **remplit mieux** au lieu de coûter proportionnellement.

**La VRAM n'est jamais la contrainte.** J'avais extrapolé ~2,8 Gio à 1920 et écarté cette
valeur pour cette raison. Mesuré : **121 Mio** (allocateur torch, lot 1), et une crête
maximale de **983 Mio** toutes configurations confondues, sur 4 096. C'est le **temps**
qui borne, jamais la mémoire — c'est pourquoi 1920 est aujourd'hui proposé.

**Le réglage.** `inferenceImgsz` voyage par requête, `null` suivant le déploiement
(convention de `confidenceThreshold`). C'est un `Choice` et jamais un curseur : le côté
doit être multiple de 32, et un 500 serait refusé par un 422 — ou pire, arrondi à 512 en
silence.

**C'est le SEUL champ d'`EngineSpec` qui ne soit pas un simple indice.** `start_ms` et
`max_lost_ms` sont des optimisations qu'un moteur peut ignorer sans changer un chiffre ;
ici il n'existe pas de règle équivalente en aval. La propriété « un moteur peut ignorer
toute la spec » cesse d'être vraie, et c'est écrit à sa place.

---

### Défaut 4 — aucun des deux réglages ne rend quoi que ce soit **seul**

C'est la découverte la plus importante de l'enquête, et elle a failli me faire livrer un
réglage inerte. Mesuré au banc, chemin de production complet, clip 720p réel,
62 instances de vérité, `yolov8n` contre `yolo11x@1280` :

| `imgsz` | confiance | rappel `car` |
|---|---|---|
| 640 | 0,35 *(défauts)* | 0,484 |
| 640 | 0,12 | **0,484** |
| 960 | 0,35 | **0,484** |
| 1280 | 0,35 | **0,484** |
| **960** | **0,20** | **0,790** |

**Pourquoi.** Les deux étages se bloquent l'un l'autre :

- **à `imgsz` 640, l'objet n'est pas détecté du tout.** Baisser la confiance ne peut pas
  rattraper une boîte qui n'existe pas ;
- **à `imgsz` 960 il l'est, mais il score sous `new_track_thresh`.** Le seuil de
  l'utilisateur *est* `new_track_thresh` depuis ADR 0024 : la détection **prolonge** une
  piste sans jamais en **ouvrir** une, donc elle n'atteint jamais le domaine.

Les deux étages du banc le montrent directement — à `imgsz` 1280 :

| étage | rappel |
|---|---|
| `--stage detector` (sans tracker) | **0,806** |
| `--stage tracked` (chemin réel) | **0,484** |

**Le détecteur trouve vingt objets de plus, et le tracker les jette tous.** C'est
exactement le mur d'association, et il ne se voit d'aucune autre façon.

`fuse_score: false` ne rachète rien sur ce cas — mesuré.

---

### Défaut 5 — le rappel lu seul mentait · [ADR 0062](docs/adr/0062-un-plancher-de-confiance-par-classe.md)

**Le mécanisme d'erreur.** Un banc de rappel pousse toujours dans le même sens : baisser
un seuil l'augmente **mécaniquement**. J'étais sur le point de changer un défaut sur ce
seul chiffre. En ajoutant la précision :

| `imgsz` | conf. | rappel | précision | F1 | effet de bord |
|---|---|---|---|---|---|
| 640 | 0,35 *(défauts)* | 0,484 | 1,000 | 0,652 | aucun |
| 960 | **0,20** | **0,790** | 0,860 | **0,824** | **17 `bus` inventés** |
| 960 | 0,12 | 0,790 | 0,583 | 0,671 | pire partout |

Trois choses invisibles sans ce chiffre :

1. **le compromis reste favorable à 0,20** — le F1 monte de 0,652 à 0,824. Et c'est le
   **tracker qui filtre** les détections instables : au détecteur nu la précision
   tomberait à 0,707 ;
2. **le modèle invente une classe** — dix-sept observations de `bus` sur un clip qui n'en
   contient aucun. Pour un compteur, un faux positif est un **véhicule fantôme dans le
   total** ;
3. **0,12 est franchement mauvais**, donc l'optimum n'est pas au plus bas. Sans la
   précision, rien ne l'aurait dit.

**Le correctif.** Le curseur unique force à choisir entre rater les petits objets et
compter des fantômes, **alors que les deux effets ne portent pas sur les mêmes classes**.
`smallObjectConfidence` s'applique à `person`, `bicycle` et `motorcycle` seulement — les
trois plus bas rappels de COCO :

| | moto | personne | vélo | voiture |
|---|---|---|---|---|
| yolov8n | 0,580 | 0,673 | **0,392** | 0,515 |
| yolo11m | 0,712 | 0,746 | 0,546 | 0,654 |

**Un seul curseur et pas sept** : ce qui sépare les classes ici est leur **taille**, et
elle partitionne le catalogue en deux. `SMALL_CLASS_IDS` (domaine, `= {0, 1, 3}`) est le
miroir exact de `SMALL_CLASSES` (client, `shared/lib/classes.ts`), verrouillé par un test
**backend** qui lit le fichier client — même procédé que `MIN_PLATE_CROP_SIDE_PX`.

Trois points :

- **`null` est un no-op strict** : tous les planchers valent le curseur unique, donc
  `minimum_floor` rend exactement `confidence`. Aucune analyse existante ne bouge, et
  c'est ce qui rend l'ADR livrable ;
- **le MINIMUM des planchers part au tracker**, jamais le seuil nominal — il devient
  `new_track_thresh`, et à 0,35 une moto à 0,25 n'ouvrirait aucune piste : le plancher par
  classe serait **inerte**. C'est la panne d'ADR 0037 à un autre étage ;
- **le filtre vit après le NMS et avant le tracker.** Plus tôt, le NMS travaillerait sur un
  jeu amputé ; plus tard, le tracker aurait ouvert une piste que rien ne saurait retirer,
  le score d'une piste venant de sa dernière détection et oscillant. Jamais dans le
  domaine, où une détection non associée n'existe déjà plus.

Le curseur **n'est rendu que si un petit objet est coché** : ailleurs il ne s'appliquerait
à rien, et un réglage sans effet est le pire état d'un réglage.

---

### Défaut 6 — « Survie d'une piste perdue » n'atteignait pas le tracker · [ADR 0058](docs/adr/0058-la-survie-d-une-piste-perdue-n-atteignait-pas-le-tracker.md)

**Le troisième réglage inerte de ce module**, après ADR 0035 (la confiance) et ADR 0037
(le plancher du détecteur). Le bug n'était pas dans un calcul : il était dans l'**absence
de transport**. `grep -rn track_buffer backend/src/` ne le trouvait **que dans des
commentaires**, et surtout **`EngineSpec` ne portait pas le champ** — la valeur ne
*pouvait pas* atteindre l'adaptateur.

**Deux horloges qui ne se parlaient pas :**

| | unité | où |
|---|---|---|
| `max_lost_ms` | millisecondes de **temps de scène** | domaine, `_release_lost` |
| `track_buffer` | **images analysées** | tracker, `self.max_frames_lost = args.track_buffer` |

Le « miroir exact » qu'annonçait `botsort_reid.yaml` n'était vrai qu'à 30 img/s au pas 1 :

- **à pas 3**, le domaine oublie à 2,5 s pendant que le tracker tient **7,5 s** : il rend
  un `track_id` que le domaine ne reconnaît plus, donc un `global_id` neuf, donc **un
  véhicule compté deux fois en silence** ;
- **à 60 img/s**, l'inverse : le tracker renonce à 1,25 s sous un curseur qui annonce 2,5.

**Trois pièces, et la troisième est une catégorie de panne nouvelle :**

1. `EngineSpec.max_lost_ms`, un **indice** comme `start_ms` — un moteur qui l'ignore reste
   correct, le domaine appliquant la règle de son côté. Le `FakeEngine` de la CI rend donc
   les mêmes chiffres ;
2. `track_buffer_frames(max_lost_ms, fps, stride)`, seul juge de la conversion, dans
   l'adaptateur parce que lui seul connaît la cadence et le pas ;
3. **`ENGRAVED_TRACKER_ATTRS`** — écrire la valeur dans le fichier dérivé **ne suffit
   pas** : vérifié à l'exécution, `args.track_buffer = 450` puis `reset()` laisse
   `max_frames_lost` à **75**. Les clés **gravées à la construction** doivent se reposer
   sur l'**instance**, pas sur `tracker.args`.

  Conséquence de doctrine : `REQUEST_TRACKER_KEYS ⊆ LIVE_TRACKER_KEYS` tient toujours mais
  **ne couvre plus tout**. Il existe désormais **deux** façons de reposer un réglage, et un
  test le verrouille.

**Le défaut ne change rien, par construction** : 2 500 ms à 30 img/s au pas 1 valent
exactement 75, la valeur du fichier versionné. **Le direct n'impose aucun tampon** — un
flux caméra n'a pas de cadence déclarée, donc la conversion est impossible.

Contrôle de non-régression le plus parlant : deux analyses à `frameStride 3`, `maxLostMs`
2500 puis 8000. Avant, elles rendaient des chiffres **strictement identiques** — cette
identité *était* le bug.

---

### Défaut 7 — le diagnostic ne pouvait pas dire ce qui n'avait jamais été détecté · [ADR 0059](docs/adr/0059-le-diagnostic-sait-dire-quel-type-n-a-jamais-ete-detecte.md)

Deux défauts du tiroir « Comptage », et le second est le plus trompeur.

**a) Tout était global.** Six chiffres qui somment les quatre classes ne distinguent pas
« 3 000 voitures et zéro moto » de « tout va bien ». Le panneau concluait pourtant « ces
chiffres disent lequel » des quatre cas — or le premier, **« jamais détecté »**, n'était
mesurable par aucun d'eux.

**b) « Pistes provisoires » est un instantané au milieu de quatre cumuls.** Il se calcule
sur `self._tracks`, que `_release_lost` purge : il décrit les **~2,5 dernières secondes**.

Mesuré sur le vrai domaine — 300 images, une voiture et **douze motos scintillant une
image chacune** au-dessus du seuil : il affiche **0**, sous une aide qui promet « baisser
*Images avant comptage* les compterait ». Confirmé sur les archives : job `74dfee38`,
28 véhicules sous `confirmedTracks: 1` ; `dd263f4c`, 165 sous 16. **Aucune** analyse
archivée n'a un `tentativeTracks` non nul.

**Deux champs, aucune comptabilité nouvelle :**

- **`unconfirmed_tracks`** = `TrackNumbering.issued - size`. Le compteur existait, testé,
  **sans consommateur**. C'est un **dérivé** et jamais un second compteur :
  `unconfirmed_tracks + tracked_vehicles == issued`, et c'est cette **égalité** — pas la
  valeur — qu'un test verrouille (invariant 3). **Ce ne sont pas des véhicules perdus** :
  un scintillement d'une image n'est pas un véhicule ;
- **`by_class`** — le même diagnostic par type, sur le patron de `near_misses`. **Les types
  cochés à zéro sont rendus** : `motorcycle: 0 / 0` *est* l'information, omettre la clé se
  lirait « pas mesuré ». La liste vient du **serveur** via `SessionConfig.class_ids` et
  jamais des cases de l'écran, dont la sélection courante peut avoir changé depuis
  l'analyse.

Le panneau est coupé en deux blocs — cumuls, puis « À la dernière image analysée ». Les
types jamais détectés sont **nommés en toutes lettres** :

> « Moto n'a jamais été détectée. Aucun curseur ne la rattrapera : il faut un modèle plus
> grand, une image plus définie, ou un plan plus serré. »

Une conséquence et trois gestes, jamais un interdit.

**`contained_out` n'est pas ventilé par paire de classes**, contrairement à ce que l'audit
recommandait : cette ventilation existait pour révéler la suppression **inter-classes**,
qu'ADR 0056 a supprimée. Ce qui reste est le cas voulu, deux boîtes de même groupe.

---

### Défaut 8 — le franchissement portait une étiquette gelée · [ADR 0061](docs/adr/0061-un-franchissement-porte-le-vote-final-du-vehicule.md)

**L'invariant 4 n'était vrai qu'à moitié.** Le registre et `tracked_by_class` sont relus à
la fin, mais `LineCrossingCounter._count` écrivait `label` **une fois pour toutes**, et
`_retally` ne déplaçait la voix que dans `tracked_by_class`. Aucun chemin ne menait aux
tallies de ligne.

**Mesuré sur le vrai domaine** — un deux-roues lu `person ×3` puis `motorcycle ×4`,
franchissant au milieu :

| | résultat |
|---|---|
| `by_class` (par ligne) | `{'person': 1}` |
| `tracked_by_class` (registre) | `{'motorcycle': 1}` |

Le même objet, deux classes, **sur le même écran**.

**Cela frappe exactement les classes qui manquent.** `person`, `bicycle` et `motorcycle`
sont les trois que le détecteur confond (défaut 2), et leur lecture **s'améliore en
approchant** (défaut 3) : le basculement tombe donc **après** le franchissement dès que la
ligne est dans la moitié éloignée du champ.

**Seconde conséquence, la plus dommageable** : la **voie réservée** était évaluée sur ce
libellé gelé, donc une voie réservée aux motos signalait **en rouge, avec sa photo**, un
deux-roues parfaitement autorisé. Et le commentaire de `lineViolations.ts` affirmait le
contraire de ce que le code faisait.

**Corrigé à la source, côté serveur** : `DirectionTally.relabel` déplace une voix sans
toucher au total, `LineCrossingCounter.relabel` la porte à la ligne, et
`TrackNumbering(on_relabel=…)` prévient la session — un **rappel** et non une dépendance,
le numérotage ignorant les lignes et le compteur ignorant le vote. Seul
`_VehicleAggregate.crossings` sait *quels* franchissements déplacer, et il les tenait déjà.
`_align_crossing_labels` réaligne enfin le **journal** à l'assemblage, les `CrossingEvent`
émis étant immuables.

Trois points :

- **aucun total ne bouge** — un franchissement reste un franchissement, seule l'étiquette
  change, donc `total == Σ by_class` tient des deux côtés (invariant 3) ;
- **conditionné à `confirmed`**, comme `_retally` : un véhicule pas encore compté n'a rien
  fait compter, et lui retirer une voix passerait un compteur sous zéro ;
- **les aperçus SSE gardent l'étiquette du moment** et c'est sans conséquence, le client
  remplaçant son journal vivant par celui du résultat à la fin. Les **tallies**, eux, sont
  corrigés au fil de l'eau : le KPI est juste en direct.

**La fréquence n'est pas mesurée** — les clips de ce dépôt ne contiennent ni moto ni
personne. Elle se lira sur `result.json.gz` en comptant les franchissements dont
`vehicle.label != crossing.label`, désormais **zéro par construction**.

---

## 4. L'instrument

`backend/scripts/recall_bench.py` — **il n'existait pas**, et c'est pourquoi la
réclamation était invérifiable. Les deux bancs qui existaient répondaient à d'autres
questions :

| banc | mesure |
|---|---|
| `anpr_bench.py` | la **justesse** de la lecture de plaque |
| `pipeline_bench.py` | la **cadence** de chaque étage |
| **`recall_bench.py`** | **ce que la chaîne a manqué**, par classe |

### Le principe

Il n'existe pas de vérité terrain annotée pour ces vidéos. Le banc en fabrique une :

```
   une image décodée
        │
        ├──→ passe de VÉRITÉ    : yolo11x @ imgsz 1280, conf 0,15
        │                         (gros modèle, grande entrée, seuil bas)
        │
        └──→ passe CANDIDATE    : le modèle et les réglages qu'on teste
                 │
                 ▼
        appariement glouton, class-agnostique, IoU ≥ 0,5
                 │
                 ▼
      rappel · précision · F1 · seaux de largeur des manqués
```

Cinq propriétés qui rendent le chiffre utilisable :

1. **la vérité et le candidat voient la MÊME image décodée.** Deux décodages
   indépendants donneraient un décalage d'image, donc des faux manqués ;
2. **l'appariement est class-agnostique**, puis on vérifie *ensuite* si le label
   correspond. Sinon une moto détectée mais nommée `bicycle` compterait comme un manqué
   *et* comme un faux positif — deux fois la même erreur ;
3. **deux étages, et l'écart entre eux est l'information** :

   | `--stage` | ce qu'il exécute |
   |---|---|
   | `tracked` *(défaut)* | `engine.iter_video` — **le vrai chemin de production**, tracker compris |
   | `detector` | `predict` nu, sans tracker |

   C'est cet écart qui a révélé le défaut 4 : 0,806 contre 0,484 ;
4. **les manqués sont rangés par largeur** — `<32`, `32-64`, `64-128`, `>=128` pixels **de
   la source**. Ces bornes encadrent le plancher où ADR 0037 situait la panne : à `imgsz`
   640 sur du 1080p, la largeur dans le tenseur vaut le tiers, donc un objet de 96 px n'en
   fait plus que 32 — la borne « small » de COCO ;
5. **le banc crie quand il n'a pas assez de matière.** `MIN_INSTANCES = 200` : en dessous,
   il imprime `⚠ 62 < 200`. Cet avertissement a eu raison une fois — voir
   [§6](#6-mesuré-et-réfuté).

### Le mode inventaire

```bash
cd backend
uv run python scripts/recall_bench.py --videos <clip> --inventory
```

Il n'exécute **que** la passe de vérité et répond à la seule question préalable : *« y
a-t-il des motos dans cette vidéo ? »* C'est ce mode qui a établi le blocage de toute
l'enquête — **les six clips de `data/jobs/` sont en 720p et ne contiennent ni moto ni
personne**.

### Usage

```bash
cd backend
# « Qu'est-ce que mes reglages actuels manquent ? »
uv run python scripts/recall_bench.py --videos <clip> --frames 300 --json out/avant.json

# « Le detecteur trouve-t-il l'objet, ou le tracker le jette-t-il ? »
uv run python scripts/recall_bench.py --videos <clip> --imgsz 1280 --stage detector
uv run python scripts/recall_bench.py --videos <clip> --imgsz 1280 --stage tracked

# Avant / apres, avec la precision
uv run python scripts/recall_bench.py --videos <clip> --imgsz 960 --confidence 0.20 \
    --json out/apres.json --compare out/avant.json
```

Options utiles : `--model`, `--imgsz`, `--confidence`, `--iou`, `--classes`,
`--truth-model`, `--truth-imgsz`, `--truth-conf`, `--truth-device cpu` (si la VRAM
manque), `--match-iou`, `--start`, `--frames`.

### Lire le rapport

- **`recall`** = trouvés / instances de vérité. Monte mécaniquement quand un seuil
  descend : **ne jamais le lire seul** ;
- **`precision`** = bons / candidats. Vaut `None` — et **jamais `1.0`** — avec zéro
  candidat : une chaîne qui ne détecte rien n'est pas parfaitement précise ;
- **`f1`** — le seul des trois qui puisse départager deux réglages ;
- **`falsePositives`** — le chiffre à regarder classe par classe. Ce sont les
  dix-sept `bus` fantômes ;
- **`missedByWidth`** — si tous les manqués sont dans `<32` et `32-64`, la cause est la
  **définition**. S'ils sont répartis, c'est autre chose.

---

## 5. Les réglages

Voici, pour chaque réglage qui touche la détection, **où il agit dans la chaîne**, ce
qu'il fait, et ce qu'il ne fait **pas**.

### Définition d'analyse — `inferenceImgsz`

| | |
|---|---|
| **Étage** | 2 (letterbox) |
| **Valeurs** | Serveur · 640 · 960 · 1280 · 1920 |
| **Défaut** | Serveur (`TRAFFIC_INFERENCE_IMGSZ` = 640) |

Le côté auquel l'image entre dans le réseau. **C'est ce réglage, et lui seul, qui décide de
la taille d'un objet pour le détecteur.**

- **il ne fait rien seul** — voir défaut 4. Il faut baisser un seuil en même temps ;
- **son coût est sous-linéaire en aire** (^0,65), pas quadratique ;
- **il rend deux jobs incomparables**, donc le récapitulatif d'avant-analyse l'affiche
  **toujours**, sans avertissement ;
- **le direct le suit aussi** (`self._spec.imgsz`) : les deux modes doivent détecter à la
  même résolution.

### Confiance véhicules — `confidenceThreshold`

| | |
|---|---|
| **Étage** | 6 (tracker) — **pas le détecteur** |
| **Défaut** | `null` côté client, résolu à **0,35** (`DEFAULT_CONFIDENCE`) |

**Ce réglage ne filtre pas le détecteur** depuis ADR 0024 : il décide ce qui **devient**
une piste. Il part dans le fichier de suivi dérivé sur `track_high_thresh` **et**
`new_track_thresh`, et le détecteur reçoit `track_low_thresh` — bien plus bas — pour que la
seconde association BYTE ait de la matière.

Conséquence à retenir : **une détection sous ce seuil prolonge une piste, elle n'en ouvre
jamais une.** C'est pourquoi monter `imgsz` sans baisser ce curseur ne rend rien.

Sous 0,10, `detector_floor` fait descendre le plancher avec lui (ADR 0037), sinon le
curseur serait mort en bas de sa plage.

### Confiance petits objets — `smallObjectConfidence` · **nouveau**

| | |
|---|---|
| **Étage** | 5 (après NMS, avant tracker) |
| **Défaut** | `null` — no-op strict |
| **S'applique à** | `person`, `bicycle`, `motorcycle` **seulement** |

Un second plancher, pour les trois classes dont le rappel COCO est le plus bas. Il existe
parce que **baisser le curseur unique invente des objets dans les classes qu'on ne
cherchait pas** (défaut 5).

- **le curseur n'est rendu que si un petit objet est coché** ;
- **il peut aussi monter** : une scène où les motos sont hallucinées appelle l'inverse, et
  le port ne l'interdit pas ;
- **le minimum des deux planchers part au tracker**, sinon il serait inerte.

### Seuil IoU — `iouThreshold`

| | |
|---|---|
| **Étage** | 4 (NMS) |
| **Défaut** | 0,45 |

Au-delà de ce recouvrement, deux boîtes **du même groupe** sont considérées comme le même
objet et la moins sûre part.

**Corollaire contre-intuitif** : sur le cas pilote/moto (IoU réaliste 0,407), **baisser ce
seuil aggrave** la suppression, le monter la soigne. Depuis ADR 0057 il ne compare plus
jamais deux catégories, donc ce cas est bien plus rare — mais le réflexe reste faux.

### Survie d'une piste perdue — `maxLostMs`

| | |
|---|---|
| **Étages** | 6 (tracker, `track_buffer`) **et** 7 (domaine, `_release_lost`) |
| **Défaut** | 2 500 ms |

Combien de temps une piste survit à une occlusion. **Deux horloges** que `track_buffer_frames`
réconcilie : le domaine compte en millisecondes de scène, le tracker en images analysées.

- **monter cette valeur réduit les doublons d'occlusion** — un véhicule masqué 3 s ne
  ressortira pas sous un numéro neuf ;
- **la monter trop fait fusionner deux véhicules** qui passent au même endroit ;
- **elle n'a aucun effet en direct** : un flux caméra n'a pas de cadence déclarée.

### Images avant comptage — `minHits`

| | |
|---|---|
| **Étage** | 8 (confirmation) |
| **Défaut** | 2 |

Combien d'images une piste doit vivre pour devenir un véhicule. Baisser rattrape les
objets brièvement vus ; monter supprime les scintillements. `unconfirmed_tracks` mesure
enfin ce que ce curseur écarte.

### Pas d'analyse — `frameStride`

| | |
|---|---|
| **Étage** | 1 (décodage) |
| **Défaut** | 1 |

Une image sur N est analysée. Il **interagit avec `maxLostMs`** — c'est tout le défaut 6 —
et avec le rappel : un objet vu trois images n'en est vu qu'une au pas 3, donc il n'atteint
pas `minHits`.

### Objets à compter — `classIds`

| | |
|---|---|
| **Étages** | 4 (partition du NMS), 5 (planchers), 9 (KPI et camemberts) |
| **Défaut** | les quatre véhicules |

Décocher une classe retire son KPI et sa part du camembert. **Une classe décochée qui porte
des entrées garde sa carte**, sinon rouvrir un résultat archivé puis décocher effacerait une
colonne de son propre contenu.

Cette sélection décide aussi de la **partition du NMS** : ajouter `person` fait passer de
une à deux parties.

### Modèle

| | |
|---|---|
| **Étage** | 3 (inférence) |
| **Défaut** | `yolov8n` |

Mesuré sur cette carte, **carte chaude** :

| modèle | `imgsz` | cadence | crête VRAM |
|---|---|---|---|
| `yolov8n` | 960 | **40 img/s** | ~200 Mio |
| `yolo11s` | 960 | 20 img/s | — |
| `yolo11m` | 960 | **8 img/s** | — |
| `yolo11x` | 1280 | 1,9 img/s | **983 Mio** |

**La VRAM n'est jamais la contrainte** sur 4 Gio ; le temps l'est toujours.

---

## 6. Mesuré et réfuté

Cette section existe pour qu'aucune de ces pistes ne soit re-proposée sans lire sa mesure.

### `multi_label` — définitivement close

ADR 0037 l'avait nommée comme le remède au cas « l'évidence `motorcycle 0,48` d'une ancre
dont le top-1 est `person 0,55` est jetée ». Deux raisons de la fermer :

1. **elle est inatteignable** : `get_cfg` lève `SyntaxError` sur la clé, et `postprocess`
   ne la passe pas ;
2. **elle serait inutile telle quelle** : deux lignes d'une même ancre portent **la même
   boîte**, donc IoU 1,0 — le NMS en supprimerait une immédiatement.

### `proximity_thresh` — j'avais le sens à l'envers

L'enquête initiale affirmait que 0,5 → 0,8 « élargit la fenêtre ». Le code dit
`dists_mask = dists > (1 - proximity_thresh)`, donc **0,8 la RÉTRÉCIT** — et tue la piste
même à `dx = 12 px`, un cas que le défaut gère très bien. C'est **0,2** qui élargit.

### `fuse_score: false`

Ne rachète rien sur le cas mesuré. Laissé tel quel, avec un test qui verrouille l'état.

### Lot d'inférence 4 → 8

Mesuré **+0,6 à +3 %** selon le modèle. Le bruit de cette machine est de **11 %** : ce
serait un placebo. Le défaut reste **4**.

### Budget de threads OpenCV

`TRAFFIC_OPENCV_THREADS` reste à `0` — sans effet en pipeline réel, contrairement à ce
qu'un micro-banc laissait espérer.

### `yolo12x` comme modèle de vérité

Rendait un rappel de **1,000 partout** — parce qu'il ne trouvait que **30 instances** là où
`yolo11x` en trouve **62**. Vérifié qu'il ne s'agissait pas de doublons chez `yolo11x`
(0 paires se recouvrant à IoU > 0,3), donc `yolo11x` est réellement plus fort. La vérité est
restée `yolo11x@1280`.

**Leçon générale** : un rappel de 1,000 est un signal de **vérité trop faible**, jamais un
succès.

### L'échelle de modèles

`yolo11s` 0,516, `yolo11l` 0,484 — **tous deux pires que le nano à 0,790**. Conclusion
honnête : **non interprétable**. À 62 instances et 1 à 2 véhicules par image, l'échantillon
ne supporte pas cette question, et l'avertissement `⚠ 62 < 200` du banc avait raison.

### Ventiler `contained_out` par paire de classes

Recommandé par l'audit, **non fait** : cette ventilation existait pour révéler la suppression
inter-classes, qu'ADR 0056 a supprimée à la racine. Ce qui reste est le cas voulu.

---

## 7. Pièges de mesure

Ils dominent tout le reste, et les deux premiers ont été payés ici.

1. **L'horloge du GPU monte de 885 à 1 518 MHz** au fil des premières courses d'une
   session, soit **×1,72**. Quatre courses successives font croire à un gain de 1,8× qui
   n'est que la montée en régime, et une comparaison lue ainsi **conclut l'inverse de la
   vérité**. Les mesures se font en **courses alternées, carte déjà chaude**, et `--warmup`
   chauffe le *modèle*, pas la *carte* ;
2. **le bruit entre deux courses strictement identiques est de 11 %.** Tout gain inférieur
   **n'existe pas**, et le prétendre serait malhonnête ;
3. **`half=False` sur cette carte** est décidé par le code (capability < 7.0). Avant Volta,
   le fp16 est *plus lent* : 38,9 → 48,9 ms mesurées. Ne pas « réactiver » `TRAFFIC_HALF` en
   croyant optimiser ;
4. **un rappel de 1,000 signale une vérité trop faible**, pas un succès ;
5. **sous 200 instances, ne pas départager deux modèles.** Le banc le dit lui-même.

---

## 8. Que faire

### Le réglage recommandé, aujourd'hui

```
Définition d'analyse      : 960
Confiance véhicules       : 0,35     ← inchangé : pas de bus fantômes
Confiance petits objets   : 0,20     ← moto / vélo / personne seulement
Objets à compter          : cocher Moto et Personne
```

C'est le seul réglage que la mesure soutient : **le gain sur les petits objets sans le coût
sur les gros**, ce que le curseur unique ne permettait pas. Reste plus rapide que le temps
réel (40 img/s) avec `yolov8n`.

Si la précision compte plus que la durée : `yolo11m` @ 960, même paire de seuils. COCO donne
**+23 % de rappel moto** par-dessus. 8 img/s, soit ~11 min pour un clip de 3 minutes.

**Aucun défaut n'a été changé.** Le gain est réel, son effet de bord dépend de la scène, et
le choix appartient à qui regarde sa vidéo.

### Les gestes qui valent mieux que n'importe quel réglage

Par ordre d'efficacité mesurée :

1. **resserrer le plan.** La taille dans le tenseur vaut `fraction de l'image × imgsz` :
   cadrer deux fois plus serré double la taille de l'objet **gratuitement**, alors que
   doubler `imgsz` coûte ×1,3 à ×3,9 ;
2. **monter `imgsz` ET baisser le plancher des petits objets.** Jamais l'un sans l'autre ;
3. **prendre un modèle plus grand** — le seul geste qui achète du rappel *par classe* ;
4. **filmer plus défini** — le geste le plus intuitif, et **le seul qui ne rend rien** tant
   qu'`imgsz` ne bouge pas.

### Comment savoir laquelle de ces causes vous frappe

| symptôme dans le tiroir « Comptage » | cause probable | geste |
|---|---|---|
| « Moto n'a jamais été détectée » | étages 2-3 : trop petite dans le tenseur | plan, `imgsz`, modèle |
| `unconfirmed_tracks` élevé | l'objet est vu mais scintille | baisser `minHits`, ou `imgsz` |
| `rescuedByLowScore` élevé | la bande basse de BYTE travaille | normal, c'est le mécanisme |
| `nearMisses` non nul sur une ligne | le tracé et le suivi se manquent de peu | déplacer la ligne |
| `containedOut` élevé | doublons de même groupe supprimés | normal depuis ADR 0056 |

Et le geste transverse : `uv run python scripts/audit_lignes.py`, qui rejoue la géométrie
seule sur la timeline persistée et **nomme** un franchissement présent dans la trajectoire
mais absent des totaux.

---

## 9. Ce qui reste dû

**Du métrage avec des motos et des personnes.** C'est le blocage, et rien ne le remplace.

Tout ce qui précède a été mesuré sur des **voitures**, sur un clip 720p de 30 images où le
banc lui-même marque `⚠ 62 < 200`. J'ai poussé cet échantillon au-delà de ce qu'il supporte
une fois — l'échelle de modèles est sortie non monotone — et il a fallu jeter le résultat.

Ce qu'il faut :

- **deux clips 1080p** sous `backend/data/bench/` ;
- **≥ 200 instances par classe** de `motorcycle` et `person`, vérifiées par
  `--inventory` ;
- de préférence un plan large et un plan serré, pour départager le geste « cadrage » du
  geste « `imgsz` ».

Ce que cela permettra de trancher, et **rien d'autre ne le permettra** :

1. **le gain réel du plancher par classe sur les motos.** ADR 0062 justifie le *mécanisme*
   par une mesure de faux positifs ; le gain lui-même est étayé par COCO, pas par ce
   métrage ;
2. **la fréquence du défaut 2** (NMS pilote/moto). Le mécanisme est certain, l'IoU réaliste
   de 0,407 le rend conditionnel ;
3. **la fréquence du défaut 8** (étiquette gelée). Se lira sur `result.json.gz` en comptant
   les franchissements dont `vehicle.label != crossing.label` — désormais zéro par
   construction ;
4. **lequel des trois régimes vaut son coût**, l'échelle de modèles étant aujourd'hui
   non interprétable.

Une soirée de mesures, une fois le métrage là.

---

## Annexe — les sept ADR

| ADR | ce qu'elle décide | change des comptages ? |
|---|---|---|
| [0056](docs/adr/0056-la-suppression-des-boites-incluses-effacait-les-petits-objets.md) | `_drop_contained` par groupe de classes | **oui**, dans un seul sens |
| [0057](docs/adr/0057-le-nms-agnostique-supprimait-la-moto-sous-son-pilote.md) | NMS par catégorie, jamais entre catégories | **oui** dès que `person` est coché |
| [0058](docs/adr/0058-la-survie-d-une-piste-perdue-n-atteignait-pas-le-tracker.md) | `maxLostMs` atteint enfin le tracker | oui hors défaut (pas ≠ 1, fps ≠ 30) |
| [0059](docs/adr/0059-le-diagnostic-sait-dire-quel-type-n-a-jamais-ete-detecte.md) | diagnostic par classe, `unconfirmed_tracks` | non — dérivés |
| [0060](docs/adr/0060-la-definition-d-analyse-devient-un-reglage-de-l-utilisateur.md) | `inferenceImgsz` par requête | oui si on le change |
| [0061](docs/adr/0061-un-franchissement-porte-le-vote-final-du-vehicule.md) | le franchissement porte le vote final | non — aucun total ne bouge |
| [0062](docs/adr/0062-un-plancher-de-confiance-par-classe.md) | plancher de confiance par classe | non au défaut (`null`) |

**Vingt-neuf commits**, `1901 passed / 1 skipped` côté backend, `947 pass` côté frontend.
