# ADR 0033 — L'autotune cuDNN se réétalonnait à chaque plaque

- **Statut** : accepté
- **Date** : 2026-08-19
- **Abroge le défaut d'** [ADR 0013](0013-le-cout-du-pipeline-de-comptage.md), qui avait
  activé l'autotune cuDNN sans jamais chiffrer ce qu'il apportait — et dont la prémisse
  était fausse pour la moitié du pipeline.
- **Explique** ce qu'[ADR 0032](0032-l-ocr-n-etait-pas-le-goulot-le-detecteur-de-plaques-l-est.md)
  laissait ouvert sous le titre « Ce que la mesure n'explique pas », et **corrige ses
  chiffres** sur le plafond par image.

## Contexte

ADR 0032 laissait un écart de **facteur cinq** sans explication : dans le pipeline, un
appel du détecteur de plaques portant **un seul** recadrage coûtait ~99 ms, contre
**21,5 ms** mesurées hors pipeline sur le même modèle et le même recadrage. Son texte le
disait « probablement le plus rentable qui reste ». Il l'était.

## Le diagnostic, en trois mesures

**1. Ce n'était pas un coût, c'était une pause.** En chronométrant `detect_many` appel
par appel dans une vraie analyse — 90 images, scène dense, plafond de un recadrage :

| p50 | p90 | p99 | max | moyenne |
|---|---|---|---|---|
| 26,6 ms | 56,8 ms | 1 238 ms | 1 238 ms | **98,8 ms** |

**Six appels sur 90 dépassaient la seconde et pesaient 73 % du temps de l'étage.** La
moyenne de 99 ms décrivait un étage qui n'a jamais existé. Les six pauses sont réparties
dans la course (rangs 45, 50, 52, 54, 68, 80), pas au démarrage : ce n'est pas un coût de
chargement.

**2. Ce n'était pas l'entrelacement des deux modèles sur la même carte.** Vérifié dans un
même processus, sur les mêmes recadrages : plaques seules, puis véhicules **et** plaques
entrelacés par lots de quatre, puis plaques seules à nouveau — **39,4 / 39,3 / 39,1 ms**,
avec `num_alloc_retries = 0` et `num_ooms = 0`. Ni contention de l'allocateur CUDA, ni
sérialisation de contextes, ni pression sur les 4 Go de la carte.

**3. C'était la forme d'entrée qui changeait, et cuDNN qui se réétalonnait.**
`Model.predict` d'Ultralytics impose `rect: True` dans ses surcharges
(`engine/model.py:498`), ce qui l'emporte sur le `rect: False` de sa configuration par
défaut. Dans `BasePredictor.pre_transform` :

```python
same_shapes = len({x.shape for x in im}) == 1
letterbox = LetterBox(self.imgsz, auto=same_shapes and self.args.rect and …)
```

Quand **un seul** recadrage est soumis, `same_shapes` est vrai, donc `auto` est vrai,
donc le letterbox rend la plus petite forme multiple de la foulée qui contienne l'image
mise à l'échelle — **une forme qui dépend du rapport d'aspect du recadrage**. Chaque
véhicule ayant sa propre boîte, presque chaque appel présentait une forme neuve. Or
`torch.backends.cudnn.benchmark = True` fait essayer plusieurs algorithmes de
convolution **à chaque nouvelle forme**, et cet étalonnage coûte environ une seconde.

Cela explique du même coup **pourquoi les appels à deux recadrages ou plus n'en
souffraient pas** : deux recadrages de tailles différentes rendent `same_shapes` faux,
donc `auto` faux, donc une entrée carrée **constante** — une seule forme, étalonnée une
fois. Le plafond `max_per_frame = 2` d'ADR 0032 gagnait sa cadence exactement là.

**Et la docstring de `enable_cudnn_autotune` énonçait la prémisse fausse depuis
ADR 0013** : « Notre forme est fixe pour une vidéo donnée — `imgsz` est un réglage, la
résolution ne change pas en cours de route ». C'est vrai du détecteur de véhicules. C'est
faux du détecteur de plaques depuis ADR 0007, qui lui donne un recadrage par piste.

## Décision — `TRAFFIC_INFERENCE_CUDNN_AUTOTUNE`, à `false` par défaut

Mesuré en **courses alternées sur le même binaire**, un seul drapeau d'écart, ANPR et
OCR actives — le protocole d'ADR 0013, cette machine variant de ±20 % selon son état
thermique :

| scène | passe | autotune actif | coupé | gain |
|---|---|---|---|---|
| **clairsemée** 1080p, 1,0 recadrage/appel | 1 | 7,15 img/s | **14,91** | **2,09×** |
| | 2 | 6,09 img/s | **10,40** | **1,71×** |
| **dense** 1080p, 2,4 recadrages/image | 1 | 8,00 img/s | **10,66** | **1,33×** |
| | 2 | 7,76 img/s | **11,90** | **1,53×** |

Et ce qui compte autant que le gain :

- **aucun pixel n'est touché.** Plaque publiée `69884` dans les **quatre** courses de la
  scène clairsemée ; comptages identiques (20 véhicules, 2 franchissements) dans les
  quatre courses de la scène dense ; volume de travail identique (2,40 recadrages par
  image) ;
- **la queue disparaît** : le pire appel de l'étage de plaques passe de 1 174–1 538 ms à
  134–271 ms. La médiane, elle, ne bouge pas (29–33 ms contre 33–49) — c'était bien une
  pause, pas un coût ;
- **l'autotune ne rendait rien au chemin dont la forme *est* fixe** : inférence
  véhicules **7,92 ms avec, 8,00 ms sans**, soit le bruit de mesure. ADR 0013 l'avait
  activé sans jamais le chiffrer, et son propre banc offrait `--no-cudnn` « pour
  chiffrer ce que l'autotune apporte » — personne ne l'avait fait.

Le réglage reste, à `false`, pour une machine où la mesure dirait autre chose : une carte
plus récente, un déploiement sans ANPR. `scripts/pipeline_bench.py --cudnn` et
`--no-cudnn` refont l'arbitrage sans toucher à l'environnement, et le rapport porte
désormais `cudnnAutotune` — un rapport qui n'annonce pas ce régime n'est comparable à
aucun autre.

## Ce qui a été essayé et rejeté

**Forcer une entrée carrée pour les plaques** (`rect=False` passé à `predict`, en gardant
l'autotune). C'est la correction qui paraît la plus ciblée : une forme constante, donc un
seul étalonnage. Le gain de cadence est **identique** (18,31 contre 18,23 img/s sur la
scène clairsemée) — et il coûte **une plaque publiée** : le remplissage change, la boîte
de plaque bouge d'un sous-pixel, la vignette envoyée à l'OCR change, et le vote bascule.
Sur la même fenêtre, `69884` est publié avec l'entrée rectangulaire et **rien** avec
l'entrée carrée, à **54 plaques localisées dans les deux cas**. Un gain égal payé d'un
pixel : non.

**Couper l'autotune seulement pour le détecteur de plaques.**
`torch.backends.cudnn.benchmark` est un drapeau **global** du processus : il n'existe pas
de portée par modèle. Et `benchmark_limit = 1`, qui borne le nombre d'algorithmes
essayés, revient exactement à l'heuristique — donc à couper.

## Ce que cela change au banc, et pourquoi c'est le vrai enseignement

**Une moyenne a caché six pauses d'une seconde pendant toute une session.** Le banc ne
rendait que des moyennes par image ; l'étage de plaques annonçait « 99 ms » et personne ne
pouvait voir que sa médiane valait 27. Les deux lectures appellent des gestes opposés :
un coût se réduit en travaillant moins — c'est le plafond par image, la mosaïque, la
taille d'entrée — une pause se supprime en trouvant ce qui bloque.

`scripts/pipeline_bench.py` rend donc désormais, **par appel et par poste**, `p50`, `p90`
et `max` à côté de la moyenne, et l'affichage signale d'un `⚠` tout poste dont le maximum
dépasse le double de sa médiane. C'est le seul ajout de ce lot qui aurait rendu le
diagnostic immédiat.

## Conséquences

- une analyse avec repérage de plaques est **1,3× à 2,1× plus rapide**, sans qu'aucun
  chiffre publié ne change — le gain est d'autant plus grand que la scène est
  **clairsemée**, c'est-à-dire dans le cas d'usage le plus courant : une route calme ;
- **les chiffres du plafond par image d'ADR 0032 sont refaits.** Son 1,27× venait surtout
  de l'évitement des appels à un recadrage ; une fois la vraie cause corrigée, sur la
  scène dense et à comptages identiques : `0` → 11,0 img/s et 180 plaques localisées,
  `2` → 9,0 et 137, `1` → 13,8 et 76. Le plafond **coûte des plaques localisées** et sa
  cadence ne s'ordonne pas proprement : il **borne** le coût quand le trafic monte, il ne
  l'améliore pas dans le cas général. Il reste à `0` par défaut ;
- la section « Ce que la mesure n'explique pas » d'ADR 0032 est **close** ;
- ADR 0013 garde tout le reste : la suppression de la compensation de mouvement
  (`gmc_method: none`, 1,93×) était et reste son gain principal. Seul son autotune tombe ;
- le préchauffage (`TRAFFIC_WARMUP`) garde son intérêt : il absorbe le chargement du
  modèle et sa fusion de couches, qui n'ont rien à voir avec l'étalonnage cuDNN.
