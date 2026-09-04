# ADR 0062 — Un plancher de confiance par classe

- **Statut** : accepté
- **Date** : 2026-09-04
- **Condition posée par l'audit fonctionnel** : « à ne construire que si la mesure montre
  que baisser le curseur global achète des petits objets **au prix** de faux positifs
  ailleurs ». Elle est remplie.

## La mesure qui la remplit

`recall_bench.py` compte les faux positifs depuis qu'un rappel lu seul a failli faire
changer un défaut. Sur le clip de ce dépôt, chemin de production complet, `yolov8n`
contre `yolo11x@1280` :

| imgsz | confiance | rappel `car` | précision `car` | F1 | effet de bord |
|---|---|---|---|---|---|
| 640 | 0,35 *(défauts)* | 0,484 | 1,000 | 0,652 | aucun |
| 960 | 0,20 | **0,790** | 0,860 | **0,824** | **17 `bus` inventés** |
| 960 | 0,12 | 0,790 | 0,583 | 0,671 | pire partout |

Le curseur unique force donc à choisir entre **rater les petits objets** et **compter
des véhicules fantômes** — alors que les deux effets ne portent pas sur les mêmes
classes. Les dix-sept `bus` n'existent pas ; les voitures retrouvées, si.

C'est exactement la condition que l'audit posait, et rien d'autre ne la satisfaisait :
si baisser le curseur n'avait rien coûté, la bonne réponse aurait été « baissez le
curseur » et aucun code n'aurait été dû.

## La décision

`smallObjectConfidence` voyage par requête, `null` par défaut. Il ne s'applique qu'aux
**trois plus petits gabarits de COCO** — `person`, `bicycle`, `motorcycle` — dont le
rappel est structurellement le plus bas :

| | moto | personne | vélo | voiture |
|---|---|---|---|---|
| yolov8n | 0,580 | 0,673 | **0,392** | 0,515 |
| yolo11m | 0,712 | 0,746 | 0,546 | 0,654 |

### Un seul curseur, pas sept

Sept planchers seraient sept curseurs dans un tiroir qui en compte déjà huit, pour une
distinction que la mesure ne soutient pas : ce qui sépare les classes ici est leur
**taille**, et elle partitionne le catalogue en deux. `SMALL_CLASS_IDS` (domaine) est le
miroir exact de `SMALL_CLASSES` (client, `shared/lib/classes.ts`), qui nomme déjà les
mêmes classes pour l'avertissement d'avant-analyse. Doublon assumé de part et d'autre de
la frontière de langage, verrouillé par un test **backend** qui lit le fichier client —
même procédé que `MIN_PLATE_CROP_SIDE_PX` et `QUERY_MARGIN`.

### Trois points qui ne se devinent pas

- **`null` est un no-op strict.** Tous les planchers valent alors le curseur unique, donc
  `minimum_floor` rend exactement `confidence` et le filtre par classe ne retire rien.
  Aucune analyse existante ne change d'un chiffre, et c'est ce qui rend l'ADR livrable ;
- **le MINIMUM des planchers part au tracker**, jamais le seuil nominal. Il devient
  `track_high_thresh` / `new_track_thresh` (ADR 0024) : s'il restait à 0,35, une moto à
  0,25 n'ouvrirait aucune piste et le plancher par classe serait **inerte**. C'est la
  panne d'ADR 0037 à un autre étage, et `minimum_floor` existe pour l'éviter ;
- **le filtre vit après le NMS et avant le tracker**, dans le `postprocess` du prédicteur
  qu'ADR 0057 a déjà introduit. Plus tôt, le NMS travaillerait sur un jeu amputé — une
  voiture faible cesserait de supprimer son propre doublon. Plus tard, le tracker aurait
  ouvert une piste que rien ne saurait retirer : le score publié d'une piste vient de sa
  dernière détection et oscille, donc filtrer en aval couperait une piste vivante au
  hasard des images. Et **jamais dans le domaine**, qui documente déjà qu'une détection
  non associée n'existe plus à ce stade.

### Le curseur n'apparaît que s'il sert

Il n'est rendu que si la sélection contient `person`, `bicycle` ou `motorcycle`. Sur une
sélection de véhicules à moteur il ne s'appliquerait à rien, et un curseur sans effet
est le pire état d'un réglage — c'est le constat qui a motivé ADR 0007 et ADR 0037.

## Ce qui n'est pas mesuré

**Le gain sur les motos.** Toute la mesure ci-dessus porte sur des **voitures** et des
`bus` fantômes, sur un clip 720p qui ne contient ni moto ni personne. Le raisonnement —
les petites classes scorent plus bas, donc un plancher plus bas les récupère — est
étayé par COCO, pas par ce métrage.

Ce qui est mesuré, et qui suffit à justifier le mécanisme : **baisser le curseur unique
invente des objets dans les classes qu'on ne cherchait pas**. Séparer les deux planchers
supprime ce coût, quel que soit le gain exact sur les motos.

## Conséquences

- **aucun défaut ne change** — `null` partout, comportement d'avant au chiffre près ;
- **le réglage rend deux jobs incomparables sans qu'on le lise**, comme la définition
  d'analyse. Il doit rejoindre le récapitulatif d'avant-analyse le jour où il sera
  couramment utilisé ;
- **il peut aussi monter**, et le port ne l'interdit pas : une scène où les motos sont
  hallucinées appelle l'inverse. Ce n'est pas au domaine d'en juger.

## Comment le vérifier

```bash
cd backend && uv run pytest tests/unit/counting/test_planchers_par_classe.py -q
```

Sur métrage réel, la paire décisive est : même clip, même modèle, `smallObjectConfidence`
à `null` puis à 0,20. Le rappel `motorcycle` doit monter **sans** que `car`, `bus` ou
`truck` gagnent des faux positifs — c'est exactement ce que le curseur unique ne
permettait pas.
