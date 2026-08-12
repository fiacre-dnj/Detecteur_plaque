/** `features/video-transport` — le lecteur maison et son état de lecture. */

export {
  ASSUMED_FPS,
  FRAME_STEP_S,
  PLAYBACK_RATES,
  formatRate,
  formatTime,
  hasSeekableDuration,
} from "./model/formatTime";

export {
  mediaErrorMessage,
  useVideoTransport,
  type TransportState,
  type VideoTransport,
} from "./model/useVideoTransport";

export { PlaybackFpsBadge } from "./ui/PlaybackFpsBadge";
export { TransportBar } from "./ui/TransportBar";
