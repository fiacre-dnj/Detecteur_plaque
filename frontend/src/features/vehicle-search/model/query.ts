/**
 * La recherche d'un véhicule par image — l'état et le cadrage, sans React.
 *
 * **Pourquoi une feature à part et non un réglage de `analysis-settings`.** Deux
 * raisons, et la seconde est structurelle :
 *
 * - `AnalysisSettings` est **persisté** dans le `localStorage`. Une photo de véhicule
 *   y tomberait sous le même cran de confidentialité qu'un numéro de plaque, que
 *   `plateWatchlist` se fait déjà retirer avant l'écriture. Une exception de plus dans
 *   `saveSettings` serait la deuxième, donc le début d'une liste ;
 * - la feature des réglages n'a pas à connaître un recadrage interactif, pas plus
 *   qu'elle ne connaît `geometry-editor`. Le studio câble, comme pour « Géométrie » et
 *   « Alertes ».
 *
 * L'état vit donc dans le studio, aux côtés de la géométrie et de l'intervalle
 * d'analyse : il décrit *cette recherche-ci*, et `resetForNewSource` le remet à neuf.
 */

import {
  DEFAULT_MATCH_THRESHOLD,
  matches,
  matchStrength,
} from "@/shared/lib/vehicleMatch";

// Réexportés : c'est `shared/lib/vehicleMatch` qui **définit** la ressemblance, parce
// que trois features la lisent. Ce module n'en garde aucune copie.
export { DEFAULT_MATCH_THRESHOLD, matches, matchStrength };


/** Bornes du recadrage, en fraction de l'image importée — jamais en pixels. */
export interface CropRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Le recadrage plein cadre : ce que vaut une image qu'on n'a pas encore ajustée.
 *
 * En fractions et non en pixels, pour la même raison que l'invariant 2 côté serveur :
 * l'image est affichée à une taille CSS qui n'a rien à voir avec sa taille réelle, et
 * mémoriser des pixels d'affichage donnerait un recadrage qui bouge avec la fenêtre.
 */
export const FULL_CROP: CropRect = { x: 0, y: 0, width: 1, height: 1 };

/** Côté minimal d'un recadrage, en fraction — en dessous il n'y a plus d'image. */
export const MIN_CROP_FRACTION = 0.05;

/** Ce que le studio retient d'une recherche par image. */
export interface VehicleQuery {
  /** Le fichier importé, tel quel. `null` = aucune recherche en cours. */
  readonly file: File | null;
  /** Son adresse locale (`createObjectURL`), pour l'aperçu. `null` avec `file`. */
  readonly previewUrl: string | null;
  /** Le cadrage retenu, en fractions de l'image. */
  readonly crop: CropRect;
  /** Le seuil au-delà duquel un véhicule est signalé comme ressemblant. */
  readonly threshold: number;
}

export const NO_QUERY: VehicleQuery = {
  file: null,
  previewUrl: null,
  crop: FULL_CROP,
  threshold: DEFAULT_MATCH_THRESHOLD,
};

/** Une recherche est-elle réellement armée ? */
export function isArmed(query: VehicleQuery): boolean {
  return query.file !== null;
}

/**
 * Ramène un recadrage dans l'image et lui garantit un côté minimal.
 *
 * Borné **à la lecture** et non corrigé par un effet, même discipline que la
 * pagination de la Statistique : un recadrage hors bornes le temps d'un rendu
 * produirait un `drawImage` vide, donc une vignette noire envoyée au serveur — une
 * recherche qui ne trouve rien sans dire pourquoi.
 */
export function clampCrop(crop: CropRect): CropRect {
  const width = Math.min(1, Math.max(MIN_CROP_FRACTION, crop.width));
  const height = Math.min(1, Math.max(MIN_CROP_FRACTION, crop.height));
  return {
    width,
    height,
    x: Math.min(1 - width, Math.max(0, crop.x)),
    y: Math.min(1 - height, Math.max(0, crop.y)),
  };
}
