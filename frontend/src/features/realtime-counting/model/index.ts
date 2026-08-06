/** Réexports internes du modèle — le point d'entrée public reste `../index.ts`. */

export { JPEG_QUALITY, captureJpeg, createCaptureSurface, hasFrame } from "./capture";
export {
  CLOSE_INTERNAL_ERROR,
  CLOSE_POLICY_VIOLATION,
  CLOSE_TRY_AGAIN_LATER,
  REALTIME_PATH,
  closeVerdict,
  hasReason,
  realtimeUrl,
  type CloseVerdict,
} from "./connection";
export { EMPTY_PACING, FramePacer, sceneTimeMs, type PacingStats } from "./pacing";
export {
  DIMENSION_TOLERANCE_PX,
  TARGET_WIDTH,
  dimensionMismatchMessage,
  dimensionsAgree,
  scaleFactor,
  scaleLine,
  scaleRequestGeometry,
  scaleZone,
  scaledSize,
  unscaleBox,
} from "./scale";
export { unscaleTrack, unscaleTracks } from "./unscaleTracks";
export {
  useRealtimeSession,
  type RealtimeSessionState,
  type RealtimeStatus,
  type UseRealtimeSessionResult,
} from "./useRealtimeSession";
