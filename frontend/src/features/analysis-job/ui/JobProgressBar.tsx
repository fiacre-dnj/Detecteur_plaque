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

import { Pause, Play, X } from "lucide-react";

import type { Job } from "@/shared/api/contracts";
import { isTerminal } from "@/shared/api/contracts";

import { formatBytes, type UploadProgress } from "../model/uploadJob";
import { statusLabel } from "../model/useJobProgress";

interface JobProgressBarProps {
  /** Progression de l'envoi, tant qu'il n'est pas achevé. */
  upload: UploadProgress | null;
  job: Job | null;
  /** Nom lisible du modèle, pour nommer ce qui se charge pendant la préparation. */
  modelLabel?: string;
  onCancel: () => void;
  /** Suspend l'analyse. Absent tant qu'aucun job ne tourne côté serveur. */
  onPause?: () => void;
  /** Reprend l'analyse suspendue, là où elle s'était arrêtée. */
  onResume?: () => void;
}

export function JobProgressBar({
  upload,
  job,
  modelLabel,
  onCancel,
  onPause,
  onResume,
}: JobProgressBarProps) {
  const uploading = upload !== null && upload.ratio < 1 && job === null;
  /**
   * Le serveur charge le modèle — souvent en le téléchargeant.
   *
   * Sans cette phase, la barre affichait « 0 / 0 images · 0.0 img/s » pendant une
   * à deux minutes, ce qui se lit exactement comme une analyse plantée. C'est le
   * seul moment où la progression ne progresse pas pour une bonne raison, et le
   * dire coûte une ligne.
   */
  const preparing = job?.preparing === true;
  const ratio = uploading ? upload.ratio : (job?.progress ?? 0);
  const finished = job !== null && isTerminal(job.status);
  const paused = job?.status === "paused";
  // Suspendre n'a de sens que sur une analyse **qui tourne** : pendant l'envoi,
  // il n'y a encore rien à suspendre côté serveur, et en file d'attente il n'y a
  // pas encore de thread à arrêter.
  const canPause = job?.status === "running" && onPause !== undefined;
  const canResume = paused && onResume !== undefined;

  return (
    <div className="rounded-card bg-surface-2 p-3">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-caption font-bold text-ink">
          {uploading
            ? "Envoi de la vidéo"
            : preparing
              ? "Préparation"
              : statusLabel(job?.status ?? "queued")}
        </p>
        <div className="flex items-center gap-2">
          <output className="text-small text-ink-muted">{Math.round(ratio * 100)} %</output>
          {canPause && (
            <button
              type="button"
              onClick={onPause}
              title="Suspendre l'analyse — elle reprendra à cette image"
              className="flex items-center gap-1.5 rounded-input px-2 py-1 text-small text-ink-muted transition-colors hover:bg-base hover:text-ink"
            >
              <Pause aria-hidden="true" className="size-3.5" />
              Suspendre
            </button>
          )}
          {canResume && (
            <button
              type="button"
              onClick={onResume}
              title="Reprendre l'analyse là où elle s'est arrêtée"
              className="flex items-center gap-1.5 rounded-input px-2 py-1 text-small font-bold text-accent transition-colors hover:bg-base"
            >
              <Play aria-hidden="true" className="size-3.5" />
              Reprendre
            </button>
          )}
          {!finished && (
            <button
              type="button"
              onClick={onCancel}
              title="Annuler l'analyse — les images déjà analysées sont perdues"
              className="flex items-center gap-1.5 rounded-input px-2 py-1 text-small text-ink-dim transition-colors hover:bg-base hover:text-negative"
            >
              <X aria-hidden="true" className="size-3.5" />
              Annuler
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
          : preparing
            ? // Le compteur d'images n'a aucun sens ici — aucune n'a été lue. Le
              // remplacer par la cause réelle de l'attente évite la lecture
              // « bloqué à 0 % » qui a produit « l'analyse ne fonctionne pas ».
              `Chargement du modèle ${modelLabel ?? job?.modelId ?? ""} — premier usage, téléchargement possible.`
            : job !== null
              ? // « Cadence (serveur) » : ce n'est pas la cadence de lecture.
                `${job.processedFrames} / ${job.totalFrames} images · ${job.processingFps.toFixed(1)} img/s (serveur)`
              : "En attente du serveur…"}
      </p>

      {/* Ce que coûte une pause, dit une fois et à l'endroit où on la décide.
          Un job suspendu garde sa place de calcul et le bail de son modèle : sans
          cette phrase, personne ne comprendrait pourquoi une autre analyse
          n'avance pas pendant ce temps. */}
      {paused && (
        <p className="mt-2 text-small text-ink-dim">
          L'analyse reprendra à cette image, avec les mêmes identités. Elle garde
          sa place sur le serveur pendant ce temps.
        </p>
      )}

      {job?.error != null && (
        <p role="alert" className="mt-2 text-small text-negative">
          {job.error}
        </p>
      )}
    </div>
  );
}
