# ADR 0051 — Une photo dès qu'il y a quelque chose à montrer

- **Statut** : accepté
- **Date** : 2026-08-31
- **Amende** : [ADR 0042](0042-une-capture-par-vehicule.md), sur sa décision « la
  meilleure **lecture**, et rien d'autre » ; et [ADR
  0046](0046-les-captures-s-ecrivent-pendant-l-analyse.md), sur sa conséquence « sans
  ANPR ni OCR, aucun véhicule ne porte de capture, donc aucune colonne ». Les deux
  règles dures d'ADR 0042 sont **conservées mot pour mot** : jamais depuis une boîte
  reprojetée, encodage à l'amélioration seulement.
- **S'appuie sur** : [ADR 0048](0048-rechercher-un-vehicule-par-image.md) (la
  recherche par image), [ADR 0041](0041-les-alertes-se-calculent-cote-client.md) (le
  seuil vit côté client).
- **Hérite de** : [ADR 0050](0050-la-regle-monotone-de-la-reid-ne-bornait-rien.md), et
  la leçon s'applique une seconde fois — voir « La marge » plus bas.

## Contexte

La capture existe parce que « le serveur se tait souvent sur une plaque, et la photo
est la seule chose qui permette de voir pourquoi » (ADR 0042). Elle était pourtant
**strictement conditionnée à un texte publié sur l'image courante** :
`_best_readable_plate` refusait toute boîte sans `text` ni `text_score`.

Les deux cas où cette photo sert le plus n'en avaient donc aucune.

**La recherche par véhicule par image (ADR 0048) n'avait rien à montrer.** L'écran
promet, mot pour mot, « Ressemble fortement à l'image recherchée — **à vérifier sur la
capture** », et la vignette du tiroir d'alertes pointait une adresse qui rendait 409
tant qu'aucune plaque n'avait été lue. Chercher un véhicule par sa photo n'oblige
personne à activer l'ANPR ; le score, lui, était déjà indépendant d'elle
(`_match_appearances` vit hors de la garde `if detector is not None`). C'est la photo
qui ne l'était pas.

**Une plaque localisée mais jamais lue n'avait pas de photo non plus**, et c'est le cas
**dominant** : sur une vue de circulation, les plaques mesurent 27 à 88 px pour un
plancher de lecture à ~64 (décision 24 de `CLAUDE.md`, `plate_unread_reason =
too_small`). Le registre disait déjà « vue à 48 px » ; il ne pouvait pas la montrer.
C'est exactement l'inverse du raisonnement d'ADR 0042 — là où le serveur refuse
d'affirmer, la photo est la seule information restante.

## Décision

Trois **causes** de capture, une échelle de priorité, **une seule photo par véhicule**.

| cause | quand | rang | marge |
|---|---|---|---|
| `plate_text` | une plaque a été **lue** sur cette image | confiance de lecture | `1.0`, imposé |
| `plate_box` | une plaque y a été **localisée**, aucun texte publié | largeur de la boîte de plaque | 1.15 |
| `appearance` | l'apparence du véhicule vient d'être **encodée** | largeur de la boîte du véhicule | 1.15 |

`plate_text` > `plate_box` > `appearance`. Un tier plus haut passe **toujours**, un
tier plus bas **jamais** ; à tier égal, la règle monotone d'ADR 0042 tranche.

### Le rang n'est comparable qu'à l'intérieur de son tier

C'est la seule subtilité du mécanisme. L'un des trois rangs est une probabilité, les
deux autres des pixels : les fondre en un nombre unique ferait perdre une plaque lue à
0,95 contre n'importe quelle boîte de 40 px, et **le chiffre resterait plausible**.
D'où la comparaison en deux temps de `should_capture`, cause d'abord.

### Capturer tout véhicule encodé, et non les seuls ressemblants

Le verdict « exacte / probable » n'existe pas au serveur : `matchStrength` vit dans
`shared/lib/vehicleMatch.ts` et se calcule contre un curseur que l'utilisateur déplace
**sans réanalyser** (ADR 0048, ADR 0041). Conditionner la photo à un seuil serveur la
rendrait absente exactement au moment où l'on descend le curseur pour la regarder.

Un véhicule dont `matchScore` est `null` — sous `reid_min_similarity` — a donc une
photo. Cela se lit comme une incohérence et n'en est pas une ; c'est le prix de la
propriété ci-dessus, et un test la nomme.

Le coût est borné par construction : on ne capture que les vues **réellement
encodées**, c'est-à-dire celles que les planchers de largeur et de netteté de
l'adaptateur viennent d'accepter. C'est exactement la barre qu'on veut pour une photo,
et elle est déjà payée.

### La marge — ADR 0050, une seconde fois

Une largeur croît de façon quasi monotone sur un véhicule qui approche, donc
« strictement plus large » est vrai à presque chaque image. C'est le défaut qu'ADR 0050
a payé sur l'encodage d'apparence, et il se rejouerait à l'identique sur la **largeur
de plaque** : l'étranglement du détecteur (une image sur trois) ne divise le problème
que par trois. Les deux tiers dont le rang est une largeur portent donc
`TRAFFIC_SNAPSHOT_WIDTH_IMPROVEMENT` (1,15), mesuré par un test : sans marge, dix
images analysées donnent dix encodages ; avec, au plus quelques-uns.

Sur `appearance`, la marge est déjà payée par `should_embed` **sur la même grandeur** —
elle est passée quand même, parce qu'un déploiement à
`TRAFFIC_REID_APPEARANCE_IMPROVEMENT=1.0` (valeur documentée comme légitime) ferait
sinon un JPEG par image et par véhicule, sans qu'aucun test ne le voie. Un couplage
invisible entre deux réglages est précisément le mode de panne d'ADR 0050.

Pas de marge sur `plate_text` : son rang est une confiance, il ne croît pas avec
l'approche, et une marge y affamerait la meilleure preuve pour rien.

### `snapshotScore` cesse d'être le drapeau de présence

Deux causes sur trois n'ont aucune lecture à publier. Le drapeau devient `snapshotMs`,
doublé de `snapshotKind` qui dit **pourquoi**. Dans l'autre sens la garantie tient, et
elle tient *par construction* : `record_snapshot` **dérive** `snapshot_score` de la
cause au lieu de l'accepter en paramètre, donc non-nul implique
`snapshotKind == "plate_text"`.

La relecture des archives est préservée : ADR 0042 posait score et instant ensemble,
donc `snapshotMs` non nul avec `snapshotKind` absent se lit « analyse antérieure, donc
`plate_text` de fait ». `snapshotHasPlateFace(undefined) === true` en découle, et c'est
le repli conservateur — répondre `false` cacherait la vignette de plaque de tous les
anciens résultats, une régression invisible puisque la modale serait simplement plus
courte.

### Une capture sans vignette de plaque

`VehicleSnapshot.plate_jpeg` devient `bytes | None`. Quand une boîte de plaque est
fournie et que son recadrage échoue, `encode` refuse la capture **entière** : dégrader
donnerait un `snapshotKind == "plate_text"` sans plaque à montrer, c'est-à-dire un
contrat qui se contredit.

La route `plate.jpg` ne gagne **aucun code d'erreur** : `snapshot_missing` couvre déjà
« il n'y a pas ce fichier », et le client sait par `snapshotKind` qu'il n'a pas à le
demander. Inventer un `plate_face_missing` ferait un code que personne ne branche.
Aucun `unlink` non plus : l'échelle étant monotone croissante, on ne redescend jamais
vers une capture sans plaque, donc aucun `-plate.jpg` ne devient orphelin.

### Deux causes, deux commutateurs

`TRAFFIC_SNAPSHOT_ON_PLATE_BOX` et `TRAFFIC_SNAPSHOT_ON_APPEARANCE`, à `true` par
défaut, **mais éteintes au niveau du service** : le constructeur d'`AnalysisService`
garde le régime d'ADR 0042 pour tout appelant qui ne demande rien, et c'est le
conteneur qui les allume. Deux bénéfices : un déploiement revient en arrière sans
toucher au code, et chaque test dit explicitement ce qu'il exerce.

Aucun seuil de **confiance** n'est ajouté. La capture continue d'hériter de ceux de
l'utilisateur — « Confiance plaques », « Confiance lecture » (ADR 0036) — et, sur le
tier apparence, des planchers `reid_min_vehicle_width_px` / `reid_min_sharpness`.

### Le plancher de recadrage refusait la capture entière — mesuré, pas déduit

C'est le seul défaut que la vérification contre le **vrai** moteur a trouvé, et il
aurait rendu ce lot inopérant dans son cas principal.

`vehicle_crop.MIN_CROP_SIDE_PX` vaut 16 px, parce que c'est le plancher d'une entrée de
réseau. Or une plaque localisée sur une vue de circulation réelle mesure **27 à 88 px
de large pour 9 à 28 px de haut** : `crop` rendait donc `None` sur la vignette de
plaque, et le refus étant total, **la photo du véhicule était perdue avec elle**. Rien
ne levait, rien n'était journalisé — mesuré sur une vraie course : 18 encodages
demandés, **zéro capture retenue**, avec des boîtes de 4,9 à 11 px.

Aucune doublure ne pouvait le voir : `FakeSnapshotEncoder` rend des octets quelconques
sans regarder une dimension. C'est le quatrième exemplaire du défaut que `CLAUDE.md`
décrit — vert en CI, faux en production.

`crop` accepte donc un `min_side`, et l'encodeur passe `MIN_PLATE_CROP_SIDE_PX = 8`
pour la face plaque. 8 et non 1 : en dessous il n'y a plus rien à agrandir, et une
« plaque » de 6×3 px est un artefact du détecteur — la refuser refuse la photo avec
elle, ce qui est le bon comportement puisqu'il n'y avait rien à montrer. Le plancher du
véhicule, lui, ne bouge pas.

### Mesuré, sur le vrai moteur

Vue de circulation 1080p, `yolov8n`, ANPR + OCR, fenêtre de 150 images :

| | avant | après |
|---|---|---|
| véhicules suivis | 11 | 11 |
| véhicules avec photo | 2 | **6** |
| encodages demandés | 2 | 7 |

Les quatre photos gagnées sont des véhicules `plate_unread_reason = too_small` — ceux
dont le registre disait « vue à 34 px » sans pouvoir la montrer. Et **la porte de
lisibilité d'ADR 0039 travaille pour nous** : elle divise les encodages par deux (7 au
lieu de 12 quand on la coupe) **sans coûter une seule photo**, la première détection
réelle d'une piste suffisant à la produire.

Sur le même clip avec une image de requête et sans aucune ANPR : 3 véhicules suivis,
**3 photos**, toutes sans vignette de plaque, 3 encodages. Avec les deux ensemble, les
deux véhicules dont la plaque est lue **remontent** de `appearance` à `plate_text` — la
priorité fonctionne — et le troisième garde sa photo de ressemblance, là où il n'en
avait aucune avant ce lot. Un de ces véhicules porte `matchScore = null` et une photo :
c'est la propriété voulue, pas une incohérence.

## Ce qui ne change pas

- **aucun chiffre publié.** Comptages, ventilations et horodatages sont identiques
  avec et sans capture, sur les trois causes ; deux tests le verrouillent, dont un
  dans `TestAucuneRegression` ;
- **rien ne transite par le SSE.** L'objection d'ADR 0042 tient : seule l'écriture
  disque avance, par le rappel `on_snapshot` d'ADR 0046 ;
- **jamais depuis une boîte reprojetée** (ADR 0010). Le filtre `not stale` est
  partagé par les deux tiers de plaque, et l'argument ne dépend pas de la lecture :
  une boîte reprojetée n'est pas une mesure de *cette* image ;
- **encodage à l'amélioration seulement**, cause et rang décidés **avant** de payer
  un encodage ;
- **les captures sont purgées avec la vidéo**, pas avec le résultat : ce sont des
  plaques et des visages ;
- **`?v=<snapshotMs>`** reste ce qui empêche `immutable` de figer une vignette pour un
  an.

## Conséquences

- **la colonne « Capture » du registre apparaît sans ANPR**, dès qu'une image de
  requête est fournie. La phrase d'ADR 0046 « sans ANPR ni OCR, aucune colonne — la
  condition est obtenue sans réglage » est donc **abrogée** ;
- **la borne mémoire devient atteignable**, et elle n'évince pas : au-delà de
  `TRAFFIC_SNAPSHOT_MAX_VEHICLES` (500), la première cause servie garde la place, donc
  un véhicule à plaque lue peut rester sans photo alors qu'un véhicule seulement
  ressemblant en occupe une. Une politique d'éviction serait une décision à part ; en
  attendant, la borne est réglable et le journal l'annonce **avec la cause** qui l'a
  heurtée ;
- **le débit d'écriture disque monte, mais bien moins que craint.** Les mesures d'ADR
  0042 et 0046 — 41 encodages, 98 ms, 0,056 % du temps d'analyse — étaient bornées par
  « une plaque lue » et **ne doivent pas être recopiées**. Mesuré ici : 7 encodages pour
  11 véhicules, contre 2 avant, sur 150 images. Le plafond théorique est « un encodage
  par cran de 15 % de largeur » par véhicule et par tier ; en pratique la porte de
  lisibilité et l'étranglement du détecteur le tiennent bien en dessous. Le rappel
  écrivant toujours dans le thread worker, la boucle d'événements reste protégée ;
- **`snapshotScore` reste au contrat en changeant de sens.** Tout lecteur qui le prend
  pour un drapeau se met à *manquer* des photos, silencieusement. C'est dit dans les
  trois docstrings — domaine, sérialiseur, `contracts.ts` — et testé aux deux bouts ;
- **la fixture du contrat exerce deux causes sur trois** (`plate_text`, `plate_box`).
  La troisième demanderait un quatrième véhicule dans la scène, donc de changer tous
  ses compteurs, pour un champ que trois tests client couvrent déjà.

## Alternatives écartées

- **une photo par cause** (jusqu'à trois par véhicule) : coût disque et mémoire ×3,
  une modale à trois vignettes, et surtout « laquelle est *la* photo de ce véhicule »
  redeviendrait une question sans réponse ;
- **faire voyager le seuil de ressemblance dans la requête** pour que le serveur
  tranche exacte / probable : rompt ADR 0048 (« le score au serveur, le seuil au
  client »), et changer d'avis imposerait une réanalyse ;
- **un champ booléen `hasSnapshot`** plutôt qu'une cause : il aurait dit qu'il y a une
  photo sans dire s'il faut demander la vignette de plaque, ni quoi écrire sous une
  photo sans confiance de lecture ;
- **un `snapshot_rank` unique, comparable entre tiers** : une erreur d'unité
  invisible, aux deux chiffres plausibles. Voir « Le rang » ci-dessus.
