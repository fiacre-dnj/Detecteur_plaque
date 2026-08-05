/** `features/vehicle-registry` — *lesquels*, là où les cartes disent *combien*. */

export {
  crossingsCsv,
  downloadText,
  exportFilename,
  resultJson,
  vehiclesCsv,
} from "./model/exportCsv";

export {
  INITIAL_ROWS,
  OVERSCAN,
  ROW_HEIGHT,
  VIRTUALISE_THRESHOLD,
  shouldVirtualise,
  visibleWindow,
} from "./model/virtualise";

export { VehicleRegistry } from "./ui/VehicleRegistry";
