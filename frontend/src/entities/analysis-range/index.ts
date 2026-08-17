/** `entities/analysis-range` — l'intervalle de vidéo qu'une analyse couvre. */

export {
  FULL_RANGE,
  MIN_RANGE_MS,
  clampRange,
  describeRange,
  formatTimecode,
  isFullRange,
  msToSeconds,
  parseTimecode,
  rangeDurationMs,
  secondsToMs,
  type AnalysisRange,
} from "./model/range";
