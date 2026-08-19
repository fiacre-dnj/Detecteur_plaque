# ADR 0030 — Le détecteur de plaques payait une inférence par véhicule

- **Statut** : accepté
- **Date** : 2026-08-19
- **Amende** : [ADR 0015](0015-le-detecteur-de-plaques-en-pt.md) — dont il réalise
  enfin la promesse — et corrige un chiffre de
  [ADR 0010](0010-etranglement-du-detecteur-de-plaques.md) devenu faux.

## Contexte

Activer « Repérer les plaques » et l'OCR faisait chuter la cadence d'analyse dans des
proportions que rien dans le code n'expliquait. Le projet avait pourtant déjà payé
deux fois pour ce poste : ADR 0010 a étranglé le détecteur (une image sur trois par
piste), ADR 0015 l'a passé sur GPU (702 ms → 45 ms par inférence).

**La docstring de `plate_detector.py` décrivait déjà le bon comportement**, depuis
ADR 0015 :

> Depuis le passage en `.pt`, le lot et la résolution sont libres : `predict()`
> accepte une liste de recadrages et les traite en un seul appel, ce qui amortit
> mieux **et** sans rien perdre.

Le code, lui, ne le faisait pas. `detect_many` découpait le travail en paquets de
`side²` recadrages, où `side` est le côté de la mosaïque d'ADR 0008 — et le défaut
étant `side = 1`, cela faisait **un paquet par véhicule, donc un `predict` par
véhicule**. Le coût fixe d'un appel Ultralytics (préparation, transfert vers la
carte, synchronisation) était payé autant de fois qu'il y avait de pistes.

C'est un mode de panne que ce dépôt connaît bien : rien ne lève, aucun chiffre
affiché ne change, et la seule trace est une cadence deux fois trop basse — que
personne ne relie spontanément à une boucle de découpage.

## La mesure

Vidéo réelle du dépôt (1920×1080, 60 fps), `yolo11s`, GPU Quadro P1000, **3,7
véhicules par image** en moyenne. Coût par image analysée, par étage :

| étage | avant | après | matériel |
|---|---|---|---|
| suivi des véhicules | 154 ms | 154 ms | GPU |
| **détection de plaques** | **217 ms** | **107 ms** | GPU |
| OCR (toutes variantes) | 321 ms | 321 ms | CPU |

Soit **2,04×** sur l'étage, mesuré entre 1,80× et 2,10× selon la passe.

**De bout en bout**, sur la vraie `AnalysisService`, même fenêtre de 33 s, même
géométrie, mêmes réglages, ANPR et OCR actives :

| | avant | après |
|---|---|---|
| cadence | 5,84 img/s | **10,63 img/s** |
| durée de l'analyse | 339 s | **186 s** |
| véhicules suivis / franchissements | 4 / 1 | 4 / 1 |
| plaque publiée | `AR606L` (0,88) | `AR606L` (0,88) |

Le gain de bout en bout (1,82×) dépasse ce que l'étage seul laisse attendre, et la
raison est l'étranglement : en production l'OCR ne tourne qu'une image sur trois par
piste et s'arrête dès que le vote est acquis (ADR 0010), tandis que la détection,
elle, tourne à chaque image analysée où une piste n'a pas d'ancre fraîche. Le
détecteur pèse donc bien plus lourd dans une analyse réelle que dans un profil où
l'on force les trois étages sur chaque image.

## Décision

Sur le chemin par défaut (`mosaic_side == 1`), `detect_many` appelle `predict` **une
fois pour tous les recadrages de l'image**, par plaques de `MAX_BATCH = 16`.

**Le lot est une dimension de tenseur, pas de pixels**, et c'est ce qui le distingue
de la mosaïque : chaque recadrage garde son propre letterbox 640×640. Il n'y a donc
aucun arbitrage rappel/vitesse à faire, contrairement à ADR 0008 où l'empaquetage en
pixels rétrécit les plaques dans l'entrée du réseau (côté 2 : 3,4× pour −16 % de
rappel). **La mosaïque reste intacte et toujours disponible** pour une machine sans
GPU, où son arbitrage garde sa valeur.

`_infer_batch` réutilise `_is_plausible`, `select_best` et la mesure de netteté en
construisant un `_Placement` **neutre** (`scale = 1`, décalages nuls) qui ne porte que
l'origine du recadrage. Le filtre géométrique du domaine et le classement ne sont donc
pas réécrits pour ce chemin — ils sont partagés avec la mosaïque.

## Ce que la vérification a montré, et qu'il faut savoir

Sur **240 véhicules** de vraie circulation, chemin séquentiel contre chemin en lot :

- **aucune plaque gagnée ni perdue** — même nombre de détections sur 240/240 ;
- **les boîtes ne sont pas identiques au bit près** : IoU de 0,943 au minimum,
  0,959 en médiane.

L'écart est sub-pixel et il a une cause précise, qu'il vaut mieux connaître avant de
la découvrir en comparant deux versions : l'ancien chemin passait par `_pack`, donc
par un redimensionnement du recadrage vers sa cellule **avant** le letterbox
d'Ultralytics. Le lot n'a plus que le letterbox. C'est un rééchantillonnage de moins,
donc la boîte du lot est la plus fidèle des deux — mais une comparaison au pixel près
entre deux versions du dépôt échouera, et c'est attendu.

## Le chiffre de `CLAUDE.md` qui est devenu faux

La décision 15 affirme encore :

> l'OCR coûte 66 ms par vignette contre 702 pour l'ancien détecteur, rapport 10,7 à
> 1 — **optimiser l'OCR ne rend rien de perceptible.**

**C'était vrai, ça ne l'est plus, et deux changements l'ont retourné** : ADR 0015 a
divisé le détecteur par ~15 en le passant sur GPU, et ADR 0029 a porté le lot d'OCR de
3 à 5 variantes. Après le présent ADR, la répartition est :

| étage | ms/image | part |
|---|---|---|
| OCR (CPU) | 262 | **60 %** |
| suivi des véhicules (GPU) | 90 | 21 % |
| détection de plaques (GPU) | 81 | 19 % |

**L'OCR est désormais le premier poste.** La phrase de la décision 15 est corrigée
dans `CLAUDE.md`.

## Ce qui a été essayé et rejeté, avec la mesure

Ne pas re-proposer ces pistes sans lire ce qui suit — chacune a son chiffre.

**Grouper l'OCR de toutes les plaques d'une image en un seul lot.** C'est
l'optimisation qui paraît symétrique de celle du détecteur, et elle est **1,6× plus
lente** : 380 ms contre 232 ms pour un appel par piste. La cause est `batch_width`,
qui aligne tout le lot sur la vignette la plus large et remplit le reste — mélanger
des plaques d'aspects différents fait donc payer le maximum à chacune. Le service
appelle déjà `reader.read` une fois par piste : **c'est la bonne forme**, il ne faut
pas la « corriger ».

**Forcer le nombre de threads intra-op d'onnxruntime.** Une première mesure donnait
274 ms au défaut contre 188 ms à 12 threads, soit 1,46×. Répétée cinq fois en
alternant les configurations, elle donne 298 ms au défaut, 242 ms à 8 threads (1,23×)
et 278 ms à 12 (1,07×, avec une dispersion de 264 à 319). Le gain est réel mais
modeste, non monotone, et **propre à cette machine**. Le réglage
`plate_ocr_intra_op_threads` existe déjà : c'est à l'exploitant de le mesurer chez
lui, pas au dépôt de figer un défaut sur une seule carte.

**Supprimer une variante de prétraitement.** Chacune coûte ~80 ms par image d'analyse,
donc la tentation est forte. Taux de victoire mesuré sur 40 vignettes réelles, et
surtout ce qu'on perdrait en la retirant :

| variante | présente | gagne | lectures perdues si retirée |
|---|---|---|---|
| base | 40 | 2 % | 0 |
| redressée | 7 | **0 %** | 0 |
| encart | 40 | 20 % | 3 |
| gauche 0,14 | 40 | **57 %** | 7 |
| gauche 0,22 | 39 | 21 % | 2 |

Trois variantes sur cinq paient leur coût en justesse, et la mieux placée est celle
qu'ADR 0029 a ajoutée. **La redressée ne gagne jamais** sur ce corpus et ne coûte rien
à retirer — mais elle n'y est présente que 7 fois, sur une seule caméra dont les
plaques sont quasi horizontales, et `estimate_skew` ne la produit que quand un angle
exploitable est mesuré. La retirer sur cet échantillon serait décider d'un cas
(caméra oblique) que le corpus ne peut pas voir. Le chiffre est consigné ici ; la
décision demande un second corpus.

**Un filtre d'attachement contre les fausses détections sur l'habillage vidéo.** Voir
ADR 0029, qui l'avait déjà rejeté ; la mesure refaite ici le confirme — le déplacement
d'un véhicule entre deux mesures est de ~1,5 px à 60 fps, soit le niveau du bruit de
boîte, donc le résidu ne sépare rien.

## Ce que cela ne corrige pas

**L'OCR tourne sur le CPU pendant que le GPU attend.** `onnxruntime` 1.28 n'expose ici
que `['AzureExecutionProvider', 'CPUExecutionProvider']` — il n'y a pas de provider
CUDA, donc l'OCR est clouée au CPU quel que soit le GPU (déjà constaté par ADR 0015).
Les 262 ms d'OCR et les 171 ms de GPU sont aujourd'hui **sérialisés** dans la boucle
d'analyse.

Les recouvrir — lire les plaques de l'image *N* pendant que la carte travaille sur
l'image *N+1* — masquerait la plus grande partie du poste dominant. C'est le seul
levier structurel qui reste, et il n'est pas gratuit : l'invariant 8 exige qu'un
`snapshot()` soit pris **après** la passe ANPR *et* après la passe OCR, donc décaler
l'OCR d'une image demande de décaler aussi la construction de la timeline, ce qui
touche l'aperçu live et l'ordre de publication. À mesurer et à décider séparément.

## Conséquences

- une analyse avec ANPR et OCR est **~1,8× plus rapide**, sans qu'aucun chiffre
  publié ne change ;
- `MAX_BATCH = 16` borne l'occupation de la carte : ~4,9 Mo par recadrage, donc
  ~79 Mo au plus. Au-delà, une intersection chargée pourrait faire déborder une carte
  plus petite, et une erreur de mémoire GPU ferait échouer *toute* la passe ANPR de
  l'image, pas seulement le véhicule de trop ;
- un test compte les appels à `predict` (`test_cinq_vehicules_ne_coutent_qu_une_
  inference`). Il ne vérifie pas un résultat mais un **coût** : une régression ici
  rendrait exactement les mêmes boîtes deux fois plus lentement, ce qu'aucune
  assertion sur les boîtes ne pourrait voir ;
- le prochain travail de performance sur l'ANPR doit viser l'OCR, et non plus le
  détecteur.
