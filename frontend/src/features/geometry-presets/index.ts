/**
 * `features/geometry-presets` — enregistrer une géométrie et la recharger ailleurs.
 *
 * La règle qui gouverne cette feature : **un preset porte la résolution pour laquelle
 * il a été tracé**, et le serveur le convertit à la lecture en disant qu'il l'a fait.
 * Charger une géométrie de 1280×720 sur une vidéo de 640×360 sans conversion placerait
 * chaque ligne à deux fois sa distance du bord — sans aucune erreur.
 */

export { createPreset, deletePreset, fetchPreset, fetchPresets } from "./model/api";
export {
  aspectNotice,
  changesAspectRatio,
  draftProblem,
  matchesResolution,
  scalingNotice,
  toDraft,
} from "./model/notice";
export { useCreatePreset, useDeletePreset, usePresets } from "./model/usePresets";
export { PresetDialog } from "./ui/PresetDialog";
