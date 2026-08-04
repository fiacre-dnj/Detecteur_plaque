# 05 — API et contrat HTTP

## 1. Principes du contrat

- **Préfixe versionné** : tout est sous `/api/v1`. Le préfixe `/api` est
  également ce qui permet au proxy Vite de distinguer l'API du repli SPA.
- **camelCase sur le fil**, `snake_case` en Python. Un `CamelModel` de base
  (pydantic `alias_generator=to_camel`, `populate_by_name=True`,
  `protected_namespaces=()` car `model_id` est un nom métier) fait la traduction.
  Le frontend a un **miroir TypeScript exact** de ces noms : c'est un contrat,
  pas une coïncidence.
- **Erreurs en Problem Details (RFC 9457)**, `application/problem+json`.
- Toute route déclare `response_model`, `status_code`, `summary`,
  `description`, `tags`, `operation_id` explicite et ses `responses` d'erreur
  avec exemples (voir [`06`](06-SECURITE-CORS-SWAGGER.md)).
- Aucune route ne rend un dict nu non typé, à une exception documentée près : le
  **résultat d'analyse**, servi tel quel depuis le fichier `json.gz` (le
  revalider en pydantic doublerait la mémoire pour rien ; son schéma est décrit
  dans OpenAPI à la main).

## 2. Vue d'ensemble

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/api/v1/health/live` | Vivacité (aucune dépendance) |
| GET | `/api/v1/health/ready` | Préparation (base joignable, catalogue lisible) |
| GET | `/api/v1/health` | Détail : device, version ultralytics, modèles résidents, ANPR dispo |
| GET | `/api/v1/models` | Catalogue + état de chaque modèle |
| POST | `/api/v1/models/{id}/preload` | Chargement anticipé (202) |
| DELETE | `/api/v1/models/{id}/loaded` | Décharge une instance résidente |
| POST | `/api/v1/jobs` | Dépose une vidéo + une configuration → 202 `{ jobId }` |
| GET | `/api/v1/jobs` | Historique paginé (persisté) |
| GET | `/api/v1/jobs/{id}` | Statut et progression |
| GET | `/api/v1/jobs/{id}/events` | **SSE** de progression |
| GET | `/api/v1/jobs/{id}/result` | Résultat complet (JSON, gzip) |
| GET | `/api/v1/jobs/{id}/vehicles` | Registre paginé (requêtable en base) |
| GET | `/api/v1/jobs/{id}/crossings` | Franchissements paginés / filtrables |
| GET | `/api/v1/jobs/{id}/export.csv` | Export CSV (registre ou franchissements) |
| DELETE | `/api/v1/jobs/{id}` | Annule si actif, purge sinon |
| WS | `/api/v1/realtime` | Comptage en direct (webcam) |
| POST | `/api/v1/benchmark` | Lance un benchmark → 202 `{ runId }` |
| GET | `/api/v1/benchmark/{runId}` | Résultat |
| GET | `/api/v1/benchmark/{runId}/events` | **SSE** de progression |
| GET | `/api/v1/benchmark/latest` | Dernier run (pour ne pas ouvrir une page vide) |
| DELETE | `/api/v1/benchmark/{runId}` | Annule |
| GET | `/api/v1/presets` | Géométries enregistrées |
| POST | `/api/v1/presets` | Enregistre une géométrie |
| GET/PUT/DELETE | `/api/v1/presets/{id}` | Lecture / mise à jour / suppression |

## 3. Schémas d'entrée

```python
class PointSchema(CamelModel):
    x: float; y: float

class LineSchema(CamelModel):
    id: str
    name: str = ""
    color: str = ""            # appartient à l'UI ; acceptée, jamais interprétée
    zone_id: str | None = None
    a: PointSchema
    b: PointSchema

class ZoneSchema(CamelModel):
    id: str
    name: str = ""
    color: str = ""
    points: list[PointSchema] = Field(min_length=3)

class AnalysisRequestSchema(CamelModel):
    model_id: str
    confidence_threshold: float = Field(0.35, ge=0.01, le=0.99)
    iou_threshold: float       = Field(0.45, ge=0.05, le=0.95)
    min_hits: int              = Field(2,    ge=1,    le=10)
    max_lost_ms: float         = Field(2500, ge=200,  le=15000)
    reid_min_similarity: float = Field(0.80, ge=0.50, le=0.99)
    mask_outside_zones: bool = False
    frame_stride: int          = Field(1, ge=1, le=10)
    detect_plates: bool = False
    plate_confidence: float | None = Field(None, ge=0.05, le=0.95)
    pixels_per_meter: float | None = Field(None, gt=0)
    lines: list[LineSchema] = []
    zones: list[ZoneSchema] = []
    def to_config(self) -> AnalysisJobConfig: ...
```

**Validations métier supplémentaires** (validateurs pydantic, message français) :
- `model_id` doit exister au catalogue (sinon 422 avec la liste des ids valides) ;
- chaque `zone_id` référencé par une ligne doit exister dans `zones` ;
- les ids de lignes et de zones doivent être uniques ;
- une ligne de longueur nulle (`a == b`) est refusée : elle ne compterait jamais
  rien, autant le dire tout de suite ;
- au moins une ligne **ou** une zone : une analyse sans géométrie ne produit
  aucun compteur (avertissement 422 explicite).

## 4. Création d'un job — la seule route multipart

`POST /api/v1/jobs`, `multipart/form-data` :
- `file` : la vidéo ;
- `request` : la `AnalysisRequestSchema` **en JSON**, validée par
  `model_validate_json` (une `ValidationError` devient 422 avec le détail).

Règles de robustesse :
1. **Écriture par morceaux** de 1 Mo, avec compteur : au-delà de
   `TRAFFIC_MAX_UPLOAD_MB`, on interrompt, on supprime le job créé et on rend
   **413** avec la limite en clair. Ne jamais charger l'upload en mémoire.
2. Un fichier **vide** ⇒ 422 « Fichier vidéo vide ».
3. **Vérification du type réel** : extension autorisée *et* `probe()` réussi
   (`cv2.VideoCapture.isOpened()` + `frame_count > 0`). Se fier au
   `content-type` du client est une faille.
4. Nom de fichier **jamais** utilisé comme chemin : le job écrit dans
   `data/jobs/<uuid4>/input<ext>`. Le nom d'origine est stocké en base pour
   l'affichage, assaini avant journalisation.
5. Réponse **202** `{ "jobId": "...", "status": "queued" }` avec un en-tête
   `Location: /api/v1/jobs/{id}`.

## 5. Statut, progression, résultat

```jsonc
// GET /api/v1/jobs/{id}
{
  "jobId": "…", "status": "running",
  "progress": 0.4213, "processedFrames": 253, "totalFrames": 600,
  "processingFps": 12.7, "error": null,
  "modelId": "yolo11m", "fileName": "carrefour.mp4",
  "createdAt": "2026-08-04T10:12:00Z", "finishedAt": null
}
```

`status ∈ {queued, running, done, error, cancelled}`.

`GET /api/v1/jobs/{id}/result` : **409** si le job n'est pas `done`, avec le
statut courant dans le message. Sinon `FileResponse` du `result.json.gz`
(`Content-Encoding: gzip`, `Cache-Control: private, max-age=31536000, immutable`
— un résultat est immuable).

### SSE de progression
`GET /api/v1/jobs/{id}/events`, `text/event-stream`, en-têtes
`Cache-Control: no-cache` et `X-Accel-Buffering: no` (sans ce dernier, un proxy
tamponne le flux et la barre paraît figée).

```
event: progress
data: {"jobId":"…","status":"running","progress":0.12,…}

event: end
data: {"jobId":"…","status":"done","progress":1.0,…}
```

Règles :
- **l'état courant est envoyé en premier** : un client qui se (re)connecte ne doit
  pas attendre la prochaine frame pour savoir où en est le job ;
- si le job est déjà terminal, on envoie `progress` puis `end` et on ferme ;
- un `ping` toutes les 15 s (commentaire SSE `: ping`) maintient la connexion à
  travers les proxys ;
- le désabonnement est garanti par un `finally`.
- **Le SSE est un accélérateur, pas la vérité** : le client double d'un sondage
  lent (3 s) sur `GET /jobs/{id}`. Le serveur doit donc rester correct si le SSE
  n'est jamais consommé.

## 6. Structure du résultat (`AnalysisResult`)

```jsonc
{
  "jobId": "…",
  "modelId": "yolo11m",
  "processingFps": 12.7,
  "video": { "width": 1920, "height": 1080, "fps": 25.0,
             "frameCount": 750, "durationMs": 30000.0 },
  "timeline": [
    { "frameIndex": 0, "timestampMs": 0.0,
      "tracks": [
        { "trackId": 3, "globalId": 1, "classId": 2, "label": "car",
          "identityLabel": "car", "score": 0.87,
          "box": { "x": 100.0, "y": 220.0, "width": 84.0, "height": 61.0 },
          "hits": 5, "counted": false, "reidCount": 0,
          "speedPxS": 412.5,
          "plates": [ { "box": {…}, "score": 0.71 } ] }
      ] }
  ],
  "crossings": [
    { "lineId": "l1", "globalId": 1, "trackId": 3, "label": "car",
      "direction": 1, "timestampMs": 4320.0, "frameIndex": 108 }
  ],
  "zoneEvents": [
    { "zoneId": "z1", "globalId": 1, "label": "car",
      "timestampMs": 4100.0, "frameIndex": 102 }
  ],
  "vehicles": [
    { "globalId": 1, "label": "car",
      "firstSeenMs": 3200.0, "lastSeenMs": 9800.0,
      "crossedLines": [ { "lineId": "l1", "direction": 1, "timestampMs": 4320.0 } ],
      "zonesVisited": ["z1"], "reidCount": 0,
      "avgSpeedPxS": 402.1, "avgSpeedKmh": null, "bestPlateScore": 0.71 }
  ],
  "stats": {
    "uniqueVehicles": 14, "uniqueByClass": { "car": 11, "truck": 3 },
    "crossings": 12, "byClass": { "car": 9, "truck": 3 },
    "byLine": { "l1": { "total": 12, "byClass": { "car": 9, "truck": 3 },
                        "byDirection": { "positive": 7, "negative": 5 } } },
    "byZone": { "z1": { "entries": 10, "inside": 0, "byClass": { "car": 8, "truck": 2 } } },
    "reidHits": 3, "vehiclesPerMinute": 24.0, "activeTracks": 4,
    "elapsedMs": 30000.0, "analysedSceneMs": 30000.0,
    "diagnostics": { "highDetections": 0, "lowDetections": 0, "maskedOut": 0,
                     "confirmedTracks": 4, "tentativeTracks": 0,
                     "rescuedByLowScore": 0 }
  }
}
```

Notes normatives :
- **`stats` a exactement la forme de l'objet que les cartes du frontend
  affichent.** L'adaptateur absorbe la différence, jamais la vue.
- `speedPxS` / `avgSpeedKmh` sont `null` tant que l'information n'existe pas
  (une seule observation, pas d'échelle). Ne jamais rendre `0` pour « inconnu ».
- `diagnostics` est renseigné de valeurs neutres côté serveur pour les compteurs
  qui n'ont de sens que frame par frame ; les champs restent présents pour que
  l'UI n'ait pas de branche conditionnelle.
- Les nombres sont **arrondis à la sérialisation** (4 décimales pour les scores,
  1 pour les pixels et les millisecondes) : cela divise la taille du JSON par
  près de deux sans rien perdre d'utile.

## 7. WebSocket temps réel

`WS /api/v1/realtime` — protocole strictement séquencé :

1. **Client → serveur**, texte : `{"type":"init", …AnalysisRequestSchema}`.
   Init invalide ⇒ fermeture code **1008** avec la raison.
2. Puis, pour chaque frame : un message **texte**
   `{"type":"frame","timestampMs":N}` **immédiatement suivi** du message
   **binaire** JPEG.
3. **Serveur → client** : `{"type":"frameResult","timestampMs":N,"tracks":[…],
   "crossings":[…],"zoneEvents":[…],"stats":{…}}`.
4. Erreur interne ⇒ fermeture **1011** ; session déjà active ⇒ **1013** avant
   `accept()`.

Règles :
- **Une frame en vol à la fois** côté client (jumeau du verrou de frame de
  l'ancien mode local) : une webcam qui produit 30 images/s noierait un serveur
  qui en traite 5, et la latence dériverait sans jamais se rattraper.
- **Une session par serveur** (`max_realtime_sessions`) : chaque session
  immobilise une instance de modèle via un bail.
- Le décodage JPEG et le `track()` partent dans un **thread worker**.
- La diagonale et la géométrie sont établies **à partir de la première frame
  reçue** : le serveur compte dans l'espace de l'image qu'il reçoit.
- **Le client réduit ses frames** (~960 px de large) et doit donc mettre la
  géométrie à la même échelle avant l'`init`. Une ligne non mise à l'échelle
  serait comptée 25 % trop haut **sans aucun message d'erreur** — le pire mode de
  défaillance possible. Le serveur se protège en renvoyant dans la réponse à
  l'init les dimensions qu'il a effectivement reçues
  (`{"type":"ready","frameWidth":…,"frameHeight":…}`), que le client compare à ce
  qu'il croit envoyer.
- **Vérification de l'`Origin`** du handshake contre `cors_origins` : un
  WebSocket n'est pas protégé par la politique de même origine.
- Fermeture propre : `finally` qui ferme le stream (et rend le bail).

## 8. Pagination, filtres, exports

`Page[T]` générique : `{ "items": [...], "total": 128, "limit": 50, "offset": 0 }`.
Bornes : `limit ≤ 200`, défaut 50.

- `GET /jobs?status=done&modelId=yolo11m&limit=&offset=` trié par `createdAt`
  décroissant.
- `GET /jobs/{id}/crossings?lineId=&direction=&fromMs=&toMs=`.
- `GET /jobs/{id}/vehicles?label=&minReid=&hasPlate=`.
- `GET /jobs/{id}/export.csv?dataset=vehicles|crossings` : `text/csv; charset=utf-8`,
  **BOM UTF-8** en tête (sans lui, Excel massacre les accents), séparateur `;`
  (convention FR), en-têtes en français, `Content-Disposition: attachment`.

## 9. Codes de statut — table de vérité

| Situation | Code |
|---|---|
| Job créé | 201/**202** (202 : l'exécution est asynchrone) |
| Job / preset / modèle inconnu | 404 |
| Résultat demandé sur job non terminé | 409 |
| Corps invalide, géométrie incohérente | 422 |
| Upload trop gros | 413 |
| Type de média non supporté | 415 |
| Débit dépassé | 429 (+ `Retry-After`) |
| Une analyse est déjà en cours et la file est pleine | 202 + statut `queued` (**pas** 503) |
| Session temps réel déjà active | WS 1013 |
| Modèle impossible à charger | 503 `model_unavailable` |
| Bug serveur | 500 sans fuite d'information |

## 10. Miroir TypeScript

`frontend/src/shared/api/contracts.ts` contient les types miroirs, avec en tête
un commentaire : « les noms correspondent exactement à
`backend/src/traffic_analysis/**/schemas.py` — c'est un contrat ». Un test
frontend vérifie qu'un échantillon de payload (fixture JSON copiée d'un vrai
résultat, committée dans `frontend/src/shared/api/__fixtures__/`) se parse sans
`any` et satisfait les types. Quand le backend change un nom, le test frontend
casse — c'est exactement ce qu'on veut.
