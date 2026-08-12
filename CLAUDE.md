# CLAUDE.md

Guide pour Claude Code (claude.ai/code) dans ce dépôt.

> Ce fichier décrit **ce qui existe**. Les 14 lots sont écrits ; l'application
> compte des véhicules de bout en bout, en différé comme en direct.
> [`prompt/`](prompt/) reste la spécification normative — quand les deux
> divergent, ce fichier a raison sur l'état du code et `prompt/` sur ce qui était
> demandé.

## Ce que fait l'application

Détection, suivi, ré-identification et comptage de véhicules sur une vidéo ou un
flux caméra. Toute l'inférence est côté serveur ; le navigateur pilote, dessine la
géométrie de comptage et rejoue le résultat.

Deux modes partagent **le même** code de comptage — la même `AnalysisSession`, les
mêmes schémas de requête, les mêmes sérialiseurs — et c'est ce qui garantit qu'un
même tracé donne les mêmes chiffres dans les deux :

- **différé** : dépôt d'un fichier, analyse asynchrone suivie en SSE, résultat
  complet relu et rejoué sur la vidéo locale. Le flux SSE porte aussi un
  **aperçu** échantillonné (`event: preview`, ~5 Hz) : la vidéo locale se cale
  sur l'image analysée et le navigateur y dessine les boîtes, les compteurs et
  les franchissements du serveur **pendant** l'analyse
  ([ADR 0006](docs/adr/0006-apercu-live-des-analyses.md)) ;
- **direct** : frames JPEG sur WebSocket, une image en vol à la fois.

En différé **seulement**, une passe ANPR optionnelle localise les plaques puis en
**lit le texte** (OCR) ; le texte publié est un vote sur la vie du véhicule, pas la
lecture de la frame courante ([ADR 0007](docs/adr/0007-lecture-du-texte-de-plaque.md)),
et ce vote tranche caractère par caractère quand deux graphies proches s'égalisent
([ADR 0008](docs/adr/0008-precision-de-l-anpr.md)). Le détecteur est **étranglé** —
une image sur trois par piste — et les images sautées portent la dernière plaque
mesurée, reprojetée sur la boîte du véhicule
([ADR 0010](docs/adr/0010-etranglement-du-detecteur-de-plaques.md)). Le direct n'a
pas d'ANPR du tout.

## `prompt/` est la spécification, pas de la documentation

Le dossier [`prompt/`](prompt/) (15 fichiers, à lire dans l'ordre depuis
[`prompt/README.md`](prompt/README.md)) **est** le cahier des charges. Quand il
écrit « obligatoire », « jamais » ou « exactement », c'est une contrainte qui a
coûté un bug dans une version antérieure.
[`prompt/13-PIEGES-CONNUS.md`](prompt/13-PIEGES-CONNUS.md) en tient la liste (56
entrées) — **le relire avant de déboguer quoi que ce soit**.

Si une contrainte semble fausse : le dire avec la preuve, proposer l'alternative,
écrire une ADR. Ne jamais la contourner en silence.

## Commandes

`uv` provisionne Python 3.12 lui-même : ne jamais invoquer un `python` du `PATH`
pour du code de ce projet.

```bash
# ── Tout servir (backend + interface, un seul origin)
docker compose up                # http://localhost:8000

# ── Backend (cd backend)
uv sync
uv run uvicorn traffic_analysis.main:app --reload --port 8000
uv run pytest                                                            # 1227 tests
uv run pytest tests/unit/counting/test_line_counter.py -k aller_retour   # un seul
uv run pytest --cov=src --cov-report=term-missing
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "ajoute la table X"
uv run python scripts/fetch_weights.py --tiers nano,medium,large,xlarge
uv run python scripts/fetch_plate_model.py
uv run python scripts/fetch_plate_ocr_model.py       # modèle OCR + son dictionnaire

# ── Frontend (cd frontend)
bun install
bun run dev                      # proxy /api → 127.0.0.1:8000, WebSocket compris
bun run lint && bun run typecheck && bun test && bun run build           # 471 tests
bun test src/features/realtime-counting/model/scale.test.ts              # un seul

# ── Dépôt
uvx pre-commit run --all-files
```

**Il n'y a pas d'extra `gpu`.** `pyproject.toml` déclare
`[tool.uv] torch-backend = "auto"` **et** une source explicite : sur Windows,
`torch` et `torchvision` viennent de l'index **cu126**. `auto` seul ne suffisait
pas — il joue à la résolution, et le lockfile committé fige son verdict, donc une
machine NVIDIA recevait la roue CPU en silence
([ADR 0012](docs/adr/0012-torch-cuda-sur-windows.md)). Pour forcer une variante —
poste Windows sans GPU, build reproductible : `UV_TORCH_BACKEND=cpu uv sync`.

## Architecture

### Backend — vertical par feature, hexagonal à l'intérieur

`backend/src/traffic_analysis/` : `core/` (socle transverse, aucune feature),
`features/<nom>/` et `api/router.py`. Sept features : `counting`, `jobs`,
`models_registry`, `realtime`, `benchmark`, `presets`, `health`. Chacune porte son
`domain/` (pur), `application/` (ports + services), `infrastructure/`
(adaptateurs) et `api/` (routes).

Règle de dépendance, **outillée** par `backend/tests/test_architecture.py` — il a
rejeté du code trois fois pendant l'écriture des lots 7 et 8, et il avait raison à
chaque fois :

```
api → application → domain
infrastructure → application (ports) → domain
core ← tout le monde ;  core → rien des features
feature A → feature B  UNIQUEMENT par son `application`
```

`features/*/domain/**` n'importe jamais `fastapi`, `sqlalchemy`, `ultralytics`,
`cv2` ni `pydantic` (`numpy` est autorisé : un descripteur de ré-identification
est du calcul). C'est ce qui permet à la CI de tourner **sans GPU, sans poids et
sans ultralytics**, en injectant un `FakeEngine`.

Cette architecture a un prix, payé deux fois : un bug de chemin de configuration
du tracker et une erreur d'encodage multipart ont traversé 500 tests verts, parce
que le moteur factice ne les atteint jamais. **Vérifier contre le vrai serveur
avant de déclarer une fonctionnalité terminée.**

`features/counting/domain/` est le cœur : `geometry`, `models`, `line_counter`,
`zone_counter`, `reid`, `speed`, `tracking_session`, plus tout ce qui décide de
l'ANPR sans toucher un pixel — `plate_geometry` (le filtre de plausibilité et les
raisons de non-lecture), `plate_policy` (les deux étranglements), `plate_anchor`,
`plate_text`, `plate_vote`. Sa spécification est
[`prompt/03-DOMAINE-COMPTAGE.md`](prompt/03-DOMAINE-COMPTAGE.md).

Le filtre géométrique vit dans le domaine **et pas dans l'adaptateur**, et ce
déplacement est ce qui rend les 426 gardées / 112 jetées d'ADR 0008 vérifiables :
derrière `ultralytics`, la CI ne les traversait jamais.

`features/models_registry/infrastructure/` est le **seul** endroit qui importe
`ultralytics`.

`counting/application/dto.py` et `request_schema.py` sont le contrat publié de la
feature `counting` : `jobs`, `realtime` et `benchmark` importent de là, jamais du
domaine.

### Frontend — Feature-Sliced Design

`frontend/src/` : `app/` (câblage), `features/<capacité>/` (13), `entities/`,
`shared/`. Aucun dossier `components/`, `hooks/` ou `utils/` global.

```
app → features → entities → shared
```

Une feature n'importe **jamais** une autre feature. Quand deux en ont besoin, le
câblage passe par `StudioPage` — c'est pourquoi `GeometryPanel` reçoit un
`onOpenPresets` plutôt que la modale elle-même.

### Le contrat, pas un build

Pas de monorepo tool. `frontend/src/shared/api/contracts.ts` est le miroir
**exact** des schémas pydantic ; une fixture JSON committée est parsée dans un
test typé, donc un renommage côté backend casse un test côté frontend.

### Livraison

Une seule image (`backend/Dockerfile`, trois étapes) sert le backend **et** le
build du frontend, sur un seul origin. Cela supprime le CORS à ouvrir, le
tamponnage SSE du proxy et le relais WebSocket — les trois pannes de déploiement
habituelles. Un **seul worker** uvicorn : l'état en mémoire (`ProgressHub`, baux
de modèles, compteur de sessions) n'est pas partagé entre processus.

## Invariants à ne jamais violer

Chacun est un bug déjà payé.

1. **Le temps est du temps de scène.** Tout horodatage métier est
   `frame_index / fps × 1000`, jamais `time.time()`. Le seul usage légitime de
   l'horloge murale est la mesure de performance. En direct, le client compte
   depuis le début de session — un flux caméra n'a pas d'index de frame.
2. **Les coordonnées sont en pixels de la vidéo source.** Jamais en pixels
   modèle, jamais en pixels CSS. Les conversions se font aux frontières.
3. **Un compteur affiché est dérivé, jamais accumulé en double.**
   `crossings == Σ by_line[*].total` et `total == positive + negative`.
4. **On compte sous `identity_label`** (vote majoritaire de la galerie), jamais
   sous la lecture de la frame courante. **Le texte de plaque suit la même règle** :
   ce qui est publié est le vote de `PlateTextVote` sur toute la vie du véhicule,
   jamais la lecture de la frame — sinon deux relectures du même clip donnent deux
   plaques.
5. **Le badge ✓ dérive du tally**, jamais de la comptabilité interne d'une piste.
6. **Un véhicule compte une fois, la ré-identification ré-arme.** La
   déduplication porte sur `(identité, génération)` — jamais sur la piste,
   détruite à chaque occlusion longue. Ni la ligne ni le sens n'entrent dans la
   clé : deux lignes en travers de la même voie ne doublent pas le total (c'est la
   **première** franchie qui le porte), et un aller-retour compte 1. La génération
   est `reid_count`, que la galerie n'incrémente que sur une réapparition réelle.
   [ADR 0009](docs/adr/0009-un-comptage-par-vehicule.md).
7. **`_release_lost` avant `_resolve_identities`.** Mesuré avec le mauvais ordre :
   2 véhicules uniques et 0 ré-identification ; avec le bon : 1 et 1.
8. **La timeline stocke des `snapshot()`**, pris **après** la passe ANPR **et**
   après la passe OCR. Un snapshot pris entre les deux porterait des boîtes muettes
   que l'analyse, elle, avait su lire.
9. **Un bail (`lease`) par usage de modèle.** Deux `track()` simultanés sur la
   même instance mélangent deux vidéos — des chiffres plausibles et faux.
10. **Ne jamais déduire une caractéristique d'un modèle de son nom de fichier.**
11. **Tout ce qui touche OpenCV, PyTorch ou le disque en volume part dans un
    thread worker** (`anyio.to_thread.run_sync`).
12. **Le code parle français à l'utilisateur, anglais au compilateur.**
    Identifiants et types en anglais ; docstrings, commentaires et copie
    d'interface en français.

### Les deux pannes silencieuses

Elles méritent leur propre section parce qu'elles ne lèvent **rien** : pas
d'exception, pas de journal, et des chiffres qui restent plausibles.

13. **La géométrie du direct est mise à l'échelle d'envoi.** Le client réduit ses
    frames à 960 px ; une ligne tracée sur du 1280 px appliquée à une image de 960
    est comptée **25 % à côté**. Le serveur ne peut pas le détecter — il ne connaît
    pas la résolution que le client croit envoyer — donc il renvoie les dimensions
    reçues, et le client compare et **refuse de compter** en cas d'écart.
    `pixelsPerMeter` est mis à l'échelle lui aussi : c'est un rapport pixels/mètre.
    Voir `frontend/src/features/realtime-counting/model/scale.ts`.
14. **L'aperçu d'un job porte les dimensions décodées par le serveur.** Le client
    les compare à celles de sa balise `<video>` et **suspend le dessin** en cas de
    désaccord — SAR non carré, rotation portée par les métadonnées. Le serveur ne
    peut pas détecter cet écart : il ne sait pas ce que le navigateur affiche. Des
    boîtes décalées se lisent comme un défaut de détection, jamais comme un défaut
    de repère.
15. **Un preset porte la résolution pour laquelle il a été tracé.** Le serveur le
    convertit à la lecture et **l'annonce** par `scaled`. Une conversion
    silencieuse serait pire que pas de conversion : une géométrie qui bouge sans
    prévenir se lit comme un bug.

## Décisions déjà prises — ne pas les rediscuter

1. **Analyse 100 % backend.** Aucune inférence navigateur.
   [ADR 0003](docs/adr/0003-analyse-100-pourcent-backend.md).
2. **Python 3.12 épinglé**, borne haute `<3.13`.
   [ADR 0001](docs/adr/0001-python-312.md).
3. **Aucun poids dans git.** [ADR 0002](docs/adr/0002-pas-de-poids-dans-git.md).
   Le dossier `yolo/` contient des `.onnx` d'une version antérieure :
   **inutilisables** (un export ONNX ne porte pas le pipeline BoT-SORT + ReID +
   GMC) et ignorés par le code.
4. **`torch` en variante automatique** selon le matériel, pas d'extra.
   [ADR 0005](docs/adr/0005-torch-cpu-par-defaut.md).
5. **Persistance SQLite + SQLAlchemy async + Alembic.** Sept tables. La timeline
   complète, elle, part dans un `json.gz` sur disque : plusieurs centaines de Mo
   n'ont rien à faire dans une base mono-écrivain que personne ne requête.
6. **`DESIGN.md` est la source de vérité des jetons visuels**, avec deux
   arbitrages dans [ADR 0004](docs/adr/0004-systeme-de-design.md) : les valeurs de
   `DESIGN.md` remplacent le `bg-slate-950` de `prompt/09`, et l'accent vert est
   **strictement fonctionnel** — la couleur du canvas encode une donnée, donc le
   vert n'est jamais une couleur de classe.
7. **Thème sombre par défaut, clair au choix** (bascule dans l'entête). Le clair
   ne fait que redéfinir les jetons sous `:root[data-theme="light"]` : aucune
   variante `dark:` dans les composants, et **les couleurs du canvas ne changent
   pas** — elles sont posées sur de la vidéo, pas sur le fond de page. Amendement
   d'[ADR 0004](docs/adr/0004-systeme-de-design.md).
8. **OCR de plaque : onnxruntime + PP-OCRv3 rec, en différé seulement, texte voté
   sur la vie du véhicule.** Aucune dépendance nouvelle — `onnxruntime` et `onnx`
   étaient déjà des dépendances dures. Ni PaddleOCR (600 Mo de `paddlepaddle` et un
   téléchargement de poids au runtime) ni EasyOCR.
   [ADR 0007](docs/adr/0007-lecture-du-texte-de-plaque.md).
9. **La précision de l'ANPR se joue au filtre géométrique, pas au modèle.** Sur 538
   détections réelles, 112 étaient la boîte du véhicule entier — dont certaines à
   0,87 de confiance, donc inatteignables par un seuil. La mosaïque d'inférence
   existe mais reste **désactivée par défaut** : elle échange du rappel contre de la
   vitesse (côté 2 : 3,4× pour −16 % de rappel ; côté 3 : 6,6× pour −44 %), et ce
   n'est pas un arbitrage à faire en silence.
   [ADR 0008](docs/adr/0008-precision-de-l-anpr.md).
10. **Un véhicule compte une fois, toutes lignes et tous sens confondus** ; seule
    une vraie ré-identification lui redonne droit à un franchissement. Plusieurs
    lignes servent à *situer* un passage, pas à le multiplier. C'est un changement
    de spécification par rapport à `prompt/03`, qui décrivait un garde
    `(ligne, identité, sens)`. [ADR 0009](docs/adr/0009-un-comptage-par-vehicule.md).
11. **Le détecteur de plaques est étranglé, et une ancre rend l'étranglement
    invisible.** Il tournait une inférence 640×640 par piste et par image :
    **823 ms/image mesurées**, soit près de dix minutes pour 30 s de vidéo. Les
    images sautées reçoivent la dernière plaque *mesurée*, reprojetée en
    coordonnées relatives à la boîte du véhicule — les rectangles ne clignotent
    donc pas, ce qui était l'objection d'ADR 0007. Mesuré : **180 → 62 recadrages**
    (2,9×). Deux règles absolues : **l'OCR ne lit jamais une boîte reprojetée**, et
    une reprojection ne nourrit aucun agrégat.
    [ADR 0010](docs/adr/0010-etranglement-du-detecteur-de-plaques.md).
12. **Le plancher de lecture est mesuré, pas supposé : ~64 px.** L'échelle de
    vérité terrain rend 8/8 lectures justes à 320 px, 4/8 à 64 px et **0/8 à
    48 px** — rejouable par `scripts/anpr_bench.py --truth-ladder`. `min_width_px`
    vaut donc 64 (et non 32, cinq fois trop permissif, ni 150, qui supprimerait
    toute lecture). L'OCR relit une identité seulement si la nouvelle vignette bat
    la meilleure déjà lue de 25 % en **qualité = largeur × netteté**.
13. **Un échec porte son message et son code.** Une `AppError` fait traverser
    `detail` et `code` jusqu'à l'écran ; tout le reste garde la phrase générique,
    parce qu'un `RuntimeError` porte des chemins serveur. Le modèle est **chargé
    avant** le passage en « en cours », donc un modèle absent échoue sans jamais
    prétendre travailler. `weights_dir` relatif est ancré sur le paquet et non sur
    le CWD. [ADR 0011](docs/adr/0011-un-job-en-echec-dit-ce-qu-il-est.md).
14. **Un véhicule sans plaque publiée dit pourquoi**, parmi cinq raisons qui
    appellent cinq gestes différents, avec la largeur de la meilleure plaque vue.
    Ce n'est pas un confort : l'étranglement et le plancher de lecture rendent le
    silence plus fréquent, et un silence non expliqué se lit comme une panne.

## Mesurer avant d'optimiser l'ANPR

`backend/scripts/anpr_bench.py` est le banc. Il existe parce qu'aucun chiffre des
ADR 0007 et 0008 n'était rejouable — tous produits hors dépôt, à la main — et
qu'ADR 0008 a déjà démontré une fois que l'intuition se trompe ici.

```bash
cd backend
# Rejouable sans aucune vidéo, donc en CI. Valide le banc lui-même.
uv run python scripts/anpr_bench.py --synthetic --truth-ladder --json out/ladder.json
# Sur de vraies vidéos, avant / après.
uv run python scripts/anpr_bench.py --videos D:/TesteIA/Video --frames 40 \
    --ocr --json out/apres.json --compare out/avant.json
```

Le couple `textsDecoded` / `textsPublished` est le chiffre qui explique tout : un
`118 / 0` dit que la chaîne lit du bruit et le **refuse**. Ce n'est pas une panne.

`backend/scripts/build_fixtures.py` régénère les fixtures du contrat. **Toujours
les régénérer, jamais les corriger à la main** : une fixture éditée pour faire
passer `tsc` affirme ce que le frontend espère au lieu de ce que le backend
produit, ce qui retire la seule propriété qu'on lui demandait.

## Pièges d'environnement de cette machine

- `uv` a été installé par winget et vit dans
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_*\`. **Il n'est pas sur le
  `PATH` du shell Bash ni de PowerShell** : les hooks pre-commit qui appellent
  `uv run` échouent alors avec « Executable `uv` not found ». Ajouter ce dossier au
  `PATH` avant de committer.
- Le Python du système est un **3.14** : il ne peut pas faire tourner ce backend.
  Toujours passer par `uv run`.
- **Jamais de commentaire en fin de ligne après une valeur vide dans un `.env`.**
  `TRAFFIC_PLATE_MODEL_PATH=  # vide = …` donne au réglage la valeur
  `« # vide = … »` : le service cherche alors son modèle de plaques à ce chemin,
  ne le trouve pas, et l'ANPR reste indisponible **sans qu'aucun message ne
  mentionne la cause**. Ce piège a tenu l'ANPR hors service pendant tout le
  projet, avec le bon fichier au bon endroit. Le commentaire va au-dessus de la
  clé ; `Settings._blank_means_unset` neutralise en plus les `.env` déjà écrits.
- Le modèle de plaques vit dans `backend/.weights/license-plate.onnx` (copié
  depuis `yolo/`, git-ignoré des deux côtés). Contrairement aux `.onnx` de
  véhicules du dossier `yolo/`, **celui-là est utilisable** : la passe ANPR est
  une simple détection, elle ne demande ni tracker ni ReID.
- **`weights_dir` relatif est ancré sur `backend/`, plus sur le répertoire de
  lancement.** Avant ce correctif, lancer `uvicorn` depuis la racine du dépôt
  faisait paraître *tous* les poids absents et rendait l'ANPR indisponible sans
  qu'aucun message ne le dise — même famille que le piège du `.env` ci-dessus. Le
  chemin résolu est journalisé au démarrage et exposé dans `/health`
  (`weightsDir`) : en cas de doute, le regarder avant de chercher ailleurs. Un
  chemin **enraciné** (`/opt/poids`, `C:\poids`) traverse inchangé.
- **Cet export est figé à `1×3×640×640` et sa grille d'ancres est une constante.**
  Vérifié par chirurgie de graphe : rendre le lot ou la résolution dynamiques fait
  échouer le `Reshape` du DFL. Ni résolution adaptative ni lot sans ré-export, et
  le `.pt` d'origine n'est pas dans le dépôt. C'est ce qui force la mosaïque comme
  seul levier de débit ([ADR 0008](docs/adr/0008-precision-de-l-anpr.md)).
- **L'OCR a un plancher de résolution, mesuré : ~150 px de large.** En dessous elle
  décroche (80 px → 3/8, 48 px → 0/8), et sur les vidéos de `D:\TesteIA\Video` les
  plaques font 27 à 88 px : elle n'y lira rien, quel que soit le prétraitement. Elle
  se tait au lieu d'inventer, ce qui est voulu — mais ne pas conclure à une panne.
- L'OCR demande **deux** fichiers dans `backend/.weights/` :
  `license-plate-ocr.onnx` (`en_PP-OCRv3_rec`, 97 classes) et
  `license-plate-ocr.charset.txt` (`en_dict.txt`, 95 lignes), récupérés ensemble par
  `scripts/fetch_plate_ocr_model.py`. `plateOcrAvailable` est faux si l'un des deux
  manque, et c'est délibéré : le dictionnaire **fait partie du contrat du modèle** —
  l'indice 37 signifie ce que le dictionnaire d'entraînement disait. Un dictionnaire
  d'une autre taille ne lève rien, il rend des plaques fausses et plausibles ;
  l'adaptateur refuse donc de charger si les tailles ne correspondent pas.
- **`en_dict.txt` contient une ligne dont le seul contenu est un espace.** C'est un
  caractère de l'alphabet, pas un blanc de mise en forme : un `line.strip()` qui
  l'écarte décale tout ce qui suit de deux crans. Ce bug a traversé 1 030 tests verts
  et n'a été trouvé qu'en installant les vrais poids — troisième cas où une doublure
  ne pouvait pas voir. 95 lignes + espace de `use_space_char` + blanc CTC = 97.
  Voir [ADR 0007](docs/adr/0007-lecture-du-texte-de-plaque.md), « Effet de bord ».
- **Un GPU depuis le 2026-08-12 : Quadro P1000 (Pascal, `sm_61`, 4 Go).** Trois
  conséquences qui ne se devinent pas :
  - **la roue torch doit être cu126**, épinglée par marqueur `win32` dans
    `pyproject.toml`. C'est la dernière ligne qui embarque `sm_61` : CUDA 13 a
    supprimé Pascal, et le pilote annonce pourtant CUDA 13.0, donc une détection
    automatique choisit une roue qui s'installe, répond `is_available() == True`,
    puis échoue à la première inférence ;
  - **`half` reste faux sur cette carte**, et le code le décide seul depuis
    ADR 0012 (capability < 7.0). Avant Volta le fp16 est *plus lent* que le fp32 :
    38,9 ms → 48,9 ms mesurées. Ne pas « réactiver » `TRAFFIC_HALF` en croyant
    optimiser ;
  - **les mesures de benchmark antérieures au 2026-08-12 sont des mesures CPU**,
    et les chiffres des ADR 0007, 0008 et 0010 n'ont pas été rejoués sur GPU.
    Les comparer à une mesure GPU sans le dire serait trompeur — c'est pourquoi un
    run persisté porte son `device`.

  Repère : `yolov8n` sur une image 1280×720 coûte 147,8 ms sur CPU et 38,9 ms sur
  ce GPU. Le conteneur, lui, n'a toujours pas de GPU.
  [ADR 0012](docs/adr/0012-torch-cuda-sur-windows.md).
- Le frontend est passé de pnpm à **bun** ; `bun.lock` est le lockfile committé.
  La version est épinglée en **trois** endroits qui doivent rester d'accord :
  `frontend/package.json` (`packageManager`), l'image `oven/bun` des deux
  Dockerfiles, et `bun-version` dans la CI.
- L'alias `@/*` est déclaré dans **trois** fichiers : `frontend/tsconfig.json` (le
  seul que `bun test` lit), `tsconfig.app.json` (pour `tsc -b`) et
  `vite.config.ts`.
- La roue `ultralytics` embarque son propre paquet `tests` : les helpers vivent
  dans `backend/tests/support/`, importés en `from tests.support.engine import …`,
  et `conftest.py` ne contient que des fixtures.
- Le hook `mixed-line-ending` **corrige** les fins de ligne au premier passage et
  fait donc échouer le premier `git commit` : ré-ajouter et recommitter.
- Le disque `C:` de cette machine est régulièrement **plein**, ce qui fait échouer
  les builds Docker avec une erreur d'entrée/sortie de BuildKit qui ne mentionne
  jamais l'espace disque. Vérifier `df -h` avant de conclure à un défaut du
  `Dockerfile`.

## Tests

| | Backend | Frontend |
|---|---|---|
| Nombre | 1227 (1 skip) | 471 |
| Lanceur | pytest, `asyncio_mode = "auto"` | `bun test` (**pas** vitest) |
| Isolation | base SQLite sous `tmp_path`, moteur factice | — |

`filterwarnings = ["error", …]` : un avertissement fait échouer la suite.

**Ne jamais borner l'attente d'un test par un nombre d'itérations.** Des tests de
benchmark passaient nus et échouaient sous `--cov` pour cette raison : un test dont
le verdict dépend de la vitesse de la machine ne prouve rien. Attendre la tâche
réelle (`await service.wait_for_idle()`), ou une échéance en temps.

## Git

Jamais de travail sur `main`. Une branche par lot, Conventional Commits avec
portée obligatoire, un commit qui compile et passe les tests même en
intermédiaire. Détails dans [CONTRIBUTING.md](CONTRIBUTING.md) et
[`prompt/11`](prompt/11-GIT-ET-CONVENTIONS.md).
