# ADR 0056 — La suppression des boîtes incluses effaçait les petits objets

- **Statut** : accepté
- **Date** : 2026-09-03
- **Complète** [ADR 0018](0018-une-bande-morte-autour-du-trait.md) et le piège 6 de
  [`prompt/13`](../../prompt/13-PIEGES-CONNUS.md), dont elle restaure le domaine de
  validité sans rien lui retirer.
- **Voisine d'**
  [ADR 0037](0037-le-plancher-du-detecteur-suit-le-curseur-quand-il-descend.md), qui
  traite le même symptôme utilisateur par une cause **distincte et cumulative**.

## Le symptôme

« On a du mal à détecter les motos et les personnes. »

Le même rapport qu'ADR 0037, un mois plus tard, après que son correctif a été livré.
Cette fois la cause n'est pas dans le détecteur : elle est dans notre domaine, et elle
est en aval du tracker.

## Ce que `_drop_contained` fait réellement

`tracking_session.py` supprime, **avant le suivi**, toute boîte dont 90 % de l'aire
tombe dans une autre. La mesure est `BoundingBox.containment`, c'est-à-dire
`intersection / min(aire)`.

Diviser par la **plus petite** aire est ce qui rend le critère utile pour le cas cible —
la cabine d'un semi-remorque, dont l'IoU avec le véhicule entier ne vaut que 0,3 — et
c'est aussi ce qui le rend **structurellement asymétrique** : un camion ne peut jamais
être contenu dans une moto, une moto l'est trivialement dans un camion.

La docstring donnait elle-même l'argument qui se retourne contre elle :

> Le seuil est sévère — 0,9 — et c'est délibéré. Le cas cible atteint 1,0, tandis
> qu'**une voiture** roulant devant un camion peut être à 0,8 dans la boîte du camion.

0,8 pour une voiture, oui. Mesuré en exécutant le vrai code du domaine :

| situation | containment | jeté |
|---|---|---|
| pilote dans la boîte de sa propre moto | **1,000** | `person` |
| piéton devant un bus | **1,000** | `person` |
| moto devant un camion | **1,000** | `motorcycle` |
| *témoin* — scooter, boîte moto = machine seule | 0,500 | rien |
| *témoin* — deux voitures côte à côte | 0,133 | rien |

Le seuil a été calibré sur la seule classe qui y échappe. Les deux classes citées par
l'utilisateur sont les plus petites du catalogue, donc celles que la mesure attrape le
plus facilement.

## Ce que cela coûte en bout de chaîne

Mesuré sur le domaine, moteur factice, déterministe :

- une moto suivie 5 images devant un camion rend `tracked_vehicles=1`,
  `tracked_by_class={'truck': 1}`, `high_detections=5`. Les cinq observations de la
  moto ne sont comptées **nulle part** ;
- une moto qui franchit une ligne à l'intérieur de la boîte d'un camion rend
  `crossings=0, by_class={}`, là où le témoin sans camion rend
  `crossings=1, by_class={'motorcycle': 1}` ;
- une moto immobile que le tracker n'a **jamais** perdue, englobée 3,3 s, ressort en
  **deux** véhicules : `[(1,'motorcycle'), (2,'truck'), (3,'motorcycle')]`. Le même
  mécanisme sous-compte *et* double-compte.

Fréquence sur les archives de ce dépôt — des clips qui ne contiennent **ni** moto **ni**
personne, donc une borne basse : job `dd263f4cb719431e8704738d1cc0f3f1`,
`containedOut = 1610` pour `highDetections + rescuedByLowScore = 18 044`, soit **8,2 %
de toutes les observations suivies effacées**. Job `74dfee38` : 28 sur 4 294, 0,65 %.

## Pourquoi personne ne l'a vu

`_drop_contained` tourne **avant** `_count_scores` :

```python
kept = self._mask(self._drop_contained(observations))
self._count_scores(kept)
```

Une observation supprimée n'est donc comptée dans aucun des six chiffres du tiroir
« Comptage ». Le seul témoin publié est `contained_out`, un scalaire **sans classe**,
affiché « Doublons inclus » sous une aide qui parle de « la cabine d'un semi-remorque ».
La phrase de conclusion du panneau énumère quatre causes de disparition et ne cite pas
celle-là.

Et le seul verrou de la suite était
`test_une_voiture_devant_un_camion_est_conservee`, construit à 0,8 **par choix des
coordonnées**. Aucun test n'avait jamais mis une boîte d'une autre classe entièrement
dans une autre.

## La décision

La suppression est bornée aux objets **physiquement exclusifs entre eux**. Trois
groupes, `class_group` dans `counting/domain/models.py` :

```
{person} · {bicycle, motorcycle} · {car, bus, truck, train}
```

`_drop_contained` teste le groupe **avant** la géométrie : que deux objets puissent être
le même objet physique ne dépend pas de l'endroit où ils se trouvent.

Quatre points qui ne se devinent pas :

- **la garde porte sur le GROUPE et jamais sur l'égalité de label.** Le détecteur ne
  nomme pas toujours la cabine comme le semi : une garde écrite
  `first.label != second.label` rouvrirait exactement le piège 6 que ce correctif est
  censé préserver — cabine `car` dans un semi `truck`, deux pistes, deux véhicules, deux
  franchissements. Un test le verrouille ;
- **trois groupes et pas deux.** `CountCategory` range déjà les objets en
  `vehicle` / `person`, et ne peut pas répondre : elle met `bicycle` et `motorcycle`
  avec les voitures. Or un scooter sort régulièrement sous l'une ou l'autre des deux
  classes de deux-roues — c'est un vrai doublon, à dédupliquer — mais il n'est pas un
  doublon de la voiture derrière lui. Les deux tables restent séparées, parce que
  « comment ranger pour l'affichage » et « ces deux boîtes sont-elles le même objet »
  n'ont aucune raison d'évoluer ensemble ;
- **le repli d'un label inconnu est `motor_vehicle`**, donc le comportement d'avant les
  groupes. Un label hors COCO vient d'un modèle qui nomme une voiture autrement ; lui
  donner un groupe à part lui retirerait la déduplication du piège 6 en silence, et
  sous-compter est l'erreur la plus difficile à remarquer. Deux boîtes de **même** label
  tombent de toute façon dans le même groupe quelle que soit la table : le cas cible est
  protégé par construction, jamais par le contenu du dictionnaire ;
- **ce correctif est nécessaire mais pas suffisant, et l'ordre importe.** Un pilote qui
  survit à `agnostic_nms` — son IoU réaliste avec la boîte de sa moto vaut 0,407, sous le
  seuil de 0,45 — était **réeffacé ici** à containment 1,000. Corriger le NMS sans
  corriger la containment n'aurait rien rendu du tout, et aurait fait conclure que la
  piste du NMS était morte.

## Ce que la garde ne protège pas

Deux objets de la même famille, et c'est assumé : un enfant marchant contre un adulte
est à 1,0 (mesuré), une voiture entièrement dans la boîte d'un bus aussi. Ce dernier cas
existait déjà avant ce correctif et n'est pas aggravé.

Le traiter demanderait un critère de plausibilité — la cabine partage un bord de la
boîte du semi, la moto au milieu du camion non — à mesurer, jamais à adopter en défaut.

## Conséquences

- **les comptages changent, par construction et dans un seul sens** : plus d'objets
  survivent au filtre, donc plus de pistes et potentiellement plus de franchissements.
  Sur une sélection de classes qui ne contient que des véhicules à moteur
  (`[2, 5, 7]` et le défaut moins la moto), le comportement est **strictement
  inchangé** — tous ces labels sont du même groupe ;
- **le coût est en aval** : les boîtes rendues au tracker alimentent l'étage d'apparence
  de BoT-SORT, qui encode par recadrage et par image
  ([ADR 0047](0047-la-reid-d-apparence-n-est-gratuite-que-sur-une-tete-avec-nms.md)),
  sur une carte déjà à p50 50 %. À mesurer sur une scène dense ;
- **le diagnostic reste anonyme**, et c'est la suite due. `contained_out` devrait être
  publié **par paire de classes** (clé `motorcycle←truck`), sur le patron de
  `near_misses` : une suppression anonyme est aussi opaque que le doublon qu'elle évite.
  Sans lui, la chute du scalaire est la seule façon de vérifier ce correctif.

## Comment le vérifier

Le rappel est déterministe : une course par branche suffit, les 11 % de bruit de cette
machine ne s'y appliquent pas.

```bash
cd backend && uv run pytest tests/unit/counting/test_containment.py -q
```

Contre le vrai serveur, sur un clip contenant réellement des motards : deux analyses
identiques avant/après, en comparant `stats.byClass['motorcycle']`,
`stats.byClass['person']`, `trackedVehicles` et surtout `diagnostics.containedOut`, qui
doit **chuter**. `scripts/audit_lignes.py <job_id> --json` doit continuer à sortir en 0.

Sans nouveau métrage, `scripts/recall_bench.py --inventory` dit d'abord si le clip
contient seulement les classes en question — les six clips de `data/jobs/` n'en
contiennent aucune.

## Alternatives écartées

- **descendre `CONTAINMENT_THRESHOLD`** — le seuil n'est pas en cause : les trois cas
  mesurés valent 1,000, donc aucun seuil inférieur à 1 ne les épargne. Le monter au-delà
  de 1 désactiverait le filtre entièrement et rouvrirait le piège 6 ;
- **supprimer `_drop_contained`** — c'est le piège 6, un bug déjà payé ;
- **comparer les labels plutôt que les groupes** — rouvre le piège 6 sur la cabine `car`
  dans un semi `truck`, exactement le cas que le filtre existe pour attraper.
