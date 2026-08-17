# ADR 0026 — Le registre se remplit pendant l'analyse

- **Statut** : accepté
- **Date** : 2026-08-17
- **Complète** : [ADR 0006](0006-apercu-live-des-analyses.md) — l'aperçu SSE
  transportait les boîtes et les compteurs ; il transporte désormais aussi le
  **registre**.
- **Ne touche pas** : [ADR 0016](0016-compter-les-objets-suivis.md) et
  [ADR 0023](0023-un-vehicule-compte-est-un-vehicule-qui-franchit.md). Aucun
  compteur, aucun prédicat d'affichage ne change ; ce qui change est *quand* les
  mêmes chiffres arrivent à l'écran.

## Contexte

Pendant une analyse, le bas de page affichait la Répartition par type et le
journal des franchissements. La **Statistique**, les deux **camemberts** et le
**Registre des véhicules** attendaient la fin.

Ce n'était pas un choix d'ergonomie, mais une contrainte : `JobPreview` ne
portait pas de `vehicles`. Les trois sections en dépendent — le registre pour ses
lignes, la Statistique pour son chiffre de tête (« Véhicules ayant traversé le
carrefour », des véhicules distincts et non des passages, ADR 0023).

L'effet à l'écran était mauvais dans les deux sens. Sur une analyse bridée à 1×
(le défaut depuis [ADR 0019](0019-la-lecture-locale-reste-a-vitesse-normale.md)),
une vidéo d'une minute laisse une minute à regarder des compteurs monter
au-dessus d'une page vide ; puis tout apparaît d'un coup à la fin, sans qu'on ait
pu vérifier une seule ligne au moment où le véhicule correspondant passait à
l'écran. Or c'est exactement ce que le registre existe pour permettre : « 47
véhicules » est un acte de foi, une ligne qu'on relie à une voiture visible dans
la vidéo est une vérification.

## Décision

**L'aperçu SSE porte le registre.** `PreviewSample.vehicles` →
`JobPreview.vehicles`, les mêmes `VehicleRecord` que le résultat final, par le
même agrégat (`AnalysisSession.vehicles()`) et le même sérialiseur
(`serialise_vehicle`).

Les quatre sections sont alimentées par **un seul jeu de composants**, avec deux
sources de même forme : l'aperçu pendant l'analyse, la tête de lecture après.

Trois réserves portent le compromis, et aucune n'est cosmétique.

### 1. Le registre est republié à sa propre cadence, dix fois plus lente

Les boîtes et le registre n'ont pas le même volume, et c'est ce qui interdit de
les publier ensemble. Les pistes d'une image sont une poignée, et leur nombre ne
dépend pas de la durée de l'analyse. Le registre, lui, **grossit** : **350 octets
par véhicule**, mesurés sur les `result.json.gz` archivés de ce dépôt (93 à 106
véhicules, 32 à 37 ko). À la cadence des boîtes — 10 Hz sur une analyse bridée —
le débit du flux croîtrait donc avec l'avancement, jusqu'à mettre le navigateur à
genoux sur une vidéo longue. Et pour rien : un tableau de véhicules ne se lit pas
dix fois par seconde.

`TRAFFIC_PREVIEW_VEHICLES_INTERVAL_MS` vaut **1000** par défaut. Mesuré sur une
analyse réelle de 25 s : **112 aperçus, 24 porteurs de registre**, 3,2 ko par
publication à 9–14 véhicules.

**Les aperçus intermédiaires portent `null`, qui veut dire « inchangé » — jamais
« aucun véhicule », que dit une liste vide.** La distinction n'est pas
théorique : confondre les deux viderait le tableau neuf fois sur dix, et
afficherait « aucun véhicule n'a franchi de ligne » à la place du serveur.
`useJobProgress.carryVehicles` reporte donc la dernière liste reçue, une fois,
pour que **aucun consommateur n'ait à connaître cette convention**.

### 2. L'aperçu ne publie que les véhicules ayant franchi

`session.vehicles(crossed_only=True)`. C'est exactement la population que l'écran
affiche depuis ADR 0023, donc le filtre ne change **rien** à ce qui s'affiche —
seulement à ce qui voyage, et sur une scène réelle deux tiers des objets suivis
n'ont franchi aucune ligne (93 objets suivis pour 22 véhicules franchissants,
mesuré). Le filtre s'applique **avant** le vote de plaque et la moyenne de
vitesse : construire des enregistrements pour les jeter aussitôt taxerait chaque
aperçu au profit de personne.

Conséquence à connaître : `vehicles` de l'aperçu et `vehicles` du résultat ont la
même forme et **pas la même population**. Le résultat archivé garde tout objet
suivi confirmé, et c'est délibéré (ADR 0023) — sans stationnement dans le
résultat, on ne peut plus diagnostiquer une ligne mal placée.

### 3. L'aperçu final porte toujours le registre

Quel que soit l'intervalle, y compris quand il est désactivé. Même raison que la
progression finale obligatoire : sinon la dernière liste affichée est celle d'un
échantillon quelconque, en retard de quelques véhicules sur les compteurs posés
juste à côté — et l'écart se lit comme un bug de comptage.

## Ce qui a été écarté

**Reconstruire le registre côté navigateur** depuis les `tracks` des aperçus et
le journal des franchissements. C'était tentant : aucune modification serveur, et
le client a déjà tous les franchissements. C'est un agrégat parallèle, donc
condamné à diverger (invariant 3) — et sur trois points vérifiables :

- les premières et dernières apparitions seraient arrondies à la cadence de
  l'aperçu, et un véhicule apparu et disparu entre deux aperçus manquerait
  entièrement ;
- ni le **vote de classe** ni le **vote de plaque** ne se refont depuis des
  images échantillonnées (invariant 4) — ils portent sur toute la vie du
  véhicule ;
- la confirmation de piste (`hits >= min_hits`), les zones visitées et la
  vitesse moyenne calibrée par ligne (ADR 0025) vivent dans le domaine serveur.

**Tronquer la liste** (les N derniers véhicules) plutôt que ralentir sa cadence.
Écarté parce que le chiffre de tête de la Statistique compte des véhicules
**distincts entrés** : une liste tronquée le ferait baisser silencieusement, et
un compteur qui recule en cours d'analyse est le pire des deux mondes. Ralentir
la cadence, elle, ne rend jamais un chiffre faux — seulement d'une seconde en
retard, ce que l'écran assume déjà pour les compteurs.

**Exporter pendant l'analyse.** Les trois boutons (CSV véhicules, CSV
franchissements, JSON) restent **masqués** tant que le résultat complet n'est pas
là : un fichier produit à mi-parcours serait amputé de tout ce qui reste à
analyser, sans dire de combien ni de quoi. C'est la règle qui vaut déjà pour la
recherche par plaque, dont les exports ne tiennent pas compte.

## Conséquences

- **Aucun chiffre ne change**, ni côté serveur ni à l'écran : les prédicats
  d'affichage restent ceux d'ADR 0023, dans le même module. Ce qui change est le
  moment où ils s'appliquent.
- **Un résultat archivé s'affiche exactement comme avant** : la branche
  « relecture » est inchangée, et c'est elle qui sert dès que `result` existe.
- **Le direct (caméra) ne gagne rien**, et c'est explicite : il n'a pas d'aperçu
  SSE, donc pas de registre. Les alimenter avec ses statistiques afficherait
  « 0 véhicule ayant traversé » sous des franchissements qui montent. La
  Répartition, qui ne lit que `by_class`, reste servie dans les trois modes.
- **Il subsiste un temps mort d'une respiration à la fin** : au statut terminal,
  l'aperçu s'efface au profit du résultat complet, dont le téléchargement peut
  prendre quelques secondes sur une longue vidéo. Le comportement est celui
  d'avant cette ADR — la Répartition et le journal disparaissaient déjà de la
  même manière — mais il devient plus visible, puisqu'il y a maintenant quatre
  sections à réafficher.
- **`TRAFFIC_PREVIEW_VEHICLES_INTERVAL_MS=0`** rend le comportement d'avant cette
  ADR sans toucher au code : registre vide jusqu'à la fin, aperçu inchangé. Les
  deux réglages sont indépendants — couper le registre ne coupe pas les boîtes.
