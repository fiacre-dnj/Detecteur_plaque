/** `features/job-history` — relire, relancer ou supprimer une analyse passée. */

export {
  NO_FILTERS,
  PAGE_SIZE,
  durationSeconds,
  formatDateTime,
  statusTone,
  useDeleteJob,
  useJobConfig,
  useJobHistory,
  type HistoryFilters,
} from "./model/useJobHistory";

export { HistoryPage } from "./ui/HistoryPage";
