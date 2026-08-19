# ADR 0032 — L'OCR n'était pas le goulot : le détecteur de plaques l'est, et il paie une inférence par véhicule

- **Statut** : accepté
- **Date** : 2026-08-19
- **Corrige** : la répartition annoncée par
  [ADR 0030](0030-le-detecteur-de-plaques-payait-une-inference-par-vehicule.md) et la
  décision 15 de `CLAUDE.md`, dont la conclusion « c'est l'OCR qu'il faut optimiser
  maintenant » ne vaut pas pour une vue de circulation.
- **Suit** : [ADR 0031](0031-le-decodage-payait-la-resolution-sur-le-chemin-critique.md),
  qui a retiré le décodage du chemin critique et laissé l'ANPR seule au sommet du
  budget.

## Contexte

ADR 0030 concluait, mesures en main, que l'OCR était devenue le premier poste :
**262 ms par image, 60 %** du budget, contre 90 ms pour le suivi et 81 pour la
détection de plaques. Le plan de travail qui en découlait était de **recouvrir l'OCR
avec le travail GPU**, seul levier structurel restant.

Cette conclusion a été vérifiée avant d'être suivie, sur une scène de circulation
réelle du dépôt (1920×1080, **6 à 14 véhicules par image**, 200 images mesurées après
20 de rodage, `yolov8n`, GPU, ANPR **et** OCR actives) :

| poste | ms/image | part |
|---|---|---|
| **détection de plaques** | **76,2** | **72,9 %** |
| suivi des véhicules (inférence) | 8,1 | 7,8 % |
| décodage | 6,0 | 5,7 % |
| association (tracker) | 5,9 | 5,6 % |
| prétraitement | 4,2 | 4,0 % |
| post-traitement (NMS) | 3,4 | 3,2 % |
| domaine | 0,4 | 0,4 % |
| **OCR** | **0,4** | **0,3 %** |

**L'OCR pèse 0,3 %, pas 60 %.** L'écart n'est pas une erreur d'ADR 0030 : ses 262 ms
venaient d'un profil où les trois étages sont forcés sur *chaque* image, ce que son
texte dit d'ailleurs. En production, l'OCR est étranglée (une image sur trois par
piste), s'arrête dès qu'un vote est acquis — et surtout, sur une vue de circulation,
**elle ne se déclenche presque jamais** : les plaques y sont sous le plancher de
lecture.

Le levier prévu — recouvrir l'OCR avec le GPU — aurait donc rendu **0,3 %**. Il n'est
pas abandonné (une scène de plan serré change tout), il est **déclassé**, avec sa
mesure.

## Ce que le détecteur de plaques coûte, et pourquoi

Le coût est **linéaire en nombre de recadrages**, mesuré hors pipeline sur les mêmes
huit véhicules d'une même image :

| recadrages soumis | ms/appel | ms/recadrage |
|---|---|---|
| 1 | 21,5 | 21,5 |
| 2 | 37,6 | 18,8 |
| 4 | 72,8 | 18,2 |
| 8 | 139,7 | 17,5 |

**Chaque véhicule paie une inférence complète**, ~17,5 ms, soit l'équivalent d'une
image entière du détecteur de véhicules (8,1 ms d'inférence + 4,2 de prétraitement +
3,4 de post-traitement ≈ 15,7 ms). Ce n'est pas un défaut d'implémentation : c'est le
prix des deux étages (ADR 0007) — une plaque fait 15 px en plein cadre, elle n'est
visible qu'après recadrage. Le lot d'ADR 0030 amortit déjà le coût fixe d'un appel ;
il ne peut pas amortir le calcul lui-même.

## Décision 1 — le côté d'entrée du détecteur devient réglable, et **reste à 640**

`TRAFFIC_PLATE_NET_SIZE` (multiple de 32, défaut 640) remplace la constante
`NET_SIZE`. C'était le levier le plus prometteur : le coût varie comme le carré du
côté, et sur une image isolée les trois valeurs trouvaient les mêmes 7 plaques sur 8.

**La mesure sur 60 images l'a démoli**, et c'est pour cela qu'elle a été faite :

| côté | ms/image | plaques localisées | textes décodés |
|---|---|---|---|
| **640** | 96,1 | **94** | 44 |
| 448 | 55,7 | **22** (−77 %) | 22 |
| 320 | 33,5 | **0** | 0 |

Le rappel s'effondre bien plus vite que le coût ne baisse. La raison est celle
d'ADR 0008 : ce qui décide qu'une plaque est trouvée est sa taille **dans l'entrée du
réseau**, et le recadrage y est agrandi jusqu'au côté choisi — une plaque y occupe
~0,15 × côté, soit ~96 px à 640 et ~48 px à 320. Descendre revient donc à demander au
réseau de trouver des objets de 48 px là où il a été entraîné à en voir de 96.

**Le réglage est conservé malgré tout**, pour la même raison que la mosaïque
d'ADR 0008 : sur un plan serré, où les plaques sont grandes, l'arbitrage peut
s'inverser, et il faut pouvoir le vérifier sans recompiler. `anpr_bench.py --net-size`
et `pipeline_bench.py --plate-net-size` rendent la mesure rejouable.

## Décision 2 — un plafond de recadrages par image, à `0` par défaut

`TRAFFIC_PLATE_DETECT_MAX_PER_FRAME` borne le nombre de recadrages soumis par image
analysée. C'est le seul mécanisme qui rende le coût de l'ANPR **indépendant de la
scène** : sans lui, la cadence suit la circulation, et une source plus définie fait
franchir le seuil de largeur à davantage de véhicules, donc coûte davantage.

Le classement est une fonction pure du domaine (`select_within_budget`) :

1. **les pistes jamais mesurées d'abord.** Sans cette priorité, un véhicule apparu au
   milieu d'un embouteillage pourrait traverser tout le champ sans une seule mesure,
   donc sans jamais afficher de rectangle — un silence qui se lit comme une panne ;
2. **les plus larges ensuite**, la largeur du véhicule étant le meilleur prédicteur
   disponible de la lisibilité de sa plaque ;
3. **l'identité à égalité stricte**, pour que deux courses du même clip dépensent au
   même endroit.

Ce qui est écarté n'est pas perdu : la piste reçoit son ancre reprojetée comme sur
n'importe quelle image sautée (ADR 0010), donc aucun rectangle ne clignote, et le
texte publié reste un vote sur la vie du véhicule (invariant 4).

Mesuré sur la scène dense, courses enchaînées, **comptages identiques** :

| plafond | img/s | recadrages/image | plaques publiées |
|---|---|---|---|
| 0 (illimité) | 7,3 | 2,47 | 0 |
| **2** | **11,0** | 1,85 | 0 |
| 1 | 7,8 | 1,00 | 0 |

Soit **1,27× à 1,51×** selon la passe, à comptage identique. Sur une scène 4K où une
plaque est effectivement publiée, le plafond ne change rien à ce qu'elle publie
(`8254S` avant comme après) : il ne mord qu'à partir de trois véhicules simultanés.

**`0` par défaut**, c'est-à-dire le comportement historique. Plafonner écarte des
mesures, donc des plaques possibles ; cet arbitrage appartient à l'exploitant.

## Ce que la mesure n'expliquait pas — et qui est expliqué depuis

**Le plafond n'était pas monotone : `1` ne gagnait rien, `2` gagnait beaucoup.** Et le
coût par appel observé *dans le pipeline* était de ~99 ms pour un seul recadrage, contre
**21,5 ms mesurées hors pipeline sur le même modèle et le même recadrage**.

[ADR 0033](0033-l-autotune-cudnn-se-reetalonnait-a-chaque-plaque.md) a trouvé la cause,
et ce n'était aucune des pistes soupçonnées ici : ce n'était pas un coût mais **une
pause**. Six appels sur 90 dépassaient la seconde et pesaient 73 % de l'étage, parce que
l'autotune cuDNN se réétalonne à chaque **nouvelle forme d'entrée** et qu'un recadrage
soumis seul en produit une par rapport d'aspect de véhicule. Deux recadrages ou plus
forcent une entrée carrée constante — d'où l'avantage apparent de `max_per_frame = 2`,
qui n'était qu'un évitement de ce défaut.

**Les chiffres de la décision 2 ci-dessus sont donc ceux d'un pipeline défectueux.**
Après correctif, sur la même scène dense et à comptages identiques :

| plafond | img/s | recadrages/image | plaques **localisées** |
|---|---|---|---|
| 0 (illimité) | 11,0 | 2,28 | **180** |
| 2 | 9,0 | 1,74 | 137 |
| 1 | 13,8 | 1,00 | 76 |

Le plafond **coûte des plaques localisées**, à peu près proportionnellement aux
recadrages écartés, et sa cadence ne s'ordonne toujours pas proprement (`2` plus lent que
`0` sur cette passe, à coût d'étage quasi égal). Ce qu'il fait reste vrai et utile — il
**borne** le coût quand le trafic monte — mais il ne l'améliore pas dans le cas général,
et il reste à `0` par défaut.

## Ce que la mesure dit à l'utilisateur, et qui compte plus que tout le reste

Sur cette scène — une vue de circulation 1080p, la cible même du projet — **aucune
plaque ne peut être publiée**, et l'ANPR y dépense donc 73 % du budget pour rien :

- les plaques localisées y font **moins de 48 px de large** (histogramme du banc : 22
  vignettes sur 22 sous 48 px) ;
- le plancher de lecture est mesuré à **64 px**, et l'échelle de vérité terrain donne
  **0/8 lectures justes à 48 px** (invariant 12) ;
- le service publie donc `plate_unread_reason = too_small` avec la largeur vue, ce qui
  était déjà la décision 14 — et c'est exactement l'information à lire avant
  d'attendre quoi que ce soit de l'OCR.

Deux gestes règlent cela, et aucun n'est un réglage de performance : **resserrer le
plan** (une plaque de 64 px demande un véhicule de ~430 px sur une vue de trafic, où le
rapport plaque/véhicule vaut 0,05 à 0,25) ou **filmer plus défini** — sur la même
scène en 4K, l'OCR se déclenche et publie. C'est le seul endroit où la haute résolution
achète quelque chose, et ADR 0031 en a supprimé le surcoût de décodage.

## Conséquences

- `plate_detector.py` porte son côté d'entrée en attribut d'instance ; les deux chemins
  — lot et mosaïque — le lisent, et un test vérifie que la tuile est **construite** au
  côté demandé. La bâtir à 640 pour l'inférer à 320 rétrécirait chaque cellule d'un
  facteur deux sans que rien ne le dise ;
- `select_within_budget` vit dans le domaine et est réexportée par le contrat de
  `counting` : le classement est une règle pure, la décision de plafonner appartient au
  service, qui seul sait ce qu'une inférence coûte. Même partage que
  `should_detect` / `_detect_plates` ;
- les deux bancs savent varier ces valeurs (`--net-size`, `--plate-net-size`,
  `TRAFFIC_PLATE_DETECT_MAX_PER_FRAME`), donc tous les chiffres ci-dessus sont
  rejouables ;
- **le recouvrement de l'OCR reste à faire**, et son gain attendu est désormais chiffré
  à 0,3 % sur une vue de circulation, contre l'essentiel du budget sur un plan serré où
  les plaques dépassent 64 px. Le décider demande de mesurer *cette* scène-là, que le
  dépôt ne contient pas encore.
