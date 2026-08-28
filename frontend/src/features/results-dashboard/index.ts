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

export { crossedByClass } from "./model/crossedByClass";

export { visibleClasses } from "./model/visibleClasses";

export { type LineFlow, lineFlows } from "./model/lineFlows";

export {
  type LineHighlight,
  busiestLine,
  busiestVsQuietestShareGap,
  mostEnteredLine,
  mostExitedLine,
  quietestLine,
  strongestInflowLine,
  strongestOutflowLine,
} from "./model/highlights";

export {
  crossingRate,
  crossroadFlowSentence,
  directionArrow,
  directionLabel,
  formatCrossingRate,
  formatFrameLatency,
  formatSceneTime,
  formatSceneTimePrecise,
  formatScore,
  plural,
} from "./model/labels";

export { ClassEntriesChart } from "./ui/ClassEntriesChart";
export { LineFlowChart } from "./ui/LineFlowChart";
export { LineFlowDashboard } from "./ui/LineFlowDashboard";
export { ResultsDashboard } from "./ui/ResultsDashboard";
export { TechnicalMetrics } from "./ui/TechnicalMetrics";
