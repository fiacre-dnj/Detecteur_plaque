# ADR 0061 — Un franchissement porte le vote final du véhicule

- **Statut** : accepté
- **Date** : 2026-09-03
- **Rend vrai l'invariant 4** là où il ne l'était pas.

## Le symptôme

Aucun, sur les clips de ce dépôt. C'est un écart de classe, pas de total : rien ne
plante, aucun compteur ne bouge, et les deux chiffres sont plausibles.

## L'invariant qui n'était vrai qu'à moitié

> **On compte sous `identity_label`** (vote majoritaire sur la vie du véhicule), jamais
> sous la lecture de la frame courante.

Vrai du registre et de `tracked_by_class`, relus à la fin. **Faux des
franchissements** : `LineCrossingCounter._count` écrit `label = track.counting_label`
une fois pour toutes, et `TrackNumbering._retally` ne déplaçait la voix que dans
`_by_class`, c'est-à-dire dans `tracked_by_class`. Aucun chemin ne menait aux tallies de
ligne.

Mesuré sur le vrai domaine — un deux-roues descendant, lu `person` trois images puis
`motorcycle` quatre, franchissant au milieu :

```
stats.by_class            = {'person': 1}
by_line['l1'].by_class    = {'person': 1}
stats.tracked_by_class    = {'motorcycle': 1}
```

Le même objet, deux classes, sur le même écran.

## Pourquoi cela frappe exactement les classes qui manquent

Les trois classes que le détecteur confond sont `person`, `bicycle` et `motorcycle`
(ADR 0057 : `person 0.55` contre `motorcycle 0.48` sur la même ancre). Et leur lecture
**s'améliore en approchant** — c'est le mécanisme d'ADR 0060 : plus l'objet est grand
dans le tenseur, plus la classification est sûre.

Un deux-roues lu `person` de loin bascule donc en `motorcycle` en approchant. Si la
ligne est dans la moitié éloignée du champ, le basculement a lieu **après** le
franchissement.

## Deux conséquences, et la seconde est la plus dommageable

1. **Deux surfaces de la même page classent le même objet différemment.** Les cartes par
   type lisent `vehicle.label` (le vote final) ; `stats.byLine[*].byClass`,
   `violationTally` et la chronologie lisent `event.label` (le gelé).
2. **La règle de voie réservée était évaluée sur le libellé gelé.** Une voie réservée
   aux motos signalait en rouge, avec sa photo, un deux-roues parfaitement autorisé.
   Le commentaire de `lineViolations.ts` affirmait d'ailleurs le contraire de ce que le
   code faisait — une propriété vraie par coïncidence, la famille de panne que ce dépôt
   documente le plus.

## La décision

**Côté serveur, à la source.** Le vote déplace la voix : tout ce qui en dérive doit
suivre.

- `DirectionTally.relabel(previous, new)` — déplace **une** voix, sans toucher au total ;
- `LineCrossingCounter.relabel(line_id, direction, previous, new)` ;
- `TrackNumbering(on_relabel=…)` — un **rappel** et non une dépendance : le numérotage
  connaît le vote et ignore les lignes, le compteur connaît les lignes et ignore le
  vote. Seule la session tient les deux, et seul `_VehicleAggregate.crossings` sait
  *quels* franchissements ce véhicule a faits — il les tenait déjà, pour le registre ;
- `_align_crossing_labels(result)` dans le service — les `CrossingEvent` déjà émis sont
  immuables et partis depuis longtemps ; on les réaligne à l'assemblage, sur le registre
  final.

### Trois propriétés qui rendent l'opération sûre

- **aucun total ne bouge**, ni `crossings`, ni celui d'une ligne, ni celui d'un sens. Un
  franchissement reste un franchissement, seule son étiquette change — donc
  `total == Σ by_class` reste vrai des deux côtés du basculement (invariant 3) ;
- **le déplacement est conditionné à `vehicle.confirmed`**, exactement comme `_retally` :
  un véhicule pas encore compté n'a rien fait compter nulle part, et lui retirer une
  voix ferait descendre un compteur de ligne sous zéro ;
- **le vote reste collant à l'égalité** (`>` strict). Trois contre trois laisse le tenant
  en place, donc aucune ventilation n'oscille sur une lecture qui alterne.

### Les aperçus gardent l'étiquette du moment

Le réalignement du journal a lieu **à l'assemblage**, pas au vote. Les trames SSE
portent donc encore le libellé de l'instant, et c'est sans conséquence : le client
remplace son journal vivant par celui du résultat dès la fin de l'analyse — le
mécanisme « deux sources, et la seconde remplace la première » que CLAUDE.md décrit
déjà pour les alertes.

Les **tallies**, eux, sont corrigés au fil de l'eau : le KPI d'un aperçu est donc juste
en direct.

## L'alternative écartée

Déplacer la ventilation côté client, depuis `VehicleRecord.label` et `crossedLines`.
C'était la voie « le serveur compte, l'interface interprète », et elle a deux coûts que
la voie serveur n'a pas : `stats.byClass` resterait dans le contrat et dans l'export CSV
de l'API sans consommateur d'affichage — donc deux chiffres continueraient de coexister,
et il faudrait l'écrire plutôt que le subir — et la correction ne profiterait pas à
l'export de l'API, qui lit les tables dénormalisées.

## Ce qui n'est pas mesuré

**La fréquence.** Sur les trois résultats archivés de ce dépôt, l'âge médian d'un
franchissement depuis la naissance de sa piste est de 3,2 à 6,6 s (97 à 198 images à
30 fps) et aucun franchissement n'a lieu dans les cinq premières images : le vote a
largement eu le temps de se stabiliser. Mais ces clips ne contiennent ni moto ni
personne, et le mode de panne visé n'est pas l'âge — c'est un vote qui **bascule après**
le passage.

Le chiffre se lira sans réanalyser, sur `result.json.gz` : compter les franchissements
dont `vehicle.label != crossing.label`. **Zéro par construction depuis ce correctif** ;
pour mesurer ce qu'il a valu, il faut comparer un résultat produit avant et un produit
après, sur le même clip.

## Comment le vérifier

```bash
cd backend && uv run pytest tests/unit/counting/test_libelle_vote_du_franchissement.py -q
```

La propriété testée est une **égalité** — `stats.by_class == stats.tracked_by_class`
pour un véhicule unique — jamais une valeur : un seul objet ne peut pas porter deux
classes. Deux des cinq tests échouent sans le correctif, vérifié en remisant la source.
