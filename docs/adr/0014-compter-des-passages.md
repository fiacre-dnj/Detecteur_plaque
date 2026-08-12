# ADR 0014 — Compter des passages, compter les personnes, et choisir ce qu'on compte

- **Statut** : accepté
- **Date** : 2026-08-12
- **Abroge** : [ADR 0009](0009-un-comptage-par-vehicule.md) comme comportement par
  défaut, et l'invariant 6 de `CLAUDE.md`

## Contexte

Trois demandes produit arrivées ensemble, et elles se tiennent :

1. la **ré-identification sort du périmètre** — elle n'est pas dans le PoC ;
2. les **humains** doivent être détectés et comptés, **à part** des véhicules ;
3. l'utilisateur doit pouvoir **choisir les classes** à détecter et à compter.

La première est un changement de ce que les chiffres veulent dire, pas une
simplification technique. Elle mérite donc d'être écrite avant d'être faite.

## Décision 1 — On compte des passages, plus des véhicules

`SessionConfig.dedupe_by_identity` vaut **`False`**. Chaque franchissement observé
compte.

**Ce que cela change, concrètement**, et il faut le savoir avant de lire un
tableau :

| scène | sous ADR 0009 | désormais |
|---|---|---|
| un véhicule fait un aller-retour | 1 | **2** |
| une boîte vacille sur la ligne | 1 | **2** |
| deux lignes en travers de la même voie | 1 | **2** |
| une occlusion longue coupe la piste en deux | 1 | **2** |

Aucune de ces lignes n'est un bug : ce sont bien deux franchissements observés à
chaque fois. Mais quiconque trace deux lignes pour *situer* un passage doit savoir
qu'il en compte deux — c'est la conséquence la plus facile à subir sans l'avoir
voulue.

**Le garde n'est pas effacé, il est débranché.** `dedupe_by_identity=True` le
rallume, et `TestDeduplication` comme `TestReArmementParReidentification` le testent
toujours. La raison est simple : un mécanisme conservé mais non testé est un
mécanisme cassé, et effacer 1 500 lignes de domaine pour les regretter après le PoC
serait plus coûteux qu'un drapeau.

**Ce qui reste de la ré-identification, et pourquoi.** La galerie continue de
tourner — elle coûte 0,6 ms par image, mesuré ([ADR 0013](0013-le-cout-du-pipeline-de-comptage.md)) —
parce qu'elle rend deux services qui n'ont rien à voir avec la déduplication :

- le **vote de classe** : `identity_label` stabilise le libellé d'un véhicule qui
  oscille entre `car` et `truck` d'une image à l'autre. Sans lui, le même véhicule
  compterait dans deux catégories selon l'image où il franchit ;
- le **vote de texte de plaque**, qui est l'invariant 4 et n'est pas en cause ici.

## Décision 2 — Les personnes ont leur propre total, jamais mélangé

`AnalysisStats.by_category` ventile les franchissements en `vehicle` et `person`.

C'est une **propriété dérivée** de `by_class`, pas un champ. Stocker cette
ventilation à côté créerait un second compteur du même fait, et deux compteurs du
même fait finissent toujours par se contredire — c'est l'invariant 3, celui qui a
déjà coûté un bug ici. Dérivée, sa somme **est** `crossings` par construction.

Les personnes franchissent les mêmes lignes et entrent dans les mêmes zones que
les véhicules : c'est la mécanique existante, et la seule chose qui change est
qu'un total affiché ne mélange jamais les deux catégories.

## Décision 3 — Les classes sont choisies par requête, dans un catalogue publié

`AnalysisJobConfig.class_ids` voyage **par requête**, contrairement aux réglages de
débit du moteur : c'est une question que seul l'utilisateur peut trancher devant sa
scène — compte-t-on les piétons de ce carrefour, les vélos de cette piste ?

Le catalogue cochable est servi par `GET /api/v1/models/classes` — **publié, et non
recopié dans l'interface**. Cela ferme la panne la plus bête de ce genre de
fonctionnalité : une case cochable dans le navigateur que le serveur refuse à
l'envoi, ou l'inverse, une classe détectable que personne ne peut cocher.

Le défaut reste **les quatre véhicules** : qui ne touche à rien obtient ce que
l'application faisait avant.

Deux refus au démarrage de la requête, tous deux pour éviter un compteur à zéro qui
se lirait comme une panne :

- une **classe hors catalogue** est refusée avec la liste de ce qui existe. Passée
  telle quelle à `classes=` d'Ultralytics, elle ne détecterait jamais rien, sans
  erreur ni journal ;
- une **liste vide** est refusée : `classes=[]` n'est pas un filtre vide côté
  Ultralytics, il rendrait les 80 classes de COCO — donc des feux et des panneaux
  comptés comme des véhicules.

## Ce que nous ne savons pas détecter, et il faut le dire

**La charrette a été demandée. Elle n'est pas livrable en cochant une case.** Les
modèles du catalogue sont tous entraînés sur COCO, qui ne contient aucune classe de
charrette, de pousse-pousse ni de tuk-tuk. Écrire la ligne dans le catalogue
donnerait une case qui ne détecte jamais rien — exactement le mode de panne que la
validation ci-dessus existe pour empêcher.

Deux voies existent, et aucune n'est un réglage :

- **vocabulaire ouvert** : `ultralytics` embarque YOLO-World et YOLOE, qui
  détectent sur description textuelle. À tester sur de vraies images de charrettes
  avant toute promesse — ces modèles sont plus lourds, et leur justesse sur ce sujet
  précis est inconnue. C'est une mesure au banc, pas une intuition ;
- **entraînement dédié** : collecte et annotation d'images locales, puis
  entraînement. Le seul chemin qui garantisse le résultat, et de loin le plus long.

## Conséquences

- **`unique_vehicles` reste calculé mais ne décrit plus ce que l'écran compte.**
  L'interface doit afficher des **passages**, et présenter les uniques comme ce
  qu'ils sont devenus : une information de suivi, pas le total.
- **Les chiffres d'avant et d'après ne sont pas comparables.** Un même clip rendra
  davantage de franchissements. Ce n'est pas une régression de justesse, c'est un
  changement d'unité — et un résultat archivé avant cette date se lit sous
  ADR 0009.
- L'invariant 6 de `CLAUDE.md` (« un véhicule compte une fois, la ré-identification
  ré-arme ») est abrogé et remplacé par sa lecture inverse. Les invariants 3 et 4
  ne bougent pas.
- Chaque classe cochée en plus coûte du post-traitement et peut introduire des
  pistes indésirables dans une scène chargée. C'est pourquoi le défaut reste étroit.
