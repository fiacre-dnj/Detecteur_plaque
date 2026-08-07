# ADR 0007 — On lit le texte des plaques, en différé, et on le fait voter

- **Statut** : accepté
- **Date** : 2026-08-06

## Contexte

Jusqu'ici l'ANPR **localisait** sans lire : `PlateDetection` valait `(box, score)`
du domaine jusqu'au fil, et le registre n'affichait qu'un pourcentage de confiance
dans sa colonne « Plaque ». Un utilisateur voyait un rectangle jaune sur une plaque
et ne pouvait pas savoir laquelle.

C'était une exclusion **explicite** de la spécification :

- [`prompt/00-CONTEXTE-ET-PERIMETRE.md`](../../prompt/00-CONTEXTE-ET-PERIMETRE.md)
  — « Pas d'OCR du texte de plaque (on **localise** la plaque, on ne lit pas les
  caractères) — point d'extension documenté. »
- [`prompt/02-ARCHITECTURE-BACKEND.md`](../../prompt/02-ARCHITECTURE-BACKEND.md)
  — « **OCR de plaque** : `PlateDetector` rend des boîtes ; un port `PlateReader`
  (image + boîte → texte + score) est déclaré et non implémenté. »

Les deux lignes ne se contredisent pas : la première borne le lot initial, la
seconde décrit *la forme* de l'arrivée de l'OCR. Ce lot n'écarte donc pas une
contrainte, il exerce le point d'extension n° 4.

Un écart mérite toutefois d'être noté : le port que `prompt/02` annonce comme
« déclaré » **n'existait nulle part dans le code** — zéro occurrence de
`PlateReader` hors du dossier `prompt/`. Le point d'extension était documenté dans
la spécification, pas préparé dans le code. Cette ADR corrige aussi cela.

## Décision

Cinq décisions, pas une.

**1. onnxruntime + une tête de reconnaissance PP-OCR exportée en ONNX**, pas
PaddleOCR. `onnxruntime` et `onnx` sont déjà des dépendances dures
([`backend/pyproject.toml`](../../backend/pyproject.toml)), déclarées parce
qu'`ultralytics` en a besoin pour lire le modèle de plaques. La lecture du texte
n'ajoute donc **aucune dépendance** : c'est la même architecture de reconnaissance que
PaddleOCR, sans son runtime.

Le modèle retenu est **`en_PP-OCRv3_rec`** et non v4 : à la date de ce lot, aucun
`en_PP-OCRv4_rec` n'est publié en ONNX — le dépôt de RapidOCR n'a d'export anglais
qu'en v3, et la v4 n'y existe qu'en chinois. Même famille (SVTR-LCNet, entrée 48 px,
décodage CTC), donc l'adaptateur est identique ; seul l'alphabet change. Le modèle
chinois à 6625 classes a été écarté explicitement : il fonctionnerait — la
normalisation du domaine retire tout ce qui sort de `A-Z0-9-` — mais il paierait un
softmax 68 fois plus large pour lire sept caractères latins.

**2. Mode différé uniquement.** `features/realtime` n'a aucune référence aux
plaques aujourd'hui — `LiveSession.process` n'appelle jamais le détecteur, et le
`detectPlates` que son protocole accepte est silencieusement ignoré. Le direct
n'avait pas d'ANPR ; il n'en gagne pas. Deux raisons de fond s'y ajoutent : le
budget de latence y est bien plus serré, et l'invariant 13 réduit les frames à
960 px avant l'envoi, ce qui dégrade précisément ce dont une plaque a besoin.

**3. Le port prend un lot de boîtes, pas une boîte.** `read(image, boxes) ->
tuple[PlateText | None, ...]`, ce qui **diffère de la signature annoncée** par
`prompt/02`. La tête de reconnaissance a une entrée fixe `(N, 3, 48, 320)` : sur un
tenseur si petit, le coût fixe d'un `session.run` — traversée pybind11, réveil du
pool intra-op, allocation de l'arène — pèse autant que le calcul. Quatre plaques en
quatre appels le paient quatre fois ; en un appel, une fois. Les GEMM du backbone
sortent du même coup du régime où leur synchronisation coûte plus que leur travail,
et le décodage CTC se vectorise sur `(N, T, C)` au lieu de boucler en Python.
L'écart à la spécification est assumé : le choix du modèle n'était pas connu
lorsqu'elle a été écrite, et c'est lui qui rend le lot rentable.

**4. Le texte publié est un vote sur la vie du véhicule.** C'est l'invariant 4
étendu au texte : on publie la plaque du *véhicule*, jamais la lecture de la frame
courante. Sans cela, le registre afficherait la dernière lecture — souvent la plus
tardive et la plus oblique — et deux relectures du même clip donneraient deux
plaques. La confiance est **cumulée** et non comptée en voix : trois lectures
floues à 0,4 ne doivent pas battre deux lectures nettes à 0,95. Le vote exige au
minimum deux lectures concordantes, une confiance cumulée plancher, et une
domination du suivant — un quasi-ex æquo entre `AB123CD` et `AB123CO` est un tirage
au sort, et publier un tirage au sort est le pire résultat possible.

**5. Aucune substitution de glyphes ambigus** (O↔0, I↔1, S↔5). Le modèle ne
connaît pas le format des plaques du pays : décider que le troisième caractère
« doit » être un chiffre, c'est inventer une information qu'on ne possède pas. Une
correction tenant compte du format national est un point d'extension, pas un
détail d'implémentation.

### Le drapeau de requête est distinct

`readPlateText` est séparé de `detectPlates`, et l'un ne désactive pas l'autre :
un déploiement sans le modèle OCR garde ses boîtes. Deux raisons. Le coût, d'abord.
Le cran de confidentialité, ensuite : `_cleanup_loop` argumente déjà qu'une vidéo
part avant son résultat parce qu'elle contient « des plaques réelles et des
visages ». Persister le *texte* franchit un cran de plus, et cela mérite un
consentement explicite plutôt qu'un effet de bord d'une case cochée pour autre
chose.

## Alternatives écartées

**PaddleOCR.** L'option demandée au départ, et la plus directe : c'est la
bibliothèque de référence du modèle retenu. Écartée pour trois coûts cumulés.
`paddlepaddle` pèse ~600 Mo dans une image Docker, sur une machine sans GPU où il
n'apportera aucune accélération. Il télécharge ses poids **tout seul au premier
appel**, ce qui contredit l'[ADR 0002](0002-pas-de-poids-dans-git.md) et le motif
de vérification SHA-256 de `scripts/fetch_plate_model.py`, et empêcherait une CI
hors-ligne. Enfin `filterwarnings = ["error"]` fait échouer la suite sur le moindre
avertissement, et paddle est bavard. Nous gardons son modèle et son prétraitement ;
nous laissons son runtime.

**EasyOCR.** Plus léger ici puisqu'il repose sur `torch`, déjà présent. Écarté
parce que son détecteur CRAFT est du travail inutile — `PlateDetector` fournit déjà
la boîte —, qu'il télécharge ~100 Mo au runtime, et qu'il ajoute `scikit-image` et
`python-bidi` pour n'utiliser qu'une tête de reconnaissance que nous savons appeler
directement.

**Étrangler le détecteur de plaques plutôt que le lecteur.** Tentant, puisque la
détection est le vrai goulot (voir Conséquences). Écarté : les boîtes du détecteur
sont **dessinées à l'écran**. Les produire une frame sur trois ferait clignoter des
rectangles que l'utilisateur lit comme un défaut de détection. On étrangle ce qui
ne se voit pas.

**Un texte au niveau plaque uniquement**, sans miroir au niveau piste. Écarté
parce que l'étranglement ne remplit `plates[].text` qu'une frame sur trois :
l'étiquette du canvas clignoterait. C'est exactement l'argument qui avait fait
ajouter `identityLabel` à côté de `label`.

## Conséquences

- **Un franchissement peut porter `plateText: null` alors que le registre porte le
  texte.** Ce n'est pas une incohérence. Les franchissements de la frame *N* sont
  émis dans `AnalysisSession.feed()`, donc **avant** la passe OCR de la frame *N*.
  Une ligne de franchissement est un enregistrement daté — ce que le serveur savait
  au moment de compter ; une ligne de registre est un enregistrement de vie.
  **L'autorité est le registre.** Un test l'affirme volontairement, pour que
  personne ne le signale comme un bug dans six mois.
- **Un dictionnaire de caractères qui ne correspond pas au modèle ne lève rien** :
  il rend des chaînes fausses et parfaitement plausibles. C'est le mode de panne
  central de ce lot, et il est traité trois fois — le dictionnaire est récupéré
  *avec* le modèle et haché comme lui, le script de récupération compare
  `len(charset)` à la dernière dimension de sortie, et l'adaptateur refuse de
  charger en cas de désaccord (OCR indisponible, détection intacte).
- **`plateOcrAvailable` est un drapeau distinct de `plateAvailable`.** Ce sont deux
  fichiers, récupérés par deux scripts, et « détecteur présent, lecteur absent » est
  l'état par défaut de tout déploiement neuf. Sans ce drapeau, l'interface
  proposerait une case à cocher qui ne fait rien — le mode de panne exact que
  `plateAvailable` avait été inventé pour éviter.
- **Le texte de plaque est une donnée personnelle** d'une nature différente d'une
  boîte. `TRAFFIC_JOB_TTL_MINUTES` gouverne désormais aussi la durée de vie de
  plaques lisibles en base.
- **L'OCR n'est pas le goulot ; la détection l'est.** La détection de plaques coûte
  ~880 ms par frame avec trois pistes, soit ~290 ms par piste ; une tête de
  reconnaissance sur `(N, 3, 48, 320)` est deux ordres de grandeur en dessous. La
  politique d'étranglement existe donc d'abord pour la **justesse** du vote — ne pas
  voter quarante fois sur le même recadrage figé d'un véhicule arrêté au feu — et
  pour rendre le surcoût invisible ; pas pour sauver une cadence déjà perdue
  ailleurs. Son économie principale n'est ni la cadence ni le déplacement, c'est
  l'**arrêt complet** dès qu'une identité a une plaque établie : un véhicule passe
  de quarante inférences à trois sur sa vie.
- **`AnalysisJobConfig.plate_confidence` reste mort** et le reste sciemment : ni
  `engine_spec()` ni `session_config()` ne le lisent, parce que le seuil du
  détecteur vient de `Settings` au moment où l'adaptateur est construit. C'est
  précisément pourquoi **tous** les réglages OCR vont dans `Settings` et **aucun**
  dans la requête. Ce champ doit être câblé ou supprimé — dans un changement
  séparé, pas ici.
## Mesures relevées

Avec les **deux vrais modèles** chargés, sur cette machine (CPU, aucun GPU).

### Coût

Trente images, deux pistes, détection de plaques active dans les deux cas — seul
`readPlateText` change. Un passage à vide précède la mesure pour que le chargement des
modèles n'y entre pas.

| | Cadence | Durée |
|---|---|---|
| `readPlateText = false` | 4,31 img/s | 6,97 s |
| `readPlateText = true` | 4,24 img/s | 7,07 s |

**Surcoût de l'OCR : 1,4 %, soit ~3,4 ms par image.** La mesure confirme ce que la
conception supposait : **l'OCR n'est pas le goulot, la détection l'est.** C'est aussi
pourquoi la politique d'étranglement doit être comprise comme une protection de la
*justesse* du vote, et non comme une optimisation de cadence — la régler plus
agressivement ne ferait rien gagner de visible.

### Justesse

Dix plaques rendues (fond clair, texte sombre, léger flou et bruit), lues par
l'adaptateur réel puis normalisées par le domaine : **9 sur 10, confiance moyenne
0,97**.

L'unique échec est instructif et doit être écrit ici : `GH-901-IJ` lu `GH-901-13`,
**à 0,89 de confiance**. C'est la confusion de glyphes I↔1 et J↔3, et elle survient à
une confiance élevée — donc **aucun seuil ne l'attrape**. Monter
`TRAFFIC_PLATE_OCR_MIN_TEXT_SCORE` protège des lectures hésitantes, pas de celle-là.
Le seul remède serait une règle de format national (« le troisième caractère est un
chiffre »), que la décision 5 écarte délibérément : c'est un point d'extension, pas un
détail. À retenir pour l'exploitation : la plaque affichée est fiable à ~90 %, et le
mode d'erreur résiduel est un caractère ambigu, pas une chaîne absurde.

Ces chiffres portent sur des rendus synthétiques, pas sur des photos de trafic réel :
ils mesurent la tête de reconnaissance et le prétraitement, pas la qualité d'un
cadrage sur une scène réelle. Une mesure sur vidéo réelle reste à faire, et elle sera
nécessairement plus basse.

### Provenance des artefacts

| | Source | SHA-256 |
|---|---|---|
| Modèle | [`SWHL/RapidOCR`, `PP-OCRv3/en_PP-OCRv3_rec_infer.onnx`](https://huggingface.co/SWHL/RapidOCR/resolve/main/PP-OCRv3/en_PP-OCRv3_rec_infer.onnx) (8,97 Mo) | `ef7abd8bd3629ae57ea2c28b425c1bd258a871b93fd2fe7c433946ade9b5d9ea` |
| Dictionnaire | [`PaddleOCR`, `ppocr/utils/en_dict.txt`](https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/main/ppocr/utils/en_dict.txt) (95 lignes) | `5662df9d2d03f0e8ca0d3b0649d6acbab904b6a14b3d3521463c71c37c668ce3` |

Les deux valeurs sont dans `.env` et vérifiées par `scripts/fetch_plate_ocr_model.py`.

## Effet de bord : un bug trouvé par les vrais poids

Installer les artefacts a révélé une erreur que **1 030 tests verts ne voyaient pas**,
et c'est le troisième cas où le vrai modèle attrape ce qu'une doublure ne peut pas.

`charset_from_lines` écartait les lignes sans contenu utile (`if line.strip()`).
Or `en_dict.txt` contient une ligne dont le seul contenu est **un espace** : c'est un
caractère de l'alphabet, pas un blanc de mise en forme. L'alphabet construit tombait
donc à 95 entrées là où le modèle en rend 97 — deux crans de décalage sur tout ce qui
suit. PaddleOCR fait `strip("\n").strip("\r\n")`, jamais `strip()`.

Deux enseignements, tous deux consignés dans le code :

- **Le garde de cohérence a fait son travail.** L'écart de taille transformait le bug
  en « OCR indisponible » — une panne franche — au lieu de plaques fausses et
  plausibles. C'était exactement sa raison d'être. Sans lui, le décalage aurait produit
  des chaînes lisibles et entièrement fausses.
- **L'espace de `use_space_char` ne peut pas être déduit du fichier.** PaddleOCR
  l'ajoute en fin d'alphabet quand le modèle a été entraîné avec, et le dictionnaire ne
  le contient pas. `_resolve_charset` l'ajoute donc **seulement si cela fait
  correspondre les tailles exactement** ; un écart de deux ou plus reste un refus. Le
  déduire ainsi est vérifiable, et l'espace en fin ne décale rien de ce qui précède.
