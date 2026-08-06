/**
 * Une session d'analyse, du dépôt au résultat.
 *
 * Ce hook rassemble ce qui va ensemble : l'envoi, le suivi, le résultat, et la
 * **signature de géométrie relevée au lancement**. Cette dernière est ce qui permet
 * de détecter un résultat obsolète, et elle doit être capturée exactement au moment
 * de l'envoi — la relever plus tard inclurait des modifications faites entre-temps,
 * plus tôt raterait celles faites pendant la préparation.
 *
 * L'ordre des opérations compte aussi à l'annulation : on annule côté serveur
 * **avant** d'oublier le job localement, sinon l'analyse continue de consommer le
 * bail d'un modèle pour un résultat que personne ne lira.
 */

import { useCallback, useRef, useState } from "react";

import { cancelJob, fetchResult, uploadJob, type UploadProgress } from "@/features/analysis-job";
import { useJobProgress } from "@/features/analysis-job";
import { geometrySignature } from "@/entities/geometry";
import type {
  AnalysisRequest,
  AnalysisResult,
  CountingLine,
  CrossingEvent,
  Job,
  JobPreview,
  Zone,
} from "@/shared/api/contracts";

export interface AnalysisSession {
  /** Job en cours ou terminé, `null` si aucune analyse n'a été lancée. */
  job: Job | null;
  upload: UploadProgress | null;
  result: AnalysisResult | null;
  /**
   * Aperçu de l'analyse **en cours**, `null` avant et après.
   *
   * Remonté tel quel : c'est le Studio qui décide de le dessiner, parce que lui
   * seul sait si une session temps réel occupe déjà le canvas.
   */
  preview: JobPreview | null;
  /** Franchissements observés pendant l'analyse, le plus récent en tête. */
  events: readonly CrossingEvent[];
  /** Message d'erreur destiné à l'utilisateur. */
  error: string | null;
  /** Vrai entre le clic et le premier octet envoyé. */
  starting: boolean;
  /** Signature de la géométrie au moment du lancement. */
  launchSignature: string | null;
  start: (file: File, request: AnalysisRequest, lines: readonly CountingLine[], zones: readonly Zone[]) => Promise<void>;
  cancel: () => void;
  reset: () => void;
}

export function useAnalysisSession(): AnalysisSession {
  const [jobId, setJobId] = useState<string | null>(null);
  const [upload, setUpload] = useState<UploadProgress | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [launchSignature, setLaunchSignature] = useState<string | null>(null);

  /** Poignée d'envoi, pour pouvoir l'interrompre avant que le job existe. */
  const handle = useRef<{ abort: () => void } | null>(null);

  /**
   * Le job est terminé : on charge le résultat.
   *
   * Seulement sur `done`. Un job `cancelled` ou `error` n'a pas de résultat, et le
   * demander produirait un 409 dont le message parlerait de « job non terminé » —
   * déroutant pour quelqu'un qui vient de voir « annulé ».
   */
  const handleDone = useCallback((finished: Job) => {
    if (finished.status !== "done") return;
    void fetchResult(finished.jobId)
      .then(setResult)
      .catch((cause: unknown) => setError(messageOf(cause)));
  }, []);

  const { job, preview, events } = useJobProgress(jobId, handleDone);

  const start = useCallback(
    async (
      file: File,
      request: AnalysisRequest,
      lines: readonly CountingLine[],
      zones: readonly Zone[],
    ) => {
      setError(null);
      setResult(null);
      setStarting(true);
      setUpload({ loaded: 0, total: file.size, ratio: 0 });
      // Relevée **ici**, au moment exact du lancement.
      setLaunchSignature(geometrySignature(lines, zones));

      const pending = uploadJob(file, request, setUpload);
      handle.current = pending;

      try {
        setJobId(await pending.jobId);
      } catch (cause) {
        setError(messageOf(cause));
        setUpload(null);
        setLaunchSignature(null);
      } finally {
        setStarting(false);
        handle.current = null;
      }
    },
    [],
  );

  const cancel = useCallback(() => {
    // Envoi en cours : il suffit d'interrompre, le job n'existe pas encore.
    if (handle.current !== null) {
      handle.current.abort();
      handle.current = null;
      setUpload(null);
      return;
    }
    // Analyse en cours : on la fait cesser **côté serveur**. Oublier le job
    // localement sans l'annuler laisserait l'analyse consommer le bail d'un modèle
    // pour un résultat que personne ne lira.
    if (jobId !== null) {
      void cancelJob(jobId).catch((cause: unknown) => setError(messageOf(cause)));
    }
  }, [jobId]);

  const reset = useCallback(() => {
    handle.current?.abort();
    handle.current = null;
    setJobId(null);
    setUpload(null);
    setResult(null);
    setError(null);
    setLaunchSignature(null);
  }, []);

  return {
    job,
    upload,
    result,
    preview,
    events,
    error,
    starting,
    launchSignature,
    start,
    cancel,
    reset,
  };
}

function messageOf(cause: unknown): string {
  return cause instanceof Error ? cause.message : "L'analyse a échoué.";
}
