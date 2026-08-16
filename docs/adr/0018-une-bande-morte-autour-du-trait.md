# ADR 0018 — Une bande morte autour du trait

- **Statut** : accepté
- **Date** : 2026-08-14
- **Amende** : [ADR 0016](0016-compter-les-objets-suivis.md) — sans rien lui retirer.

## Contexte

Depuis ADR 0016, **chaque franchissement observé compte** : plus de déduplication
par identité, un aller-retour vaut 2, deux lignes valent 2. C'est ce qu'on veut, et
ce n'est pas remis en cause ici.

Mais « observé » était décidé par le seul **signe** d'un produit vectoriel. Un
centroïde à un dixième de pixel du trait a donc un côté parfaitement défini, et le
compteur le croit. Relevé sur `video_7.mp4`, quatre lignes, `yolo11s` :

| véhicule | ligne | passages comptés | distances au trait |
|---|---|---|---|
| `#17` | `l4` | **3** en 0,14 s | +0,1 / −0,1 / +0,2 px |
| `#21` | `l2` | **3** en 0,10 s | −0,9 / +4,6 / −1,3 px |

`#17` est un véhicule **arrêté sur le trait** pendant 0,4 s : il ne bouge pas, et le
signe bascule sur du bruit numérique. `#21` est un véhicule dont la boîte de
détection s'effondre puis se rétablit — demi-boîte 69 → 47 → 38 → 61 px — ce qui
déplace son centre de quelques pixels sans que le véhicule ait bougé.

Aucun des deux n'a franchi trois fois quoi que ce soit. C'est **le doublon** que
l'utilisateur signale, et il devient plus visible à mesure que le détecteur
s'améliore : plus il détecte de véhicules lents ou partiellement occultés, plus il y
a de centroïdes qui traînent sur un trait.

L'ancien garde d'identité d'ADR 0009 masquait ce défaut sans le corriger — il
supprimait *aussi* les vrais seconds franchissements. Le supprimer était juste ; il
a simplement révélé un bug qui était là depuis le début.

## Décision

**Une bande morte autour du trait, épaisse d'un quart de demi-boîte du véhicule.**
Tant que le centroïde y est, son côté n'est pas tranché : ni franchissement, ni mise
à jour du côté mémorisé. C'est exactement le traitement que le compteur réservait
déjà au centroïde tombant *pile* sur la ligne — avec une épaisseur mesurée au lieu
de zéro.

Deux propriétés valent d'être écrites noir sur blanc :

1. **Ce n'est pas un garde d'identité.** La bande ne regarde ni le numéro du
   véhicule, ni les autres lignes, ni ce qui a déjà été compté. Un aller-retour
   franc compte toujours 2 ; deux lignes franchies comptent toujours 2. ADR 0016
   reste entier.
2. **Le segment testé enjambe la bande.** Le compteur mémorise la dernière position
   **hors bande** (`settled_centroid`) et c'est d'elle que part le segment confronté
   au trait. Sans cela, une bande morte *perd* les franchissements lents : à la
   sortie de bande, l'image précédente est du même côté que la piste, le segment ne
   coupe rien, et le véhicule n'est jamais compté. Ce mode de panne est **plus grave
   que les doublons qu'on corrige**, puisqu'il fait manquer des véhicules ; il est
   verrouillé par `test_un_vehicule_qui_traverse_la_bande_compte_une_fois`.

## Pourquoi `0.25` demi-boîte

Les deux bornes ont été touchées, et c'est ce qui fixe la valeur :

- **plancher** — le bruit mesuré plafonne à **0,10** demi-boîte (`#21` : 4,6 px pour
  une demi-boîte de 47). `0.25` laisse 2,5× de marge. En dessous, les doublons
  reviennent ;
- **plafond** — la bande est traversée *avant* d'être franchie : trop large, elle
  avale des trajets entiers. À `0.5`, un poids lourd de 400 px de large obtient une
  bande de 100 px, et le scénario de non-régression du doublon cabine/remorque —
  120 px de trajet — cessait d'être compté. **Ce test a rejeté la valeur `0.5`**, et
  c'est lui qui a fixé `0.25`.

Le seuil est **relatif à la boîte du véhicule**, jamais en pixels. Deux raisons, et
la seconde est propre à ce cas :

- un plancher absolu réglé sur du 720p ne veut plus rien dire en 4K ;
- le bruit dominant est **proportionnel à la boîte**. Une boîte qui perd 30 % de son
  étendue déplace son centre d'environ 15 % de cette étendue — donc un seuil qui ne
  suivrait pas la boîte serait trop lâche pour une moto et trop serré pour un
  camion, sur la *même* image.

## Conséquences

- un véhicule arrêté sur un trait ne produit plus de passages ; il en produira **un**
  quand il repartira, du côté où il repart ;
- **l'horodatage d'un passage est celui de la sortie de bande, pas du contact avec
  le trait.** Le décalage vaut typiquement quelques images, mais il n'est pas
  toujours négligeable, et le chiffre mérite d'être écrit : mesuré à **2,2 s** sur
  `video_7.mp4` pour un véhicule de demi-boîte 164 px abordant `l8` presque
  parallèlement — sa bande fait alors 41 px, et son centre ne dérive que de 11 px
  par seconde. Le comptage est juste, sa date est tardive.

  Le remède existe et n'a pas été retenu ici : mémoriser l'instant de
  l'intersection réelle comme *candidat*, puis l'émettre — avec sa date d'origine —
  une fois la bande franchie. Il déplace le problème sur l'ordre d'émission des
  événements, que le journal et l'histogramme supposent croissant. À reprendre si
  la date d'un passage devient un usage à part entière ;
- **un franchissement peut être perdu si la piste meurt dans la bande.** Le cas
  n'est pas silencieux : il devient un quasi-franchissement, publié par ligne dans
  `diagnostics.nearMisses` et affiché sur la carte de la ligne ;
- mesuré sur `video_7.mp4`, tracé identique, avant/après : `yolo11m` **16 → 14**
  passages, `yolo11s` **18 → 14**. Les disparus sont exactement les répétitions
  d'une même ligne par un même véhicule en moins d'une seconde. `yolov8n` reste à
  **13**, inchangé : il ne produisait pas ce défaut, faute de détecter les véhicules
  concernés assez finement.

  Le contrôle le plus parlant n'est pas la baisse, c'est la **convergence** :
  `yolo11s` et `yolo11m`, deux détecteurs différents, publient désormais les *mêmes*
  14 passages, sur les mêmes lignes, aux mêmes secondes. Avant la bande, ils
  différaient de quatre.

## Alternatives écartées

**Un délai de garde temporel** — ignorer un second franchissement de la même ligne
par la même piste avant *N* millisecondes. Plus simple, mais il choisit un seuil
dans une unité qui n'a rien à voir avec la cause : le bruit est spatial, pas
temporel. Un véhicule à l'arrêt sur le trait pendant dix secondes le déjouerait, et
un vrai demi-tour rapide serait supprimé.

**Lisser la trajectoire du centroïde** — un filtre sur les positions. Il déplace les
franchissements dans le temps, touche *tout* le domaine (vitesse, zones, ancre de
plaque) pour corriger un défaut local à une ligne, et son réglage serait bien plus
difficile à justifier que « un quart de boîte ».

**Compter sur le franchissement de la boîte plutôt que du centroïde** — cela
changerait la sémantique du comptage partout (invariant 2 et piège 10 : le
centroïde décide de tout), et une boîte large franchirait la ligne bien avant le
véhicule.
