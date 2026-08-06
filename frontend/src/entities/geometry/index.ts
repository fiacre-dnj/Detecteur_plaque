/**
 * `entities/geometry` — la géométrie de comptage, partagée par les features.
 *
 * Un seul point d'entrée par tranche (règle FSD du projet) : une feature importe
 * `@/entities/geometry` et jamais un chemin interne. Sans cette contrainte, un
 * refactor du dossier casse dix imports dispersés.
 */

export {
  geometryReducer,
  defaultLine,
  moveHandle,
  resetIdCounter,
  translateLine,
  translateZone,
  type GeometryAction,
} from "./model/reducer";

export {
  EMPTY_GEOMETRY,
  NO_SELECTION,
  geometrySignature,
  hasGeometry,
  scaleGeometry,
  type GeometryState,
  type Selection,
} from "./model/types";
