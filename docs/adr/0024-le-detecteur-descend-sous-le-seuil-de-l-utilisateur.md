# ADR 0024 — Le détecteur descend sous le seuil de l'utilisateur

- **Statut** : accepté
- **Date** : 2026-08-17
- **Complète** : [ADR 0023](0023-un-vehicule-compte-est-un-vehicule-qui-franchit.md),
  même objectif — qu'un véhicule qui entre soit toujours compté.

## Contexte

BoT-SORT hérite de ByteTrack, dont toute la valeur tient dans une idée : le
tracker reçoit **toutes** les détections et les range en deux bandes
(`byte_tracker.py`, `_split`) —

- **haute** (`≥ track_high_thresh`) : première association, et seule à pouvoir
  *créer* une piste (`new_track_thresh`) ;
- **basse** (`track_low_thresh < score < track_high_thresh`) : seconde
  association, qui sert **uniquement à prolonger une piste existante**, par
  recouvrement de boîtes seul (`iou_distance`, seuil 0,5).

C'est la bande basse qui tient un véhicule dont la confiance plonge le temps
d'une occlusion partielle, d'un flou de mouvement ou d'un reflet.

**Elle était vide.** Ultralytics filtre les détections *avant* que le tracker les
voie, et le projet passait `conf = confidence_threshold` (0,35 par défaut) à
`track()`. La bande basse du fichier de suivi va de 0,10 à 0,25 : rien ne pouvait
y tomber. La seconde association était du code mort depuis toujours.

Conséquence en chaîne, et c'est elle qui coûte des franchissements : une
confiance qui plonge une seule image coupe la piste ; une piste coupée reçoit un
`track_id` neuf, donc un numéro de véhicule neuf ; le compteur de lignes
**ré-amorce** sur cette nouvelle identité (ADR 0023) et perd le franchissement
s'il tombe dans cette fenêtre. Le même véhicule est en outre compté deux fois.

## Décision

Le détecteur reçoit `track_low_thresh` (0,10) comme plancher. Le seuil de
l'utilisateur est transmis au tracker, dans le fichier de suivi dérivé, sur
**deux** clés :

- `track_high_thresh` — sépare les deux bandes. Sans lui, toutes les détections
  resteraient « hautes » et la bande basse resterait vide ;
- `new_track_thresh` — garde la **création** de pistes au seuil de l'utilisateur.

C'est cette seconde clé qui rend le changement **strictement additif** : une
détection faible peut prolonger une piste, jamais en ouvrir une. La création de
pistes est donc bit-pour-bit celle d'avant.

## Mesure

Vidéo de trafic réelle du dépôt, `yolo11n`, quatre lignes, seuil utilisateur 0,35.

| | avant | après |
|---|---|---|
| observations suivies | 4 271 | 5 181 (**+21 %**) |
| pistes distinctes (600 images) | 35 | 35 (**inchangé**) |
| franchissements (clip entier) | 61 | 61 (**inchangé**) |
| véhicules distincts ayant franchi | 36 | **37** |
| objets suivis confirmés | 92 | **83** (−9) |
| quasi-franchissements `l12` / `l14` | 10 / 3 | 8 / 1 |

Les 913 observations récupérées sont exactement celles de la bande basse. Les
−9 objets suivis sont des pistes qui se fragmentaient : le même véhicule comptait
deux fois. Les quasi-franchissements en baisse sont des pistes qui mouraient près
d'un trait et qui, désormais, vivent assez pour le franchir.

## Conséquences

- **Le total de franchissements ne bouge pas ; leur attribution, si.** Sur le clip
  entier, `l12` perd un passage et `l14` en gagne un. C'est une correction : la
  chute des quasi-franchissements de `l14` (3 → 1) montre que des pistes qui
  mouraient avant le trait le franchissent maintenant.
- **`confidence_threshold` change de rôle sans changer de sens pour l'utilisateur** :
  il ne filtre plus le détecteur, il décide ce qui *devient* une piste. La
  formulation « à partir de quelle confiance je compte un véhicule » reste vraie.
- **Coût** : le détecteur rend plus de boîtes, donc un NMS un peu plus chargé.
  Non mesurable devant l'inférence elle-même.
- Le fichier de suivi est désormais dérivé par couple (mouvement, seuil), au lieu
  du seul mouvement. Quelques fichiers temporaires de plus, un par seuil employé.
