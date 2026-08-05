/**
 * Miroir TypeScript des schémas du backend.
 *
 * **Les noms correspondent exactement à `backend/src/traffic_analysis/**\/schemas.py`
 * — c'est un contrat, pas une coïncidence.** Le backend sérialise en camelCase
 * précisément pour que ce fichier soit une transcription et non une traduction.
 *
 * Quand le backend renomme un champ, le test de fixture casse ici. C'est le seul
 * garde-fou automatique entre les deux moitiés du projet.
 */

/** Corps d'erreur RFC 9457, servi en `application/problem+json`. */
export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  /** Message français destiné à l'utilisateur. */
  detail: string;
  /** Code machine stable, sur lequel un client peut brancher. */
  code: string;
  instance: string | null;
  requestId: string | null;
}

/** Diagnostic du service — ce que le badge d'état affiche en permanence. */
export interface Health {
  status: "ok";
  version: string;
  environment: string;
  /** « cpu », « 0 », « cuda:0 »… */
  device: string;
  /** Toujours faux hors GPU : en fp16 sur CPU, l'inférence ralentit. */
  half: boolean;
  ultralyticsVersion: string;
  loadedModels: string[];
  maxLoadedModels: number;
  /** Faux ⇒ l'option de lecture de plaques est désactivée dans l'interface. */
  plateAvailable: boolean;
  defaultModelId: string;
}

export type ModelTier = "nano" | "small" | "medium" | "large" | "xlarge";

/**
 * Un détecteur du catalogue.
 *
 * Trois états distincts, et les confondre est ce qui produisait le
 * « pourquoi ma première analyse a mis 90 secondes » :
 * présent au catalogue, `downloaded` sur ce serveur, `loaded` en mémoire.
 */
export interface VehicleModel {
  id: string;
  label: string;
  family: string;
  tier: ModelTier;
  tierLabel: string;
  note: string;
  /** Estimation du catalogue, pour annoncer un téléchargement avant qu'il ait lieu. */
  sizeMb: number;
  /** Taille réelle sur disque, ou `null` si le poids n'est pas là. */
  sizeBytes: number | null;
  downloaded: boolean;
  loaded: boolean;
  isDefault: boolean;
}

export interface ModelCatalogue {
  models: VehicleModel[];
  tiers: { id: ModelTier; label: string }[];
  device: string;
  half: boolean;
  ultralyticsVersion: string;
  plateAvailable: boolean;
  loadedIds: string[];
  maxLoadedModels: number;
}

export type JobStatus = "queued" | "running" | "done" | "error" | "cancelled";

export interface Job {
  jobId: string;
  status: JobStatus;
  /** Fraction accomplie, bornée à 1. */
  progress: number;
  /** En images **analysées**, pas en images du fichier. */
  processedFrames: number;
  totalFrames: number;
  processingFps: number;
  /** Message destiné à l'utilisateur, jamais une trace. */
  error: string | null;
  modelId: string;
  fileName: string;
  createdAt: string;
  finishedAt: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

/** Statuts terminaux : au-delà, un job ne change plus. */
export const TERMINAL_STATUSES: readonly JobStatus[] = ["done", "error", "cancelled"];

export function isTerminal(status: JobStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

/* ═══════════════════════════════════════════════════════════════════════════
   Géométrie — ce que le client envoie au serveur.

   Les coordonnées sont en **pixels de la vidéo source**, jamais en pixels CSS
   (invariant 2 du projet). La conversion se fait au dessin, côté canvas.
   ═══════════════════════════════════════════════════════════════════════════ */

export interface Point {
  x: number;
  y: number;
}

/**
 * Une ligne de comptage.
 *
 * `color` appartient à l'interface : le serveur l'accepte pour qu'une
 * configuration soit rejouable à l'identique, et ne l'interprète **jamais**.
 *
 * `zoneId` restreint la ligne à une zone : `null` signifie « toute l'image ».
 */
export interface CountingLine {
  id: string;
  name: string;
  color: string;
  zoneId: string | null;
  a: Point;
  b: Point;
}

export interface Zone {
  id: string;
  name: string;
  color: string;
  /** Au moins trois sommets — le serveur refuse en dessous. */
  points: Point[];
}

/** Configuration d'une analyse, telle que `POST /jobs` l'attend dans `request`. */
export interface AnalysisRequest {
  modelId: string;
  confidenceThreshold: number;
  iouThreshold: number;
  minHits: number;
  maxLostMs: number;
  reidMinSimilarity: number;
  maskOutsideZones: boolean;
  frameStride: number;
  detectPlates: boolean;
  plateConfidence: number | null;
  /** `null` ⇒ les vitesses restent en px/s au lieu d'être converties à tort. */
  pixelsPerMeter: number | null;
  lines: CountingLine[];
  zones: Zone[];
}

/* ═══════════════════════════════════════════════════════════════════════════
   Résultat d'analyse — miroir de `counting/application/serializers.py`.

   C'est le seul objet que le backend sert **sans validation pydantic** : le
   revalider doublerait la mémoire d'une timeline de plusieurs centaines de Mo.
   Ce fichier est donc la seule description typée qui existe de sa forme, et la
   fixture committée est ce qui empêche les deux moitiés de diverger.
   ═══════════════════════════════════════════════════════════════════════════ */

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface PlateDetection {
  box: Box;
  score: number;
}

/** Une piste, telle qu'une frame de la timeline la fige. */
export interface TrackSnapshot {
  trackId: number;
  /** Identité stable au travers des occlusions. C'est **sous elle** qu'on compte. */
  globalId: number;
  classId: number;
  /** Lecture de la frame courante — peut vaciller d'une image à l'autre. */
  label: string;
  /**
   * Libellé **voté** sur la galerie d'apparence.
   *
   * Le canvas colore par lui et non par `label` : une lecture qui vacille ne doit
   * pas faire clignoter la couleur de la boîte.
   */
  identityLabel: string;
  score: number;
  box: Box;
  /** Images accumulées. En dessous de `minHits`, la boîte est en pointillés. */
  hits: number;
  counted: boolean;
  reidCount: number;
  speedPxS: number | null;
  plates: PlateDetection[];
}

export interface TimelineRow {
  frameIndex: number;
  /** Temps de **scène** (`frameIndex / fps × 1000`), jamais l'horloge murale. */
  timestampMs: number;
  tracks: TrackSnapshot[];
}

export interface CrossingEvent {
  lineId: string;
  globalId: number;
  trackId: number;
  label: string;
  /** Signe du côté d'arrivée par rapport à la ligne orientée A→B : `+1` ou `-1`. */
  direction: number;
  timestampMs: number;
  frameIndex: number;
}

export interface ZoneEntryEvent {
  zoneId: string;
  globalId: number;
  label: string;
  timestampMs: number;
  frameIndex: number;
}

export interface VehicleRecord {
  globalId: number;
  label: string;
  firstSeenMs: number;
  lastSeenMs: number;
  crossedLines: { lineId: string; direction: number; timestampMs: number }[];
  zonesVisited: string[];
  reidCount: number;
  avgSpeedPxS: number | null;
  /** `null` sans échelle px/m — et non 0, qui voudrait dire « à l'arrêt ». */
  avgSpeedKmh: number | null;
  bestPlateScore: number | null;
}

export interface VideoInfo {
  width: number;
  height: number;
  fps: number;
  frameCount: number;
  durationMs: number;
}

export interface LineTally {
  total: number;
  byClass: Record<string, number>;
  byDirection: { positive: number; negative: number };
}

export interface ZoneTally {
  entries: number;
  /** Occupation **instantanée**, pas un cumul : elle redescend. */
  inside: number;
  byClass: Record<string, number>;
}

/**
 * Le diagnostic qui rend « le compte est faux » diagnosticable.
 *
 * Sans lui, un véhicule manquant est un mystère ; avec lui, on sait s'il n'a
 * jamais été détecté, l'a été faiblement, n'était pas confirmé, ou a été masqué
 * par une zone.
 */
export interface Diagnostics {
  highDetections: number;
  lowDetections: number;
  maskedOut: number;
  confirmedTracks: number;
  tentativeTracks: number;
  rescuedByLowScore: number;
}

/**
 * Statistiques d'une analyse.
 *
 * Deux invariants que le frontend ne doit jamais recalculer autrement :
 * `crossings === Σ byLine[*].total` et `total === positive + negative`.
 */
export interface AnalysisStats {
  uniqueVehicles: number;
  uniqueByClass: Record<string, number>;
  crossings: number;
  byClass: Record<string, number>;
  byLine: Record<string, LineTally>;
  byZone: Record<string, ZoneTally>;
  reidHits: number;
  vehiclesPerMinute: number;
  activeTracks: number;
  elapsedMs: number;
  analysedSceneMs: number;
  diagnostics: Diagnostics;
}

export interface AnalysisResult {
  jobId: string;
  modelId: string;
  processingFps: number;
  video: VideoInfo;
  timeline: TimelineRow[];
  crossings: CrossingEvent[];
  zoneEvents: ZoneEntryEvent[];
  vehicles: VehicleRecord[];
  stats: AnalysisStats;
}

/* ═══════════════════════════════════════════════════════════════════════════
   Benchmark — miroir de `benchmark/api/schemas.py`.
   ═══════════════════════════════════════════════════════════════════════════ */

export type BenchmarkStatus = JobStatus;

export interface BenchmarkEntry {
  modelId: string;
  label: string;
  tier: string;
  /** **0 si le modèle était déjà résident** — pas une mesure manquante. */
  loadMs: number;
  /** La valeur à lire : une médiane, qu'une seule valeur aberrante ne déplace pas. */
  medianMs: number;
  /** Ce que la médiane a écarté reste visible ici. */
  p95Ms: number;
  minMs: number;
  maxMs: number;
  /** Dérivée de la médiane, jamais mesurée à part. */
  fps: number;
  /** `null` si le moteur ne l'expose pas — et non 0, qui se lirait « instantané ». */
  preprocessMs: number | null;
  postprocessMs: number | null;
  detections: number;
  frames: number;
  wasLoaded: boolean;
  /** `false` ⇒ l'instance servait une analyse en cours, le registre a refusé. */
  released: boolean;
  error: string | null;
}

export interface BenchmarkRun {
  runId: string;
  status: BenchmarkStatus;
  progress: number;
  completed: number;
  total: number;
  error: string | null;
  device: string;
  half: boolean;
  ultralyticsVersion: string;
  frames: number;
  imageSource: "sample" | "job";
  /** Deux runs ne sont comparables que s'ils portent le même hash. */
  imageHash: string;
  imageWidth: number;
  imageHeight: number;
  jobId: string | null;
  confidenceThreshold: number;
  iouThreshold: number;
  fastestModelId: string | null;
  entries: BenchmarkEntry[];
}
