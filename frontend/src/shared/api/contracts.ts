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
