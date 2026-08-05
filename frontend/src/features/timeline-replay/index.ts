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
  frameAt,
  frameIndexAt,
  hasRate,
  ratePerMinute,
  statsAt,
  tracksAt,
  trailsAt,
  vehiclesAt,
} from "./model/replay";

export { useReplay, type ReplayState } from "./model/useReplay";
