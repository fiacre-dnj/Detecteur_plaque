/** `features/results-dashboard` — ce que l'analyse a trouvé, chiffre par chiffre. */

export {
  type DirectionRow,
  type FlowBalance,
  type Movement,
  directionRows,
  flowBalance,
  movements,
} from "./model/directions";

export {
  VEHICLE_CLASSES,
  classLabel,
  crossingRate,
  directionArrow,
  directionLabel,
  formatCrossingRate,
  formatFrameLatency,
  formatSceneTime,
  formatScore,
  formatSpeed,
  plural,
  type VehicleClass,
} from "./model/labels";

export {
  ClassBreakdown,
  LineAndZoneDetail,
  MovementMatrix,
  ResultsDashboard,
} from "./ui/ResultsDashboard";
