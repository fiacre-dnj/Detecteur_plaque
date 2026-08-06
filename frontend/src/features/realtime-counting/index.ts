/**
 * `features/realtime-counting` — compter en direct sur le flux d'une caméra.
 *
 * La règle qui justifie cette feature à elle seule : **la géométrie est mise à
 * l'échelle d'envoi**, et le serveur confirme les dimensions qu'il a reçues. Sans
 * cette paire, une ligne tracée sur du 1280 px appliquée à une image de 960
 * compterait 25 % à côté sans lever la moindre erreur. Voir `model/scale.ts`.
 */

export {
  DIMENSION_TOLERANCE_PX,
  REALTIME_PATH,
  TARGET_WIDTH,
  closeVerdict,
  dimensionMismatchMessage,
  dimensionsAgree,
  realtimeUrl,
  scaleFactor,
  scaleRequestGeometry,
  scaledSize,
  unscaleBox,
  unscaleTracks,
  useRealtimeSession,
  type PacingStats,
  type RealtimeSessionState,
  type RealtimeStatus,
  type UseRealtimeSessionResult,
} from "./model";

export { RealtimePanel } from "./ui/RealtimePanel";
