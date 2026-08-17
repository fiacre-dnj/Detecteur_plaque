/** `features/results-dashboard` — ce que l'analyse a trouvé, chiffre par chiffre. */

export {
  type DirectionRow,
  type FlowBalance,
  directionRows,
  flowBalance,
  isEntryRow,
} from "./model/directions";

export {
  crossingVehicles,
  enteringVehicleCount,
  hasCrossedAnyLine,
  hasEnteredCrossroad,
} from "./model/crossedVehicles";

export { entriesByClass } from "./model/entriesByClass";

export {
  type LineHighlight,
  busiestLine,
  busiestVsQuietestShareGap,
  mostEnteredLine,
  mostExitedLine,
  strongestInflowLine,
  strongestOutflowLine,
} from "./model/highlights";

export {
  VEHICLE_CLASSES,
  classLabel,
  crossingRate,
  crossroadFlowSentence,
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

export { ClassEntriesChart } from "./ui/ClassEntriesChart";
export { ClassEntriesGrid } from "./ui/ClassEntriesGrid";
export { LineFlowChart } from "./ui/LineFlowChart";
export { LineFlowDashboard } from "./ui/LineFlowDashboard";
export { ResultsDashboard } from "./ui/ResultsDashboard";
