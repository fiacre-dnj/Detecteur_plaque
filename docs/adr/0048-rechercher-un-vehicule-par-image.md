# ADR 0048 — Rechercher un véhicule par image de requête

- **Statut** : accepté
- **Date** : 2026-08-28
- **N'abroge pas** [ADR 0016](0016-compter-les-objets-suivis.md), et c'est le point
  central de cette décision : cette ADR-là a fermé la porte à *l'apparence branchée sur
  le compteur*, pas à l'apparence. Une recherche est un index de consultation ; elle
  n'entre dans aucun total.
- **Déroge partiellement à** [ADR
  0041](0041-les-alertes-se-calculent-cote-client.md) : le *score* est calculé au
  serveur, le *seuil* reste au client. La dérogation et sa limite sont motivées plus bas.
- **S'appuie sur** [ADR 0042](0042-une-capture-par-vehicule.md) pour sa règle monotone et
  [ADR 0039](0039-ne-pas-payer-pour-une-plaque-prouvee-illisible.md) pour son plancher.

## Contexte

Un article Ultralytics affirme que YOLO11 « gère la ré-identification ». Il dit en fait
l'inverse — « les modèles Ultralytics YOLO ne réalisent pas eux-mêmes la
ré-identification » — et décrit un pipeline où YOLO détecte et suit tandis qu'un réseau
séparé compare les apparences. La ré-identification d'apparence **interne au tracker**
est par ailleurs déjà active dans ce projet depuis toujours, et [ADR
0047](0047-la-reid-d-apparence-n-est-gratuite-que-sur-une-tete-avec-nms.md) vient d'en
chiffrer le coût réel.

Elle ne peut pas servir de recherche, et pour deux raisons mesurables :

- **elle est verrouillée derrière l'IoU.** Dans `BOTSORT.get_dists`,
  `emb_dists[dists_mask] = 1.0` annule la distance d'apparence dès que le
  recouvrement tombe sous `proximity_thresh` (0,5). L'apparence ne peut donc rapprocher
  que des boîtes qui se chevauchent déjà — utile contre une occlusion courte, inutilisable
  pour comparer une photo importée à un véhicule quelconque de la vidéo ;
- **son descripteur n'est pas un descripteur d'identité.** Avec `model: auto`,
  l'« embedding » est une tranche moyennée des cartes d'entrée de la tête `Detect`
  (`min(canaux P3, P4, P5)`, de l'ordre de 64 dimensions au palier nano) : des
  caractéristiques de *détection*, entraînées à répondre « est-ce une voiture, où sont ses
  bords ».

La demande est donc une fonctionnalité neuve : importer une photo de véhicule, la cadrer,
lancer l'analyse, et obtenir les véhicules ressemblants avec un score.

## Le modèle

`vehicle-reid-0001` de l'Open Model Zoo, récupéré par `scripts/fetch_reid_model.py`.

| | |
|---|---|
| Architecture | OSNet-**AIN** (`osnet_ain_x1_0_vehicle_reid.onnx`) |
| Entrée | `1×3×208×208` annoncée ; le graphe réel est **entièrement dynamique** |
| Sortie | 512 flottants, comparaison par distance cosinus |
| Taille | 8 836 743 octets, 2,18 MParams, 2,64 GFLOPs |
| Précision publiée | **Rank-1 96,31 % / mAP 85,15 %** sur VeRi-776 |
| Licence | MIT (Kaiyang Zhou, `deep-person-reid`) |

À comparer aux références académiques du même jeu : FastREID 81,9 mAP / 97,0 rank-1,
TransREID 82,3 / 97,1, pour des modèles bien plus lourds.

L'empreinte SHA-384 publiée dans le `model.yml` de l'OMZ a été vérifiée avant de retenir
le SHA-256 que `.env.example` documente. **CPU seulement** : `onnxruntime` n'a pas de
provider CUDA ici (vérifié : `['AzureExecutionProvider', 'CPUExecutionProvider']`),
comme pour l'OCR.

## Ce que la mesure a dit, et où elle a contredit l'intuition

`scripts/reid_bench.py` — un banc nouveau, pour la raison qui a fait naître
`anpr_bench.py` : ADR 0008 a démontré une fois que l'intuition se trompe ici.

**Il ne lit pas les captures déjà sur disque**, contrairement à ce que le plan
prévoyait : ADR 0042 n'écrit qu'**une** capture par véhicule, donc
`data/jobs/*/snapshots/` ne contient aucune paire même-véhicule — précisément ce qu'il
faut mesurer. Le banc extrait ses propres recadrages en faisant tourner le vrai moteur et
garde plusieurs vues **de la même piste** à des instants différents.

### 1. Le prétraitement n'a aucun effet, et ce n'est pas un hasard

Le README de l'OMZ ne documente ni moyenne ni écart-type. Cela ressemblait au piège du
dictionnaire décalé d'ADR 0007 — un prétraitement faux ne lève rien, il rend des
embeddings plausibles et dégradés. Mesuré sur 12 vraies vignettes :

| comparaison | cosinus |
|---|---|
| `x/255` contre `(x/255 − mean)/std` (ImageNet) | **1,0** |
| `x/255` contre `x` (facteur 255) | **1,0** |
| RGB contre BGR | **0,508** au minimum, 0,714 en moyenne |

La normalisation d'intensité est donc **sans effet**, pour une raison architecturale : le
« AIN » d'OSNet-AIN est de l'*Adaptive Instance Normalization*, qui normalise par canal et
par échantillon sur les dimensions spatiales — le réseau est invariant à toute
transformation affine par canal de son entrée. C'est pourquoi l'OMZ n'en documente pas :
il n'en a pas besoin. L'adaptateur n'en applique donc aucune ; une arithmétique dont on a
**prouvé** qu'elle ne change rien est du code mort qui prétend compter.

L'**ordre des canaux**, lui, décide tout, et c'est le seul réglage de cet étage. Écart
same/diff : **+0,694 en RGB contre +0,642 en BGR**.

### 2. L'encodeur sépare — mais les distributions se recouvrent

Sur une vue de circulation 720p réelle, 14 pistes, 53 vues :

| | valeur |
|---|---|
| similarité moyenne, **même** véhicule | **+0,816** |
| similarité minimale, même véhicule | **+0,387** |
| similarité moyenne, véhicules **différents** | **+0,249** |
| similarité **maximale**, véhicules différents | **+0,891** |
| rang-1 (le plus proche voisin est-il le bon ?) | **100 %** |

**Les deux chiffres qui commandent tout le reste sont les deux extrêmes** :
`sameMin` = 0,387 est *inférieur* à `diffMax` = 0,891. Aucun seuil global n'est donc à la
fois sûr et utile. C'est la mesure qui interdit de présenter un verdict et qui impose
une **liste classée de candidats à vérifier** — la même honnêteté que « correspondance
probable » pour les plaques (ADR 0029) et que les quasi-franchissements.

Contrôle en conditions réelles, chaîne complète : la même vignette encodée par les deux
chemins — `embed_query` sur les octets, `embed` sur une boîte — rend **1,0000**, ce qui
prouve que les deux côtés de la comparaison cadrent identiquement ; un autre véhicule
rend **0,1770**.

### 3. Le plancher de largeur est un garde de coût, pas une falaise

Échelle de vérité terrain, **vivier commun** de 14 vues / 4 pistes nativement ≥ 208 px,
chaque palier notant exactement les mêmes vues :

| largeur | écart same − diff | `diffMean` | rang-1 |
|---|---|---|---|
| 208 px | **+0,462** | 0,243 | 100 % |
| 160 px | +0,434 | 0,278 | 92,9 % |
| 128 px | +0,399 | 0,301 | 92,9 % |
| 96 px | +0,366 | 0,334 | 85,7 % |
| 64 px | +0,361 | 0,367 | 92,9 % |
| 48 px | **+0,310** | 0,384 | 92,9 % |

La séparation décroît **de façon monotone** (−33 % de 208 à 48 px) et `diffMean` monte
régulièrement : deux véhicules différents se ressemblent de plus en plus à mesure que la
définition tombe. Le rang-1 est bruité — 14 vues, donc un point vaut 7,1 % — et il ne
faut pas y lire de tendance.

**Il n'y a pas de falaise**, contrairement à l'OCR qui passe de 7/8 à 0/8 entre 64 et
48 px (invariant 12). `reid_min_vehicle_width_px = 96` est donc un arbitrage de **coût** :
on n'encode pas ce qui rapporte peu, on ne refuse pas ce qui serait faux. La distinction
compte pour qui voudra le régler.

Une première version du banc était fautive sur ce point et vaut d'être notée : elle
laissait chaque palier noter une population différente (4 pistes à 160 px, 9 à 48 px) et
présentait le tout comme une progression. Deux tâches de difficultés différentes lues
comme une dégradation de l'encodeur.

**Ce que ce banc ne mesure pas** : le cas inter-caméra. Toutes ses vues viennent d'une
même vidéo, donc d'un même point de vue, alors qu'une photo importée vient d'ailleurs.
Ses chiffres sont une **borne haute** — même précaution que l'échelle synthétique
d'ADR 0029, qui rend des plaques trop propres.

## Décision

### Une passe d'apparence, indépendante de l'ANPR, sous règle monotone

Un port `VehicleEmbedder` dans `counting/application/ports.py` ; un adaptateur
`OnnxVehicleEmbedder` dans `counting/infrastructure/` — et non dans
`models_registry/infrastructure/` comme les étages de plaques, parce qu'il a besoin de la
définition partagée de « la vignette d'un véhicule » et qu'il n'importe pas `ultralytics`.

La passe s'insère entre `session.feed()` et le snapshot de timeline, **hors** de la garde
`if detector is not None` : un utilisateur qui cherche une voiture n'a aucune raison
d'activer la lecture de plaques.

### La clé monotone est la largeur de boîte, et non « largeur × netteté »

C'est le point de conception le moins évident, et la première version s'y est cassée.

Le patron d'ADR 0042 veut deux appels séparés : `should_embed` demande « est-ce que ça
vaut une inférence » **avant** toute dépense, `record_embedding` n'enregistre qu'après
succès. Pour que la première question ait un sens, sa clé doit être évaluable **sans
pixels** — or la netteté demande un recadrage.

La première version classait sur largeur × netteté et interrogeait donc le pré-filtre
avec `0.0`, faute de mieux. Conséquence : dès qu'un véhicule était encodé une fois,
`0.0 > qualité` était faux et il ne pouvait **plus jamais** être réencodé. La propriété
« elle suspend, elle n'abandonne pas » que le code annonçait était fausse — un véhicule vu
de loin gardait à jamais l'embedding le plus flou de sa vie, l'exact contraire du but.
`test_une_meilleure_vue_remplace_la_precedente` l'a trouvée.

Le rang se joue donc sur la **largeur de la boîte**, que le domaine connaît seul, et la
netteté reste un **plancher** dans l'adaptateur. `VehicleAppearance` a perdu son champ
`quality` au passage : un champ dont personne ne décide rien est un champ de trop.

### Le score au serveur, le seuil au client

C'est la dérogation à ADR 0041, et elle est bornée. Ce que cette ADR protégeait
réellement — pouvoir corriger la règle sans réanalyser — est **préservé** : le serveur
publie `matchScore` brut dans `VehicleRecord`, et le curseur de ressemblance vit côté
client. Le baisser fait apparaître des candidats sans relancer quoi que ce soit.

L'alternative — transporter les 512 flottants et comparer au navigateur — respectait ADR
0041 à la lettre pour **~2 ko par véhicule** dans un aperçu republié chaque seconde et
dont ADR 0026 documente qu'il « grossit avec l'analyse à ~350 octets par véhicule ». On
l'aurait multiplié par six.

`shared/lib/vehicleMatch.ts` est le seul juge du seuil côté client — trois features en ont
besoin (le tiroir de recherche, les alertes, la colonne du registre), et une feature
n'importe jamais une autre. Même raison qui a fait naître `shared/lib/directions.ts`.

### L'image de requête ne touche jamais le disque

Une troisième partie multipart sur `POST /jobs`, lue **en mémoire**, bornée par
`max_query_image_kb` (2 Mio), et qui n'entre **pas** dans `config_json` : elle n'est donc
ni persistée ni relue à la réouverture du job. Même doctrine que `plateWatchlist` côté
client, appliquée à une donnée plus sensible encore. Un dépassement de taille **refuse le
job** plutôt que d'ignorer l'image — une recherche silencieusement abandonnée afficherait
« aucune correspondance » pour une analyse qui n'a rien cherché.

Le **cadrage se fait côté client**, avant l'envoi. Trois bénéfices d'un seul geste : on ne
transporte que la vignette, le serveur ne voit ni l'arrière-plan ni les passants, et
surtout les deux côtés de la comparaison convergent — le serveur encode les véhicules
depuis la vignette de `vehicle_crop` (boîte plus 6 % de marge), donc la requête doit lui
ressembler. Une photo pleine mettrait la voiture sur un tiers de l'entrée du réseau là où
la galerie la met sur la totalité, et la similarité deviendrait sans rapport avec la
ressemblance réelle.

Sur « ajouter le tracker de YOLO à l'image importée », qui était demandé : un tracker suit
dans le *temps*, et une image fixe n'en a pas. Ce qu'il faut est une **détection** — mais
elle n'est pas nécessaire, le cadrage manuel jouant le même rôle pour un coût nul.

## Vérification

- `1621 passed, 1 skipped` côté backend (+21), `851 pass` côté frontend (+19).
- **La non-régression est un test, pas une intention** : `TestAucuneRegression` compare
  `crossings`, `tracked_vehicles`, `crossed_unique`, `by_class`, les totaux par ligne
  **et les horodatages de franchissement** sur le même clip, avec et sans encodeur.
- `FakeVehicleEmbedder.vectors_produced` compte les vecteurs réellement produits — c'est
  ce chiffre, et non le registre, qui prouve que la règle monotone protège le chemin
  critique. Même raison d'être que le comptage d'appels d'ADR 0042.
- Contre le vrai encodeur : `available: True`, `probe: True`, requête 512-d de norme
  1,0000, même véhicule **1,0000** par les deux chemins de recadrage, autre véhicule
  **0,1770**, et un trou positionnel là où la boîte est trop étroite.
- Pipeline complet sur 900 images : 8 véhicules suivis, **2 encodés** — les six autres
  sous le plancher de 96 px, ce qui est le comportement voulu et chiffre l'économie.

## Un contrôle annoncé et inerte, trouvé en vérifiant

L'adaptateur refusait un modèle dont la sortie n'aurait pas 512 dimensions, en lisant
`session.get_outputs()[0].shape[-1]` au chargement. Ce graphe déclare sa sortie
`['batch_size', 'dim']` : `shape[-1]` rend la **chaîne** `"dim"`, donc
`isinstance(dim, int)` était toujours faux et la garde ne se déclenchait **jamais** — sur
le seul modèle qu'elle avait à surveiller. Le journal de démarrage l'a révélé en
affichant `dimension=dim`.

Le contrôle est déplacé dans `_infer`, où la sortie est concrète, et il rend la session
inutilisable pour de bon plutôt que de réessayer à chaque véhicule. Vérifié en chargeant
volontairement le modèle d'OCR à sa place : `probe()` rend `False`, `embed` ne rend que
des trous, `reidLoadable` passerait à `false`.

C'est la même leçon qu'ADR 0016 énonce sur les réglages : un contrôle annoncé et sans
effet est pire que pas de contrôle.

## Conséquences

- **Un artefact optionnel de plus.** Sans `vehicle-reid.onnx`, `reidAvailable` est faux,
  le tiroir « Recherche » n'est pas monté, et pas un compteur ne change. Trois états pour
  `reidLoadable` comme pour les plaques : `null` n'est pas un échec.
- **Le registre gagne une colonne « Ressemblance »**, décidée sur le registre entier et
  jamais sur les rangées rendues — une colonne qui apparaîtrait au défilement décalerait
  toutes les autres sous le curseur, même règle que « Capture ».
- **Deux natures d'alerte** (`vehicle-exact`, `vehicle-partial`) dans une table
  exhaustive, donc c'est la compilation qui signale un oubli. Leur clé ne porte **ni
  instant ni score** : un véhicule ressemblant est un *état*, et une clé datée
  produirait une carte par aperçu SSE.
- **`alertsArmed` gagne un troisième terme.** La règle « rien ne s'affiche tant que rien
  n'est cherché » reste vraie.
- **Le seuil survit à `resetForNewSource`, la photo non.** Le premier est une préférence
  de lecture ; la seconde décrit une recherche en cours.
- Ce que cette fonctionnalité ne promet pas : un verdict. La mesure interdit de le
  promettre, et l'écran le dit — « à vérifier sur la capture ».
