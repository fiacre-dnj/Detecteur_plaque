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

## Ce que la première version a raté — corrigé le 2026-09-01

Première mesure sur du métrage réel : une vidéo **doublée bout à bout**, 7 véhicules
franchisseurs par copie, décalage de 111,0 s. La bonne réponse vaut **1,00 par
construction** — les pixels sont identiques. Le registre a rendu :

| Attendu | Publié |
|---|---|
| #12 → #1 | `#1 — 100 %` ✅ |
| #13 → #2 | `#2 — 60 %` |
| #14 → #3 | `#3 — 100 %` ✅ |
| #17 → #6 | `#6 — 100 %` ✅ |
| #18 → #7 | `#7 — 42 %` |
| #19 → #8 | `#8 — 83 %` |
| #22 → #11 | **`#7 — 27 %`** ❌ mauvais véhicule |

Six appariements sur sept étaient déjà justes ; trois scores sur sept seulement
valaient 1,00. **L'encodeur n'y était pour rien** : provider CPU épinglé, aucun aléa,
et les trois 100 % le prouvent — des pixels identiques rendent un vecteur identique.

### La cause, unique, et elle explique chaque chiffre

Chaque véhicule franchit **deux** lignes, donc interroge la galerie **deux** fois,
avec deux vues **différentes** de lui-même. Or :

- `record_rematch` **écrasait sans comparer** : la dernière mesure gagnait ;
- la galerie ne gardait qu'**une** vue par véhicule, la plus large.

Donc, pour un jumeau B d'un antécédent A dont la galerie avait retenu la vue de son
*premier* franchissement : au 1ᵉʳ franchissement de B, on compare deux vues
correspondantes → **1,00**, enregistré ; au 2ᵉ, on compare sa vue 2 à la vue 1 de A →
0,60, qui **écrase** le 1,00. Quand la galerie avait retenu la vue du *second*
franchissement de A, l'écrasement final tombait juste — d'où les trois 100 %. Pour
#22, la seconde mesure trouvait même **mieux ailleurs** (#7 à 0,27), d'où
l'appariement faux.

### Les deux correctifs

1. **`record_rematch` retient le maximum**, numéro compris — jamais le meilleur score
   d'un antécédent avec le numéro d'un autre. À lui seul il suffit sur ce cas : la vue
   retenue pour A vient d'un de ses franchissements, et le franchissement correspondant
   de B produit la même image, donc 1,00.
2. **La galerie devient multi-vues** (`MAX_VIEWS_PER_VEHICLE = 4`, la plus étroite cède),
   et `lookup` prend le maximum sur les vues d'un déposant. Retire la dépendance à
   « quelle vue unique a été stockée » : sans cela, un jumeau dont un franchissement est
   refusé par les planchers de l'adaptateur rate son antécédent, refus dont il n'y a
   **aucune seconde chance** — un franchissement est un instant. Coût :
   `déposants × vues` produits scalaires, contre 21,8 ms pour un seul encodage.

Corrigé au passage, même famille : **`record_embedding` rabaissait
`appearance_width_px`** sans comparer, alors que la galerie, elle, comparait. Un
encodage forcé au franchissement sur une boîte étroite remettait donc la règle
monotone d'ADR 0050 en arrière et rouvrait des ré-encodages déjà payés.

### Et le même défaut vivait sur la recherche par image

Cette ADR a d'abord écrit, dans ce paragraphe même, que `match_score` devait **rester
remplacé** — « c'est une mesure sur la vue courante, pas un rang ». **L'argument était
faux**, et il l'était pour la raison exacte qui a fait corriger `rematch_score` : un
véhicule est encodé six à onze fois, donc publier la dernière mesure ne la rend pas
plus honnête, cela la rend **arbitraire**. La question posée est « ce véhicule
ressemble-t-il à la photo cherchée ? », et une vue oblique ne réfute pas une vue
franche (0,387 au plus bas entre deux vues d'un même véhicule, ADR 0048).

Pire, la correction ci-dessus l'avait **aggravé** : un franchissement forcé contourne
la marge de largeur, donc une vue étroite prise au passage du trait pouvait écraser le
score d'une vue trois fois plus large. Le `VehicleRecord` annonçait alors « meilleure
vue : 320 px » en portant le score d'une vue de 100 px.

Et un bug sans ambiguïté s'y cachait : **`None` effaçait un score acquis.**
`cosine_similarity` étant bornée à `[-1, 1]`, une similarité négative échoue
`score >= reid_min_similarity` **même au défaut `0.0`** — donc un `None` passait
par-dessus un 0,83 légitime, le véhicule disparaissait des résultats qu'il avait
mérités, et il gardait la photo qui servait à le vérifier (`_keep_snapshot` étant
indépendant du plancher).

`record_embedding` retient donc désormais le maximum, et `None` ne retire rien : le
plancher de déploiement décide de ce qu'on **publie**, jamais de ce qu'on **efface**.

**Ce qui ne s'est pas transposé, et c'est délibéré.** La règle « — sous le seuil » du
registre ne passe pas à la colonne « Ressemblance » : la recherche par image a un
curseur de 0 à 0,95 dont l'aide dit « descendre trouve plus de candidats », la cellule
n'affirme aucune **identité** — elle montre un nombre — et c'est ce nombre qui permet
de comprendre pourquoi un véhicule tombe juste sous le curseur. `hasMatch` continue
pour la même raison de ne pas exiger un score au-dessus du seuil : cette colonne
**est** la surface de retour du curseur.

### Et le bruit sous le seuil

Les sept véhicules de la **première** copie n'ont, par construction, aucun jumeau
antérieur — et la colonne leur affichait quand même leur meilleur voisin, à 2 %, 27 %,
31 %, en gris. Le motif d'origine (« voir qu'on est passé à côté de peu ») ne survit
pas à l'usage : l'écran se lisait comme « le système se trompe partout ». Une identité
affirmée à 2 % n'est pas une information nuancée, c'est une affirmation fausse.

Le registre applique donc le seuil, comme le tiroir d'alertes le faisait déjà — les
deux surfaces disaient deux choses différentes des mêmes données. Le score brut reste
dans l'infobulle, où il sert au réglage sans rien prétendre, et le CSV continue de
l'exporter : c'est de la donnée, pas une vue.

### Enfin, une fonctionnalité qui n'avait jamais tourné

`AlertsPanel` accepte une prop `scores` et `alertScore` était testé — mais
`StudioPage` ne l'a **jamais** passée (`git log -S "scores={"` : aucun résultat). Les
alertes de plaque s'en sortaient par leur score gelé ; « Véhicule recherché » et
« Véhicule déjà vu » n'affichaient donc **aucun** pourcentage. La carte est désormais
construite et passée.

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
