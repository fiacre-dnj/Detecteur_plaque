# ADR 0016 — Compter les objets suivis, et nommer les sens de franchissement

- **Statut** : accepté
- **Date** : 2026-08-13
- **Abroge** : [ADR 0009](0009-un-comptage-par-vehicule.md) définitivement — son garde
  est supprimé, plus seulement débranché — et la décision d'[ADR 0014](0014-compter-des-passages.md)
  de conserver le drapeau `dedupe_by_identity`
- **Amende** : les invariants 3, 4, 6 et 7 de `CLAUDE.md`

## Contexte

### Le défaut observé

Un utilisateur regarde l'overlay pendant une analyse et voit `car #1`, `car #2`,
`car #3`… puis, au milieu de la vidéo, **`car #1` revient**. Le comptage global est
donc faux : le badge le plus élevé ne décrit pas le nombre de véhicules vus.

Ce numéro n'est pas celui du tracker. C'est `globalId`, émis par notre galerie de
ré-identification (`counting/domain/reid.py`). La galerie *relâche* une identité quand
sa piste se tait plus de `max_lost_ms`, puis la *ré-attache* à une piste ultérieure dont
l'apparence correspond. Le numéro qui revient est donc le comportement documenté du
mécanisme, pas une régression — mais c'est un mécanisme dont ADR 0014 avait déjà
constaté qu'il **sortait du périmètre produit**.

Ce que la galerie coûtait encore : un descripteur d'apparence 16×16 calculé pour chaque
piste sans identité et rafraîchi une image sur huit, un appariement glouton sur toutes
les entrées éligibles, un gate de déplacement en fraction de diagonale, et une clé de
comptage `(identité, génération)` que rien ne consommait plus — `dedupe_by_identity`
étant à `False` depuis ADR 0014.

### La question produit derrière

« Combien de véhicules passent à ce carrefour ? » n'a pas de réponse dans l'écran
actuel. `crossings` compte des passages et dépend du tracé ; `uniqueVehicles` promettait
des véhicules distincts et ne les tenait pas. Et « combien entrent ou sortent de cette
rue ? » n'a pas de réponse du tout : un sens s'affiche « ↑ 12 · ↓ 8 », ce qui n'apprend
rien à qui n'a pas la convention A→B en tête.

## Décision 1 — Un objet suivi est un véhicule

`counting/domain/reid.py` est **supprimé**. Il est remplacé par
`counting/domain/track_numbering.py`, qui ne compare rien et ne recolle jamais deux
pistes. `AnalysisSession.feed()` ne reçoit même plus l'image : le comptage ne touche
plus un seul pixel.

`AnalysisStats.tracked_vehicles` remplace `unique_vehicles` : le nombre de pistes du
tracker **confirmées** (`hits >= min_hits`). Un scintillement du détecteur sur une seule
image n'est pas un véhicule.

### Ce qu'on garde de la galerie : le vote de classe

Une seule pièce survit, et elle n'a rien à voir avec la ré-identification : le **vote
majoritaire de classe**, à égalité duquel le tenant garde la place. C'est lui qui tient
l'invariant 4 — un véhicule dont la lecture vacille entre `bus` et `truck` ne doit pas
changer de compteur au gré des images — et c'est ce qui rend le type **cohérent entre
véhicules de types différents**, qui était la demande explicite.

### Faisabilité : le tracker fait déjà exactement ce qu'il faut

Vérifié dans les sources installées, `backend/.venv/Lib/site-packages/ultralytics/trackers/` :

| fait | où | conséquence |
|---|---|---|
| `next_id()` ne fait qu'incrémenter `BaseTrack._count` | `basetrack.py:74-77` | aucun chemin ne décrémente ni ne recycle |
| une piste perdue est réactivée avec `new_id=False` | `byte_tracker.py:412` | elle retrouve **son** identifiant, jamais celui d'un autre objet |
| `BYTETracker.reset()` remet le compteur à zéro | `byte_tracker.py:521-528` | déjà appelé par `reset_trackers()` au début de chaque analyse |
| le compteur est unique pour toutes les classes | `basetrack.py:57` | la cohérence inter-types est native, pas à construire |

### Mais le numéro publié reste **local à la session**

`globalId` n'est pas le `track_id` brut, et ce n'est pas de la prudence gratuite.

`BaseTrack._count` est un attribut de **classe**, donc partagé par tout le processus.
`JobManager` borne à un job simultané (`max_concurrent_jobs=1`) et `SessionService` à une
session temps réel (`max_sessions=1`), mais ce sont **deux bornes indépendantes** :
ouvrir la caméra pendant qu'un fichier s'analyse appelle `reset_trackers()`, remet le
compteur global à zéro, et l'analyse en cours se remet à émettre des identifiants 1, 2,
3 — qu'elle a déjà utilisés. Avec `globalId = trackId`, deux véhicules distincts
fusionneraient sous le même numéro, **sans qu'aucune exception ne soit levée**.

La session tient donc sa propre correspondance `track_id → numéro`, et
`TrackNumbering.forget()` la retire quand la piste est abandonnée. Un identifiant réémis
au-delà de `max_lost_ms` reçoit alors un numéro neuf.

### Émettre un numéro et compter un véhicule sont deux gestes distincts

Un numéro est émis dès la **première image** d'une piste, pas à sa confirmation. Sans
cela, la première lecture de plaque n'aurait pas d'agrégat où voter et `first_seen_ms`
daterait de la confirmation au lieu de la première apparition — les deux ont été mesurés
en tentant l'inverse, et les deux régressaient.

Seule une piste **confirmée** entre dans `size`. Conséquence à connaître : **la suite
des numéros comptés a des trous**. Un scintillement consomme un numéro sans jamais être
compté, donc `tracked_vehicles` est inférieur au plus grand numéro visible à l'écran.
C'est le prix d'un badge qui ne change jamais en cours de route ; renuméroter à la
confirmation ferait qu'un même véhicule change de numéro entre sa première et sa
deuxième image.

### La conséquence assumée

**Une occlusion plus longue que `track_buffer` (2,5 s) donne un véhicule de plus.** Plus
rien ne recolle deux morceaux de piste. C'est la contrepartie directe d'un numéro qui ne
revient jamais en arrière, et elle est verrouillée par un test —
`test_un_vehicule_occulte_trop_longtemps_compte_deux_fois` — qui remplace celui qui
attendait l'inverse. Un test qui affirme la contrepartie autant que le bénéfice est ce
qui empêche de « corriger » l'un en cassant l'autre.

### Le garde d'ADR 0009 est supprimé, plus débranché

`dedupe_by_identity` disparaît, ainsi que `reid_count`, `reid_hits` et la clé
`(identité, génération)`. ADR 0014 l'avait conservé pour que « le rallumer soit un
mot » ; sa clé était `reid_count`, qui n'existe plus. Garder le drapeau aurait été garder
un réglage annoncé et sans effet — le pire état d'un réglage, exactement ce que ce même
ADR reprochait au curseur de similarité.

## Décision 2 — Chaque ligne porte deux sens nommés, avec un rôle

`CountingLineDef` gagne `positive_name`, `negative_name`, `positive_role`,
`negative_role`. `DirectionRole` vaut `entry`, `exit` ou `neutral`.

**Le compteur ne les lit jamais.** Ils traversent le domaine pour être persistés dans
`config_json` — ce qui les rend rejouables depuis l'historique sans une seule colonne
nouvelle — et rendus à l'interface.

### Les rôles ne sont pas agrégés côté serveur

`AnalysisStats` ne gagne ni `entries` ni `exits`. La correspondance sens → rôle est faite
en **un seul endroit**, le frontend
(`features/results-dashboard/model/directions.ts`), à partir de sa géométrie courante.
Deux raisons, dans cet ordre :

1. **corriger un libellé ou un rôle est instantané** et ne demande pas de relancer une
   analyse de trente minutes. Un mot ne doit pas changer un chiffre du serveur ;
2. **la règle de classement n'existe pas en double.** C'est la famille de bug que ce
   dépôt documente le plus : deux copies d'une règle finissent par diverger, et c'est un
   passage qui change de colonne selon l'écran qui le montre.

Corollaire : `geometrySignature()` continue d'**exclure** les noms et les rôles.
Renommer un sens ne change aucun chiffre, donc n'affiche pas la bannière « résultat
obsolète ».

### Le nom vide est un signal, pas un oubli

`''` demande à l'interface de poser son défaut géométrique
(`defaultDirectionNames`), **recalculé à l'affichage**. C'est ce qui fait suivre le
libellé quand on fait pivoter la ligne : écrire un défaut à la création le figerait à
l'orientation de ce moment-là, et une ligne devenue verticale dirait « Vers le bas ».

Le vocabulaire est celui de l'**image** — « vers le haut », « vers la droite » — et non
celui d'une boussole : « vers le nord » demanderait de connaître l'orientation de la
caméra, que rien ne nous dit. L'utilisateur qui veut du cardinal l'écrit lui-même, et
c'est à quoi servent les champs.

### Trois étiquettes, deux côtés : le placement se calcule

Un trait n'offre que deux côtés, et il y avait trois choses à écrire — le nom de la
ligne et les deux sens. Posées naïvement, elles se recouvraient dans trois cas
distincts, tous visibles sur un tracé réel :

| collision | cause | correctif |
|---|---|---|
| nom ↔ sens négatif | les deux au milieu, sur le même axe perpendiculaire | le nom passe près de la poignée A, comme les zones |
| sens ↔ sens | décalage fixe de 30 px, alors qu'une boîte fait 130 px de large | décalage = dégagement + `\|n.x\|·w/2 + \|n.y\|·h/2`, donc **espace constant quel que soit l'angle** |
| ligne ↔ ligne voisine | chaque ligne s'étiquetait seule | une passe globale, `resolveLabelCollisions`, après tous les traits |

Deux règles gouvernent l'écartement : une étiquette fuit **le long de son propre
normal** — de l'autre côté du trait, elle nommerait le mauvais sens — et une étiquette
qui ne trouve pas de place est **posée quand même**, parce qu'un libellé absent se lit
comme un sens non configuré. Tout est borné au canvas : une ligne tracée près d'un bord
poussait sinon son libellé hors cadre, où il était simplement invisible.

Le flash de comptage **met en valeur le libellé existant** au lieu d'en peindre un
quatrième : c'est le sens qui vient de compter, pas une information nouvelle. Une
étiquette de plus, c'était une collision de plus.

### `DirectionTally` : le détail par sens

`LineTally` est restructuré. `total` et `by_class` deviennent des **propriétés dérivées**
de deux `DirectionTally`, qui portent chacun son `total`, son `by_class`, son `first_ms`
et son `last_ms`. L'invariant 3 devient structurel plutôt que surveillé :
`total == positive.total + negative.total` est vrai par construction.

C'est ce qui rend calculable la matrice **type × sens** — « combien de camions
*entrent* » — qu'un `by_class` fusionné ne sait pas distinguer d'un camion qui sort.

## Décision 3 — Les KPI répondent aux questions d'un carrefour

Ce que l'écran gagne, et la question à laquelle chaque chiffre répond :

| chiffre | question | source |
|---|---|---|
| Véhicules détectés | combien passent ici, tracé ou pas ? | `trackedVehicles` |
| Franchissements | combien de passages sur mes lignes ? | `crossings` |
| Entrées / Sorties / Solde | la rue se remplit-elle ou se vide-t-elle ? | rôles, côté client |
| Sans franchissement | ma ligne est-elle bien posée ? | `trackedVehicles − crossedUnique` |
| Par sens : total, part, débit, types, premier/dernier | quel sens porte le trafic, et quand ? | `DirectionTally` |
| Mouvements (O-D) | entré par où, ressorti par où ? | `vehicles[].crossedLines` |

La **matrice origine-destination** est dérivée des franchissements consécutifs d'un même
véhicule. Rien de nouveau ne voyage sur le fil et rien n'est accumulé côté serveur. Deux
limites sont **écrites à l'écran** plutôt que découvertes en additionnant : un véhicule
qui franchit trois lignes produit deux mouvements (la somme décrit des trajets, pas des
véhicules), et un véhicule qui n'a franchi qu'une ligne n'y apparaît pas tout en comptant
dans les totaux. Elle n'existe que sur un résultat complet — l'aperçu SSE ne transporte
pas le registre — et l'onglet le dit au lieu d'afficher une matrice vide.

`ClassBreakdown` perd toute mention d'« unique » : par type, elle affiche les véhicules
détectés, les passages, la part en barre, et la ventilation par sens.

## Décision 4 — Le contrat est renommé, avec migration

| avant | après |
|---|---|
| `stats.uniqueVehicles` | `stats.trackedVehicles` |
| `stats.uniqueByClass` | `stats.trackedByClass` |
| `stats.reidHits` | supprimé |
| `track.reidCount`, `vehicle.reidCount` | supprimés |
| `request.reidMinSimilarity` | supprimé |
| `byLine[*].byDirection.{positive,negative}: number` | `: DirectionTally` |
| `jobs.unique_vehicles` | `jobs.tracked_vehicles` |
| `jobs.reid_hits` | supprimée |
| `job_vehicles.reid_count` | `job_vehicles.crossings_count` |

Migration `5d1c7b9042ae`. `crossings_count` est **recréée à zéro** et non transposée : les
deux colonnes comptent des choses différentes, et transposer l'une sur l'autre
remplirait la nouvelle de chiffres plausibles et faux — la pire des reprises de données.
Elle est dénormalisée depuis `crossed_lines_json` pour rendre indexable « montre-moi les
véhicules qui n'ont franchi aucune ligne », qui remplace le filtre `minReid` de l'API.

**Les résultats archivés avant cette date ne se rechargent plus dans le studio.** Leur
`result.json.gz` porte les anciennes clés. C'est assumé, et c'est la même position
qu'ADR 0014 : les chiffres d'avant et d'après un changement de sémantique de comptage ne
sont pas comparables. La liste d'historique reste lisible — elle ne lit que les colonnes
dénormalisées.

## Conséquences

### Ce qui devient vrai

- le badge le plus élevé de l'overlay **est** le nombre de véhicules détectés, aux
  scintillements près ;
- `len(vehicles()) == stats.tracked_vehicles`, exactement. Sous la galerie, seul un
  `<=` tenait : le registre était indexé sur les agrégats et le total sur un compteur
  d'émission distinct ;
- plus aucun descripteur d'apparence n'est calculé par image. Le gain n'a pas été
  mesuré séparément — la galerie était chiffrée à 0,6 ms/image en ADR 0014, à comparer
  aux 38,9 ms d'inférence GPU : ce n'est pas une décision de performance, et la
  présenter comme telle serait trompeur ;
- l'ordre « relâcher avant admettre » (invariant 7) perd son objet : plus rien n'est
  admis. L'ordre `_release_lost` → `_number_tracks` reste, pour une autre raison —
  libérer l'identifiant de piste avant de numéroter.

### Ce qui devient faux, et qu'il faut savoir

- une occlusion longue compte deux véhicules ;
- la suite des numéros a des trous ;
- comparer un `tracked_vehicles` d'aujourd'hui à un `unique_vehicles` d'hier n'a pas de
  sens.

## Alternatives écartées

**Publier le `track_id` brut comme numéro.** Le plus simple, et c'était l'intention
initiale. Écarté à cause du `BaseTrack._count` partagé : la panne est silencieuse et
fusionne deux véhicules, ce qui est l'erreur la plus difficile à remarquer — un total qui
baisse sans que rien à l'écran ne l'explique.

**Numéroter à la confirmation pour une suite sans trou.** Tenté, puis abandonné sur
mesure : la première lecture de plaque perdait son agrégat et `first_seen_ms` datait de
la confirmation. Deux régressions réelles contre une propriété cosmétique.

**Garder la galerie et se contenter d'empêcher la réattribution d'un numéro.** Aurait
laissé en place l'appariement d'apparence, ses six réglages et ses sept pièges
(entrées 12 à 18 de `prompt/13`), pour un mécanisme hors périmètre depuis ADR 0014.

**Agréger les entrées/sorties côté serveur.** Aurait rendu un renommage dépendant d'une
relance d'analyse, et aurait posé la règle de classement à deux endroits — le rejeu
client la duplique nécessairement.
