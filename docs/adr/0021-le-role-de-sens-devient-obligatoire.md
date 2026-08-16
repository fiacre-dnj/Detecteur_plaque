# ADR 0021 — Le rôle de sens devient obligatoire, et remplace le nom libre

- **Statut** : accepté
- **Date** : 2026-08-16
- **Amende** : [ADR 0016](0016-compter-les-objets-suivis.md) — sans toucher au
  comptage, seulement à l'édition des sens.

## Contexte

Depuis ADR 0016, chaque sens de ligne porte un nom libre (« Vers le haut », « Vers
le bas », ou tout texte saisi) et un rôle **optionnel** — entrée, sortie, ou
« ni l'un ni l'autre » (`neutral`), le défaut. Le panneau de géométrie proposait
deux champs distincts : un champ de texte pour le nom, trois boutons pour le
rôle.

Deux frictions observées :

- le nom géométrique par défaut (« Vers le haut ») ne dit rien du bilan du
  carrefour, contrairement à « Entrée » ou « Sortie » ;
- le rôle étant optionnel et `neutral` le défaut, une ligne tracée sans y penser
  ne contribue à aucun bilan entrées/sorties — `flowBalance` affiche alors
  `declared: false`, « — », sans qu'on comprenne pourquoi sans relire la
  documentation.

## Décision

Le panneau de géométrie n'offre plus de champ de texte pour nommer un sens : un
seul `<select>` par sens, **obligatoire**, avec deux options exactement —
« Entrée » et « Sortie ». Le rôle **devient** le libellé
(`shared/lib/directions.ts:directionName`) : il n'y a plus de nom à saisir en
plus du rôle à déclarer.

Une ligne nouvellement tracée (`defaultLine`) porte désormais un rôle par
défaut déjà tranché — `entry` pour le sens positif, `exit` pour le négatif —
plutôt que `neutral`. Une paire arbitraire mais **toujours valide** : rien
n'empêche l'utilisateur de l'inverser, mais aucune ligne fraîchement tracée
n'est plus exclue du bilan par défaut.

## Décision — les deux sens sont mutuellement exclusifs

Poser un sens à « Entrée » bascule automatiquement l'autre à « Sortie », et
inversement (`geometryReducer`, action `setDirectionRole`). Une ligne à deux
sens ne peut pas dire l'entrée des deux côtés à la fois — ce serait un état que
`flowBalance` compterait sans le contredire, silencieusement faux. Forcer
l'utilisateur à corriger le second menu à la main aurait ajouté un geste que le
premier choix explique déjà entièrement.

`neutral` ne bascule rien : il n'est plus atteignable depuis le panneau, et il
n'a pas d'opposé à imposer à une ligne héritée qui le porte encore.

## Décision — les flèches suivent l'angle réel de la ligne

Le préfixe du libellé de sens (canvas) et le repère à côté de chaque menu
(panneau) étaient des glyphes **figés** — « → »/« ← » sur le canvas, « ↑ »/« ↓ »
dans le panneau — corrects pour une ligne horizontale ou verticale, faux (pas
inversés, juste à côté) pour toute ligne tracée en diagonale. Une flèche
légèrement fausse se remarque moins qu'une flèche inversée, donc se corrige
moins vite.

`shared/lib/geometry.ts:compassArrow` arrondit un vecteur à la plus proche des
huit flèches cardinales unicode (`→ ↘ ↓ ↙ ← ↖ ↑ ↗`), au lieu d'un angle continu
qu'aucun glyphe ne peut représenter et qu'un texte peint sur un `<canvas>` ne
peut pas faire pivoter en CSS. Les deux appelants lui passent le normal réel de
la ligne (`positiveNormal`, son opposé pour le sens négatif) plutôt qu'une paire
de constantes.

## Essayé puis abandonné — les libellés de sens à l'extrémité opposée au nom

Une itération a déplacé le point de centrage des deux libellés de sens du milieu
du trait vers l'extrémité opposée à celle du nom de la ligne (`lineNameAnchor`,
près de A), avec une fonction symétrique `directionsReferencePoint` construite
depuis la poignée B. L'intention : éviter que le nom et les sens se disputent la
même bande sur une ligne penchée.

**Revenu en arrière après relecture** : le milieu du trait reste l'endroit où
l'œil regarde en premier une ligne de comptage, et déplacer les libellés vers un
bout la rendait moins lisible d'un coup d'œil que le chevauchement occasionnel
que `resolveLabelCollisions` sait déjà résoudre en écartant un libellé le long de
son propre normal. `directionLabelAnchors` reste donc centré sur `midpoint(a, b)`,
calculé en interne — la fonction est revenue à sa signature d'origine.

## Décision — le nom et les sens s'estompent pendant l'analyse serveur

Le nom de la ligne et les deux libellés de sens restent visibles à pleine
opacité en édition — c'est alors la seule information à l'écran — mais
s'effacent partiellement (`DIMMED_LABEL_OPACITY`, 40 %) pendant qu'une analyse
tourne, différée ou en direct (`GeometryCanvasProps.analysing`, câblé sur
`busy`) : c'est alors le train de boîtes, de trajectoires et de compteurs qui
mérite l'attention, pas une géométrie déjà validée en la traçant.

Un sens qui **vient de compter** reste net malgré l'estompage — le flash
existant (ADR antérieur à celui-ci, `lineFlashes`) est l'événement qui justifie
de regarder l'écran à cet instant précis, et l'assourdir aurait fait disparaître
l'information la plus utile au moment où elle compte le plus. `drawLabelBox`
compose les deux opacités (`opacity * emphasis`) plutôt que de les traiter comme
exclusives.

Seuls le nom et les sens s'estompent — jamais le trait, les poignées, les
zones, les trajectoires ni les boîtes des véhicules : c'est une question de
confort de lecture sur un texte qu'on n'a plus besoin de vérifier pendant que ça
tourne, pas un jugement sur l'importance relative des couches.

## Ce qui ne change pas

- **Le champ `positiveName`/`negativeName` du contrat reste.** Le retirer
  casserait la lecture d'un preset ou d'un `configJson` archivé avant ce
  changement, pour un gain nul : ADR 0016 documente déjà que ces champs ne sont
  lus par aucun compteur, seulement par le client. Le panneau ne l'écrit
  simplement plus.
- **`neutral` reste un rôle valide du type `DirectionRole`, des deux côtés du
  contrat.** Une ligne tracée avant ce changement peut encore le porter, et
  `withDirectionDefaults` continue d'y retomber pour un champ **manquant** —
  deviner entrée ou sortie à sa place fausserait un bilan que personne n'a
  demandé. Le panneau affiche alors une option masquée « à préciser » qui force
  un choix explicite au premier contact, plutôt qu'un défaut silencieux.
- **Aucun compteur ne change.** Comme pour ADR 0016, le rôle ne traverse jamais
  le domaine de comptage — il vit dans `config_json` et n'est agrégé que côté
  client (`features/results-dashboard/model/directions.ts`).

## Conséquences

- Une ligne fraîchement tracée contribue tout de suite au bilan entrées/sorties
  (`flowBalance.declared === true`), sans geste supplémentaire.
- Le panneau perd un champ de texte par sens et un groupe de trois boutons, au
  profit d'un seul `<select>` — moins large, plus rapide à lire.
- Choisir un sens configure toujours **les deux** côtés de la ligne d'un seul
  geste — jamais deux menus à renseigner pour un résultat cohérent.
- Une ligne tracée en diagonale montre une flèche qui pointe réellement où elle
  va, sur le canvas comme dans le panneau — jusqu'ici une diagonale se lisait
  sous un « → » ou un « ↑ » qui mentait un peu.
- Pendant une analyse, l'écran se lit d'abord par ses boîtes et ses compteurs ;
  la géométrie reste visible, estompée, pour qui veut vérifier qu'une ligne est
  toujours à sa place sans qu'elle dispute l'attention aux pistes.
- Une ligne héritée avec `neutral` (preset ou résultat archivé) reste affichable
  et rejouable telle quelle ; seul le panneau d'édition, s'il rouvre cette ligne,
  demande alors un choix explicite avant de laisser filer le rôle « à
  préciser ».
