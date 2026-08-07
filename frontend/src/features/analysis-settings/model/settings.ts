/**
 * Les réglages d'analyse, et leur **persistance tolérante aux versions**.
 *
 * Deux décisions méritent d'être lues avant de modifier ce module.
 *
 * **1. `confidenceThreshold` est `number | null`.** `null` signifie « suivre le
 * défaut », une valeur explicite signifie « je sais ce que je fais ». La distinction
 * compte parce qu'elle survit au changement de modèle : sans elle, régler la
 * confiance puis changer de modèle écraserait silencieusement le réglage — ou le
 * conserverait alors que l'utilisateur voulait repartir du défaut, et rien à l'écran
 * ne dirait lequel des deux s'est produit. Le bouton « Défaut » est le chemin de
 * retour ; avant lui, c'était le seul réglage sans réinitialisation.
 *
 * **2. Une lecture de schéma périmé rend les valeurs par défaut, jamais une
 * exception.** Un `localStorage` écrit par une version antérieure de l'application
 * est le cas **normal** après une mise à jour, pas une anomalie. Faire tomber
 * l'écran de comptage parce qu'un réglage a changé de forme serait absurde ; on
 * repart des défauts et l'utilisateur ne remarque rien.
 */

import type { AnalysisRequest, CountingLine, Zone } from "@/shared/api/contracts";

/**
 * Version du schéma persisté.
 *
 * **À incrémenter dès qu'un champ change de nom, de type ou de sens.** Une valeur
 * relue sous un sens différent est bien pire qu'une valeur perdue : elle produit une
 * analyse dont les réglages ne sont pas ceux que l'écran affiche.
 */
export const SETTINGS_SCHEMA_VERSION = 1;

const STORAGE_KEY = "traffic-analysis.settings.v1";

export interface AnalysisSettings {
  modelId: string;
  /** `null` = suivre le défaut du modèle. Voir la décision 1 ci-dessus. */
  confidenceThreshold: number | null;
  iouThreshold: number;
  minHits: number;
  maxLostMs: number;
  reidMinSimilarity: number;
  maskOutsideZones: boolean;
  frameStride: number;
  detectPlates: boolean;
  plateConfidence: number | null;
  /**
   * Lire le **texte** des plaques, en plus de les encadrer.
   *
   * Subordonné à `detectPlates` — sans boîte, il n'y a rien à lire — et gardé par
   * `plateOcrAvailable`, qui décrit un **autre** fichier que `plateAvailable`.
   *
   * Pas d'incrément de `SETTINGS_SCHEMA_VERSION` pour ce champ : la fusion est champ
   * par champ, donc un `localStorage` écrit avant lui reprend simplement le défaut.
   * La version se réserve aux champs qui changent de **sens**, où relire une valeur
   * ancienne produirait une analyse différente de ce que l'écran affiche.
   */
  readPlateText: boolean;
  /** `null` = échelle non définie : les vitesses restent en px/s. */
  pixelsPerMeter: number | null;
  showTrails: boolean;
}

/** Défauts alignés sur ceux du serveur, pour que l'écran ne mente pas. */
export const DEFAULT_SETTINGS: AnalysisSettings = {
  modelId: "yolov8n",
  confidenceThreshold: null,
  iouThreshold: 0.45,
  minHits: 2,
  maxLostMs: 2_500,
  reidMinSimilarity: 0.8,
  maskOutsideZones: false,
  frameStride: 1,
  detectPlates: false,
  plateConfidence: null,
  // Faux par défaut : l'OCR est un surcoût, et persister un texte de plaque franchit
  // un cran de confidentialité qui doit être choisi, pas hérité.
  readPlateText: false,
  pixelsPerMeter: null,
  showTrails: true,
};

/** Confiance effective quand l'utilisateur suit le défaut. */
export const DEFAULT_CONFIDENCE = 0.35;

/** Bornes acceptées par le serveur — les dépasser produirait un 422. */
export const BOUNDS = {
  confidenceThreshold: { min: 0.01, max: 0.99, step: 0.01 },
  iouThreshold: { min: 0.05, max: 0.95, step: 0.05 },
  minHits: { min: 1, max: 10, step: 1 },
  maxLostMs: { min: 200, max: 15_000, step: 100 },
  reidMinSimilarity: { min: 0.5, max: 0.99, step: 0.01 },
  frameStride: { min: 1, max: 5, step: 1 },
  plateConfidence: { min: 0.05, max: 0.95, step: 0.05 },
  pixelsPerMeter: { min: 0, max: 500, step: 0.5 },
} as const;

/**
 * Construit la requête envoyée au serveur.
 *
 * C'est **le seul endroit** où `confidenceThreshold: null` devient un nombre : le
 * serveur n'accepte pas `null`, et résoudre le défaut plus tôt ferait perdre
 * l'information « je suis le défaut ».
 *
 * `pixelsPerMeter: 0` est traduit en `null` : le curseur utilise 0 pour « non
 * définie », mais le serveur refuse `0` (`gt=0`) — et il a raison, une échelle nulle
 * n'a pas de sens.
 */
export function toRequest(
  settings: AnalysisSettings,
  lines: readonly CountingLine[],
  zones: readonly Zone[],
): AnalysisRequest {
  return {
    modelId: settings.modelId,
    confidenceThreshold: settings.confidenceThreshold ?? DEFAULT_CONFIDENCE,
    iouThreshold: settings.iouThreshold,
    minHits: settings.minHits,
    maxLostMs: settings.maxLostMs,
    reidMinSimilarity: settings.reidMinSimilarity,
    maskOutsideZones: settings.maskOutsideZones && zones.length > 0,
    frameStride: settings.frameStride,
    detectPlates: settings.detectPlates,
    plateConfidence: settings.detectPlates ? settings.plateConfidence : null,
    // Subordonné à `detectPlates`, comme côté serveur : lire sans détecter n'a pas de
    // sens, et laisser passer `true` seul demanderait au serveur d'arbitrer une
    // incohérence que le client pouvait éviter.
    readPlateText: settings.detectPlates && settings.readPlateText,
    pixelsPerMeter:
      settings.pixelsPerMeter !== null && settings.pixelsPerMeter > 0
        ? settings.pixelsPerMeter
        : null,
    lines: [...lines],
    zones: [...zones],
  };
}

/**
 * Relit les réglages persistés, en repartant des défauts au moindre doute.
 *
 * **Ne lève jamais.** Les trois cas d'échec — pas de stockage (navigation privée),
 * JSON illisible, schéma d'une autre version — mènent tous au même résultat : les
 * défauts. C'est le comportement attendu après une mise à jour de l'application.
 *
 * La fusion est champ par champ et **typée** : un champ absent prend son défaut, un
 * champ du mauvais type est ignoré. Un `Object.assign` global laisserait passer une
 * chaîne là où un nombre est attendu, et le serveur refuserait la requête en 422
 * sans que l'utilisateur comprenne quel réglage est en cause.
 */
export function loadSettings(storage: Pick<Storage, "getItem"> | null = safeStorage()): AnalysisSettings {
  if (storage === null) return { ...DEFAULT_SETTINGS };

  let raw: string | null;
  try {
    raw = storage.getItem(STORAGE_KEY);
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
  if (raw === null) return { ...DEFAULT_SETTINGS };

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { ...DEFAULT_SETTINGS };
  }

  if (typeof parsed !== "object" || parsed === null) return { ...DEFAULT_SETTINGS };
  const record = parsed as Record<string, unknown>;

  // Version différente = forme inconnue. On ne devine pas : une valeur relue sous
  // un sens différent produirait une analyse dont les réglages ne sont pas ceux
  // que l'écran affiche.
  if (record.version !== SETTINGS_SCHEMA_VERSION) return { ...DEFAULT_SETTINGS };

  const settings = record.settings;
  if (typeof settings !== "object" || settings === null) return { ...DEFAULT_SETTINGS };

  return mergeSettings(settings as Record<string, unknown>);
}

/** Fusion typée, champ par champ. */
function mergeSettings(source: Record<string, unknown>): AnalysisSettings {
  const merged = { ...DEFAULT_SETTINGS };

  if (typeof source.modelId === "string" && source.modelId !== "") {
    merged.modelId = source.modelId;
  }
  merged.confidenceThreshold = nullableNumber(source.confidenceThreshold, merged.confidenceThreshold);
  merged.iouThreshold = boundedNumber(source.iouThreshold, merged.iouThreshold, BOUNDS.iouThreshold);
  merged.minHits = boundedNumber(source.minHits, merged.minHits, BOUNDS.minHits);
  merged.maxLostMs = boundedNumber(source.maxLostMs, merged.maxLostMs, BOUNDS.maxLostMs);
  merged.reidMinSimilarity = boundedNumber(
    source.reidMinSimilarity,
    merged.reidMinSimilarity,
    BOUNDS.reidMinSimilarity,
  );
  merged.frameStride = boundedNumber(source.frameStride, merged.frameStride, BOUNDS.frameStride);
  merged.plateConfidence = nullableNumber(source.plateConfidence, merged.plateConfidence);
  merged.pixelsPerMeter = nullableNumber(source.pixelsPerMeter, merged.pixelsPerMeter);

  if (typeof source.maskOutsideZones === "boolean") merged.maskOutsideZones = source.maskOutsideZones;
  if (typeof source.detectPlates === "boolean") merged.detectPlates = source.detectPlates;
  if (typeof source.readPlateText === "boolean") merged.readPlateText = source.readPlateText;
  if (typeof source.showTrails === "boolean") merged.showTrails = source.showTrails;

  return merged;
}

function boundedNumber(
  value: unknown,
  fallback: number,
  bounds: { min: number; max: number },
): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  // Borné plutôt que rejeté : une valeur légèrement hors bornes vient d'un
  // changement de bornes entre versions, et la ramener dans l'intervalle respecte
  // mieux l'intention de l'utilisateur que de l'oublier.
  return Math.min(bounds.max, Math.max(bounds.min, value));
}

function nullableNumber(value: unknown, fallback: number | null): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  return value;
}

/** Écrit les réglages. Silencieux en cas d'échec : ce n'est pas critique. */
export function saveSettings(
  settings: AnalysisSettings,
  storage: Pick<Storage, "setItem"> | null = safeStorage(),
): void {
  if (storage === null) return;
  try {
    storage.setItem(
      STORAGE_KEY,
      JSON.stringify({ version: SETTINGS_SCHEMA_VERSION, settings }),
    );
  } catch {
    // Quota dépassé ou navigation privée : perdre une préférence n'est pas une
    // raison de faire échouer une analyse.
  }
}

/**
 * `localStorage` s'il est accessible.
 *
 * Y accéder **lève** dans un iframe restreint ou avec les cookies tiers bloqués :
 * ce n'est pas seulement `null`, c'est une exception au premier accès.
 */
function safeStorage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}
