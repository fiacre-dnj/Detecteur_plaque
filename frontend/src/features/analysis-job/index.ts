/** `features/analysis-job` — déposer une vidéo, suivre l'analyse, récupérer le résultat. */

export { cancelJob, fetchResult, inputVideoUrl, pauseJob, resumeJob } from "./model/fetchResult";
export {
  PROGRESS_MIN_INTERVAL_MS,
  PROGRESS_MIN_STEP,
  formatBytes,
  shouldPublishProgress,
  uploadJob,
  type UploadHandle,
  type UploadProgress,
} from "./model/uploadJob";
export {
  POLL_INTERVAL_MS,
  mergeProgress,
  statusLabel,
  useJobProgress,
  type JobProgressState,
} from "./model/useJobProgress";
export { LOG_LIMIT, appendCrossings, formatSceneTime } from "./model/previewLog";
export {
  BUCKET_LADDER,
  BUCKET_TARGET_PER_GROUP,
  NO_CROSSING_FILTER,
  bucketiseCrossings,
  chooseBucketMs,
  crossingFacets,
  describeCrossings,
  filterCrossings,
  formatBucketRange,
  formatDuration,
  isFilterEmpty,
  passageNote,
  type CrossingBucket,
  type CrossingEntry,
  type CrossingFilter,
  type LineFacet,
  type PreviousPassage,
  type RoleFilter,
} from "./model/crossingTimeline";
export {
  SEEK_TOLERANCE_MS,
  STALL_PROMOTE_MS,
  shouldSeek,
  useSyncedPreview,
  type SyncedPreview,
} from "./model/useFollowAnalysis";
export {
  analysisProgress,
  type AnalysisPhase,
  type AnalysisProgress as AnalysisProgressState,
} from "./model/analysisProgress";
export { CrossingTimeline } from "./ui/CrossingTimeline";
export { AnalysisControls } from "./ui/AnalysisControls";
export { AnalysisProgress } from "./ui/AnalysisProgress";
export { JobProgressBar } from "./ui/JobProgressBar";
export { LaunchDialog } from "./ui/LaunchDialog";
