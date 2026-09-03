# ADR 0057 — Le NMS agnostique supprimait la moto sous son pilote

- **Statut** : accepté
- **Date** : 2026-09-03
- **Complète** le piège 5 de [`prompt/13`](../../prompt/13-PIEGES-CONNUS.md), dont elle
  restaure le domaine de validité sans rien lui retirer.
- **Indissociable d'**
  [ADR 0056](0056-la-suppression-des-boites-incluses-effacait-les-petits-objets.md) :
  livrée seule, elle ne rend rien du tout. Voir « L'ordre importe ».
- **Ferme** la piste `multi_label` laissée ouverte par
  [ADR 0037](0037-le-plancher-du-detecteur-suit-le-curseur-quand-il-descend.md).

## Le symptôme

« On a du mal à détecter les motos et les personnes. » La seconde cause, après celle
d'ADR 0056.

## Le mécanisme

Les deux appels à `model.track()` passent `agnostic_nms=True`. Dans
`ultralytics/utils/nms.py` :

```python
c = x[:, 5:6] * (0 if agnostic else max_wh)   # classes
boxes = x[:, :4] + c                          # boxes (offset by class)
i = torchvision.ops.nms(boxes, scores, iou_thres)
```

Le décalage par classe tombe à zéro : **toutes les classes retenues entrent dans un
seul bassin de suppression**, et celle qui score le moins disparaît dès que le
recouvrement dépasse `iou_threshold` (0,45 par défaut). Un motard rend donc un objet
là où il y en a deux.

Vérifié en exécutant la vraie fonction sur un tenseur fabriqué : deux boîtes à IoU
0,667, `person 0.55` et `motorcycle 0.48` — la moto disparaît. Le mécanisme est
**symétrique** : avec `person 0.40` contre `motorcycle 0.62`, c'est la personne qui
tombe. C'est la moitié « personnes » du symptôme.

Le commentaire qui justifiait le réglage invoquait une prémisse :

> Nos **quatre** classes sont mutuellement exclusives sur un objet physique, donc la
> suppression doit ignorer la classe.

`git log -S` date ce commentaire du 2026-08-06 et l'ajout de `person`, `bicycle` et
`train` au catalogue du 2026-08-12. La prémisse a été falsifiée six jours après avoir
été écrite, et le code est resté juste-par-coïncidence pendant treize mois — jusqu'à
ce que quelqu'un coche « Personne ».

## Ce qui est mesuré, et ce qui ne l'est pas

Le mécanisme est certain. **Sa fréquence ne l'est pas**, et il faut le dire : sur une
géométrie réaliste — boîte piéton haute et étroite sur boîte moto plus large et plus
basse — l'IoU mesurée vaut **0,407**, donc **sous** le seuil de 0,45. Il faut un
cadrage serré, ou une boîte de moto qui englobe son pilote, pour déclencher la
suppression.

Corollaire pratique, contre-intuitif et donc à écrire : **baisser le « Seuil IoU »
aggrave ce cas**, alors que c'est le réflexe de qui ne détecte pas assez. Le monter le
soigne.

Aucun des six clips de ce dépôt ne contient de moto ni de piéton
(`recall_bench.py --inventory`), donc la fréquence réelle reste à mesurer le jour où
du métrage existera.

## La décision

Le NMS reste agnostique **à l'intérieur** d'un groupe de classes, et ne compare jamais
deux groupes. `nms_class_groups` (dans `counting/application/ports.py`, le contrat
publié que l'adaptateur peut lire) partitionne les classes demandées, et un
`DetectionPredictor` dérivé appelle `non_max_suppression` **une fois par groupe**.

### Le groupe est la catégorie, et surtout pas `class_group`

Les deux tables existent, elles se ressemblent, et les confondre est le piège de ce
correctif — un test verrouille l'écart. Elles répondent à deux questions distinctes :

| | question | moto vs camion |
|---|---|---|
| `class_group` (ADR 0056) | cet objet peut-il être **à l'intérieur** de l'autre en restant distinct ? | **séparés** — une moto devant un camion est contenue à 1,0 |
| `nms_class_groups` (ici) | ces deux boîtes, qui **coïncident**, décrivent-elles le même objet ? | **ensemble** — deux boîtes de véhicule à IoU > 0,45 ont la même taille et la même place |

La moto **devant** le camion n'atteint jamais IoU 0,45 : les tailles sont trop
différentes. C'est précisément ce qui rend les deux réponses différentes sans qu'aucune
des deux soit fausse.

La seule classe dont la boîte coïncide légitimement avec celle d'un **autre** objet est
`person` — un pilote occupe la boîte de sa machine. La partition est donc la
**catégorie** (`vehicle` / `person`), qui existait déjà : aucune table nouvelle.

**Conséquence décisive** : le jeu de classes par défaut (`car`, `motorcycle`, `bus`,
`truck`) est entièrement `vehicle`, donc **une seule partie, donc un seul appel au NMS,
donc le chemin d'aujourd'hui au bit près**. Un test compare les tenseurs de sortie et
exige `torch.equal`. Aucune analyse existante ne change de chiffre.

Une première version de ce correctif utilisait `class_group` et découpait donc le
défaut en deux parties. Elle a été rejetée par ses propres tests.

## Les pièges de l'implémentation

Trois, et chacun rendrait le correctif faux ou inerte **en silence**.

### 1. Le prédicteur n'est construit qu'une fois — et le préchauffage gagne la course

`engine/model.py` :

```python
if not self.predictor or self.predictor.args.device != args.get("device", ...):
    self.predictor = (predictor or self._smart_load("predictor"))(...)
```

Or `ModelRegistry.warmup()` appelle `model.predict()` au démarrage, et le registre
garde ses instances chargées d'un job à l'autre. Le prédicteur **par défaut** est donc
en place avant le premier `track()`, et l'argument `predictor=` est ignoré pour toute
la vie du processus.

C'est le mode de panne d'ADR 0035, en pire : là-bas la première analyse après un
démarrage obéissait, ici **aucune** ne l'aurait fait. Le correctif aurait été livré,
testé, documenté, et entièrement inopérant.

`install_group_aware_nms` échange donc la **classe de l'instance** déjà construite.
Les deux mécanismes sont nécessaires et aucun ne suffit : `predictor=` couvre le
déploiement sans préchauffage, l'échange couvre le cas normal. Un test l'exige aux deux
sites d'appel — le direct partage l'instance résidente avec le différé.

**Ne pas « simplifier » en posant `model.predictor = None`** : `track()` ferait
`hasattr(self.predictor, "trackers")` → faux → `register_tracker` une seconde fois, et
`model.callbacks` empile. Un `on_predict_postprocess_end` en double appelle
`tracker.update()` **deux fois par image** : des chiffres plausibles et complètement
faux. Même raison que la note de `reset_trackers`.

### 2. `non_max_suppression` convertit les boîtes en place

```python
prediction = prediction.transpose(-1, -2)          # une VUE
prediction[..., :4] = xywh2xyxy(prediction[..., :4])
```

Le tenseur de l'appelant est modifié. Un second appel sur le même tenseur
reconvertirait des xyxy en xyxy : des boîtes plausibles et fausses, sans la moindre
erreur. Chaque groupe reçoit donc un `clone`, et un test vérifie l'invariance de
l'entrée.

### 3. La fusion doit être triée par score

Concaténer les groupes rend un ordre par blocs, là où `torchvision.ops.nms` rend
toujours un ordre décroissant. C'est aussi ce qui rend la troncature à `max_det`
honnête : elle doit couper les scores les plus bas, pas le dernier groupe de la liste.

## L'ordre importe : cette ADR ne rend rien sans ADR 0056

Un pilote qui survit désormais au NMS était **réeffacé** par `_drop_contained`, à
containment 1,000. Livrer ce correctif seul n'aurait produit aucune boîte de plus, et
aurait fait conclure que la piste du NMS était morte.

L'inverse est également vrai à un degré moindre : ADR 0056 seule ne rend le pilote que
lorsque le NMS ne l'a pas déjà supprimé.

## `multi_label` est une impasse, et la question est close

ADR 0037 laissait `multi_label=True` en « à mesurer », comme remède au fait que
`nms.py:126 conf, j = cls.max(1, keepdim=True)` jette l'évidence `motorcycle 0.48`
d'une ancre dont le top-1 est `person 0.55`. Deux faits ferment la question :

- **inatteignable** : `DetectionPredictor.postprocess` passe cinq arguments
  positionnels puis cinq nommés à `non_max_suppression`, et `multi_label` n'y figure
  pas ; la clé n'existe pas dans `cfg/default.yaml`, et
  `get_cfg(overrides={'multi_label': True})` lève `SyntaxError` ;
- **inutile telle quelle** : les deux lignes issues d'une même ancre portent la
  **même** boîte, donc IoU 1,0. Dans le même groupe elles se suppriment, ce qui est
  correct — un objet est d'une classe ou d'une autre. Elle ne rendrait quelque chose
  que dans des groupes différents, c'est-à-dire pour publier un piéton fantôme à la
  boîte de chaque moto, ce qui gonflerait `by_class["person"]`.

## Conséquences

- **aucun chiffre ne change sur le jeu de classes par défaut**, vérifié sur la sortie
  du NMS elle-même ;
- **le coût est un appel de NMS par groupe**, donc au plus deux, et seulement pour qui
  coche « Personne ». Le NMS est très en dessous de l'inférence dans le budget
  (`pipeline_bench.py`) ;
- **le piège 5 est intégralement préservé**, y compris quand « Personne » est cochée :
  `car` et `truck` restent dans le même groupe. C'est ce qui distingue ce correctif
  d'un simple `agnostic_nms=False`, qui aurait rouvert la panne de la camionnette pour
  cette sélection ;
- **une tête `end2end` délègue au parent** : `non_max_suppression` sort en tête de
  fonction pour ces modèles, il n'y a rien à découper.

## Comment le vérifier

```bash
cd backend && uv run pytest tests/unit/models_registry/test_nms_par_famille.py tests/unit/counting/test_nms_class_groups.py -q
```

Ces tests font tourner la **vraie** fonction d'Ultralytics sur des tenseurs fabriqués :
pas de poids, pas de GPU, pas de vidéo, verdict déterministe. Ils portent leur propre
témoin — le comportement d'avant est exécuté à côté de la correction, pour que l'écart
se lise.

Contre le vrai serveur, le jour où du métrage avec des motards existera : deux analyses
du même clip, `classIds=[3]` puis `[0,3]`. Aujourd'hui la seconde rend **moins** de
motos que la première ; après ce correctif elles doivent rendre le même nombre.

## Alternatives écartées

- **`agnostic_nms` conditionnel** (`False` dès que `person` est cochée) — deux lignes,
  aucun prédicteur à injecter, mais rouvre le piège 5 pour cette sélection : une
  camionnette scorée `car` et `truck` redeviendrait deux véhicules et deux
  franchissements. Un test montre l'écart entre les deux approches ;
- **monkeypatcher `ultralytics.utils.nms.non_max_suppression`** — fonctionnerait
  (`detect/predict.py` résout l'attribut à l'appel), mais agirait aussi sur le
  détecteur de plaques, qui partage la fonction ;
- **remapper la colonne de classe sur un identifiant de groupe avant l'appel** —
  impossible : la colonne de classe n'existe qu'*à l'intérieur* de
  `non_max_suppression`, après l'argmax. Avant l'appel, il n'y a que `nc` colonnes de
  scores.
