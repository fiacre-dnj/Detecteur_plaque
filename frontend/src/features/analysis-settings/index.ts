/** `features/analysis-settings` — les réglages envoyés au serveur, et leur diagnostic. */

export {
  BOUNDS,
  DEFAULT_CONFIDENCE,
  DEFAULT_SETTINGS,
  SETTINGS_SCHEMA_VERSION,
  loadSettings,
  sanitiseClassIds,
  saveSettings,
  toRequest,
  type AnalysisSettings,
} from "./model/settings";

export { downloadNotice } from "./model/launchNotice";

export {
  type PlateCapability,
  type PlateHealth,
  plateCapability,
} from "./model/plateCapability";

export { SettingsPanels } from "./ui/SettingsPanels";
