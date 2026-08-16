/** `features/media-source` — choisir et libérer la source à analyser. */

export {
  ACCEPTED_EXTENSIONS,
  ACCEPT_ATTRIBUTE,
  DEMO_MISSING_MESSAGE,
  DEMO_VIDEO_URL,
  hasAcceptedExtension,
  useMediaSource,
  type MediaSource,
  type SourceKind,
} from "./model/useMediaSource";

export { DropZone, SourceLabel, SourcePicker } from "./ui/SourcePicker";
export { VideoScene } from "./ui/VideoScene";
