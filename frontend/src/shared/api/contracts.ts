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
  /**
   * Pourquoi `device` vaut cette valeur : configuré explicitement, GPU détecté,
   * aucun GPU détecté, torch indisponible, ou repli après un échec d'inférence
   * constaté au préchauffage. Un « cpu » seul ne distingue pas ces causes, qui
   * n'appellent pas le même geste — installer un pilote n'est pas la même chose
   * que revoir un réglage explicite.
   */
  deviceReason: string | null;
  /** Nom du GPU retenu par le pilote, `null` hors GPU. */
  gpuName: string | null;
  /** Toujours faux hors GPU : en fp16 sur CPU, l'inférence ralentit. */
  half: boolean;
  ultralyticsVersion: string;
  loadedModels: string[];
  maxLoadedModels: number;
  /**
   * Le modèle de **détection** de plaques est présent.
   *
   * Faux ⇒ l'option ANPR est désactivée dans l'interface. Ne dit **rien** de la lecture
   * du texte, qui dépend d'un autre fichier — voir `plateOcrAvailable`.
   */
  plateAvailable: boolean;
  /**
   * Le modèle de **lecture** et son dictionnaire de caractères sont présents.
   *
   * Distinct de `plateAvailable` : deux artefacts, récupérés par deux scripts, et
   * « détection sans lecture » est l'état de tout déploiement neuf. Faux ⇒ les plaques
   * sont encadrées mais leur texte n'est pas lu, et l'interface doit le dire plutôt
   * que de proposer une case qui ne fait rien.
   */
  plateOcrAvailable: boolean;
  defaultModelId: string;
  /**
   * Répertoire **résolu** où le serveur cherche ses poids, en absolu.
   *
   * Exposé pour la même raison que `plateAvailable` : un opérateur doit pouvoir
   * voir *où* le service regarde. Un `plateAvailable: false` avec le bon fichier
   * au bon endroit ne s'explique autrement que par une fouille du disque.
   */
  weightsDir: string;
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
  /** Deux drapeaux et non un : le détecteur et le lecteur sont deux artefacts. */
  plateOcrAvailable: boolean;
  loadedIds: string[];
  maxLoadedModels: number;
}

/**
 * `paused` est un état **vivant**, pas terminal : le serveur garde l'analyse en
 * mémoire, arrêtée entre deux images, et la reprise continue la même — mêmes
 * identités, mêmes totaux. Un job suspendu occupe donc toujours sa place de
 * calcul, ce que l'interface doit dire.
 */
export type JobStatus = "queued" | "running" | "paused" | "done" | "error" | "cancelled";

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
  /**
   * Code **stable** de l'échec, à côté du message français.
   *
   * Deux champs et non un, pour la raison qui vaut côté serveur : le message se
   * réécrit sans casser de client, le code non. C'est lui — et jamais une
   * correspondance sur le texte — qui décide de l'action proposée avec l'erreur,
   * comme le bouton « précharger puis relancer » sur `model_unavailable`.
   */
  errorCode: string | null;
  /**
   * Le modèle se charge — **état de passage, jamais persisté**.
   *
   * Pas un `JobStatus` : en faire un toucherait `isTerminal`, `statusLabel` et
   * tous leurs tests pour un état qui ne dure que le temps d'un chargement. Vrai
   * uniquement sur l'unique trame publiée avant le passage en « en cours », et
   * c'est elle qui permet d'écrire « Préparation : chargement du modèle » au lieu
   * de « 0 / 0 images · 0.0 img/s » — le 0 % que l'utilisateur lisait comme une
   * panne pendant la minute de téléchargement.
   */
  preparing: boolean;
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
  /**
   * Lire le **texte** des plaques localisées, en plus de les encadrer.
   *
   * Subordonné à `detectPlates` — sans boîte, il n'y a rien à lire — et ignoré si
   * `plateOcrAvailable` est faux. Un drapeau distinct parce que l'OCR a son propre
   * coût et parce que persister un texte de plaque franchit un cran de
   * confidentialité qui mérite un consentement explicite.
   */
  readPlateText: boolean;
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

/**
 * Une plaque repérée sur un véhicule suivi.
 *
 * `box` et `score` viennent du **détecteur** ; `text` et `textScore` de l'**OCR**,
 * qui est une seconde passe optionnelle. Les deux couples sont donc indépendants, et
 * c'est ce qui rend trois états distinguables : pas de plaque du tout, une plaque vue
 * mais illisible (`text === null` avec un `score` bien réel), une plaque lue. Les
 * confondre afficherait « aucune plaque » sur un véhicule dont le rectangle jaune est
 * visible à l'écran — la contradiction la plus rapide à repérer et la plus longue à
 * expliquer.
 *
 * `text` n'est rempli qu'une image sur trois : l'OCR est étranglée côté serveur. Pour
 * une étiquette stable, c'est `TrackSnapshot.plateText` qu'il faut lire.
 */
export interface PlateDetection {
  box: Box;
  score: number;
  /** `null` quand la plaque est repérée mais qu'aucune lecture n'a abouti. */
  text: string | null;
  /** Confiance de la **lecture**, distincte de celle de la détection. `null` sans texte. */
  textScore: number | null;
  /**
   * Cette boîte est une **reprojection**, pas une mesure de cette image.
   *
   * Le serveur étrangle son détecteur de plaques — c'était le poste dominant du
   * coût de l'ANPR — et donne aux images sautées l'ancre de la dernière détection
   * réelle, reprojetée sur la boîte courante du véhicule. Sans cela, le rectangle
   * disparaîtrait deux images sur trois, ce qui se lit comme un défaut de
   * détection. Le canvas le dessine d'un trait plus fin : même vocabulaire visuel
   * que les pistes non confirmées en pointillés.
   *
   * **Optionnel, et c'est délibéré** — la seule exception à la règle « `null`
   * explicite » de ce fichier. Un booléen porté par 100 % des plaques de 45 000
   * images pèse sur chaque octet du résultat, alors qu'il n'a de sens que dans le
   * cas minoritaire. Absent signifie « mesurée sur cette image ».
   */
  stale?: boolean;
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
  /**
   * Texte de plaque **voté** sur la vie du véhicule, ou `null`.
   *
   * Même discipline qu'`identityLabel` face à `label` (invariant 4), et pour la même
   * raison pratique : `plates[].text` n'est rempli qu'une image sur trois — l'OCR est
   * étranglée côté serveur — donc dessiner celui-là ferait clignoter l'étiquette.
   * **C'est ce champ que l'overlay affiche.**
   */
  plateText: string | null;
  plateTextScore: number | null;
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
  /**
   * La plaque du véhicule **telle qu'elle était connue au moment du comptage**.
   *
   * Souvent `null` alors que le registre porte le texte, et ce n'est pas une
   * incohérence : côté serveur, un franchissement est émis *avant* la passe OCR de la
   * même image. Un franchissement dit ce que le serveur savait quand il a compté ; le
   * registre dit ce qu'il sait à la fin. **L'autorité est le registre.**
   */
  plateText: string | null;
  /** `null` et non `0` : ici l'absence de lecture et une lecture nulle diffèrent. */
  plateTextScore: number | null;
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
  /** Meilleure confiance de **détection** de plaque sur la vie du véhicule. */
  bestPlateScore: number | null;
  /**
   * La plaque **votée sur toute la vie du véhicule** — l'autorité de l'interface.
   *
   * `null` avec un `bestPlateScore` non nul veut dire quelque chose de précis : une
   * plaque a bien été vue, aucune lecture ne fait consensus. La colonne « Plaque » doit
   * dire *cela*, et non rester vide en face d'un rectangle visible à l'écran.
   */
  plateText: string | null;
  /** Confiance moyenne de la **lecture** gagnante. C'est l'`ocrConfidence` du vote. */
  plateTextScore: number | null;
  /**
   * **Pourquoi** aucune plaque n'est publiée. `null` quand il y en a une.
   *
   * Cinq causes parce qu'elles appellent cinq gestes différents : installer un
   * modèle, resserrer le plan, stabiliser la caméra, ou ne rien faire. Une case
   * vide, elle, se lit comme une panne du service.
   */
  plateUnreadReason: PlateUnreadReason | null;
  /**
   * Largeur de la meilleure plaque vue, en pixels. `null` si aucune.
   *
   * C'est ce chiffre qui rend la raison actionnable : « vue à 48 px » dit de
   * resserrer le plan, là où « non détectée » dit tout autre chose.
   */
  plateBestWidthPx: number | null;
  /**
   * Le meilleur candidat lu même **sans** consensus — un indice, jamais un vote.
   *
   * `null` sauf quand `plateUnreadReason === "no_consensus"` : dans les autres
   * raisons de silence, aucune lecture n'a eu lieu. Ne remplace jamais `plateText` :
   * afficher ce candidat à sa place republierait la lecture la plus favorable,
   * exactement ce que le vote sur la vie du véhicule interdit.
   */
  plateBestGuess: string | null;
  /** Confiance moyenne de `plateBestGuess`. `null` ssi lui-même l'est. */
  plateBestGuessScore: number | null;
}

/**
 * Pourquoi une plaque n'est pas publiée — miroir exact du `Literal` pydantic.
 *
 * - `ocr_disabled` : la lecture n'a pas été demandée, ou son modèle est absent.
 * - `not_detected` : aucune plaque localisée — angle, occlusion, vue de côté.
 * - `too_small` : vue, mais sous le plancher de lecture (~64 px mesurés).
 * - `too_blurry` : assez large, trop floue — flou de mouvement ou mise au point.
 * - `no_consensus` : plusieurs lectures, aucune majorité. Le refus **honnête** du
 *   vote, et non une panne.
 */
export type PlateUnreadReason =
  | "ocr_disabled"
  | "not_detected"
  | "too_small"
  | "too_blurry"
  | "no_consensus";

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
  /**
   * Boîtes écartées parce qu'incluses dans une autre — la cabine d'un
   * semi-remorque dans la boîte du véhicule entier. Sans cette suppression, elles
   * compteraient deux fois ; sans ce chiffre, la suppression serait invisible.
   */
  containedOut: number;
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

/**
 * Un aperçu de l'analyse **en cours**, reçu sur l'événement SSE `preview`.
 *
 * Même forme que le `frameResult` du temps réel, et pour la même raison : les
 * deux sortent des mêmes sérialiseurs côté serveur, donc l'overlay les dessine
 * sans branche. Deux chemins de rendu finiraient par diverger, et l'écran
 * montrerait deux vérités selon le mode.
 *
 * `crossings` et `zoneEvents` sont **cumulés depuis l'aperçu précédent**, pas
 * ceux de la seule image publiée : le serveur n'en échantillonne qu'une sur N,
 * et un journal amputé contredirait ses propres compteurs.
 *
 * `frameWidth` / `frameHeight` sont les dimensions **décodées par le serveur**.
 * Elles ne servent pas au dessin — tout est déjà en pixels source — mais à
 * refuser de dessiner si la balise `<video>` locale n'est pas d'accord.
 */
export interface JobPreview {
  jobId: string;
  frameIndex: number;
  /** Temps de **scène**, celui sur lequel caler la vidéo locale. */
  timestampMs: number;
  frameWidth: number;
  frameHeight: number;
  tracks: TrackSnapshot[];
  crossings: CrossingEvent[];
  zoneEvents: ZoneEntryEvent[];
  stats: AnalysisStats;
}

/* ═══════════════════════════════════════════════════════════════════════════
   Presets de géométrie — miroir de `presets/api/schemas.py`.
   ═══════════════════════════════════════════════════════════════════════════ */

/** Ce qu'on envoie pour enregistrer ou remplacer une géométrie. */
export interface PresetDraft {
  name: string;
  description: string;
  /** Dimensions de la vidéo sur laquelle la géométrie a été tracée. Obligatoires. */
  sourceWidth: number;
  sourceHeight: number;
  maskOutsideZones: boolean;
  lines: CountingLine[];
  zones: Zone[];
}

/**
 * Un preset tel que l'API le rend.
 *
 * `scaled` est le champ qui fait la différence entre une fonctionnalité utile et un
 * piège : vrai, il dit que les coordonnées **ne sont pas** celles qui ont été
 * enregistrées, mais une conversion vers la résolution demandée. L'interface le dit
 * à l'utilisateur — une géométrie qui bouge sans prévenir se lit comme un bug.
 */
export interface Preset {
  id: string;
  name: string;
  description: string;
  /** Résolution dans laquelle les coordonnées rendues sont exprimées. */
  sourceWidth: number;
  sourceHeight: number;
  /** Résolution pour laquelle le preset a été **enregistré**, toujours. */
  originalWidth: number;
  originalHeight: number;
  scaled: boolean;
  maskOutsideZones: boolean;
  lines: CountingLine[];
  zones: Zone[];
  createdAt: string | null;
  updatedAt: string | null;
}

/* ═══════════════════════════════════════════════════════════════════════════
   Temps réel — miroir de `realtime/api/protocol.py`.

   Le protocole est **séquencé** : `init` → `ready` → (`frame` + JPEG binaire) →
   `frameResult`. Le client n'a pas le droit d'anticiper : envoyer une frame avant
   d'avoir reçu `ready` fait échouer la session côté serveur, qui n'a pas encore
   de session de comptage.
   ═══════════════════════════════════════════════════════════════════════════ */

/** Premier message envoyé. `request` est **exactement** celle de `POST /jobs`. */
export interface InitMessage {
  type: "init";
  request: AnalysisRequest;
}

/** Annonce d'une frame, suivie **immédiatement** du JPEG en binaire. */
export interface FrameMessage {
  type: "frame";
  /** Temps de scène décidé par le client (invariant 1), jamais `Date.now()`. */
  timestampMs: number;
}

/**
 * Réponse à l'`init` — **le filet contre une géométrie mal mise à l'échelle**.
 *
 * `frameWidth`/`frameHeight` sont `null` jusqu'à la première frame : le serveur ne
 * peut pas les connaître avant d'avoir décodé une image, et les inventer serait
 * précisément le mensonge que ce message existe pour empêcher.
 */
export interface ReadyMessage {
  type: "ready";
  frameWidth: number | null;
  frameHeight: number | null;
  /** Peut différer du modèle demandé si le serveur a dû se replier. */
  modelId: string;
  device: string;
}

/**
 * Résultat d'une frame.
 *
 * `tracks`, `crossings`, `zoneEvents` et `stats` sortent des **mêmes**
 * sérialiseurs que le mode différé : l'affichage est réutilisé sans branche.
 */
export interface FrameResultMessage {
  type: "frameResult";
  timestampMs: number;
  frameIndex: number;
  /** Répétées à chaque frame : une webcam peut renégocier sa résolution. */
  frameWidth: number;
  frameHeight: number;
  tracks: TrackSnapshot[];
  crossings: CrossingEvent[];
  zoneEvents: ZoneEntryEvent[];
  stats: AnalysisStats;
}

/** Erreur **non fatale** : la session continue. Distincte d'une fermeture. */
export interface RealtimeErrorMessage {
  type: "error";
  detail: string;
  code: string;
}

export type ServerMessage = ReadyMessage | FrameResultMessage | RealtimeErrorMessage;

/* ═══════════════════════════════════════════════════════════════════════════
   Benchmark — miroir de `benchmark/api/schemas.py`.
   ═══════════════════════════════════════════════════════════════════════════ */

/**
 * Les mêmes statuts qu'un job, **sauf `paused`** : un run de benchmark ne se
 * suspend pas. Énuméré plutôt qu'aliasé sur `JobStatus` — l'alias annoncerait un
 * état que le serveur ne produit jamais ici, et l'interface écrirait du code mort
 * pour le traiter.
 */
export type BenchmarkStatus = "queued" | "running" | "done" | "error" | "cancelled";

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
