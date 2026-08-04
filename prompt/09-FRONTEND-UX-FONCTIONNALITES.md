# 09 — Frontend : écrans, composants, interactions

Toute la copie d'interface est **en français**. Les libellés donnés ici sont
normatifs : ce sont ceux qui ont été validés à l'usage.

## 1. Coquille et navigation

`AppShell` : une entête compacte (titre « Comptage de véhicules », sous-titre
« Détection, suivi, ré-identification et franchissement de lignes »), le badge
d'état du backend, et trois liens : **Studio** (`/`), **Historique**
(`/historique`), **Benchmark** (`/benchmark`). Thème sombre
(`bg-slate-950 text-slate-200`), largeur max 1600 px.

Le badge backend affiche :
- joignable : `● Serveur prêt · CUDA` (ou `· CPU`), infobulle avec la version
  d'Ultralytics et les modèles résidents ;
- injoignable : `● Serveur injoignable` en ambre, avec l'action « Réessayer », et
  **tous les boutons d'analyse désactivés** avec une infobulle qui explique.
  Aucune page blanche, aucune erreur console.

## 2. Studio (`/`) — l'écran principal

Disposition : `grid xl:grid-cols-[minmax(0,1fr)_20rem]` — la scène à gauche, le
panneau de réglages à droite ; les résultats en pleine largeur en dessous.

### 2.1 Sélecteur de source
Trois cartes : **Fichier vidéo**, **Vidéo de démonstration**, **Caméra**.
- Le dépôt accepte le glisser-déposer et le clic. Il **dit** que la vidéo est
  envoyée au serveur pour analyse.
- La vidéo de démo est servie depuis `public/demo/traffic.mp4` ; si elle est
  absente, message explicite indiquant le chemin où la déposer — pas un échec
  silencieux.
- La caméra demande `getUserMedia({ video: { width: 1280, height: 720 } })`.
  Refus ⇒ message clair. Le passage à la caméra charge paresseusement la feature
  temps réel.

Changer de source : arrête tout, remet les compteurs à zéro, efface la
géométrie, libère l'URL `blob:` précédente.

> **Piège webcam à reproduire** : tant que `video.srcObject` est posé, la
> spécification impose d'ignorer `video.src`. Sans `srcObject = null` à l'arrêt du
> flux, **le fichier suivant ne se charge jamais**, sans même un événement
> `error`.

### 2.2 Scène
- `<video muted playsInline preload="metadata">`, **sans `loop`** : un clip qui
  repart en silence donnerait les mêmes véhicules à compter une seconde fois.
- Un `<canvas>` en superposition absolue (`GeometryCanvas`).
- Un HUD discret en coin : cadence, latence, « Uniques : N ».
- `onLoadedMetadata` fixe `size = { videoWidth, videoHeight }` et **amorce une
  première ligne horizontale** dans le tiers inférieur si aucune n'existe : un
  écran sans ligne ne compte rien et l'utilisateur ne sait pas pourquoi.

### 2.3 Barre d'actions
- **Différé** : « Lancer l'analyse serveur » (désactivé sans ligne **ni** zone,
  avec infobulle « Ajoutez d'abord une ligne de comptage »), pendant l'analyse :
  barre de progression + « Annuler ».
- **Temps réel** (caméra) : « Démarrer le comptage » / « Pause ».
- « Réinitialiser » (compteurs et résultat, garde la source et la géométrie),
  « Fermer » (tout).
- **Avertissement « résultat obsolète »** : si la géométrie a changé depuis
  l'analyse, un bandeau ambre l'annonce et invite à relancer. Implémenté par une
  **signature de géométrie** (`ax,ay,bx,by,zoneId` par ligne ; sommets par zone)
  comparée à celle enregistrée au lancement.
- **Bandeau de fin** : « Analyse terminée — la vidéo a été lue en intégralité.
  Les statistiques ci-dessous sont figées. » + bouton « Revoir la vidéo » dont
  l'infobulle précise que les compteurs ne repartent pas de zéro.

### 2.4 Éditeur de géométrie (canvas)
Tout est stocké en **pixels source** et converti au dessin (`sx = rect.width /
sourceWidth × dpr`) : la géométrie reste ancrée à la scène quand le lecteur est
redimensionné, et les mathématiques ne dépendent jamais de la mise en page CSS.
Un `ResizeObserver` sur la vidéo redessine.

Dessin, dans cet ordre (l'ordre est le contrat visuel) :
1. **Zone masquée** : un seul chemin couvrant l'image avec les zones
   « percées », rempli en règle **even-odd** (`rgba(2,6,23,0.62)`). L'utilisateur
   voit exactement ce que le détecteur reçoit.
2. Zones (remplissage `color+"1f"`, contour, sommets, étiquette).
3. Trajectoires (couleur de classe à 53 % d'opacité).
4. Boîtes : couleur par **classe votée** (`identityLabel || label`) — une lecture
   qui vacille ne doit pas faire clignoter la couleur ; **pointillés** si
   `hits < minHits` ; centroïde ; badge
   `#globalId label [↻n] [✓|…]`.
5. Lignes de comptage (trait, poignées A/B, étiquette).
6. Polygone en cours de tracé (pointillés + sommets + segment vers le curseur).

Interactions :
- **Glisser** une ligne par son corps ou une poignée ; une zone par son corps ou
  un sommet. Décalage de préhension conservé (rien ne saute au curseur).
  Coordonnées bornées à l'image.
- **Test de sélection** : les lignes gagnent sur les zones (elles sont dessus),
  et à égalité de type le plus récemment ajouté gagne. Rayon de sélection
  exprimé en pixels **écran** puis converti en pixels source, pour que la
  précision de clic ne dépende pas de la taille d'affichage.
- **Tracé de zone** : un clic par sommet, fermeture par double-clic **ou** par
  clic sur le premier sommet (les deux gestes existent parce que les gens
  attendent l'un ou l'autre), `Échap` annule. Le brouillon vit dans un **ref**
  (source de vérité) doublé d'un state pour le rendu : un double-clic livre deux
  `pointerdown` **et** le `dblclick` dans un seul rendu, donc lire le brouillon
  depuis le state lirait une liste périmée. Un clic sur le dernier sommet est
  ignoré (sinon le double-clic laisse une arête de longueur nulle).
- `touch-none`, `setPointerCapture` : le glisser fonctionne au doigt et ne se
  perd pas en sortant du canvas.

### 2.5 Panneau « Géométrie »
Liste des lignes et des zones : couleur, nom **renommable**, sélection,
suppression, et pour chaque ligne un sélecteur « zone : toute l'image / <zone> ».
Bouton « Ajouter une ligne », bascule « Dessiner une zone ».
Boutons « Enregistrer comme preset » / « Charger un preset » (modale paresseuse).
Un preset enregistré pour une autre résolution propose une mise à l'échelle
proportionnelle, en le disant.

### 2.6 Panneau latéral — trois sections repliables

**Détection**
- `ModelPicker` : liste groupée par palier avec entêtes **collantes**, navigation
  clavier (les flèches parcourent la liste **à plat**, les groupes sont purement
  visuels), affichage par modèle : libellé, taille, note, et trois états —
  *au catalogue* / *téléchargé* / *résident*. Un modèle non téléchargé affiche
  « premier usage : téléchargement ~N Mo ».
- Slider **Confiance véhicules** + bouton **« Défaut »** : la valeur est
  `number | null` ; `null` suit le défaut du modèle sélectionné, une valeur
  explicite survit au changement de modèle. Le bouton est le chemin de retour —
  avant lui, c'était le seul réglage sans réinitialisation.
- Bascule **« Lire les plaques (ANPR) »** avec l'infobulle qui dit le coût
  (« recadre chaque véhicule suivi et y cherche une plaque — nettement plus
  lent »), désactivée si le serveur signale le modèle de plaques absent.
- Slider **Confiance plaques**, visible seulement si l'ANPR est actif.

**Comptage** (tous ces réglages sont envoyés au serveur avec la requête)
- `minHits` (images avant qu'une piste puisse compter),
- `maxLostMs` (survie d'une piste sans détection),
- `reidMinSimilarity` (similarité d'apparence pour retrouver une identité),
- seuil IoU,
- et le **diagnostic live** : détections retenues, pistes confirmées /
  provisoires, détections masquées par zone. Ce panneau n'est pas décoratif :
  « le compte est faux » n'est diagnosticable que si l'on peut voir si un
  véhicule manquant n'a jamais été détecté, l'a été faiblement, n'était pas
  confirmé, ou a été masqué par une zone.

**Affichage & analyse**
- Bascules « Trajectoires », « Ignorer hors zone » (désactivée sans zone, avec
  l'explication),
- Slider **« Pas d'analyse »** (1 → 5, affiché « toutes » / « 1 sur N ») avec
  l'infobulle : « Toutes » donne le comptage le plus fiable ; augmenter le pas
  accélère sur une machine sans GPU au prix de véhicules rapides manqués.
- Slider **« Échelle (px/m) »** (0 = non définie) : sans elle les vitesses restent
  en px/s plutôt que d'être converties à tort en km/h.

### 2.7 Lecteur maison (`video-transport`)
Lecture/pause, timeline avec position `mm:ss / mm:ss`, ±1 s, ±10 s, pas-à-pas
image (**met en pause d'abord**), vitesses `0,1 · 0,25 · 0,5 · 0,75 · 1 · 1,5 · 2`.

Deux comportements obligatoires :
1. **Réappliquer `playbackRate` sur `loadedmetadata`** : le navigateur le remet à
   1 à chaque nouvelle source.
2. **Masquer la timeline quand `duration` n'est pas fini** (caméra, clips issus
   de `MediaRecorder`).
L'état de lecture est **miroité localement** depuis les événements média, pour
que le défilement de la timeline ne re-rende jamais le studio (et avec lui le
canvas). L'événement `ended` doit être écouté : un clip qui se termine émet
`ended`, pas `pause`, et sans cela le bouton reste sur « Pause ».
Le pas-à-pas suppose 30 fps (le navigateur n'expose aucune cadence par fichier) ;
être légèrement à côté fait atterrir sur l'image voisine, ce qui est acceptable.

### 2.8 Relecture d'un résultat (`timeline-replay`)
- Recherche **binaire** de la frame dont l'horodatage ne dépasse pas la position
  de lecture (une timeline de 30 min à 30 fps compte 54 000 lignes, et la
  fonction est appelée à chaque rafraîchissement).
- Suivi par `requestAnimationFrame`, **pas** par `timeupdate` : cet événement ne
  se déclenche que ~4 fois par seconde, ce qui ferait visiblement traîner les
  boîtes derrière les véhicules.
- Les **trajectoires sont reconstituées côté client** depuis les ~24 frames
  précédentes : le serveur n'a pas à transporter un historique recalculable.
- **Les compteurs suivent la tête de lecture** : `statsAt(result, timeMs)`
  rejoue les événements jusqu'à `timeMs`. Reculer dans la vidéo doit faire
  **baisser** les chiffres — sinon l'image et les nombres racontent deux
  histoires différentes. L'occupation de zone est remise à zéro (c'est une
  lecture instantanée, pas un cumul).
- Un résultat fraîchement reçu s'affiche **avant** toute relecture : sans cela
  l'écran reste vide sur une analyse pourtant terminée.

### 2.9 Temps réel (caméra)
- Capture `canvas.toBlob("image/jpeg", 0.8)` réduite à **960 px** de large.
- **Une frame en vol à la fois** ; les frames produites pendant l'attente sont
  **abandonnées**, jamais mises en file (sinon la latence dérive sans se
  rattraper).
- La géométrie est **mise à l'échelle** du même facteur avant l'envoi
  (`scaleRequestGeometry`) et les boîtes reçues sont remises à l'échelle source.
  Une ligne non mise à l'échelle serait comptée 25 % à côté **sans aucune erreur
  visible** — le pire mode de défaillance possible ; un test unitaire couvre cette
  fonction.
- Perte de connexion : message explicite et arrêt propre ; pas de repli local
  (il n'y a plus de moteur local).

## 3. Résultats (sous la scène)

### 3.1 Cartes
« Véhicules uniques — tous types », « Franchissements de ligne »,
« Ré-identifications », « Débit estimé /min », « Objets suivis »,
« Cadence » (libellée **« Cadence (serveur) »** en différé : les deux chiffres
n'ont pas le même sens, la carte doit dire lequel elle montre).

### 3.2 Répartition par type
Une tuile par classe **que le modèle peut réellement émettre** (pas les 80
classes COCO) : icône, libellé FR, `N uniques · M passages`.
Texte explicatif : « Le type retenu pour un véhicule est celui que le détecteur
lui a donné le plus souvent, pas celui de la dernière image. »
Ligne de session : « X s d'analyse · Y s de flux analysé », avec « — débit
disponible après 3 s de flux » sous le seuil.

### 3.3 Détail par ligne
Une ligne par ligne de comptage : pastille de couleur, nom, portée
(« toute l'image » ou « zone : … »), répartition par classe, **`↑ p · ↓ n`**
(infobulle : « Passages par sens relatif au tracé A→B. Un aller-retour compte
une fois dans chaque sens. »), total.

### 3.4 Détail par zone
Nom, répartition par classe, **entrées uniques**, **présents**.

### 3.5 Histogramme de flux
Tranches adaptatives (paliers 1 s / 5 s / 15 s / 30 s / 1 min / 5 min / 10 min,
~12 barres visées) — sans quoi un clip de 30 s tiendrait dans une seule barre.
SVG maison, accessible (`role="img"` + `aria-label` résumant le maximum et la
tranche), chargé paresseusement.

### 3.6 Registre des véhicules
Colonnes : `#` (globalId), Type, « Vu de / à » (`mm:ss → mm:ss`),
« Lignes franchies » (puces avec flèche de sens et infobulle
« <ligne> à mm:ss, sens A→B »), Vitesse (`km/h` si échelle, sinon `px/s`, sinon
`—`), Ré-id (`↻ n`), Plaque (`NN %`).
12 lignes puis « Afficher les N véhicules restants » ; virtualisation au-delà de
200 lignes. Note de bas de tableau si aucune échelle n'est fournie.
Boutons **« Exporter CSV »** (registre / franchissements) et
**« Exporter JSON »**.

> Pourquoi ce tableau existe : les cartes disent *combien*, le registre dit
> *lesquels*. C'est ce qui rend un total **vérifiable** plutôt que croyable.

## 4. Historique (`/historique`)

Tableau paginé des analyses persistées : date, fichier, modèle, statut, durée,
uniques, franchissements, taille du résultat. Actions : **Ouvrir** (charge le
résultat dans le studio en relecture, en rechargeant aussi la géométrie depuis
`config_json`), **Relancer** (préremplit le studio avec la même configuration —
un nouveau job, jamais une mutation de l'ancien), **Supprimer**.
Filtres : statut, modèle. État vide explicite.

## 5. Benchmark (`/benchmark`)

- Bouton « Lancer le benchmark », choix des modèles (tous par défaut), nombre de
  runs, source d'image (exemple embarqué ou frame d'un job existant).
- Pendant l'exécution : modèle courant, progression, bouton « Annuler ».
- Tableau triable : modèle, palier, chargement (ms), inférence médiane (ms), p95,
  détections, erreur. Barres relatives pour comparer d'un coup d'œil.
- Rappel du contexte : device, version d'Ultralytics, date, hash d'image.
- **À l'ouverture, le dernier run est rechargé depuis la base** : pas d'écran
  vide alors qu'une mesure existe.
- Infobulle expliquant que chaque modèle est **libéré après mesure** (sinon la
  mémoire serait épuisée) et que le premier appel d'un modèle inclut son
  téléchargement.

## 6. États vides, chargements, erreurs — la règle

Chaque zone a **trois** rendus explicites :
1. **vide** : ce qu'il faut faire pour la remplir (« Choisissez une source »,
   « Ajoutez une ligne de comptage ») ;
2. **en cours** : squelette de la forme finale, pas un spinner centré ;
3. **erreur** : phrase française qui dit ce qui a échoué **et** l'action
   suivante, plus le `requestId` s'il existe.

Aucun message ne doit contenir de jargon non traduit, de trace de pile, ni un
statut HTTP nu.

## 7. Tests frontend attendus

`bun test` sur les modules purs — c'est là qu'est la logique testable :
- `geometry.ts` : `sideOfLine` (même signe que la convention backend),
  `pointInPolygon` (concave), `distanceToSegment` ;
- `replay.ts` : `frameIndexAt` (bornes, timeline vide, avant la première
  frame), `statsAt` (les compteurs augmentent avec le temps et **jamais**
  au-delà des totaux finaux), `toTrackedVehicles` (trajectoires reconstituées),
  `flowBuckets` (choix de palier, clip court, événement au dernier ms) ;
- `scaleRequestGeometry` : facteur 1 = identité, facteur 0,75 exact ;
- `format.ts` : `mm:ss`, nombres `fr-FR` ;
- `geometry reducer` : ajout/suppression de ligne, suppression d'une zone
  utilisée par une ligne (la ligne doit repasser à « toute l'image »),
  signature de géométrie stable et **différente** après déplacement ;
- persistance des préférences : lecture d'un schéma périmé ⇒ valeurs par défaut,
  jamais un plantage.

`@testing-library/react` sur trois composants critiques seulement : le
sélecteur de modèle (clavier), le lecteur (réapplication de la vitesse), la
frontière d'erreur. Tout ce qui exige un canvas réel, un GPU ou une caméra est
vérifié en lançant l'application — et documenté comme tel.
