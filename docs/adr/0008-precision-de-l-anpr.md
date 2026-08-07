# ADR 0008 — La précision de l'ANPR se joue au filtre géométrique, pas au modèle

- **Statut** : accepté
- **Date** : 2026-08-06
- **Amende** : [ADR 0007](0007-lecture-du-texte-de-plaque.md)

## Contexte

[ADR 0007](0007-lecture-du-texte-de-plaque.md) a fait lire le texte des plaques. Il
mesurait sa justesse sur **dix plaques synthétiques** (9/10, confiance 0,97) et son
coût sur trente images, faute de mieux : le dépôt ne contenait aucune vidéo où une
plaque soit lisible.

La demande était d'améliorer « considérablement » le détecteur, quitte à changer de
modèle. La première chose à faire était donc de **mesurer sur du réel**. Dix-huit
vidéos de circulation ont servi de banc ; trois d'entre elles portent des plaques
exploitables.

Ce qui en est ressorti n'était pas ce qu'on cherchait, et c'est le cœur de cette ADR.

### Ce que la mesure a montré

Sur **538 détections** issues de circulation réelle, la chaîne d'origine — toutes les
boîtes au-dessus du seuil, aucun filtre — rendait :

- **426 vraies plaques**, occupant 11 à 25 % de la largeur de leur véhicule ;
- **112 fausses**, occupant 98 à 100 % de cette largeur : la boîte du véhicule
  entier, une paire de phares, un bloc de feux arrière. Certaines à **0,87 de
  confiance**, c'est-à-dire au-dessus de tout seuil qu'un utilisateur poserait.

Ces 112 boîtes étaient dessinées à l'écran **et** envoyées à l'OCR. Sur un
sous-ensemble de 52, l'OCR y a lu deux fois `ERVICE` — le lettrage de carrosserie
d'un utilitaire, publié comme une plaque.

**Aucun réglage de confiance ne pouvait les écarter** : elles scoraient plus haut que
de vraies plaques. Le seul signal qui les sépare est géométrique, et il est net.

## Décision

### 1. Un filtre de plausibilité géométrique, et c'est lui l'amélioration

Une boîte n'est la plaque de ce véhicule que si elle est plus large que haute
(1,1 à 9,0), occupe entre 3 et 90 % de la largeur du véhicule, moins de la moitié de
sa hauteur, et a son centre sous les 12 % supérieurs. Chaque borne est volontairement
large : on écarte l'absurde, pas l'inhabituel — les plaques de moto (~1,4:1) passent.

**Un filtre ne peut que retirer des détections.** À modèle inchangé il ne peut donc
pas dégrader le rappel des boîtes correctes. Sur les 538 détections mesurées, la
séparation est parfaite : les 426 gardées sont toutes des plaques, les 112 jetées n'en
sont aucune.

S'y ajoute **une plaque par véhicule** (`max_per_vehicle`, réglable). Le `max_det` par
défaut d'Ultralytics vaut 300 : un seul véhicule pouvait porter des dizaines de
rectangles, et chacun partait en OCR.

### 2. Changer de modèle n'était pas le levier

Le `.onnx` en place est un YOLO à classe unique, entraîné le 2026-08-02, exporté en
`1×3×640×640` **statique**. Il localise correctement ; ce qui manquait n'était pas sa
qualité mais le tri de sa sortie. Un modèle plus récent aurait produit les mêmes
fausses détections de calandre — c'est un mode d'erreur de la tâche, pas du modèle.

L'export est figé : sa grille d'ancres (8400) est une constante. Vérifié par chirurgie
de graphe — rendre le lot ou la résolution dynamiques fait échouer le `Reshape` du DFL
(`{1,64,2100}` contre `{1,4,16,8400}` attendu). Ni résolution adaptative ni lot
possibles sans ré-export, et le `.pt` d'origine n'est pas dans le dépôt.

### 3. La mosaïque existe, et elle est **désactivée par défaut**

Puisque l'entrée est figée, la seule façon d'amortir l'inférence est d'empaqueter
plusieurs recadrages de véhicules dans une même image de 640×640, chacun dans sa
cellule, séparés par une gouttière neutre.

L'intuition qui la justifiait — « un recadrage de 200 px agrandi à 640 ne gagne aucune
information, donc l'empaqueter ne coûte rien » — est **fausse**, et c'est la mesure qui
l'a dit. Ce qui décide qu'une plaque est trouvée n'est pas le facteur d'agrandissement
mais la taille de la plaque **dans l'entrée du réseau**, et elle ne dépend que de la
cellule :

    plaque_dans_le_réseau ≈ 0,15 × côté_de_cellule

Sur 657 véhicules de vraie circulation, à 8,2 véhicules par image :

| côté | cellule | ms/image | rappel |
|------|---------|----------|--------|
| 1    | 616 px  | 760      | 100 %  |
| 2    | 302 px  | 221      | 84 %   |
| 3    | 197 px  | 116      | 56 %   |

Le défaut est **1**. On ne troque pas de la justesse contre du débit sans que
quelqu'un le demande, et la demande était de la précision. `2` reste l'échange
raisonnable quand le débit prime : 3,4× pour 16 % de détections en moins, largement
absorbées par le vote qui agrège plusieurs images du même véhicule. Un test épingle ce
défaut pour qu'un futur réglage de performance ne le fasse pas glisser sans refaire la
mesure.

### 4. `plate_confidence` cesse d'être mort

ADR 0007 le laissait « mort et sciemment » : annoncé dans l'API, ignoré par le
service. C'est le pire état d'un réglage — l'utilisateur le déplace, les chiffres ne
bougent pas, et il conclut que la détection est mauvaise. Il descend désormais jusqu'à
l'adaptateur en argument de `detect_many`, et un test l'affirme.

Il reste le **seul** réglage de plaques qui voyage par requête : il répond à une
question que seul l'utilisateur peut trancher devant sa vidéo. Les seuils d'OCR sont
des arbitrages de déploiement et restent dans `Settings`.

### 5. L'alphabet de l'OCR est lu dans le modèle

PaddlePaddle grave la liste des caractères dans le `.onnx` sous la clé `character`.
C'est la seule source qui ne puisse pas se désynchroniser des poids : elle voyage avec
eux. Le fichier de dictionnaire reste exigé — `plateOcrAvailable` en dépend, et un
opérateur doit pouvoir *voir* l'alphabet — mais il devient une seconde opinion, pas
l'autorité. Quand les deux divergent, on le journalise et on suit le modèle.

C'est la réponse structurelle au mode de panne que l'« effet de bord » d'ADR 0007
raconte : un dictionnaire décalé ne lève rien, il produit des plaques fausses et
parfaitement plausibles.

### 6. Le vote tranche désormais caractère par caractère

ADR 0007 refusait de publier un quasi-ex æquo : `AB123CD` et `AB123CO` à confiance
voisine sont « un tirage au sort, et publier un tirage au sort est le pire résultat
possible ». Le raisonnement vaut **entre deux chaînes**. Il ne vaut pas position par
position : six des sept caractères sont unanimes, et jeter cette unanimité pour cause
de désaccord sur le septième revient à jeter la quasi-totalité de ce qui a été mesuré.

Le vote enregistre donc chaque lecture deux fois — comme chaîne entière, et position
par position, pondérée par la confiance que le modèle a donnée à **chaque caractère**.
Quand la voie par chaîne refuse, le consensus tranche la case litigieuse.

Deux gardes le rendent sûr, et elles sont le cœur de la décision :

- **le consensus ne publie que du déjà-lu.** Une chaîne reconstruite qui n'a jamais
  été lue par personne est refusée. Sans cette garde, deux lectures franchement
  différentes de même longueur produiraient une chimère, et publier une plaque que le
  modèle n'a jamais lue est pire que se taire ;
- **les positions sont groupées par longueur.** Comparer la position 4 de `AB123CD` à
  celle de `AB1234CD` ne veut rien dire.

Cela **ne lève pas** l'interdiction de substituer les glyphes ambigus (O↔0, I↔1) : le
consensus marginalise sur plusieurs lectures réelles, il n'invente aucun caractère à
partir d'un format national supposé. Cette interdiction tient.

### 7. Prétraitement d'OCR : variantes et largeur négociée

Chaque plaque produit une à trois variantes — chaîne d'origine, redressée si un angle
exploitable est mesuré, cadre rogné — toutes envoyées dans le **même** lot. Le
décodage départage à confiance **cumulée** : entre trois caractères à 0,99 et sept à
0,85, la moyenne préfère la première alors qu'elle a manqué quatre glyphes ; la somme
préfère celle qui a lu le plus, aussi sûrement, sans qu'on ait à inventer un facteur
de longueur.

La largeur du tenseur est négociée avec le lot au lieu des 320 px de PP-OCR. Une
plaque européenne (4,7:1) tient en 226 px : calculer 320 colonnes revient à payer 40 %
de convolutions pour du remplissage. Dans l'autre sens, une plaque plus large que
6,7:1 était **comprimée** à 320 ; le graphe accepte plus large, on le lui donne.

## Alternatives écartées

**Télécharger un détecteur plus récent.** Écarté après mesure : le modèle en place
localise correctement, et ses fausses détections sont un mode d'erreur de la tâche que
partagerait n'importe quel détecteur de plaques à classe unique. Introduire des poids
neufs aurait ajouté un artefact à valider pour corriger un défaut qui n'était pas dans
les poids. La porte reste ouverte — le script de récupération et les réglages d'URL
existent déjà.

**Réécrire l'inférence en onnxruntime direct**, pour contourner Ultralytics. Mesuré
avant d'écrire : 75,6 ms via Ultralytics contre 74,0 ms en onnxruntime direct sur le
même recadrage. Le surcoût du wrapper est de 2 %, l'inférence *est* le coût. La
réécriture aurait remplacé un letterbox et une NMS éprouvés par les nôtres pour rien.

**Empaqueter par défaut.** Écarté par la mesure du rappel (§3).

**Laisser toutes les boîtes et filtrer côté interface.** Le filtre appartient à
l'adaptateur : les boîtes non filtrées partent aussi en OCR, et le fil publierait des
rectangles que le canvas devrait apprendre à ignorer.

## Conséquences

- La colonne « Plaque » du registre ne peut plus se remplir avec du lettrage de
  carrosserie. En contrepartie, un véhicule dont la seule détection est une fausse
  n'affiche plus **rien** — ce qui est l'information juste.
- Le seuil `plateConfidence` fait maintenant quelque chose. Son infobulle le dit :
  seule la meilleure plaque de chaque véhicule est retenue, donc monter le seuil en
  garde **moins**, pas de plus précises.
- Le contrat publié ne change pas. Les confiances par caractère sont **de passage** :
  `record_plates` les consomme pour le vote puis les jette avant de ranger la
  détection dans la piste. Elles ne figurent ni dans la timeline ni sur le fil — une
  information utile pendant trois lignes n'a pas à peser sur chaque image d'un clip de
  trente minutes.
- `plate_iou`, `plate_max_per_vehicle`, `plate_mosaic_side`, `plate_ocr_variants` et
  `plate_ocr_dynamic_width` s'ajoutent aux réglages.
- Le frontend n'a pas bougé, sauf deux textes d'infobulle. Ses 444 tests passent sans
  modification, ce qui est la preuve que le contrat a tenu.

## Mesures relevées

Machine sans GPU, `TRAFFIC_HALF=false`. Mesures **CPU**, à lire comme telles.

### Le tri des détections

538 détections, circulation réelle, quatre vidéos :

| | avant | après |
|---|---|---|
| Boîtes rendues | 538 | 426 |
| Dont véhicule entier | 112 (21 %) | **0** |
| Score max d'une fausse | 0,87 | — |
| Textes publiés depuis une fausse | `ERVICE` ×2 | 0 |

### La chaîne d'OCR, sur vérité terrain connue

Huit plaques rendues puis dégradées (réduction, flou, bruit, JPEG q70, inclinaison).

Plaque nette à 320 px : **8/8 exactes**, confiance 0,995 (chaîne d'origine) et 0,998
(variantes + largeur négociée). La chaîne est donc juste — ce que les mesures d'ADR
0007 laissaient supposer sans le prouver hors du synthétique.

**Plancher de résolution**, mesuré :

| largeur de plaque | px/caractère | avant | après |
|---|---|---|---|
| 320–160 px | 46–23 | 8/8 | 8/8 |
| 128 px | 18 | 6/8 | 7/8 |
| 96 px | 14 | 7/8 | 7/8 |
| 80 px | 11 | 3/8 | 4/8 |
| 64 px | 9 | 1/8 | 2/8 |
| 48 px | 7 | 0/8 | 0/8 |

Les variantes gagnent un cas sur trois paliers, n'en perdent aucun, et remontent la
confiance de ~0,005 partout. Le gain est **réel et modeste** ; il se concentre là où
la lecture est marginale, ce qui est l'endroit où il sert.

### Le coût de la lecture

Largeur négociée contre 320 px figés, sur 33 vraies vignettes : **27,2 ms → 14,8 ms
par vignette**, soit 1,8×, à lecture identique.

## Ce que la mesure n'a pas pu établir

**Aucune plaque des vidéos disponibles n'est lisible par l'OCR, et ce n'est pas un
défaut de la chaîne.** Elles font 27 à 88 px de large — 4 à 12 px par caractère —
c'est-à-dire sous le plancher mesuré ci-dessus. Les deux configurations y lisent du
bruit (`PEYAS`, `HRTE`, `TiNgy`), et **les deux le refusent** : le plancher de
confiance et la longueur minimale de `normalise_plate_text` font que rien n'est
publié. C'est le comportement voulu — se taire plutôt qu'inventer — mais cela signifie
que le gain des variantes n'a pu être mesuré que sur du rendu dégradé, pas sur du réel.

Il faudrait, pour aller plus loin, une vidéo où les plaques dépassent ~150 px : plan
plus serré, capteur plus défini, ou caméra dédiée. C'est la limite honnête de ce lot,
et elle porte sur la **lecture** seule — le tri des détections, lui, est mesuré sur du
réel.
