# ADR 0047 — La ReID d'apparence n'est gratuite que sur une tête avec NMS

- **Statut** : accepté
- **Date** : 2026-08-28
- **Amende** [ADR 0013](0013-le-cout-du-pipeline-de-comptage.md), qui a gardé
  `with_reid: true` sur la foi d'une mesure — « 0,3 à 3,5 ms par image, il n'y a rien à
  y gagner » — restée vraie pour les familles v8, 11 et 12 et **fausse d'un facteur 19**
  pour la famille 26, arrivée au catalogue après elle.
- **Ne touche pas** [ADR 0016](0016-compter-les-objets-suivis.md) : il ne s'agit pas de la
  galerie d'identités supprimée là-bas, mais de l'association d'apparence *interne au
  tracker*, qui n'a jamais quitté le projet.

## Contexte

`backend/config/botsort_reid.yaml` porte `with_reid: true` et `model: auto` depuis le
début du projet. `auto` veut dire « prends les caractéristiques que le détecteur produit
déjà » : un crochet posé sur l'entrée de la tête `Detect` récupère les cartes de
caractéristiques, et l'encodeur n'est qu'une passe-plat. C'est ce qui justifiait le
commentaire du fichier — « gratuite ici puisque le modèle produit déjà les
caractéristiques nécessaires » — et la mesure d'ADR 0013.

Cette phrase est vraie tant que la tête du détecteur est une tête classique. Elle cesse
de l'être sur une tête **sans NMS**.

## Le diagnostic

`ultralytics/cfg/models/26/yolo26.yaml:9` porte `end2end: True`. C'est le **seul** yaml de
modèle du catalogue qui le porte — vérifié sur v8, 11, 12 et 26 dans la roue installée
(`ultralytics 8.4.115`). Or dans `trackers/track.py`, au démarrage du prédicteur :

```python
if cfg.tracker_type in {"botsort", ...} and cfg.with_reid and cfg.model == "auto":
    if not (isinstance(...) and isinstance(head, Detect) and not head.end2end):
        cfg.model = "yolo26n-cls.pt"     # <<< plus "auto"
    else:
        predictor._hook = head.register_forward_pre_hook(pre_hook)
```

Sur une tête `end2end`, le crochet n'est pas posé et `model` cesse d'être `auto` : c'est
un **réseau de classification complet**, exécuté sur chaque recadrage de chaque image.
Trois conséquences, et la première n'est pas la plus coûteuse :

**1. Le poids est téléchargé au runtime.** `yolo26n-cls.pt` n'est pas dans
`backend/.weights/`, donc `attempt_download_asset` va le chercher sur GitHub au premier
`track()`. C'est ce que le projet refuse depuis [ADR
0002](0002-pas-de-poids-dans-git.md), et c'est le motif exact du rejet de PaddleOCR en
[ADR 0007](0007-lecture-du-texte-de-plaque.md). Hors ligne ou en conteneur sans réseau,
l'analyse échoue ou se dégrade sans le dire.

Ce n'est pas une hypothèse : **deux exemplaires du fichier traînaient dans l'arborescence
au moment d'écrire cette ADR**, 5 786 434 octets chacun, l'un dans `backend/` daté du
2026-08-12, l'autre à la racine du dépôt daté du 2026-08-19 — deux téléchargements
distincts, depuis deux répertoires de travail différents, à une semaine d'écart. Ils sont
couverts par `.gitignore` (`*.pt`), donc ADR 0002 n'a pas été violée dans l'historique ;
elle l'a été à l'exécution, en silence, deux fois.

**2. La cadence s'écroule d'un facteur quatre.** Mesuré par
`scripts/pipeline_bench.py`, même vidéo 1080p, 150 images, 15 de chauffe, GPU Quadro
P1000, `gmc=none`, autotune cuDNN coupé :

| modèle | `with_reid` | encodeur réel | img/s | poste `tracker` | franchissements |
|---|---|---|---|---|---|
| `yolov8n` | false | — | 61,21 | 1,26 ms | 2 |
| `yolov8n` | **true** | passe-plat du détecteur | 55,94 | **2,37 ms** | 2 |
| `yolo26n` | false | — | 61,81 | 1,33 ms | 4 |
| `yolo26n` | **true** | `yolo26n-cls.pt` | **15,09** | **45,19 ms** | 4 |

Les deux familles ne sont pas comparables entre elles — elles ne détectent pas la même
chose, d'où 2 franchissements contre 4 — mais chaque ligne l'est à sa voisine. La ReID
coûte **0,91×** sur `yolov8n` et **4,10×** sur `yolo26n`. Le poste `tracker` de la
seconde est **19 fois** celui de la première, ReID active dans les deux cas.

C'est exactement le profil de coût qu'[ADR
0030](0030-le-detecteur-de-plaques-payait-une-inference-par-vehicule.md) et [ADR
0032](0032-l-ocr-n-etait-pas-le-goulot-le-detecteur-de-plaques-l-est.md) ont combattu sur
le détecteur de plaques : linéaire en recadrages, une inférence par véhicule.

**3. Le banc ne pouvait pas le montrer.** `_tracker_settings` lisait `with_reid` dans le
fichier de suivi, qui dit `true` dans les deux cas. Le rapport annonçait donc
`reid=True` pour `yolov8n` comme pour `yolo26n`, et un écart de cadence de 4× ne se
rattachait à **rien de visible** dans le rapport.

## Décision

**La ré-identification d'apparence est coupée quand, et seulement quand, la tête du
détecteur est `end2end`.**

Le fichier versionné reste à `with_reid: true` : la valeur par défaut ne change pour
personne, et le fichier du dépôt reste celui qui tourne dans le cas courant.
`resolved_tracker_config` gagne un troisième paramètre, `appearance_reid=True`, qui pose
`with_reid: False` dans un fichier dérivé quand il vaut `False`.

Quatre points qui ne se devinent pas :

- **la question est posée au graphe, jamais au nom du fichier**, et c'est l'invariant 10.
  Ici il n'est pas décoratif : `end2end` est une clé du *yaml de modèle*, donc un poids
  réentraîné ou réexporté peut la porter sans s'appeler « yolo26 », et un fichier renommé
  peut s'appeler yolo26 sans la porter. `head_is_end2end` lit
  `model.model.model[-1].end2end`, une propriété d'Ultralytics qui répond
  `hasattr(self, "one2one")` — vraie si et seulement si le graphe a réellement la branche
  un-pour-un ;
- **le repli est conservateur** : sans réponse — doublure de test, version d'Ultralytics
  qui changerait de forme — `head_is_end2end` rend `False`, donc l'apparence reste
  active, donc le comportement d'avant. Se tromper dans ce sens ne coûte que de la
  cadence sur un modèle exotique ; se tromper dans l'autre changerait des comptages sur
  toute la famille v8/11/12 ;
- **seul `with_reid` est posé, et pas `model`.** `build_encoder` sort sur son premier
  argument : à `False`, la valeur de `model` n'est jamais lue. La changer aussi serait un
  réglage annoncé et sans effet, le pire état d'un réglage (ADR 0016) ;
- **le fichier de suivi ne peut plus être résolu avant d'avoir pris le bail**, puisque la
  réponse dépend du modèle chargé. `_tracker_for` prend donc le modèle en argument,
  `iter_video` le résout à l'intérieur de son `with`, et `UltralyticsStream` reçoit le
  *résolveur* au lieu du chemin — il le calcule après avoir ouvert son bail. Les deux
  modes continuent d'appeler le même résolveur, ce qui reste la garantie qu'un même tracé
  donne les mêmes chiffres en différé et en direct.

Le nom du fichier dérivé porte l'apparence
(`botsort-gmc-none-hi-0.25-reid-0.yaml`). Sans cela, un job `yolov8n` et un job
`yolo26n` du même processus, à mouvement et seuil égaux, écriraient dans le **même**
fichier : le second réécrirait sous les pieds du premier, et le comptage du premier
changerait en cours de route sans rien lever.

## Vérification

Contre le vrai moteur, pas le `FakeEngine` — cet étage ne se traverse pas autrement.

| course | avant | après | comptage |
|---|---|---|---|
| `yolo26n` | 15,09 img/s, tracker 45,19 ms | **60,16 img/s, tracker 1,42 ms** (3,99×) | franchissements 4 → 4 |
| `yolov8n` | 55,94 img/s | 54,82 img/s (0,98×) | **« comptage identique »** |

La ligne qui porte la non-régression est la seconde : c'est le comparateur du banc
lui-même — celui qui écrit « ⚠ LE COMPTAGE A CHANGÉ » — qui reste silencieux.

Sur `yolo26n`, `trackedVehicles` passe de 12 à 11 et les **franchissements ne bougent
pas**. C'est le sens attendu : l'association d'apparence fusionnait une piste fragmentée,
exactement l'effet qu'[ADR
0024](0024-le-detecteur-descend-sous-le-seuil-de-l-utilisateur.md) avait mesuré dans
l'autre sens (92 → 83 objets suivis, franchissements 61 → 61). Un objet suivi de plus ou
de moins sur une fenêtre de 150 images n'est pas un franchissement, et l'invariant 6
sépare précisément ces deux unités.

## Ce qui a été écarté

- **Pré-récupérer `yolo26n-cls.pt` dans `scripts/fetch_weights.py`.** Supprime le
  téléchargement au runtime et rien d'autre : la famille 26 continuerait de payer 4× sa
  cadence pour une association d'apparence qui ne change aucun franchissement. C'était le
  geste le plus petit, pas le plus juste.
- **Forcer `rect=False` ou une autre forme d'entrée sur l'encodeur.** Hors sujet : le coût
  n'est pas une pause d'étalonnage comme en ADR 0033, c'est du calcul. Les `p50 42 / p90
  56 / max 142 ms` par appel montrent une distribution resserrée, pas six pauses d'une
  seconde.
- **Couper `with_reid` pour tout le monde.** Ce serait défaire ADR 0013 sur les trois
  familles où sa mesure tient toujours, et changer des comptages là où personne ne le
  demande. Le critère d'ADR 0013 — « un gain indiscernable du bruit de mesure » — est
  **conservé** : il est simplement appliqué famille par famille, et il s'inverse là où le
  coût a été multiplié par 19.

## Conséquences

- **Aucun réglage nouveau côté utilisateur ni côté déploiement.** C'est une propriété du
  modèle choisi, pas un choix à faire. Le journal de course porte désormais
  `appearance_reid` à côté du seuil et du plancher, parce que c'est ce qu'on vient
  regarder quand une cadence s'écroule.
- **Le banc dit la vérité** : `withReid` est relu du fichier réellement résolu pour le
  modèle réellement mesuré. `_tracker_settings` prend le registre et l'identifiant de
  modèle, et un test verrouille les deux cas.
- **Les deux `yolo26n-cls.pt` déjà téléchargés sont morts** : plus aucun chemin ne les
  charge. Ils peuvent être supprimés.
- Le commentaire de `botsort_reid.yaml` a été corrigé : il annonçait la gratuité sans
  condition, et renvoyait encore à « la galerie du domaine » supprimée par ADR 0016.
- Une famille de modèles ajoutée au catalogue devra être mesurée avant d'être livrée. Ce
  défaut est né d'un poids nouveau glissé dans un mécanisme dont l'hypothèse de coût
  n'était plus vraie — et personne n'a rien vu, parce que rien n'échoue.
