# ADR 0059 — Le diagnostic sait dire quel type n'a jamais été détecté

- **Statut** : accepté
- **Date** : 2026-09-03
- **Suite d'**
  [ADR 0056](0056-la-suppression-des-boites-incluses-effacait-les-petits-objets.md) et
  [ADR 0057](0057-le-nms-agnostique-supprimait-la-moto-sous-son-pilote.md) : les deux
  corrigent une perte que **rien à l'écran** ne pouvait montrer.

## Le symptôme

« On a du mal à détecter les motos. » L'utilisateur ouvre le tiroir « Comptage », lit
six chiffres, et n'apprend rien : ils additionnent toutes les classes.

## Deux défauts, et le second est le plus trompeur

### 1. Tout était global

Six chiffres qui somment `car`, `motorcycle`, `bus` et `truck` ne peuvent pas
distinguer « 3 000 voitures détectées et zéro moto » de « tout va bien ». Or c'est
exactement la question qu'on pose en ouvrant ce panneau.

Le panneau concluait par une phrase que ces chiffres ne pouvaient pas tenir :

> Un véhicule manquant est soit jamais détecté, soit détecté faiblement, soit non
> confirmé, soit masqué par une zone. **Ces chiffres disent lequel.**

Le premier cas — « jamais détecté » — n'était mesurable par aucun d'eux. Le domaine
documente d'ailleurs pourquoi : après le suivi, une détection non associée n'existe
plus, et c'est ce qui avait fait supprimer `low_detections`.

### 2. « Pistes provisoires » est un instantané au milieu de cumuls

Quatre des six nombres s'accumulent sur toute l'analyse. **Deux ne le font pas** :
`confirmed_tracks` et `tentative_tracks` sont calculés sur `self._tracks`, que
`_release_lost` purge après `max_lost_ms`. Ils décrivent donc les ~2,5 dernières
secondes.

Or « provisoire » est précisément l'état où meurt un petit objet. Mesuré sur le vrai
domaine — 300 images, une voiture continue et **douze motos qui scintillent une image
chacune** à 0,60, au-dessus du seuil :

| | valeur |
|---|---|
| Pistes confirmées | 1 |
| **Pistes provisoires** | **0** |
| Détections retenues | 312 |
| `tracked_by_class` | `{'car': 1}` |

L'utilisateur lit « Pistes provisoires : 0 » sous une aide qui dit « baisser *Images
avant comptage* les compterait », conclut que la confirmation n'est pas en cause, et va
chercher ailleurs.

Confirmé sur les résultats archivés de ce dépôt, où l'incohérence saute aux yeux : job
`74dfee38` publie 28 véhicules sous `confirmedTracks: 1` ; job `dd263f4c`, 165 véhicules
sous `confirmedTracks: 16`. **Aucune** analyse archivée n'a un `tentativeTracks` non nul.

## La décision

Deux champs, aucune comptabilité nouvelle.

### `unconfirmed_tracks`

Le cumul qui manquait : `TrackNumbering.issued - size`. Le compteur existait déjà,
testé, et **n'avait aucun consommateur** — `grep -rn issued src/` ne rendait que sa
définition.

C'est un **dérivé** d'un état déjà tenu, jamais un second compteur :
`unconfirmed_tracks + tracked_vehicles == issued` par construction, et c'est cette
égalité — pas la valeur — qu'un test verrouille. Un compteur parallèle finirait par
diverger (invariant 3).

**Ce ne sont pas des véhicules perdus**, et l'aide le dit : un scintillement d'une image
n'est pas un véhicule, `min_hits` existe pour cela. Un chiffre élevé sur une scène
chargée est normal ; ce qui était anormal, c'est qu'il soit invisible.

### `by_class`

Le même diagnostic par type, sur le patron exact de `near_misses` :
`field(default_factory=dict)`, donc un résultat archivé sans la clé se relit.

**Les types cochés à zéro sont rendus, pas omis.** `motorcycle: 0 / 0` est
l'information — la classe a été cherchée et jamais trouvée. Omettre la clé se lirait
« pas mesuré », ce qui envoie chercher ailleurs. La fixture du contrat le montre
directement : `bus` et `motorcycle` y sont présents à `0 / 0`.

**La liste vient du serveur, jamais des cases de l'écran.** Le client connaît sa
sélection *courante*, qui peut avoir changé depuis l'analyse : afficher « Moto 0 / 0 »
sur un résultat où la moto n'a jamais été cherchée serait exactement le mensonge que ce
champ existe pour éviter. `SessionConfig` gagne donc `class_ids`, **pour le diagnostic
seul** — le comptage ne les lit pas, le filtrage ayant lieu au détecteur. Même statut
que `confidence_threshold`, ajouté pour la même raison.

La somme des `high_detections` par classe égale `high_detections`, et de même pour la
bande basse. Deux tests le verrouillent, un de chaque côté du contrat.

## À l'écran

Le panneau est coupé en deux blocs — les cumuls, puis « À la dernière image analysée »
avec sa propre phrase. Aligner les deux natures dans une seule grille était le défaut
qui rendait `tentative_tracks` trompeur, et aucun réglage ne l'aurait corrigé.

La ventilation par type suit, bâtie comme `NearMisses`. Les types jamais détectés sont
en teinte d'alerte et **nommés en toutes lettres** sous le tableau :

> Moto, Bus n'ont jamais été détectés. Aucun curseur ne les rattrapera : il faut un
> modèle plus grand, une image plus définie, ou un plan plus serré.

C'est une conséquence et trois gestes, jamais un interdit — la doctrine des
avertissements de ce projet.

## Ce qui n'est pas fait

**`contained_out` n'est pas ventilé par paire de classes**, alors que l'audit le
recommandait. La raison a changé entre-temps : cette ventilation existait pour *révéler*
la suppression inter-classes, qu'ADR 0056 a supprimée. Ce qui reste est le cas voulu —
cabine dans semi, deux boîtes de **même** groupe — et une ventilation par paire y dirait
`truck←truck`. Le scalaire suffit, et sa chute est la façon de vérifier ADR 0056.

## Conséquences

- **aucun chiffre existant ne change** : les deux champs sont ajoutés, rien n'est
  recalculé ;
- **le contrat gagne deux clés optionnelles** ; les résultats archivés se relisent, et
  la rangée « Jamais confirmées » n'est simplement pas rendue quand le champ manque —
  « pas mesuré » et « zéro » ne se disent pas de la même façon ;
- **le dictionnaire grossit avec le nombre de classes cochées**, sept au maximum : sans
  effet même dans l'aperçu SSE republié dix fois par seconde ;
- **le risque est de lire ces chiffres comme des véhicules.** Ce sont des
  **observations suivies** — plusieurs milliers pour quelques dizaines de véhicules — et
  l'aide le dit, sinon l'écran gagne un chiffre de plus qu'on divisera par un autre.

## Comment le vérifier

```bash
cd backend && uv run pytest tests/unit/counting/test_diagnostic_par_classe.py -q
```

Le test central rejoue la mesure : douze motos scintillantes, `tentative_tracks == 0` et
`unconfirmed_tracks == 12`. Sur données réelles et sans nouveau métrage, relancer
n'importe quel job archivé suffit : le nouveau chiffre doit être non nul là où
`tentativeTracks` vaut `0`.
