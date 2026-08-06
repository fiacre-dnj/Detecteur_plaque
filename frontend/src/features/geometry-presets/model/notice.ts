/**
 * Ce que l'interface **dit** à propos d'un preset, avant et après le chargement.
 *
 * Séparé du composant parce que c'est la partie qui doit être juste : une phrase
 * approximative sur une géométrie qui a bougé vaut à peine mieux que le silence.
 * L'utilisateur doit apprendre trois choses en une lecture — que ses lignes ont été
 * déplacées, de quelle résolution vers quelle résolution, et qu'il devrait vérifier.
 */

import type { CountingLine, Preset, PresetDraft, Zone } from "@/shared/api/contracts";

/** Un preset a-t-il été tracé pour la résolution courante ? */
export function matchesResolution(preset: Preset, width: number, height: number): boolean {
  return preset.originalWidth === width && preset.originalHeight === height;
}

/**
 * L'avertissement affiché **avant** de charger, dans la liste.
 *
 * `null` quand les résolutions coïncident : afficher « aucune adaptation nécessaire »
 * sur chaque ligne noierait le seul cas qui mérite l'attention.
 *
 * Le texte donne les deux résolutions parce que c'est ce qui permet à l'utilisateur
 * de juger. « Adapté à votre vidéo » sans chiffres l'oblige à faire confiance ;
 * « tracé pour du 1280×720, adapté à votre 640×360 » lui dit exactement ce qui va se
 * passer, et il sait si l'écart est raisonnable.
 */
export function scalingNotice(preset: Preset, width: number, height: number): string | null {
  if (matchesResolution(preset, width, height)) return null;
  return (
    `Tracé pour du ${preset.originalWidth}×${preset.originalHeight}. ` +
    `Il sera adapté à votre ${width}×${height} — vérifiez les lignes après le chargement.`
  );
}

/**
 * Le rapport d'aspect change-t-il ?
 *
 * Un cas à signaler séparément, parce qu'il est visuellement plus violent : une mise
 * à l'échelle 16/9 → 16/9 conserve les angles, une 16/9 → 4/3 les déforme. Une ligne
 * diagonale tracée le long d'une voie ne suit plus la voie.
 *
 * La tolérance de 1 % absorbe les résolutions « presque » standard (1366×768 n'est
 * pas exactement du 16/9) sans laisser passer un vrai changement de format.
 */
export function changesAspectRatio(preset: Preset, width: number, height: number): boolean {
  if (preset.originalWidth <= 0 || preset.originalHeight <= 0 || height <= 0) return false;
  const original = preset.originalWidth / preset.originalHeight;
  const target = width / height;
  return Math.abs(original - target) / original > 0.01;
}

/** L'avertissement supplémentaire du changement de format, ou `null`. */
export function aspectNotice(preset: Preset, width: number, height: number): string | null {
  if (!changesAspectRatio(preset, width, height)) return null;
  return (
    "Le format de l'image change : les lignes obliques ne suivront plus le même angle. " +
    "Un contrôle visuel est indispensable."
  );
}

/**
 * Construit le brouillon envoyé au serveur.
 *
 * Le nom est **rogné** : un nom entouré d'espaces passerait la validation de
 * longueur, s'afficherait identique à un autre dans la liste, et rendrait l'unicité
 * inutile — deux presets « Carrefour » et « Carrefour » indiscernables à l'œil.
 */
export function toDraft(
  name: string,
  description: string,
  width: number,
  height: number,
  maskOutsideZones: boolean,
  lines: readonly CountingLine[],
  zones: readonly Zone[],
): PresetDraft {
  return {
    name: name.trim(),
    description: description.trim(),
    sourceWidth: width,
    sourceHeight: height,
    // Comme dans `toRequest` : un masque sans zone n'a aucun effet, et
    // l'enregistrer à vrai ferait recharger un réglage qui ment sur ce qu'il fait.
    maskOutsideZones: maskOutsideZones && zones.length > 0,
    lines: [...lines],
    zones: [...zones],
  };
}

/**
 * Le brouillon est-il enregistrable ?
 *
 * Les mêmes règles que le serveur, vérifiées ici pour que le bouton soit grisé
 * plutôt que pour découvrir un 422 après le clic. Le serveur reste l'autorité — on
 * duplique la règle, pas la confiance.
 */
export function draftProblem(
  name: string,
  width: number,
  height: number,
  lines: readonly CountingLine[],
  zones: readonly Zone[],
): string | null {
  if (name.trim() === "") return "Donnez un nom au preset.";
  if (name.trim().length > 120) return "Le nom ne peut pas dépasser 120 caractères.";
  if (width <= 0 || height <= 0) return "Les dimensions de la vidéo ne sont pas encore connues.";
  if (lines.length === 0 && zones.length === 0) {
    return "Tracez au moins une ligne ou une zone avant d'enregistrer.";
  }
  return null;
}
