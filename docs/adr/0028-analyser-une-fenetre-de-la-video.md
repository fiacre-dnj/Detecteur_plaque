# ADR 0028 — Analyser une fenêtre de la vidéo, pas toujours le fichier entier

- **Statut** : accepté
- **Date** : 2026-08-17
- **Complète** : [ADR 0017](0017-brider-l-analyse-sur-le-temps-de-la-scene.md) et
  [ADR 0020](0020-un-plafond-absolu-de-cadence.md) — trois façons de dépenser moins
  de temps sur une analyse, mais celle-ci change **ce qui est compté**, pas la
  vitesse à laquelle on le compte. Ne pas les confondre : brider ralentit une
  analyse complète, borner en analyse une portion.

## Contexte

« Lancer l'analyse serveur » posait une question à laquelle il répondait tout seul :
**toujours depuis le début, toujours jusqu'à la fin**. Or on n'arrive presque jamais
sur ce bouton par hasard. Le parcours réel est : importer la vidéo, la faire défiler
jusqu'au moment qui pose problème — l'heure de pointe, l'incident, le créneau qu'on
veut chiffrer —, tracer ses lignes là-dessus, puis lancer. À ce moment précis, la
tête de lecture est à 00:34 et l'utilisateur veut compter à partir de là.

Repartir de zéro coûte alors deux choses, et la seconde est la plus chère :

- **du calcul** : les minutes qui précèdent sont détectées, suivies, et jetées ;
- **du temps d'attente**, et il est directement visible. Avec le bridage par défaut
  (`analysisSpeed: 1`, ADR 0019), une analyse dure **exactement la durée de la
  vidéo**. Analyser cinq minutes utiles d'un fichier d'une heure prend donc une
  heure, pour cinq minutes de résultat.

S'y ajoute un besoin distinct, qui ne se règle pas par un simple décalage du début :
**chiffrer un créneau**. « Combien de véhicules entre 7 h 30 et 8 h 00 » demande deux
bornes, et découper une longue vidéo en tranches comparables en demande deux à chaque
fois.

## Décision

`AnalysisRequest` gagne **deux champs**, `startMs` et `endMs`, en millisecondes de
temps de scène. `0` et `null` sont les défauts et **sont exactement le comportement
d'avant** : qui ne touche à rien retrouve ses chiffres.

Côté écran, le bouton **ouvre une modale** au lieu d'analyser :

- **Toute la vidéo** ;
- **À partir d'où j'en suis** — la position de lecture devient le début ;
- **Entre deux moments précis** — deux champs `mm:ss`, plus deux poignées
  glissables **dessinées sur le lecteur**, alignées sur la barre de position ;
- **Annuler**.

Cinq points portent tout le reste, et chacun ferme une façon de mentir sans lever.

### 1. Les horodatages restent absolus

Une analyse lancée à 00:34 date son premier franchissement à **00:34**, jamais à
00:00. Décaler à zéro paraîtrait plus « logique » à la lecture du code, et casserait
deux choses d'un coup : la vidéo locale se cale sur le temps de scène de l'aperçu
(elle sauterait au mauvais endroit pendant toute l'analyse), et deux analyses de
fenêtres différentes du même clip cesseraient d'être comparables.

C'est aussi ce qui rend la fenêtre **purement soustractive** : elle ne fabrique
aucune donnée, elle en retire.

### 2. La borne de fin est **exclue**

`[0 ; 1000[` puis `[1000 ; 2000[` ne partagent aucune image. Incluse, l'image de
1000 ms tomberait dans les deux fenêtres, et qui découpe une longue vidéo en tranches
compterait deux fois ce qui s'y passe — le genre d'erreur qui ne se voit qu'en
additionnant les tranches et en comparant au total.

### 3. La fenêtre est tranchée par l'**application**, jamais par l'adaptateur

`AnalysisService` filtre sur les horodatages qu'un moteur rapporte. `EngineSpec`
porte bien un `start_ms`, mais c'est **un indice de performance** : un moteur qui
l'ignore — le `FakeEngine` de la CI — produit exactement les mêmes chiffres,
simplement plus lentement.

Cette asymétrie est délibérée et elle a un historique dans ce dépôt. `CLAUDE.md`
rappelle que l'architecture a déjà laissé passer deux bugs à travers 500 tests verts
« parce que le moteur factice ne les atteint jamais ». Une fenêtre implémentée dans
l'adaptateur seul aurait été le troisième exemplaire : la CI n'aurait vérifié aucune
de ses bornes.

### 4. Le déplacement, lui, **doit** vivre dans l'adaptateur — et vérifier où il tombe

Sans lui, la fenêtre ne ferait économiser que la fin. `LoadImagesAndVideos`
d'Ultralytics **ne sait pas se déplacer** : il ouvre à zéro et avance (vérifié dans
la roue installée — aucun `CAP_PROP_POS_FRAMES` dans le chargeur). Analyser à partir
de la cinquantième minute d'un fichier d'une heure aurait donc coûté cinquante
minutes d'inférence sur des images jetées, avec une barre de progression qui avance
sans rien produire.

`iter_video` a donc **un second chemin**, emprunté seulement quand un début est
demandé : OpenCV décode après déplacement et confie les images une par une au modèle,
exactement comme le fait déjà le temps réel. Les arguments de `model.track()` sont
identiques à ceux de l'autre chemin — `test_engine_arguments.py` le vérifie sur la
source, et c'est lui qui a signalé l'apparition du troisième appel.

Le déplacement se fait en **deux temps**, et le second n'est pas une précaution de
style : `CAP_PROP_POS_FRAMES` est approximatif sur plusieurs conteneurs (FFmpeg se
pose sur l'image-clé précédente, certains démultiplexeurs dépassent). On lit donc la
position réellement atteinte, on repart de zéro si elle a dépassé, puis on avance par
`grab()` — qui démultiplexe sans convertir, donc quelques dizaines d'images de
rattrapage coûtent bien moins qu'une seule inférence. Accepter le déplacement sans
vérifier aurait donné des `frame_index` faux, donc des horodatages faux, donc des
vitesses et des franchissements datés à côté — sans aucune exception.

### 5. Une fenêtre vide est **refusée**, pas rendue en compteurs à zéro

Deux refus, à deux endroits, parce qu'ils ne savent pas la même chose :

- le **schéma de requête** refuse une fin qui ne suit pas le début. Il ne peut pas
  faire mieux : il ne connaît pas la durée du fichier ;
- `AnalysisService` refuse, **après avoir sondé la vidéo**, une fenêtre qui ne
  contient aucune image — une borne posée au-delà de la fin, un chiffre tapé deux
  fois. Le message donne la durée réelle et les deux bornes ; le code est
  `empty_analysis_range`, et il traverse jusqu'à l'écran (ADR 0011).

Sans le second, le job serait « terminé » et parfaitement vide, indiscernable d'une
panne de détection — et l'utilisateur chercherait le défaut dans sa vidéo ou son
modèle.

## Conséquences

- **La barre de progression compte les images de la fenêtre.** `_expected_frames`
  convertit les bornes en ordinaux par la cadence. Sans cela, une analyse bornée à un
  dixième d'un fichier s'arrêterait à 10 % en annonçant « terminé », ce qui se lit
  comme une analyse tronquée.
- **L'intervalle n'est pas persisté**, contrairement aux autres réglages d'analyse.
  « De 00:34 à 05:00 » décrit *cette* vidéo ; relu au chargement suivant, il
  découperait un autre fichier au hasard. `resetForNewSource` le remet à neuf, comme
  la géométrie, qui est en pixels de la source.
- **Il vit dans `entities/analysis-range`** et non dans une feature : le lecteur le
  dessine, la modale le fait choisir, l'envoi le transporte, et une feature n'a pas le
  droit d'en importer une autre.
- **Le direct n'en a rien.** Un flux caméra n'a ni début ni fin à borner ; les deux
  champs voyagent quand même dans la requête, parce que le direct envoie
  *exactement* celle du différé — c'est ce partage qui garantit qu'un même tracé
  compte pareil dans les deux modes. Le rail est simplement masqué sur une caméra,
  plutôt qu'affiché inerte.
- **Les bornes ne rendent pas un résultat « périmé ».** `launchSignature` ne compare
  que la géométrie, et c'est assumé : un résultat obtenu sur une fenêtre reste juste
  pour cette fenêtre. Ce que l'écran garantit à la place, c'est que l'intervalle
  retenu est **rappelé sous le bouton de lancement** — un intervalle posé puis oublié
  ferait analyser un morceau qu'on croit entier, et les compteurs bas paraîtraient
  faux.
- **Un véhicule à cheval sur une borne est un véhicule tronqué.** Sa piste naît (ou
  meurt) à la coupe, et le suivi n'a rien d'avant. C'est le comportement attendu d'un
  découpage, mais il faut le savoir avant d'additionner deux tranches : la somme de
  `[A ; B[` et `[B ; C[` n'est pas exactement `[A ; C[`, pour les mêmes raisons qu'une
  occlusion longue donne un véhicule de plus (ADR 0016).

## Ce qui a été écarté

- **Un décalage des horodatages à zéro** — voir §1.
- **Filtrer dans l'adaptateur seul** — voir §3.
- **Sauter les images dans l'application sans déplacement** : correct, mais fait
  payer tout le début en inférence, ce qui vide la fonctionnalité de son intérêt
  principal.
- **Un intervalle exprimé en index d'images** : le navigateur n'expose **aucune
  cadence par fichier** (voir `ASSUMED_FPS` dans `video-transport`), donc l'écran
  n'aurait eu aucun moyen honnête de fabriquer un index.
- **Plusieurs intervalles disjoints en une analyse** : le suivi n'a pas de sens à
  travers une coupe, et le résultat porterait des trous que ni la relecture ni les
  vitesses ne sauraient interpréter. Découper en plusieurs jobs reste possible et dit
  ce qu'il fait.
