# ADR 0045 — Un passage global est un véhicule, pas un passage

- **Statut** : accepté
- **Date** : 2026-08-28
- **Amende** : l'**invariant 3** sur un seul chiffre, et le nom du KPI de tête posé
  par [ADR 0040](0040-une-ligne-porte-un-type.md) et
  [ADR 0023](0023-un-vehicule-compte-est-un-vehicule-qui-franchit.md). N'abroge
  rien : les passages restent comptés partout où ils l'étaient.

## Contexte

Le chiffre de tête des Résultats s'appelait « Passages en entrée » et valait la
somme des passages sur tous les sens marqués « entrée ». Deux propriétés en
découlaient, toutes deux voulues à l'époque et toutes deux devenues gênantes :

- **un véhicule pouvait y compter plusieurs fois.** Un aller-retour vaut 2, deux
  lignes d'entrée franchies valent 2, une occlusion qui coupe une piste vaut 2.
  C'est juste — ce sont bien deux passages — mais ce n'est pas ce qu'on lit quand on
  cherche « combien de véhicules sont passés » ;
- **il dépendait des rôles de sens.** Sur une géométrie entièrement en « Comptage
  seul », il affichait « — » alors que le comptage était juste.

Le registre, lui, répond déjà à la question sans ambiguïté : **une rangée = un
véhicule ayant franchi au moins une ligne**, avec une colonne « Passages » qui dit
combien de fois. Les deux écrans donnaient donc deux réponses différentes à ce que
l'utilisateur lisait comme une seule question, et rien ne permettait de les
rapprocher.

## Décision — le chiffre de tête compte des véhicules distincts

« **Passages globaux** » vaut `crossingVehicles(vehicles).length` : les véhicules
distincts ayant franchi **au moins une** ligne, tous rôles confondus.

C'est, exactement, **le nombre de rangées du registre**. La propriété est le but :
les deux écrans se vérifient l'un l'autre, ce qui était impossible tant que l'un
comptait des passages et l'autre des véhicules.

Le prédicat n'est pas neuf — `crossingVehicles` de
`results-dashboard/model/crossedVehicles.ts` est déjà le juge du registre depuis
ADR 0023, et `StudioPage` lui passe **la même liste** qu'au tableau. Il n'y a donc
pas deux sources à garder d'accord, il y en a une.

**Le « — » change de juge.** Il ne dépend plus des rôles (`flowBalance.declared`)
mais de `lines.length === 0` : sans trait, aucun franchissement n'est possible et un
zéro s'y lirait « personne n'est passé ». Dès qu'une ligne existe, `0` est la vérité
et s'affiche. Une géométrie entièrement en « Comptage seul » rend donc désormais un
chiffre.

## Décision — le mot « Passages » couvre un compte de véhicules, et on le dit

C'est l'entorse, et elle est assumée. L'invariant 3 interdit de mêler les deux
unités, précisément parce qu'elles ont divergé une fois et que le « taux de
franchissement » l'a payé d'un affichage à 200 %.

Trois choses la rendent tenable :

- **l'aide de la carte porte l'unité en toutes lettres** — « véhicules distincts
  ayant franchi au moins une ligne — un aller-retour compte 1. Une rangée du
  registre. » ;
- **rien ne divise ce chiffre par un autre.** L'invariant interdit surtout le
  quotient, et il n'y en a aucun ;
- **les passages bruts n'ont pas disparu** : chaque carte de ligne affiche
  `flow.total`, le camembert par ligne les découpe, et le résumé d'alertes rappelle
  explicitement qu'il en compte, lui.

## Décision — les cartes par type suivent la même unité

`entriesByClass` est **supprimé** et remplacé par `crossedByClass(vehicles)` :
véhicules distincts ayant franchi, par classe **votée** (invariant 4).

C'est la propriété qui rend ces cartes lisibles à cet endroit — **leur somme est
exactement le chiffre de tête** — et elle est verrouillée par un test. Les laisser
en passages d'entrée aurait posé sous le total une série de cartes qui ne s'y
additionnent pas : deux chiffres plausibles qui ne se recoupent pas sont pires que
pas de chiffre du tout.

`ClassEntriesChart` suit pour la même raison, et sa prop `metric` passe de
« entrée » à « véhicule ». C'est précisément ce que cette prop existe pour
empêcher : une erreur d'unité invisible, à côté d'un camembert voisin qui, lui,
compte bien des passages par ligne.

## Ce qui ne change pas

- **Le serveur.** Aucun champ du contrat, aucun calcul, aucun schéma. Tout est
  dérivé côté client de `VehicleRecord.crossedLines`, ce qui garde la propriété
  d'ADR 0016 : basculer un sens entrée ↔ sortie ou renommer une ligne se voit sans
  réanalyser. Ce chiffre-ci ne lit même plus les rôles, donc il ne bouge pas du
  tout.
- **`isEntryRow`, `flowBalance` et `enteringVehicleCount`** restent : ils servent le
  bilan entrées / sorties, qui garde tout son sens sur les cartes de ligne, la
  Statistique et les colonnes du registre.
- **Les résultats archivés** se relisent à l'identique — le calcul change, pas la
  donnée. Un même job rouvert affiche un chiffre de tête différent d'avant, plus
  petit ou égal, et c'est le but.

## Conséquences

- Le contrôle qui vaut la mesure : « Passages globaux » et le nombre de rangées du
  registre doivent être **égaux**, pendant l'analyse comme après. S'ils divergent,
  c'est que les deux ne lisent plus la même liste — et non qu'un comptage est faux.
- Un tracé sans aucun rôle déclaré (tout en « Comptage seul ») affiche maintenant un
  vrai total, ce qui était l'un des griefs cités par ADR 0040 contre l'ancien nom.
