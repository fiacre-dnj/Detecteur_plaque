# ADR 0037 — Le plancher du détecteur suit le curseur quand celui-ci descend

- **Statut** : accepté
- **Date** : 2026-08-25
- **Complète** [ADR 0024](0024-le-detecteur-descend-sous-le-seuil-de-l-utilisateur.md), dont
  le mécanisme se défaisait en silence à l'autre bout de sa plage, et
  [ADR 0035](0035-le-seuil-de-confiance-n-atteignait-le-tracker-qu-une-fois.md), qui avait
  corrigé le câblage sans regarder les valeurs.

## Le symptôme

« On n'arrive pas à bien détecter les motos. Des fois oui, des fois pas de boîte du
tout. »

Le geste naturel — descendre « Confiance véhicules » pour rattraper un petit objet — ne
change rien. Ni message, ni erreur, ni différence dans les chiffres.

## Pourquoi une moto, et pas une voiture

Une moto est le plus petit gabarit COCO en circulation, et l'entrée du réseau la punit
deux fois : `imgsz = 640` avec `rect=True` réduit une source 16:9 à 640×384, donc une moto
de 60 px dans la vidéo en fait une vingtaine dans le tenseur. Son score tourne
couramment entre 0,20 et 0,35 — c'est-à-dire **juste sous** le défaut du curseur.

Or `new_track_thresh` porte ce défaut depuis ADR 0024 : une détection sous le seuil peut
**prolonger** une piste, jamais en **ouvrir** une. Et une détection qui n'ouvre pas de
piste n'existe nulle part — `_to_observations` rend `()` dès que `boxes.id is None` et
n'itère que les boîtes suivies. Pas de piste, pas d'observation, **pas de boîte à
l'écran**. La moto n'est pas mal dessinée : elle est absente.

Quand son score frôle le seuil, elle apparaît une image sur trois et disparaît le reste du
temps — le « des fois oui, des fois non » du rapport.

## La cause du réglage sans effet

`detector_floor()` lisait `track_low_thresh` du **fichier de base** et le rendait tel quel,
quelle que soit la requête :

```python
def detector_floor() -> float:
    return float(_base_tracker()["track_low_thresh"])   # 0,10, toujours
```

Deux conséquences, et la seconde est une régression d'ADR 0024 :

- **sous 0,10, le curseur était mort.** C'est ce plancher qui part en `conf=` à
  `model.track()`, donc le détecteur ne rendait jamais une boîte à 0,07. Descendre le
  curseur de 0,10 à 0,02 ne pouvait strictement rien changer — il n'y avait rien de
  nouveau à filtrer ;
- **pire, la bande basse de BYTE devenait vide.** Vérifié dans la roue installée
  (`byte_tracker.py`) :

  ```python
  remain_inds   = scores >= self.args.track_high_thresh
  inds_low      = scores >  self.args.track_low_thresh
  inds_below_high = scores <  self.args.track_high_thresh
  ```

  La seconde association travaille sur `low < s < high`. À confiance 0,05, le fichier
  dérivé portait `track_high_thresh = 0,05` sous un `track_low_thresh = 0,10` resté à la
  valeur du fichier de base : **l'ensemble est vide**. La seconde association redevenait
  du code mort — exactement la panne qu'ADR 0024 avait corrigée — sans qu'aucun message ne
  le dise.

## La décision

`detector_floor(confidence)` prend le seuil de la requête et rend :

```python
min(base_low, confidence * base_low / base_high)
```

**Le rapport de bande vient du fichier versionné lui-même** (`0,10 / 0,25 = 0,4`), et non
d'un nombre choisi ici : c'est l'écart que le déploiement a déjà tranché entre
« prolonger » et « créer ». Il n'y a donc pas de constante nouvelle à justifier.

`track_low_thresh` rejoint `REQUEST_TRACKER_KEYS` : il dépend désormais de la requête, donc
il doit être écrit dans le fichier dérivé **et** reposé par `reset_trackers` sur les
trackers vivants. L'oublier redonnerait la panne d'ADR 0035 à la deuxième analyse d'un
processus. La condition qui rend `reset_trackers` suffisante tient toujours sans rien
changer : `track_low_thresh` était **déjà** dans `LIVE_TRACKER_KEYS`, donc relu à chaque
image sur `self.args` et jamais gravé à la construction. Un test verrouille l'inclusion.

## Ce qui ne change pas, et c'est la propriété qui rend le correctif livrable

Le `min` avec le plancher de base signifie que **rien ne bouge au-dessus de
`track_high_thresh` du fichier versionné** :

| confiance | plancher avant | plancher après |
|---|---|---|
| 0,99 | 0,10 | 0,10 |
| 0,35 (défaut) | 0,10 | **0,10** |
| 0,25 | 0,10 | 0,10 |
| 0,20 | 0,10 | 0,08 |
| 0,10 | 0,10 | 0,04 |
| 0,05 | 0,10 (**bande vide**) | 0,02 |

Aucune analyse au réglage par défaut ne change d'un chiffre. Seul le bas de la plage
descend — là, précisément, où le curseur ne servait à rien.

Et `plancher < confiance` est vrai sur **toute** la plage du contrat (`ge=0.01, le=0.99`),
pour n'importe quel rapport strictement inférieur à 1 : si `confiance × ratio ≤ base_low`
alors le plancher vaut `confiance × ratio < confiance` ; sinon `confiance > base_low /
ratio > base_low` et le plancher vaut `base_low < confiance`. La bande basse ne peut donc
plus jamais être vide. Un test le passe valeur par valeur.

## Ce que cela ne corrige pas

**Ce n'est pas toute la cause du problème de motos**, et il faut le dire pour que le
prochain ne cherche pas là. Le filtre de classes d'Ultralytics est appliqué **après**
l'argmax par ancre (`utils/nms.py`) :

```python
else:  # best class only
    conf, j = cls.max(1, keepdim=True)
    ...
if classes is not None:
    x = x[(x[:, 5:6] == classes).any(1)]
```

Une ancre dont le meilleur score est `person 0,55` avec `motorcycle 0,48` juste derrière
est émise en `person`, puis **supprimée entièrement** par `classes=[2,3,5,7]` : l'évidence
« moto » de cette ancre est jetée sans recours. Le remède serait `multi_label=True`, mais
la clé n'existe pas dans `cfg/default.yaml` et `check_dict_alignment` la refuserait — il
faudrait envelopper une fonction interne de la bibliothèque. **À mesurer avant d'y
toucher, jamais à adopter par défaut.**

Restent aussi ouverts, chacun sur sa mesure : la résolution d'entrée (`imgsz`), le modèle
par défaut (`yolov8n` a le pire rappel petit objet du catalogue), et `fuse_score`, qui
pénalise **deux fois** une détection peu sûre — à la création et à l'association.

## Comment le vérifier

Le curseur doit cesser d'être inerte en bas de plage :

```bash
uv run python scripts/pipeline_bench.py --videos data/jobs --frames 300 --json out/00.json
```

Avant ce correctif, `--confidence 0.05` et `--confidence 0.10` rendent **exactement** les
mêmes `counts` — c'est la signature de la panne. Après, les deux courses divergent et
`rescuedByLowScore` cesse d'être nul.

**Contrôle non négociable** : à confiance 0,35, `counts.crossings` et `counts.byLine` sont
identiques au chiffre près avant et après. Un gain sur la moto payé par un franchissement
perdu n'est pas un gain.

Et comme toujours ici : le `FakeEngine` n'atteint jamais `UltralyticsEngine`, donc
`uv run pytest` ne peut pas prouver ce correctif. Il se vérifie contre le vrai serveur, sur
une vraie vidéo de motos.
