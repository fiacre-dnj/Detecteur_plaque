/** `features/analysis-settings` — les réglages envoyés au serveur, et leur diagnostic. */

export {
  BOUNDS,
  DEFAULT_CONFIDENCE,
  DEFAULT_SETTINGS,
  SETTINGS_SCHEMA_VERSION,
  loadSettings,
  saveSettings,
  toRequest,
  type AnalysisSettings,
} from "./model/settings";

export { SettingsPanels } from "./ui/SettingsPanels";
