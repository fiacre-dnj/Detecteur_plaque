# ADR 0013 — Le pipeline de comptage, mesuré : la compensation de mouvement coûtait plus cher que l'inférence

- **Statut** : accepté
- **Date** : 2026-08-12

## Contexte

Le GPU est en service depuis [ADR 0012](0012-torch-cuda-sur-windows.md) et
l'analyse tourne à ~20 images/s. La demande est d'aller beaucoup plus haut. Le
matériel, lui, est contraint et le restera : TensorRT exige SM ≥ 7.5 quand la
Quadro P1000 est SM 6.1, donc **ni INT8 ni moteur optimisé**, et le fp16 y est
plus lent que le fp32. Il ne reste que le pipeline.

Or **personne ne savait ce qu'il y avait dans les 47 ms par image.** Le chiffre
était un total opaque, et l'intuition partagée — « c'est l'inférence, c'est le
GPU » — n'avait jamais été vérifiée. ADR 0008 avait déjà démontré une fois que
l'intuition se trompe sur ce projet.

## Décision 1 — Un banc par étage, avant toute optimisation

`backend/scripts/pipeline_bench.py` chiffre, par image analysée : décodage,
prétraitement, inférence, NMS, suivi, compensation de mouvement, domaine,
sérialisation. Il fait tourner le **vrai** moteur et la **vraie**
`AnalysisSession`, dans l'ordre où `AnalysisService` les enchaîne.

Trois sources de mesure, qui ne se recouvrent pas :

- `result.speed` d'Ultralytics pour prétraitement / inférence / NMS — ces
  chronomètres **synchronisent CUDA**, donc l'inférence est du vrai temps GPU ;
- le suivi n'est **pas** dans `speed` (il tourne dans un callback exécuté après
  les chronomètres du prédicteur) : il est mesuré en enveloppant `BOTSORT.update`,
  et la compensation en enveloppant `GMC.apply` ;
- le décodage n'est chronométré nulle part par Ultralytics : il est obtenu **par
  différence** et porte ce nom (`decodeAndOther`). Un poste soustrait ne doit
  jamais prétendre au même statut qu'un poste mesuré.

**Le banc porte aussi les compteurs** — `unique_vehicles`, `crossings`,
`reid_hits`, par ligne et par classe — et son `--compare` affiche débit et
justesse côte à côte. C'est délibéré : un gain de débit payé par un comptage
différent n'est pas un gain, et le lire dans deux tableaux séparés laisserait
croire le contraire.

## Ce que la mesure a dit

Trois vidéos 720p réelles, yolov8n, 200 images après rodage, GPU :

| poste | ms/image | part |
|---|---|---|
| **suivi (BoT-SORT)** | **23,0** | **44,7 %** |
| *dont compensation de mouvement* | *20,2* | *39,2 %* |
| inférence GPU | 17,8 | 34,6 % |
| décodage et transport | 4,6 | 8,9 % |
| NMS | 3,5 | 6,9 % |
| prétraitement | 1,9 | 3,7 % |
| domaine (`session.feed`) | 0,6 | 1,1 % |
| sérialisation (`snapshot()`) | 0,02 | 0,0 % |

**Le poste le plus cher du pipeline n'était pas le GPU.** `sparseOptFlow` — un
flux optique épars recalculé à chaque image sur CPU — coûtait plus que
l'inférence elle-même, pour compenser un mouvement de caméra **qui n'existe pas
sur une caméra fixe**.

Le domaine, lui, est hors de cause : 0,6 ms, soit 1 % du budget. Toute
optimisation du comptage lui-même aurait été du temps perdu.

## Décision 2 — `gmc_method: none` par défaut, et réglable

Mesure appariée, machine au repos, même vidéo, même géométrie :

| vidéo | avant | après | gain | comptage |
|---|---|---|---|---|
| A | 15,58 img/s | 30,03 img/s | **1,93×** | **identique** |
| B | 17,67 img/s | 36,64 img/s | **2,07×** | **identique** |
| C | 16,16 img/s | 32,01 img/s | **1,98×** | **identique** |

Le réglage est `TRAFFIC_TRACKER_GMC`. Ultralytics ne prend sa configuration de
suivi que par chemin de fichier : quand le réglage diffère du fichier versionné,
le moteur écrit un fichier dérivé (`resolved_tracker_config`) et journalise celui
qu'il charge. En configuration par défaut, aucun fichier n'est dérivé et c'est
bien le fichier du dépôt qui tourne — celui qu'on peut lire pour savoir ce qui
s'exécute.

**Quand le remettre à `sparseOptFlow`** : dès que la caméra bouge — plan embarqué,
drone, mât mal haubané par grand vent. Sans compensation, un mouvement global se
lit comme un mouvement des véhicules ; les prédictions de Kalman partent à côté et
les identités se multiplient. Le symptôme n'est pas une erreur, c'est un
`unique_vehicles` qui gonfle.

## Ce qui n'est **pas** un levier, et il fallait le mesurer pour le savoir

**La ré-identification interne du tracker.** Une fois la compensation retirée,
`BOTSORT.update` **entier** coûte 0,3 à 3,5 ms par image. Il n'y a rien à y
gagner, et `with_reid: true` reste donc en place : la couper aurait dégradé la
continuité des identités à travers les occlusions courtes pour un gain
indiscernable du bruit de mesure.

## Conséquences

- **Cette machine varie de ±20 % d'une course à l'autre** selon son état
  thermique : la même référence a été mesurée à 19,4 puis 15,6 images/s. C'est un
  portable dont `nvidia-smi` rapporte un compteur de bridage par la puissance non
  nul. **Seules des courses appariées, enchaînées et sans autre charge, sont
  comparables** — une mesure lancée pendant les tests unitaires a affiché 1,40× là
  où le protocole propre en donne 1,93×, et l'anomalie ne s'est vue que parce que
  le banc chiffre *tous* les postes : l'inférence GPU, que retirer le GMC ne peut
  pas ralentir, avait bougé de 17,0 à 19,9 ms.
- Le fichier `config/botsort_reid.yaml` porte désormais la valeur de base `none`
  et le réglage la surcharge. Les deux doivent rester d'accord, et un test le
  vérifie : laisser diverger le fichier versionné et le défaut rendrait le premier
  trompeur pour quiconque le lit — et c'est le premier endroit où on regarde.
- `pyyaml` devient une dépendance déclarée. Elle arrivait déjà par ultralytics,
  mais l'adaptateur l'importe maintenant lui-même : même règle que pour `onnx`,
  ce qu'on importe se déclare.
- Le prochain budget est très différent de celui d'avant : à ~32 images/s,
  l'inférence GPU pèse désormais **57 %** du temps. Les leviers suivants —
  résolution d'entrée, lots, ROI, recouvrement du décodage — s'attaquent donc à
  un pipeline dont le GPU est enfin le facteur limitant.
