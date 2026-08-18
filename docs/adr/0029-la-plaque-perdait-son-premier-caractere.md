# ADR 0029 — La plaque perdait son premier caractère

- **Statut** : accepté
- **Date** : 2026-08-18
- **Amende** : [ADR 0007](0007-lecture-du-texte-de-plaque.md) et
  [ADR 0008](0008-precision-de-l-anpr.md) — sans rien leur retirer.

## Contexte

Le registre affichait `606L` pour une plaque `苏A·R606L`, à **81 % de confiance de
lecture**. Ce n'est pas un refus honnête au sens d'ADR 0007 : la chaîne n'a pas dit
« je ne sais pas », elle a affirmé une plaque tronquée avec l'assurance d'une plaque
lue. C'est le pire des deux mondes — un texte faux, présenté comme sûr.

Le diagnostic a demandé de constituer un corpus, parce qu'aucune mesure existante ne
pouvait voir le défaut. Les deux bancs du dépôt regardent ailleurs :
`scripts/anpr_bench.py --truth-ladder` rend des plaques **françaises de synthèse**, et
`pipeline_bench.py` ne fait pas tourner la passe ANPR.

**Le corpus.** 320 vignettes extraites d'une vidéo réelle du dépôt (1920×1080, 60 fps,
6 min 10) par le vrai détecteur, dont 40 étiquetées à la main sur six plaques
distinctes, plus 7 non-plaques. Les plaques y font **69 à 115 px de large** : la bande
que la note 12 de `CLAUDE.md` décrit comme « l'OCR travaille mais son vote est
incertain ».

### Ce que la mesure a montré

Les lectures n'étaient pas du bruit. Elles étaient **la plaque moins un caractère de
bord** :

| vérité | publié avant | confiance annoncée |
|---|---|---|
| `AR606L` | `R606L` | 0,89 |
| `A96886` | `96886` | 0,90 |
| `A8254S` | `8254S` | 0,84 |
| `A3K961` | `A3K96` | — |

Une seule plaque sur six était juste, et 8 vignettes sur 40.

**La cause est l'alphabet du modèle.** `en_PP-OCRv3_rec` connaît l'ASCII imprimable, et
rien d'autre. Une plaque chinoise commence par un idéogramme de province, qui
n'appartient à aucune de ses 97 classes. Le CTC doit pourtant émettre quelque chose
pour ces pas de temps — et ce quelque chose **contamine le caractère voisin**. Le
contrôle est net : le même recadrage privé de son bord gauche rend `A96886` à **0,97**
là où le recadrage entier rendait `96886` à 0,90.

Ce n'est donc pas un problème de résolution, de netteté, ni de seuil. C'est un
caractère hors alphabet posé contre un caractère utile.

### Le second défaut, et c'est lui qui décidait de tout

Corriger la lecture ne suffisait pas, et c'est la mesure **de bout en bout** qui l'a
dit — le harnais isolé l'aurait manqué, et l'a manqué. Avec les nouvelles variantes, le
serveur lisait bien `AR606` et `A8254S`… et publiait **zéro** plaque là où il en
publiait une (fausse) avant.

Le vote était affamé. `PlateTextVote` exige deux lectures concordantes, une confiance
cumulée de 1,2 et une domination de 1,5 — et `plate_ocr_quality_improvement`, à 1,25,
n'autorisait une relecture que si la nouvelle vignette battait la meilleure déjà lue de
25 % en largeur × netteté. Sur la vie d'un véhicule, cela laissait **deux ou trois
lectures**. Réparties sur quatre graphies voisines, aucune ne pouvait dominer, et
`DOMINANCE_RATIO` faisait son travail : refuser de trancher.

Le raisonnement d'origine de ce garde n'était pas faux — relire un recadrage équivalent
gonfle la confiance d'un texte peut-être faux — mais il était **déjà couvert** par
`plate_ocr_skip_iou`, qui interdit de relire le recadrage figé d'un véhicule arrêté au
feu, c'est-à-dire précisément ce cas.

**L'attribution, mesurée, sur la même fenêtre de la même vidéo** (vérité `AR606L`) :

| rognages | `quality` | consolidation | publié |
|---|---|---|---|
| non | 1,25 | non | `R606` ❌ |
| oui | 1,25 | non | *rien* |
| oui | 1,25 | oui | *rien* |
| oui | **1,0** | oui | **`AR606L`** ✅ |
| non | **1,0** | oui | **`AR606L`** ✅ |
| oui | **1,0** | non | **`AR606L`** ✅ |

Il faut le lire sans se raconter d'histoire : **sur ce cas précis, le seul changement
nécessaire et suffisant est `quality_improvement = 1,0`.** Ni les rognages ni la
consolidation ne portent cette correction. Ils sont retenus pour ce qu'eux-mêmes
mesurent — la justesse de chaque lecture et le sort des lectures partielles — et la
section « Ce que chaque changement gagne, séparément » le dit chiffre par chiffre.

## Décision

**Trois changements, à trois étages, et un seul des trois corrige le cas de la
capture.**

### 0. L'OCR peut relire (`settings.py`)

`plate_ocr_quality_improvement` passe de `1.25` à **`1.0`** — le garde est désactivé.
C'est le changement décisif ci-dessus.

**Et il ne coûte pas plus cher.** L'analyse de la même fenêtre n'a pas ralenti ; la
mesure la donne même plus rapide (163 s contre 209 s), parce qu'un vote qui converge
déclenche `stop_when_confident`, lequel arrête le **détecteur** de plaques — le vrai
goulot d'ADR 0015. Passer en plus à une lecture toutes les deux images analysées
(`every_n_frames = 2`) ne change **rien** au texte publié et double le temps : ce
réglage reste à 3.

### 1. Des variantes rognées à gauche (`plate_reader.py`)

Une variante de lecture de plus par fraction de `LEFT_INSET_FRACTIONS`, valant
`(0,14 ; 0,22)`, toutes dans le **même lot** que les variantes existantes.

`0,14` ≈ une cellule de caractère d'une plaque à sept cases, `0,22` ≈ une cellule d'une
plaque courte : la largeur à retirer dépend du nombre de caractères, qu'on ne connaît
pas. C'est le décodage qui départage, à confiance cumulée, comme pour toutes les
variantes depuis ADR 0007.

**L'ajout est strictement additif.** Sur une plaque latine, rogner 14 % coupe un vrai
caractère, la variante rend une chaîne plus courte, et la confiance cumulée la fait
perdre. Une variante ne peut que gagner ou être ignorée.

### 2. Une lecture partielle renforce la lecture complète (`plate_vote.py`)

`_consolidated` remplace la première voie de `PlateTextVote.text`. Un candidat reçoit
la confiance cumulée de tous les candidats dont il est un **sur-texte contigu**, puis
les trois conditions de publication de toujours s'appliquent à ce total.

Deux gardes, et **la seconde est celle qui empêche l'inverse du bug** :

- **un sur-texte ne reçoit rien tant qu'il n'a pas ses propres
  `MIN_AGREEING_READS`.** Un caractère parasite de tête — l'idéogramme lu comme un `T`,
  donnant `TA96886` là où `A96886` est juste — fabrique lui aussi un sur-texte, qui
  aspirerait les voix du bon. La règle qui l'écarte n'est pas un seuil de plus : c'est
  celle que tout le fichier applique déjà, une lecture unique est la lecture de la
  frame courante (invariant 4). Un parasite ne survient que sur la variante qui l'a
  fabriqué ; un vrai caractère de plus est relu à chaque image lisible ;
- **la domination ne se joue que contre de vrais rivaux**, c'est-à-dire les candidats
  qui ne sont ni un morceau ni une extension du gagnant. Compter un morceau de
  soi-même comme rival rendrait la garde ininterprétable : plus la plaque est lue,
  moins elle pourrait être publiée.

**Sans relation de sous-texte, `_consolidated` est exactement l'ancien code** —
`support` vaut `accumulated`, `reads_eff` vaut `reads`, le gagnant est `leader`. C'est
ce qui rend le changement additif, et les 21 tests de vote antérieurs passent sans
modification.

**Rien n'est inventé.** La consolidation ne reverse des voix qu'à des candidats
**existants** : `AR606` et `606L` se chevauchent et suggèrent `AR606L`, mais si personne
n'a lu `AR606L`, `AR606L` n'est pas publié. C'est la même garde que le consensus par
caractère, et pour la même raison — publier une plaque que personne n'a lue est le
pire résultat possible. Un test le verrouille.

## Ce que chaque changement gagne, séparément

| changement | ce qu'il corrige | mesure |
|---|---|---|
| `quality_improvement` → 1,0 | le vote n'a plus assez de lectures pour trancher | `R606` → **`AR606L`** de bout en bout ; pas de perte de cadence |
| rognages à gauche | chaque lecture perd son premier caractère | vignettes justes **8 → 17 / 40** ; échelle latine **39 → 43 / 56** ; hypothèses `8254S` → `A8254S` |
| consolidation | une lecture partielle battait la complète | plaques publiées justes **1 → 3 / 6** sur le corpus, à jeu de variantes inchangé |

**Ce que la consolidation n'a *pas* démontré**, et il faut l'écrire : sur la fenêtre
de bout en bout, elle ne change rien — la retirer publie la même plaque. Ce n'est pas
une preuve qu'elle est inutile, c'est une preuve que cette fenêtre ne la teste pas :
elle ne contient **qu'une** plaque publiable, et le gain mesuré sur le corpus porte
sur des plaques que cette fenêtre ne publie pas. Elle est retenue sur la mesure du
corpus, ses tests unitaires, et le fait qu'elle est un **no-op** en l'absence de
relation de sous-texte. Si une mesure future la trouve nuisible, c'est elle qu'il faut
retirer en premier — c'est le changement le moins étayé des trois.

## Ce que le rognage coûte

Mesuré dans le même processus, entrée identique, ordre alterné pour qu'aucune des deux
configurations ne bénéficie du réchauffement de l'autre :

| largeur de vignette | sans rognage | avec `(0,14 ; 0,22)` | facteur |
|---|---|---|---|
| 320 px | 89,4 ms | 170,6 ms | 1,91× |
| 128 px | 94,3 ms | 183,6 ms | 1,95× |
| 80 px | 99,2 ms | 170,1 ms | 1,71× |

**Et ce coût est invisible de bout en bout.** Sur la même fenêtre de la même vidéo,
avec le vrai service : **5,47 → 5,57 images par seconde**, `trackedVehicles` et
`crossings` identiques. `PlateOcrPolicy` étrangle déjà l'OCR à une lecture pour trois
images analysées et l'arrête dès que le vote est acquis ; doubler le coût d'un poste
qui ne s'exécute presque jamais ne se mesure pas. L'arbitrage d'ADR 0015 — l'OCR n'est
pas le goulot, la détection l'est — reste vrai.

**Le risque du nouveau défaut de `quality_improvement` est borné, mais pas clos.** Le
cas redouté est une vidéo où des plaques sont *détectées* sans jamais être lisibles :
l'OCR y tournerait alors une image sur trois par piste pendant toute leur vie, sans que
`stop_when_confident` puisse jamais l'arrêter. Un second clip a été mesuré
(`video_7.mp4`, 30 s) : **30,6 s contre 30,5 s**, identique — mais ce clip ne détecte
aucune plaque, il ne teste donc pas le cas. `min_width_px` (64) et `min_sharpness` (8)
restent les deux gardes qui le couvrent, et si un jour un clip montre la panne, c'est
là qu'il faudra regarder, pas dans le facteur de qualité.

## Pourquoi ces valeurs, et non les meilleures

`(0,16 ; 0,22)` publiait **quatre** plaques justes sur six au lieu de trois, et
`(0,16 ; 0,24)` retombait à trois. Un point de pourcentage qui fait basculer un
résultat sur six plaques est du **surajustement**, pas une mesure : ces valeurs n'ont
pas été retenues.

Le balayage complet montre un plateau, et c'est lui qui décide :

| rognage | plaques justes /6 | vignettes /40 | échelle latine /56 |
|---|---|---|---|
| aucun | 1 | 8 | 40 |
| 14 % seul | 2 | 15 | 43 |
| 16 % seul | 3 | 18 | 42 |
| 18 % seul | 3 | 15 | 40 |
| 20 % seul | 3 | 22 | 39 |
| 14 / 20 % | 2 | 17 | 43 |
| **14 / 22 %** | **3** | **17** | **43** |
| 16 / 22 % | 4 | 20 | 43 |
| 18 / 24 % | 3 | 16 | 40 |
| 13 / 18 / 23 % | 2 | 12 | 44 |

Toute la bande 14–22 % fait mieux que l'absence de rognage, sur les deux métriques.
`(0,14 ; 0,22)` est au milieu de ce plateau **et** au maximum du contrôle indépendant.

**Le contrôle indépendant est l'échelle de vérité terrain synthétique**, qui n'a aucun
idéogramme : si le rognage coûtait quelque chose aux plaques latines, c'est là qu'on le
verrait. Elle passe de 39 à 43 lectures justes sur 56, le gain tenant surtout au palier
64 px (**4/8 → 7/8**) et au palier 80 px (6/8 → 7/8).

## Ce qui a été essayé et **rejeté**, avec la mesure

Quatre pistes plausibles ont été mesurées et abandonnées. Elles sont écrites ici parce
que chacune se re-proposera, et que l'ADR 0008 a déjà démontré une fois que
l'intuition se trompe sur ce sujet.

1. **Élargir le recadrage** (prendre une marge autour de la boîte du détecteur, sur de
   vrais pixels de l'image source). L'hypothèse était que le détecteur rognait un
   caractère. **Elle dégrade tout** : 8/40 → 4/40 à 6 % de marge, 0/40 à 30 %. La
   raison est mécanique — la hauteur d'entrée de la tête est fixée à 48 px, donc
   élargir la vignette **rétrécit les glyphes** dans le tenseur. Le défaut n'était pas
   un cadrage trop serré.
2. **Un consensus spatial des caractères.** Le modèle ramène la largeur au huitième
   (`T = W/8`, vérifié), donc chaque caractère décodé est situable en x dans la plaque ;
   l'idée était de faire voter les **positions** plutôt que les chaînes, en agrégeant
   plusieurs variantes et sous-fenêtres. Mesuré : **1 à 3 vignettes justes sur 40**,
   contre 8 pour la référence. Le regroupement par position est trop fragile quand les
   variantes n'ont pas la même échelle.
3. **Trois réglages gratuits** — suréchantillonner pour atteindre les 48 px de hauteur
   plutôt que 120 px de largeur, `INTER_CUBIC` dans la mise en tenseur, et la limite de
   CLAHE. Aucun ne gagne : la cible en hauteur tombe à 9/40, `INTER_CUBIC` est neutre à
   négatif, et CLAHE à 3,0 ou 4,0 rend exactement le même résultat qu'à 2,0.
4. **Un filtre d'attachement** contre les fausses détections sur l'habillage vidéo.
   Une plaque bouge avec sa tôle ; une incrustation ne bouge pas. Le résidu
   `|Δplaque − Δvéhicule| / |Δvéhicule|` devait les séparer. **Il ne les sépare pas** :
   entre deux mesures étranglées, le véhicule ne se déplace que de ~1,5 px médian, soit
   le niveau du bruit de boîte, et les vraies plaques affichent déjà un résidu médian de
   0,92. Aucun seuil ne tient là-dedans.

**Couper CLAHE mérite sa propre ligne**, parce que c'est le seul cas où les deux
mesures se contredisent : l'échelle synthétique passe de 43 à **46/56**, et le corpus
réel tombe de 17 à 15 vignettes. Les plaques de synthèse sont trop propres — CLAHE n'y
a que du bruit à amplifier, alors qu'il rattrape le contraste des vraies. **Le corpus
réel tranche**, et c'est une limite de l'échelle synthétique qu'il faut garder en tête
avant de lui faire arbitrer un réglage de contraste.

## Ce que cela ne corrige pas

- **Les confusions `O`/`0` et `S`/`5`** restent (`AE67OS` pour `AE670S`). Elles sont
  inhérentes : les deux graphies sont dans l'alphabet des plaques, et aucune
  substitution ne les départage sans connaître le format national — ce qu'ADR 0007
  refuse explicitement d'inventer.
- **L'idéogramme de province n'est pas lu**, il est seulement écarté du chemin. Le
  texte publié reste la partie ASCII de la plaque. Lire `苏` demanderait un modèle de
  reconnaissance chinois (6625 classes) **et** d'étendre `ALPHANUMERIC` dans le
  domaine, l'export CSV et l'affichage : c'est un autre sujet, pas un détail
  d'implémentation.
- **Les fausses détections sur l'habillage de la vidéo source.** Cette vidéo incruste
  un panneau « voiture scannée » et un bandeau « ZEBA TECHNOLOGIE » ; le détecteur de
  véhicules y voit — légitimement — une voiture, et le détecteur de plaques trouve le
  bandeau dans son recadrage. Aucune géométrie ne les distingue, et le point 4
  ci-dessus montre que la cinématique non plus. **Le dispositif existant y répond
  déjà** : une zone de comptage sur la chaussée avec « Ignorer hors zone » exclut les
  incrustations, sans heuristique et sans risque de rejeter une vraie plaque.

## Conséquences

- `plate_ocr_left_insets` est un réglage, et `plate_ocr_variants` reste le commutateur
  maître : le couper coupe aussi les rognages, sans quoi « désactivé pour comparer » ne
  comparerait pas ce qu'on croit ;
- `scripts/anpr_bench.py` écrit `ocrLeftInsets` dans son contexte JSON, pour la même
  raison que `RenderParams` y figure déjà : deux exécutions avec des rognages
  différents ne mesurent pas la même chaîne, et un `--compare` comparerait deux
  inconnues ;
- `PlateTextVote.score` suit la voie qui a publié. Le score de la voie consolidée est
  celui des lectures **directes** du gagnant, jamais de son soutien : le soutien sert à
  *choisir* quel texte publier, il ne dit rien de la confiance avec laquelle ce
  texte-là a été lu.
