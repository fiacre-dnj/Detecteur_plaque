/** `features/timeline-replay` — rejouer un résultat en phase avec la vidéo. */

export {
  BUCKET_STEPS_MS,
  TARGET_BUCKETS,
  chooseBucketMs,
  flowBuckets,
  formatBucketSpan,
  type FlowBucket,
} from "./model/flowBuckets";

export {
  RATE_MIN_ELAPSED_MS,
  TRAIL_LENGTH,
  crossingsUpTo,
  frameAt,
  frameIndexAt,
  hasRate,
  ratePerMinute,
  statsAt,
  tracksAt,
  trailsAt,
  vehiclesAt,
} from "./model/replay";

export { activeCrossingIndex, formatTimecode } from "./model/timeline";

export {
  NO_FILTER,
  type DensityBucket,
  type TimelineFilter,
  type TimelineGroup,
  chooseGroupMs,
  densityBuckets,
  filterCrossings,
  groupByTime,
  presentLabels,
  presentLines,
  toggle,
} from "./model/timelineFilters";

export { useReplay, type ReplayState } from "./model/useReplay";

export { CrossingTimeline } from "./ui/CrossingTimeline";
