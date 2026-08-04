# 04 — Modèles YOLO, registre, ANPR et benchmark

## 1. Objectif : un large choix, exploité côté Python

L'utilisateur doit pouvoir **comparer plusieurs familles et plusieurs tailles**
de YOLO sur son propre matériel, dans l'application, sans toucher au code.
Conséquences de conception :

- Le catalogue est **une donnée**, pas du code dispersé : `features/models_registry/domain/catalogue.py`.
  **Ajouter un modèle = ajouter une ligne**, et le sélecteur, le benchmark, le
  registre et l'API suivent.
- Les poids ne sont **jamais committés** : ils sont téléchargés à la demande
  dans `TRAFFIC_WEIGHTS_DIR` (`.weights/`, git-ignoré).
- Les poids véhicules sont les **`.pt` natifs d'Ultralytics** : `model.track()`
  veut le pipeline natif complet (BoT-SORT + embeddings ReID + GMC), qu'un export
  ONNX ne porte pas. Le modèle de plaques est l'exception : c'est un `.onnx`, et
  `YOLO(path, task="detect")` le charge très bien pour du `predict`.

## 2. Catalogue

```python
@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    id: str            # identique côté frontend — c'est un contrat
    label: str
    family: str        # "yolov8" | "yolo11" | "yolo12" | "yolo26"
    tier: ModelTier    # "nano" | "small" | "medium" | "large" | "xlarge"
    size_mb: int
    note: str          # une phrase FR affichée dans le sélecteur
    weights: str       # nom de fichier .pt téléchargé par ultralytics
    task: Literal["detect"] = "detect"
```

Catalogue initial (20 détecteurs véhicules + 1 modèle de plaques). `size_mb` est
la taille approximative du `.pt`, utilisée pour l'avertissement de
téléchargement :

| id | label | famille | palier | ~Mo | note |
|---|---|---|---|---|---|
| `yolov8n` | YOLOv8n | yolov8 | nano | 6 | Le plus rapide — bon défaut |
| `yolov8s` | YOLOv8s | yolov8 | small | 22 | Un cran au-dessus du nano |
| `yolov8m` | YOLOv8m | yolov8 | medium | 52 | Référence historique |
| `yolov8l` | YOLOv8l | yolov8 | large | 88 | — |
| `yolov8x` | YOLOv8x | yolov8 | xlarge | 137 | — |
| `yolo11n` | YOLO11n | yolo11 | nano | 6 | Nano de dernière génération |
| `yolo11s` | YOLO11s | yolo11 | small | 19 | — |
| `yolo11m` | YOLO11m | yolo11 | medium | 39 | Meilleur compromis précision/cadence |
| `yolo11l` | YOLO11l | yolo11 | large | 49 | Précision supérieure |
| `yolo11x` | YOLO11x | yolo11 | xlarge | 109 | Précision maximale (famille 11) |
| `yolo12n` | YOLO12n | yolo12 | nano | 6 | Attentionnel, palier nano |
| `yolo12s` | YOLO12s | yolo12 | small | 19 | — |
| `yolo12m` | YOLO12m | yolo12 | medium | 39 | Attentionnel, palier medium |
| `yolo12l` | YOLO12l | yolo12 | large | 52 | Attentionnel — lourd à l'inférence |
| `yolo12x` | YOLO12x | yolo12 | xlarge | 113 | Le plus gros — hors temps réel |
| `yolo26n` | YOLO26n | yolo26 | nano | 6 | NMS intégré au graphe |
| `yolo26s` | YOLO26s | yolo26 | small | 19 | NMS intégré au graphe |
| `yolo26m` | YOLO26m | yolo26 | medium | 39 | NMS intégré au graphe |
| `yolo26l` | YOLO26l | yolo26 | large | 48 | NMS intégré au graphe |
| `yolo26x` | YOLO26x | yolo26 | xlarge | 107 | NMS intégré, précision max |

Défaut : `yolov8n` (`TRAFFIC_DEFAULT_MODEL_ID`).

> **Deux vérités à énoncer explicitement dans le code.**
> 1. **Ne jamais déduire une caractéristique d'un modèle de son nom de
>    fichier.** Le palier vit dans `tier`, le format de sortie dans les
>    métadonnées du fichier. La version précédente encodait le palier dans le nom
>    (`yolo11l_large.onnx`) et c'est la seule raison pour laquelle le modèle de
>    plaques paraissait mal rangé.
> 2. Ces `size_mb` sont **indicatifs** : ils servent l'avertissement « ce
>    téléchargement pèse ~137 Mo ». La vérité vient du disque après
>    téléchargement, et l'API la renvoie (`sizeBytes` réel si le fichier est
>    présent).

Un test vérifie l'unicité des `id`, que chaque `tier` est dans l'énumération, et
que chaque `weights` est un nom de fichier plausible (`^[a-z0-9._-]+\.pt$`).

## 3. `ModelRegistry` — résidence, bail, éviction LRU

Responsabilités, et **rien d'autre** : cataloguer, charger paresseusement,
prêter, évincer, préchauffer, dire le device.

```python
class ModelRegistry:
    def catalogue(self) -> tuple[ModelDescriptor, ...]
    def describe(self, model_id: str) -> ModelDescriptor        # UnknownModelError sinon
    def device(self) -> str                                     # "auto" résolu UNE fois
    def half(self) -> bool
    def loaded_ids(self) -> list[str]
    @contextmanager
    def lease(self, model_id: str) -> Iterator[YOLO]
    def warmup(self, model_id: str) -> None
    def unload(self, model_id: str) -> bool                      # exposé par l'API admin
```

Règles :

- **`device()` : `"auto"` est résolu une seule fois** — `"0"` si
  `torch.cuda.is_available()`, sinon `"cpu"` — et mémorisé. `torch` est importé
  **localement** dans la méthode : les tests ne doivent jamais payer l'import.
- **`half()` ne rend `True` que sur GPU.** En fp16 sur CPU, l'inférence ralentit.
- **`lease()` réserve une instance dédiée pour la durée de l'usage.** Deux
  `track()` simultanés sur la même instance **partagent l'état de suivi et
  mélangent deux vidéos** : c'est un bug silencieux qui produit des chiffres
  plausibles et faux. Le bail marque l'instance `busy`, la libère dans un
  `finally`, et une instance occupée n'est **jamais** évincée.
- **Éviction LRU au-delà de `max_loaded_models` (2 par défaut).** Un modèle
  résident coûte des centaines de Mo (poids + activations) ; dix modèles
  résidents épuisent la mémoire — leçon déjà payée par le benchmark de la version
  précédente. Le verrou n'est **pas** tenu pendant le chargement (il peut durer :
  téléchargement de 137 Mo).
- **Préchauffage** (`TRAFFIC_WARMUP=true`) : une inférence factice sur
  `np.zeros((640, 640, 3))` au démarrage, dans une tâche de fond du `lifespan`,
  pour que la première requête réelle ne paie ni le chargement ni la fusion du
  modèle. Un échec de préchauffage est **journalisé, pas fatal**.
- **Téléchargement rangé** : Ultralytics dépose le poids dans le répertoire
  courant s'il n'existe pas au chemin demandé ; le registre le déplace ensuite
  dans `weights_dir` pour que les démarrages suivants le retrouvent.
- Verrou `threading.Lock` autour de l'état de résidence : le registre est
  appelé depuis des threads workers.

## 4. `UltralyticsEngine` — l'adaptateur, seul importateur d'ultralytics

C'est **ici et nulle part ailleurs** que `Results`/`Boxes`/`xyxy` deviennent des
`TrackObservation`.

```python
def probe(self, video_path) -> VideoInfo         # cv2.VideoCapture, fps par défaut 30
def iter_video(self, video_path, spec) -> Iterator[EngineFrame]
def open_stream(self, spec) -> TrackingStream
```

- `iter_video` ouvre **un bail pour toute l'itération** et appelle
  `model.track(source=…, stream=True, tracker=<botsort_reid.yaml>, conf, iou,
  classes=[2,3,5,7], device, half, vid_stride=stride, verbose=False)`.
- `frame_index = enumerate_index × stride` et
  **`timestamp_ms = frame_index / fps × 1000`** : le temps de scène est vrai par
  construction. Ne jamais utiliser `time.time()` ici.
- **`boxes.id is None` ⇒ liste vide** : le tracker n'a encore rien confirmé sur
  cette frame. Ce n'est pas une erreur.
- `zip(..., strict=True)` sur les tableaux parallèles : une désynchronisation
  entre boîtes, ids, classes et scores doit lever, pas produire des chiffres.
- Les labels viennent de `result.names` (dict) avec repli sur `str(class_id)`.
- `UltralyticsStream` (temps réel) : `persist=True` — c'est ce qui fait d'une
  suite d'images un **flux** et non des frames indépendantes — et **garde le bail
  ouvert** jusqu'à `close()`.

### `config/botsort_reid.yaml`
BoT-SORT avec `with_reid: true` (ReID d'apparence gratuit), et
**`track_buffer: 75`** ≈ 2,5 s à 30 fps — le miroir exact du `max_lost_ms` du
domaine. Les deux valeurs doivent être commentées l'une par rapport à l'autre :
si l'une change, l'autre doit suivre, sinon le moteur et le domaine ne sont plus
d'accord sur ce qu'est « une piste perdue ».

> **Pourquoi pas `ultralytics.solutions.ObjectCounter`** (à écrire dans une
> ADR) : une région par instance alors qu'il nous faut N lignes **et** des zones
> sur un même flux ; déduplication une fois par id de piste sans règle par
> identité et par sens ; pas de ligne liée à une zone ; pas de report `minHits`.
> Ultralytics fait la détection **et le suivi** ; notre domaine fait le comptage.

## 5. ANPR — `OnnxPlateDetector`

- Port `PlateDetector.detect(image, box) -> list[PlateDetection]`.
- **Deux étages, pour une raison mesurée** : une plaque fait ~15 px de large sur
  un plan large 1920×1080, ~240 px une fois recadrée sur son véhicule. Le modèle
  plein cadre ne la voit pas.
- Refus si le crop fait moins de 32 px de côté.
- Chargement **paresseux** derrière un verrou (le modèle n'est chargé qu'à la
  première utilisation réelle) ; l'absence du fichier n'empêche pas le service
  de démarrer : on journalise un avertissement et l'option ANPR est signalée
  indisponible dans `/api/v1/health` et `/api/v1/models`.
- Les boîtes rendues sont **réexprimées en coordonnées de l'image complète**
  (`+ x1`, `+ y1`). Aucune couche en aval ne doit avoir à le savoir.
- Une exception du modèle de plaques est **capturée et journalisée**, et rend une
  liste vide : une passe ANPR ratée ne doit jamais faire échouer un comptage.
- `scripts/fetch_plate_model.py` télécharge le `.onnx` depuis une URL
  configurable, **vérifie une somme SHA-256** et le range dans `weights_dir`.
  L'URL et la somme sont dans `.env.example` et documentées dans le README.

### Coût à documenter
La passe ANPR ajoute **une inférence par piste et par frame**. Mesuré sur la
version précédente : ~880 ms par frame avec 3 pistes. Le coût croît
linéairement avec le nombre de pistes — l'UI doit le dire dans l'infobulle de
l'option, et le service doit journaliser le surcoût moyen en fin de job.

## 6. Benchmark — désormais **côté serveur**

C'est la fonctionnalité qui remplace `useModelBenchmark` du frontend. Elle
mesure les modèles là où l'inférence a lieu : sur la machine du serveur.

### Contrat
`POST /api/v1/benchmark` avec `{ modelIds?: string[], frames?: int,
imageSource?: "sample" | "job", jobId?: string }` → `202 { runId }`,
progression en **SSE** `GET /api/v1/benchmark/{runId}/events`, résultat
`GET /api/v1/benchmark/{runId}`.

### Protocole de mesure (à respecter, sinon les chiffres ne veulent rien dire)
1. Une **image de référence** unique pour tous les modèles : soit une frame
   extraite d'un job existant (`jobId`), soit l'image d'exemple embarquée. Une
   comparaison sur des images différentes ne compare rien.
2. Pour chaque modèle, dans l'ordre du catalogue :
   `load_ms` (0 si déjà résident — ne pas inventer un chargement rapide),
   puis **1 run de chauffe écarté**, puis `frames` runs (défaut **5**).
3. On rapporte la **médiane** de `inference_ms`, plus `p95`, plus
   `preprocess_ms` / `postprocess_ms` si Ultralytics les expose (`result.speed`),
   plus le nombre de détections retenues.
4. **Les seuils utilisés sont les seuils vivants** (ceux de la requête, pas ceux
   du catalogue) : sinon la colonne « détections » contredit ce que l'utilisateur
   voit à l'écran.
5. **Libération après mesure** : chaque modèle est déchargé après son passage,
   sauf celui utilisé par une analyse en cours. Vingt modèles résidents = mémoire
   épuisée. Le fait d'avoir libéré est **dit dans la réponse**
   (`released: true`) et affiché en infobulle.
6. Un échec sur un modèle (téléchargement, mémoire) est **capturé par modèle** :
   la ligne porte `error` et le benchmark continue.
7. Le run est **persisté** (table `benchmark_runs` + `benchmark_entries`) avec le
   device, la version d'Ultralytics et un hash de l'image de référence : un
   résultat sans son contexte matériel est trompeur.
8. Un seul benchmark à la fois (`asyncio.Semaphore(1)`), annulable
   (`DELETE /api/v1/benchmark/{runId}`).

### Ce que l'UI en fait
Une page paresseuse `/benchmark` : tableau triable (modèle, palier,
chargement, inférence médiane, p95, détections, erreur), barre de progression,
bouton d'annulation, rappel du device, et **le dernier run rechargé depuis la
base** à l'ouverture — pas d'écran vide alors qu'une mesure existe.

## 7. `ModelService` (application) — ce que l'API voit

```python
class ModelService:
    def catalogue_with_state(self) -> list[ModelInfo]   # + loaded, + downloaded, + size réelle
    def device(self) -> str
    def ultralytics_version(self) -> str                # "indisponible" si l'import échoue
    def plate_available(self) -> bool
    async def preload(self, model_id: str) -> None       # thread worker
    def unload(self, model_id: str) -> bool
```

`available` ne mentait pas dans la version précédente, mais il était optimiste :
les poids se téléchargeant à la demande, la disponibilité réelle ne se prouve
qu'au chargement. Le nouveau contrat distingue donc :
`downloaded` (le fichier est là), `loaded` (résident en mémoire), `available`
(présent au catalogue). L'UI affiche ces trois états distinctement — c'est ce qui
évite « pourquoi ma première analyse a mis 90 secondes ».
