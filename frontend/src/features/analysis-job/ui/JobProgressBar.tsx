/**
 * La barre de progression d'une analyse — deux phases distinctes.
 *
 * **Envoi** puis **analyse**, et l'interface le dit. Les confondre en une seule
 * barre est une erreur d'affichage courante et coûteuse : sur une vidéo de 800 Mo,
 * l'envoi prend des minutes, puis la barre repartirait de zéro pour l'analyse. Un
 * utilisateur qui voit une barre retomber à 0 % conclut à un échec et recommence.
 *
 * La cadence affichée est libellée **« serveur »** : c'est le débit de traitement
 * du backend, pas celui de la lecture vidéo. Deux chiffres de cadence sans
 * étiquette dans la même interface se confondent immanquablement.
 */

import { X } from "lucide-react";

import type { Job } from "@/shared/api/contracts";
import { isTerminal } from "@/shared/api/contracts";

import { formatBytes, type UploadProgress } from "../model/uploadJob";
import { statusLabel } from "../model/useJobProgress";

interface JobProgressBarProps {
  /** Progression de l'envoi, tant qu'il n'est pas achevé. */
  upload: UploadProgress | null;
  job: Job | null;
  onCancel: () => void;
}

export function JobProgressBar({ upload, job, onCancel }: JobProgressBarProps) {
  const uploading = upload !== null && upload.ratio < 1 && job === null;
  const ratio = uploading ? upload.ratio : (job?.progress ?? 0);
  const finished = job !== null && isTerminal(job.status);

  return (
    <div className="rounded-card bg-surface-2 p-3">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-caption font-bold text-ink">
          {uploading ? "Envoi de la vidéo" : statusLabel(job?.status ?? "queued")}
        </p>
        <div className="flex items-center gap-3">
          <output className="text-small text-ink-muted">{Math.round(ratio * 100)} %</output>
          {!finished && (
            <button
              type="button"
              onClick={onCancel}
              aria-label="Annuler l'analyse"
              title="Annuler l'analyse"
              className="grid size-6 place-items-center rounded-input text-ink-dim transition-colors hover:bg-base hover:text-negative"
            >
              <X aria-hidden="true" className="size-3.5" />
            </button>
          )}
        </div>
      </div>

      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(ratio * 100)}
        aria-label={uploading ? "Envoi de la vidéo" : "Progression de l'analyse"}
        className="mt-2 h-1 overflow-hidden rounded-pill bg-line"
      >
        <div
          className="h-full rounded-pill bg-accent transition-[width] duration-200"
          style={{ width: `${Math.min(100, ratio * 100)}%` }}
        />
      </div>

      <p className="mt-2 text-small text-ink-dim">
        {uploading
          ? `${formatBytes(upload.loaded)} sur ${formatBytes(upload.total)}`
          : job !== null
            ? // « Cadence (serveur) » : ce n'est pas la cadence de lecture.
              `${job.processedFrames} / ${job.totalFrames} images · ${job.processingFps.toFixed(1)} img/s (serveur)`
            : "En attente du serveur…"}
      </p>

      {job?.error != null && (
        <p role="alert" className="mt-2 text-small text-negative">
          {job.error}
        </p>
      )}
    </div>
  );
}
