/**
 * Recherche d'un véhicule par image de requête.
 *
 * Cette feature n'en connaît aucune autre : elle reçoit un état de requête et rend un
 * tiroir de réglage plus les fonctions de cadrage. C'est le studio qui la câble, et
 * c'est lui qui envoie la vignette au serveur — même contrat que `geometry-editor` et
 * `alerts`.
 *
 * La **règle de correspondance** vit dans `model/query.ts` et nulle part ailleurs :
 * trois lecteurs en ont besoin — le tiroir, les alertes et la colonne du registre — et
 * trois copies d'un seuil finiraient par diverger sur un écran qui signale et un autre
 * qui compte.
 */

export { cropToJpeg, MAX_QUERY_SIDE_PX } from "./model/crop";
export {
  clampCrop,
  DEFAULT_MATCH_THRESHOLD,
  FULL_CROP,
  isArmed,
  matches,
  matchStrength,
  MIN_CROP_FRACTION,
  NO_QUERY,
  type CropRect,
  type VehicleQuery,
} from "./model/query";
export { VehicleSearchPanel } from "./ui/VehicleSearchPanel";
