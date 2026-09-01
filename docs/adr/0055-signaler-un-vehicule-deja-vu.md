# ADR 0055 — Signaler un véhicule déjà vu, sans rien compter deux fois

- **Statut** : accepté
- **Date** : 2026-09-01
- **Ne remet pas en cause** :
  [ADR 0016](0016-compter-les-objets-suivis.md), qui a supprimé la galerie
  d'identités. La distinction est écrite plus bas et elle est **testée**, pas
  affirmée.
- **Reprend la doctrine de** :
  [ADR 0048](0048-rechercher-un-vehicule-par-image.md) — un index de consultation
  n'est pas un compteur, et il se prouve par un test de non-régression.

## Contexte

Le besoin est venu d'un cas d'usage précis : **une même vidéo doublée sur une seule
timeline**. Quand l'analyse atteint la seconde moitié, l'écran doit dire que ces
véhicules sont déjà passés. Plus généralement : reconnaître qu'un véhicule qui
franchit une ligne ressemble à un franchisseur antérieur.

Rien de ce qui existait ne répondait à cette question :

- l'**apparence du tracker** (BoT-SORT, `with_reid`) ne sort jamais du tracker, et
  `emb_dists[dists_mask] = 1.0` annule la distance d'apparence dès que l'IoU tombe
  sous 0,5. Elle ne relie que des images consécutives (ADR 0048, ADR 0047) ;
- la **recherche par image** (ADR 0048) compare à une photo que l'utilisateur
  fournit. Elle ne peut pas répondre à « ce véhicule est-il déjà passé ? », qui ne
  suppose aucune photo et compare la vidéo à elle-même ;
- la **galerie d'identités** d'avant ADR 0016 faisait cela — et c'est précisément
  pour cela qu'elle a été supprimée.

## Ce qui distingue cette galerie de celle qu'ADR 0016 a supprimée

C'est la seule question qui compte, et la réponse tient en une phrase : **l'ancienne
alimentait le compteur, celle-ci ne le touche pas.**

L'ancienne relâchait une identité puis la ré-attachait : le second véhicule
*devenait* le premier, donc `#1` réapparaissait au milieu d'une vidéo et le total
n'avançait pas. Celle-ci **signale sans fusionner** — les deux numéros existent, les
deux véhicules sont comptés, leurs deux franchissements aussi, et un champ à part dit
qu'ils se ressemblent.

Ce n'est pas une nuance de vocabulaire, c'est une propriété vérifiable :
`test_redetection.py::TestAucuneRegression` compare `crossings`,
`tracked_vehicles`, `by_class`, la ventilation `by_line` **entière** et les
**horodatages** de chaque franchissement, avec et sans galerie. Son échec devrait
faire retirer la fonctionnalité, pas la corriger.

## Décision

Une **galerie interne au clip** (`counting/domain/appearance_gallery.py`) : chaque
véhicule qui franchit une ligne y dépose l'apparence de sa meilleure vue, et chaque
nouveau franchisseur y est comparé.

- **activée par requête**, `vehicleRematch`, **éteinte par défaut**. Un réglage de
  scène et non de déploiement, doctrine d'ADR 0036 : « des faux positifs ou rien »
  dépend de ce qu'on filme. Éteinte, aucun objet n'est construit et pas un encodage
  n'est payé — le chemin est celui d'avant, au bit près ;
- **tous les types de ligne**, sans exception. La table de `lineRules.ts` contient
  déjà toutes les lignes, `restricted` distinguant celles qui portent une règle : le
  résolveur de nom marche donc aussi sur une ligne « Comptage seul » ;
- **le score est publié brut** (`rematchOf`, `rematchScore`), le seuil d'affichage
  vit côté client. Même raison qu'ADR 0048 : les distributions se recouvrent, donc
  aucun seuil serveur n'est à la fois sûr et utile, et le baisser après coup doit
  faire apparaître les candidats sans réanalyser ;
- **une alerte par véhicule**, datée de son **premier franchissement** et nommant la
  ligne, avec son pourcentage et sa capture.

## Les quatre choix qui ne se devinent pas

### 1. Interroger avant de déposer

`lookup` puis `remember`, jamais l'inverse. `lookup` exclut bien le numéro du
candidat, mais s'appuyer là-dessus seul serait fragile : déposer d'abord ferait
remonter, au franchissement **suivant du même véhicule**, sa propre vue précédente
avec un score proche de 1. Un aller-retour se signalerait lui-même.

### 2. La garde temporelle

Un déposant n'est éligible que s'il avait **disparu de l'écran** avant que le
candidat n'apparaisse. Deux véhicules simultanément visibles ne peuvent pas être le
même objet physique, quelle que soit leur ressemblance — et c'est le faux positif le
plus visible en trafic dense, où deux voitures du même modèle et de la même couleur
se suivent.

La galerie tient donc sa **propre** fenêtre de présence, alimentée par `observe` pour
toute piste visible. Deux comparaisons de flottants par piste et par image. La lire
sur la session aurait lié un index de consultation au cœur du comptage, ce que toute
cette ADR s'emploie à éviter.

### 3. Le franchissement force l'encodage, mais pas les planchers

Un franchisseur contourne la marge de largeur (`TRAFFIC_REID_APPEARANCE_IMPROVEMENT`)
**et** le plafond par image (`TRAFFIC_REID_MAX_PER_FRAME`) : la question « ce véhicule
est-il déjà passé ? » se pose au moment du passage, pas quand la boîte atteint sa plus
grande largeur, et un franchissement n'a pas de seconde chance — c'est un instant, pas
un état.

Il ne contourne **pas** les planchers de l'adaptateur (96 px, netteté). Un embedding
sur 40 px ressemble surtout au flou (mesuré, ADR 0048) : un score calculé dessus
serait plausible et faux, ce qui est pire que pas de score.

Le coût est donc borné par le **nombre de franchissements**, pas par celui d'images —
c'est ce qui rend l'étage abordable à 21,8 ms par vignette, là où ADR 0050 a dû
inventer une marge pour borner un étage indexé sur les images.

### 4. Deux planchers de similarité, et pas un

`reid_rematch_min_similarity` est distinct de `reid_min_similarity`, et le seuil
client `DEFAULT_REMATCH_THRESHOLD` (0,75) est plus haut que
`DEFAULT_MATCH_THRESHOLD` (0,55). Deux raisons :

- **la question n'est pas la même.** Dans la recherche par image, l'utilisateur a
  fourni une photo : il *attend* des candidats et un faux positif se balaie d'un coup
  d'œil. Ici personne n'a rien demandé, et la carte affirme d'elle-même une identité
  entre deux passages ;
- **le lot grandit.** La re-détection compare chaque franchisseur à *tous* les
  précédents. Le meilleur score d'un lot de cent est mécaniquement plus haut que celui
  d'un lot de deux, donc un seuil calé sur l'autre étage dériverait avec la durée de la
  vidéo.

## Un piège corrigé au passage

`isViolation(alert)` se décidait sur `alert.line !== null`. C'était un raccourci
**exact** tant que seules les infractions nommaient une ligne — et il est devenu faux
au moment précis où une re-détection en a porté une. Sans correction, une
re-détection aurait été teintée, comptée et filtrée comme une infraction, sans que
rien ne lève. Le prédicat se décide désormais sur la **nature**, et un test le
verrouille.

C'est la même famille de panne que celles que ce dépôt documente le plus : une
propriété vraie par coïncidence, qui cesse de l'être sans bruit.

## Conséquences

- **Le comptage est inchangé**, et c'est testé sur cinq axes dont les horodatages.
- **Le coût est nul quand la case est décochée** — vérifié à la dépense
  (`vectors_produced == 0`), pas sur le résultat : un code qui encoderait quand même
  rendrait exactement le même registre, deux ordres de grandeur plus cher.
- **La capture vient gratuitement.** Tout véhicule encodé est déjà photographié
  depuis ADR 0051 (`snapshotKind: "appearance"`), donc l'alerte tient sa promesse
  « à vérifier sur la capture » sans une ligne de code de plus.
- **La colonne « Déjà vu » du registre est cliquable**, et elle ouvre les deux
  véhicules **côte à côte**. C'est la contrepartie indispensable de tout ce qui
  précède : l'écran affirme une ressemblance, et cette modale est le seul endroit où
  l'affirmation devient vérifiable. Sans elle, comparer deux captures demandait
  d'ouvrir la première, la fermer, retrouver la seconde rangée, l'ouvrir — donc de
  comparer deux images **de mémoire**, ce que l'œil fait très mal. Quatre points :
  - **l'antécédent se cherche dans TOUS les véhicules, jamais dans le jeu filtré**
    (`model/rematchPair.ts`, testé). Il peut être masqué par le filtre courant, et le
    taire viderait la comparaison de son sens précisément au moment de l'enquête. Le
    filtre décide de ce qu'on *parcourt*, pas de ce qu'on a le droit de regarder ;
  - **l'ordre est chronologique**, le déposant à gauche, jamais « celui qu'on a
    cliqué ». Une disposition qui change d'une comparaison à l'autre empêche
    justement de comparer ;
  - **la plaque lue est affichée sous chaque véhicule**, quand elle existe : deux
    textes différents réfutent une ressemblance mieux que n'importe quel score ;
  - **un second dialogue et non un mode de plus.** `SnapshotDialog` empile une
    capture et sa plaque, celui-ci met deux véhicules en colonnes : les fondre
    demanderait un drapeau qui change la disposition entière. Ce qui *est* partagé —
    le cadre d'image et son repli « purgée » — l'est pour de vrai, par
    `SnapshotFrame`, extrait à cette occasion.
- **Un résultat archivé avant cette ADR se relit** : les deux champs sont optionnels
  et absents valent « pas de re-détection ».

## Ce que cette ADR ne prétend pas

**Le seuil n'est pas mesuré.** 0,75 est un point de départ raisonné, pas un chiffre
issu du banc. La vidéo doublée est le cas idéal — métrage identique au pixel près,
donc similarité proche de 1 — et elle valide le **câblage**, pas le seuil. En trafic
réel, deux vues du même véhicule descendent à 0,387 et deux véhicules différents
montent à 0,891 (ADR 0048) : le recouvrement est large, et l'écran promet des
candidats à vérifier, jamais un verdict.

`scripts/reid_bench.py` est l'outil pour trancher sur du métrage réel. Tant que ce
n'est pas fait, ce chiffre reste un défaut d'affichage déplaçable, et non une
propriété du système.
