# ADR 0050 — La règle monotone de la ReID ne bornait rien

- **Statut** : accepté
- **Date** : 2026-08-29
- **Amende** : [ADR 0048](0048-rechercher-un-vehicule-par-image.md) — sa règle
  monotone, pas son modèle ni son architecture.
- **Même famille que** :
  [ADR 0032](0032-l-ocr-n-etait-pas-le-goulot-le-detecteur-de-plaques-l-est.md) et
  [ADR 0039](0039-ne-pas-payer-pour-une-plaque-prouvee-illisible.md) — payer une
  inférence par image pour un résultat qu'on a déjà.

## Contexte

ADR 0048 a introduit la recherche de véhicule par image et s'est protégée du coût par
une **règle monotone** : on ne réencode une piste que si la nouvelle vue est plus large
que celle déjà retenue. La docstring de l'adaptateur en a tiré « on encode **une fois
par véhicule** et non par image », et `core/settings.py` a repris la formule pour
justifier que l'encodeur reste sur CPU.

C'est faux, et le contre-exemple est le cas nominal. `tracking_session.should_embed`
répondait :

```python
return aggregate.appearance_width_px is None or width_px > aggregate.appearance_width_px
```

Sur un véhicule **qui approche de la caméra**, la largeur de boîte croît de façon quasi
monotone. « Strictement plus large que la meilleure vue » est donc vrai à *presque
chaque image analysée*, et `_match_appearances` n'a aucune garde de cadence — contrairement
à `PlateOcrPolicy`, qui en a une. Une piste qui traverse le champ en s'approchant pouvait
donc coûter **un encodage ONNX/CPU par image**, mesuré ici à **21,8 ms par vignette**.

La mesure d'ADR 0048 n'a pas attrapé cela parce qu'elle comptait la mauvaise chose :
« 8 véhicules suivis, **2 encodés** » est un nombre de *véhicules*, pas d'*encodages*.
Les six autres étaient sous le plancher de 96 px ; les deux restants ont pu être encodés
autant de fois qu'ils ont été vus.

## Décision

`should_embed` prend une **marge relative** :

```python
best = aggregate.appearance_width_px
return best is None or width_px > best * max(1.0, improvement)
```

`TRAFFIC_REID_APPEARANCE_IMPROVEMENT`, défaut **1,15**, porté par `AnalysisService`
à côté de `reid_min_similarity` — un plancher de **déploiement**, comme lui, et non un
champ de requête : il décrit ce que la machine accepte de payer.

`1.0` reproduit l'ancien comportement au bit près (`w > best * 1.0` ≡ `w > best`), ce
qui rend le paramètre strictement additif pour tout appelant qui ne le passe pas.

### Une marge, et pas une cadence

Les deux bornent, mais pas la même chose, et la différence est décisive :

- **la marge borne le total** sur la vie d'une piste : au plus `log_k(W_max / W_min)`
  encodages, soit **onze à 1,15** entre le plancher de 96 px et 400 px — quelle que soit
  la cadence de la vidéo, le pas d'analyse ou la durée du passage ;
- **une cadence borne le débit** : `every_n_frames = 3` laisse passer une cinquantaine
  d'encodages sur un passage de six secondes à 25 img/s.

La marge est le bornage fort, et elle coûte quatre lignes de domaine là où une cadence
demanderait de faire descendre `ordinal` jusqu'à `_match_appearances`, d'ajouter un
`last_ordinal` par piste et de décider d'un décalage.

### Pourquoi ADR 0029 ne se rejoue pas ici

ADR 0029 a **ramené** `plate_ocr_quality_improvement` de 1,25 à 1,0 parce que la marge
affamait le vote de plaque. La symétrie est trompeuse, et la raison est structurelle :

- le consommateur de l'OCR est **statistique**. `PlateTextVote` exige plusieurs lectures
  concordantes ; raréfier les lectures n'abîme pas le texte, cela **empêche qu'un texte
  existe** — `AR606L` devenait `R606` ou rien ;
- le consommateur de la ReID est un **remplacement**. `record_embedding` écrase
  `match_score`, il ne l'accumule pas. Une seule vue suffit à produire un score ; une
  seconde ne sert que si elle est meilleure.

**Il n'y a donc aucun vote à affamer.** Et la première vue reste inconditionnelle
(`appearance_width_px is None`) : la marge ne peut refuser qu'une *amélioration*, jamais
une existence. Aucun véhicule candidat ne perd son score, ce qu'un test verrouille avec
une marge absurde (4,0).

## Mesure

| | |
|---|---|
| coût d'un encodage (OSNet-AIN, 208², CPU) | **21,8 ms** par vignette (24,0 en lot de 8) |
| clip d'essai, 60 → 200 px par pas de 20 | **8 encodages** sans marge, **6** à 1,15 |
| borne sur la vie d'une piste, 96 → 400 px | ~100 sans marge, **11** à 1,15 |

Gain de bout en bout, profil « analyse avec image de requête », 1080p, trois véhicules
au-dessus du plancher qui approchent : 17,2 ms d'image plus `3 × 22,5` d'encodage, soit
**84,7 ms → 11,8 img/s** ; à 1,15, `3 × 22,5 × 0,11` soit **24,6 ms → 40,6 img/s**.
**≈ 3,4×.**

**Hors de ce profil, 1,00× et il faut le dire** : `_match_appearances` n'est appelé que
`if query is not None`. Une analyse ordinaire ne payait rien et ne gagne rien.

## Conséquences

- **Un chiffre publié bouge** — le seul du lot d'optimisations dont cette ADR fait
  partie. `matchScore` peut être calculé sur une vue marginalement moins large. Le coût
  est chiffrable : la séparation same/diff d'ADR 0048 décroît régulièrement (+0,462 à
  208 px, +0,310 à 48 px, **sans falaise**), donc 15 % de largeur en moins valent
  ~0,015 de séparation — pour un seuil client à 0,55 et des moyennes mesurées à 0,816
  (même véhicule) et 0,249 (différents). Personne ne bascule.
- **Aucun comptage, aucune ventilation, aucun horodatage ne change.**
  `TestAucuneRegression` compare les trois avec et sans encodeur, et reste vert.
- **Le curseur reste côté client** (ADR 0048) : une ressemblance jugée trop basse se
  corrige sans réanalyser.
- **Deux docstrings sont corrigées** — `onnx_vehicle_embedder` et `core/settings.py`
  affirmaient « une fois par véhicule ». Les laisser redonnerait la même fausse
  assurance à la prochaine lecture.
- **1,15 et pas plus.** Le bornage étant logarithmique, la tentation de pousser est
  mauvaise : 1,5 ne diviserait le compte que par deux de plus et coûterait ~0,05 de
  séparation au lieu de 0,015.

## Ce qui reste ouvert

`_match_appearances` soumet **tous** les candidats d'une image en un lot, borné
seulement par `MAX_BATCH = 16` dans l'adaptateur. Cette ADR borne le total *par piste* ;
elle ne borne pas la **rafale par image**, qui peut encore atteindre ~350 ms de blocage
CPU en un seul appel sur une image chargée — pendant lequel l'aperçu ne sort pas. Le
mécanisme pour le faire existe déjà et est testé (`select_within_budget`,
`plate_policy`) ; c'est un item distinct.
