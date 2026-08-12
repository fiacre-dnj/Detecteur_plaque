# ADR 0015 — Le détecteur de plaques passe en `.pt`, et l'auto-test rend la panne visible

- **Statut** : accepté
- **Date** : 2026-08-12
- **Amende** : [ADR 0008](0008-precision-de-l-anpr.md) — la contrainte « export figé à
  `1×3×640×640` » qui justifiait la mosaïque comme seul levier de débit
- **Complète** : [ADR 0007](0007-lecture-du-texte-de-plaque.md) (l'OCR, elle, **reste**
  en ONNX), [ADR 0012](0012-torch-cuda-sur-windows.md) (la règle fp16/Volta s'applique
  désormais aussi au détecteur de plaques)

## Contexte

L'ANPR était annoncée indisponible par l'interface. Le diagnostic tient en une phrase :
`backend/.weights/` ne contenait que `yolov8n.pt` et `yolo26n.pt`. Ni
`license-plate.onnx`, ni `license-plate-ocr.onnx`, ni son dictionnaire. Le dossier
`yolo/` que `CLAUDE.md` désignait comme la source du modèle **n'existait plus**, il n'y
avait pas de `backend/.env`, et `TRAFFIC_PLATE_MODEL_URL` était vide dans
`.env.example` — sans qu'aucun commit de l'historique n'ait jamais contenu d'URL
(`git log -S "TRAFFIC_PLATE_MODEL_URL=http"` ne rend rien).

**Rien n'était cassé dans le code.** `plate_available()` n'est qu'un `path.is_file()` :
le message disait la vérité. Mais il fallait choisir un modèle, et ce choix rouvrait la
question du format.

## Décision 1 — Le détecteur passe en `.pt`

### La mesure qui tranche

`onnxruntime 1.28.0`, sur ce poste, n'expose que :

```
['AzureExecutionProvider', 'CPUExecutionProvider']
```

**Pas de provider CUDA.** Tout `.onnx` est donc cloué au CPU, quel que soit le GPU
présent — alors que `torch 2.13.0+cu126` voit la Quadro P1000 sans difficulté. Ce
n'est pas une question de réglage : c'est la roue `onnxruntime` installée, et passer à
`onnxruntime-gpu` demanderait une seconde pile CUDA à faire coexister avec celle de
torch.

Mesuré sur ce poste, **même modèle, même image, 20 inférences après préchauffage** :

| variante | ms / inférence |
|---|---|
| `.pt` sur GPU (Quadro P1000) | **45,2** |
| `.pt` sur CPU | 183,9 |

Soit **4,1×**. Le chiffre honnête est celui-là, et pas un rapport au 702 ms des
ADR 0007/0008 : ces 702 ms ont été mesurées sur un i5-8350U, une autre machine. Les
comparer serait exactement le genre de raccourci qu'ADR 0012 interdit en exigeant
qu'un run persisté porte son `device`.

### Ce que le `.pt` lève, au-delà de la vitesse

L'export ONNX était figé à `1×3×640×640`, sa grille de 8400 ancres gravée dans le
graphe : vérifié par chirurgie de graphe à l'époque, toute autre forme faisait échouer
le `Reshape` du DFL. C'est **la** raison pour laquelle la mosaïque d'ADR 0008 était le
seul levier de débit disponible. En `.pt`, le lot et la résolution redeviennent des
paramètres.

### Ce qui ne change pas, et pourquoi

- **`NET_SIZE` reste à 640.** C'était une constante de l'export, c'est maintenant un
  choix — gardé à la résolution d'entraînement du modèle. Monter plus haut interpole
  des pixels que le réseau n'a jamais vus à cette échelle ; cela se mesure au banc
  avant de se décider, ça ne se suppose pas.
- **La mosaïque reste, et reste désactivée par défaut.** Son arbitrage mesuré garde sa
  valeur sur une machine sans GPU, et la supprimer effacerait un résultat qu'on
  regretterait. Le vrai remplaçant — passer une liste de recadrages à `predict()`, ce
  que le `.pt` permet — est une optimisation à mesurer, pas un acquis de cette ADR.
- **L'OCR reste en ONNX**, et ce n'est pas une incohérence. PP-OCRv3 rec est un modèle
  de reconnaissance CTC, pas un détecteur YOLO : Ultralytics ne sait pas le charger. Le
  seul équivalent `.pt` imposerait PaddlePaddle, 600 Mo, refusé en ADR 0007. Et
  l'arbitrage est franc : 66 ms par vignette contre 702 pour le détecteur à l'époque,
  rapport 10,7 à 1. **Optimiser l'OCR ne rend rien de perceptible.**
- **Les poids véhicules étaient déjà des `.pt`**, par nécessité : `model.track()` a
  besoin du pipeline BoT-SORT + ReID + GMC qu'un export ONNX ne porte pas. Il n'y avait
  rien à convertir de ce côté, contrairement à ce que la présence historique de `.onnx`
  dans `yolo/` pouvait laisser croire.

### Le modèle retenu

`morsetechlab/yolov11-license-plate-detection`, variante **nano**, classe unique
`License_Plate`, **AGPL-3.0** — la même licence que ce dépôt et qu'`ultralytics`.
L'URL et sa somme SHA-256 sont documentées dans `.env.example` : sans URL committée, le
prochain déploiement retombe dans le trou d'où celui-ci sort.

Nano et non small/medium : le détecteur tourne **par véhicule et par image**, c'est le
goulot du pipeline (ADR 0010), et ADR 0008 a établi que la justesse se gagne au filtre
géométrique bien plus qu'au palier de modèle — 426 boîtes gardées sur 538, dont 112
« véhicule entier » que le seuil de confiance ne pouvait pas écarter. Les variantes
s/m/l/x sont au même endroit, à un réglage près.

## Décision 2 — Le suffixe fait partie du contrat, et le script le vérifie

**Ultralytics choisit son backend d'après le nom du fichier**, jamais d'après son
contenu (`ultralytics/nn/autobackend.py`, `_model_type()`). Or
`fetch_plate_model.py` écrivait dans `resolved_plate_model_path` sans jamais regarder
l'URL, et ce chemin valait `license-plate.onnx`.

Télécharger un `.pt` sans rien changer aurait donc produit : empreinte SHA-256 valide,
fichier présent sur le disque, `plateAvailable: true`, option cochable dans
l'interface — et **zéro plaque à chaque image**, avec pour seule trace un
`"passe ANPR en échec"` par processus, `_checked` verrouillant après le premier échec.

C'est le **quatrième exemplaire du même mode de panne** dans ce projet :

| # | panne | symptôme |
|---|---|---|
| 1 | `.env` avec commentaire en fin de ligne | ANPR indisponible, bon fichier au bon endroit |
| 2 | `en_dict.txt` et son `line.strip()` | plaques fausses et plausibles, 1 030 tests verts |
| 3 | `weights_dir` ancré sur le CWD | *tous* les poids paraissent absents |
| 4 | suffixe qui trompe le choix de backend | drapeau vert, pipeline muet |

Chaque fois : aucune exception, aucun journal utile, et des chiffres plausibles.

Deux correctifs :

- le défaut devient **`license-plate.pt`** ;
- `fetch_plate_model.py` **refuse** un téléchargement dont le suffixe d'URL contredit
  celui de la destination, **avant** d'écrire quoi que ce soit — un refus qui a déjà
  posé le fichier laisse derrière lui le piège qu'il prétend éviter. Le refus nomme le
  réglage à corriger : un garde qui ne dit pas quoi changer se contourne en le
  supprimant.

Une URL qui n'annonce aucun format (lien signé, redirection, route d'API) passe : la
refuser bloquerait des installations légitimes pour un doute que l'auto-test lèvera de
toute façon.

## Décision 3 — `plateAvailable` ne suffit pas : un auto-test au démarrage

`available` n'est qu'un test de présence, et **c'est délibéré** — l'interface interroge
`/health` en permanence, charger un modèle à chaque appel serait absurde. Mais cette
économie laisse passer précisément les quatre pannes du tableau ci-dessus.

`PlateDetector.probe()` charge les poids et lance **une** inférence sur une image
noire. Appelé une fois au démarrage, dans un thread worker (invariant 11), accroché au
`warmup` existant — donc soumis au même `TRAFFIC_WARMUP=false` qui protège la CI.

Le verdict remonte dans `/health` sous **`plateLoadable`**, à trois états :

| `plateAvailable` | `plateLoadable` | lecture |
|---|---|---|
| `false` | `null` | déploiement neuf, aucun modèle. Normal. |
| `true` | `null` | préchauffage désactivé, ou en cours. Pas un échec. |
| `true` | `true` | l'ANPR fonctionne. |
| `true` | **`false`** | **poids présents et illisibles — l'ANPR est muette.** |

Trois états et non deux : confondre « pas encore testé » et « en échec » ferait passer
tout démarrage sans préchauffage pour une panne, et c'est le bruit qui apprend à un
opérateur à ignorer un champ. La dernière ligne est la seule qu'aucun autre drapeau ne
peut exprimer, et c'est celle qui trompe : elle passe donc en tête de l'infobulle
d'état, et en `logger.error` au démarrage — pas en `warning`, parce que l'utilisateur
croit que l'ANPR marche.

## Conséquences

- **`TRAFFIC_INFERENCE_THREADS` atteint désormais le détecteur de plaques.** Il vit sur
  torch comme le reste. Le commentaire de `.env.example` qui affirmait le contraire
  était vrai de l'export ONNX et ne l'est plus.
- **La règle fp16/Volta d'ADR 0012 s'applique au détecteur de plaques.** Il reçoit
  `device` et `half` **du registre** plutôt que de refaire sa propre détection : une
  seule décision par machine, prise à un seul endroit, testée une seule fois. Deux
  détections indépendantes finiraient par se contredire, et celle du détecteur de
  plaques serait la moins testée. Sur cette Pascal, `half=False`.
- **`OnnxPlateDetector` devient `UltralyticsPlateDetector`.** La classe n'a jamais fait
  que passer son chemin à `YOLO(path, task="detect")` ; un nom qui affirme un format
  que la classe n'impose pas finira par mentir.
- **L'ONNX reste chargeable** en pointant `TRAFFIC_PLATE_MODEL_PATH` sur un `.onnx`.
  Il fonctionne, il reste simplement sur le CPU.
- **Le plancher de lecture de l'OCR ne bouge pas d'un pixel.** Cette ADR accélère la
  *détection* ; elle ne rend pas lisible une plaque de 40 px. Sur une vidéo dont les
  plaques font 27 à 88 px, la chaîne se taira toujours — correctement, et en disant
  pourquoi (invariant 14). Ne pas lire l'accélération comme une amélioration de
  justesse.

## Vérifié

Sur le vrai conteneur de production, pas sur le moteur factice :

```
plate model path  : …/backend/.weights/license-plate.pt
plateAvailable    : True
plateOcrAvailable : True
fp16 désactivé : ce GPU le calcule plus lentement que le fp32  capability=6.1  gpu='Quadro P1000'
modèle de plaques chargé  device=0  half=False
auto-test du détecteur de plaques réussi
probe verdict     : True
```

Et le garde de format, sur une destination volontairement incohérente :

```
ÉCHEC : format incohérent.
L'URL annonce un fichier « .pt » et la destination est « .onnx » : …
```

— sans qu'aucun fichier ait été écrit.
