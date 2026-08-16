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

import {
  cancelJob,
  fetchResult,
  pauseJob,
  resumeJob,
  uploadJob,
  type UploadProgress,
} from "@/features/analysis-job";
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
  /**
   * Code stable de l'échec, `null` quand il n'y en a pas.
   *
   * Distinct de `error` parce qu'il sert à autre chose : `error` s'affiche,
   * `errorCode` décide de l'action proposée à côté. Brancher sur le texte
   * casserait à la première reformulation du message.
   */
  errorCode: string | null;
  /** Vrai entre le clic et le premier octet envoyé. */
  starting: boolean;
  /** Signature de la géométrie au moment du lancement. */
  launchSignature: string | null;
  start: (file: File, request: AnalysisRequest, lines: readonly CountingLine[], zones: readonly Zone[]) => Promise<void>;
  /**
   * Adopte une analyse **déjà terminée** et charge son résultat.
   *
   * C'est ce qui manquait pour que l'historique tienne sa promesse. « Ouvrir »
   * passait bien un `jobId` au Studio, mais rien ne savait quoi en faire : `jobId`
   * n'était écrit que par `start()` et `result` n'avait aucun point d'entrée. Les
   * deux boutons « Ouvrir » et « Relancer » avaient donc un effet identique au bit
   * près — seule la géométrie revenait — et l'infobulle « recharge le résultat »
   * était une fausse promesse.
   *
   * Ne relance rien et ne renvoie aucun fichier : le résultat est déjà sur le
   * serveur, immuable, et se relit tel quel.
   *
   * Synchrone : elle pose l'identifiant et laisse le suivi faire le chargement, par
   * le même chemin qu'à la fin d'une analyse. `result` arrive donc un peu après.
   */
  adopt: (jobId: string) => void;
  cancel: () => void;
  /** Suspend l'analyse en cours ; l'état vient ensuite du suivi, pas d'ici. */
  pause: () => void;
  resume: () => void;
  reset: () => void;
}

/**
 * Ce qu'il faut faire d'un job qui vient d'atteindre un statut terminal.
 *
 * **Les trois issues, pas seulement `done`** — c'était le défaut : seul `done`
 * était traité, donc un échec serveur n'alimentait aucun des deux canaux
 * d'affichage du Studio, et son message partait avec la barre de progression à
 * l'instant même où il devenait utile.
 *
 * - `done` ⇒ charger le résultat. Uniquement sur celui-là : un job annulé ou en
 *   échec n'en a pas, et le demander produirait un 409 parlant de « job non
 *   terminé », déroutant pour quelqu'un qui vient de voir « annulé ».
 * - `cancelled` ⇒ **rien**. L'utilisateur sait ce qu'il a fait ; lui afficher une
 *   erreur pour son propre geste serait faux.
 * - `error` ⇒ le message du serveur et son code.
 *
 * Fonction pure et exportée : la décision se teste sans monter de composant, et
 * c'est la seule partie du hook qui porte une règle métier.
 */
export type TerminalOutcome =
  | { kind: "fetchResult" }
  | { kind: "reportError"; message: string; code: string | null }
  | { kind: "silent" };

export function terminalOutcome(finished: Job): TerminalOutcome {
  if (finished.status === "done") return { kind: "fetchResult" };
  if (finished.status === "error") {
    return {
      kind: "reportError",
      // Le repli existe pour un serveur d'une version antérieure, ou un échec
      // dont le message n'a pas été rempli : « échec » sans phrase vaut mieux
      // qu'une alerte vide, qui se lit comme un défaut d'affichage.
      message: finished.error ?? "L'analyse a échoué.",
      code: finished.errorCode,
    };
  }
  return { kind: "silent" };
}

export function useAnalysisSession(): AnalysisSession {
  const [jobId, setJobId] = useState<string | null>(null);
  const [upload, setUpload] = useState<UploadProgress | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [launchSignature, setLaunchSignature] = useState<string | null>(null);

  /** Poignée d'envoi, pour pouvoir l'interrompre avant que le job existe. */
  const handle = useRef<{ abort: () => void } | null>(null);

  /** Applique la décision de `terminalOutcome` aux trois états concernés. */
  const handleTerminal = useCallback((finished: Job) => {
    const outcome = terminalOutcome(finished);
    if (outcome.kind === "fetchResult") {
      void fetchResult(finished.jobId)
        .then(setResult)
        .catch((cause: unknown) => setError(messageOf(cause)));
      return;
    }
    if (outcome.kind === "reportError") {
      setError(outcome.message);
      setErrorCode(outcome.code);
    }
  }, []);

  const { job, preview, events } = useJobProgress(jobId, handleTerminal);

  const start = useCallback(
    async (
      file: File,
      request: AnalysisRequest,
      lines: readonly CountingLine[],
      zones: readonly Zone[],
    ) => {
      setError(null);
      setErrorCode(null);
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

  const adopt = useCallback((existingJobId: string) => {
    setError(null);
    setErrorCode(null);
    setResult(null);
    // La signature de géométrie reste nulle : elle sert à détecter qu'un tracé a
    // bougé **depuis le lancement**, et il n'y a pas eu de lancement ici. La poser
    // sur le tracé rechargé ferait croire à une comparaison qui n'a pas eu lieu.
    setLaunchSignature(null);
    // **Poser l'identifiant suffit, et c'est tout l'intérêt.** `useJobProgress`
    // s'abonne dessus ; un job déjà terminal reçoit immédiatement `progress` puis
    // `end`, ce qui déclenche `handleTerminal` — donc exactement le même chemin de
    // chargement qu'à la fin d'une analyse lancée ici.
    //
    // Appeler `fetchResult` en plus le téléchargerait **deux fois** : sur une
    // timeline de trente minutes, c'est plusieurs centaines de mégaoctets payés pour
    // rien. Et deux chemins de chargement finiraient par diverger.
    setJobId(existingJobId);
  }, []);

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

  /**
   * Suspendre et reprendre.
   *
   * Aucun état optimiste : on n'écrit pas « suspendue » avant que le serveur l'ait
   * confirmé. Le statut arrive par le suivi — SSE et sondage — comme tous les
   * autres, et c'est ce qui garantit qu'un refus (409, job déjà terminé) laisse
   * l'interface sur l'état réel plutôt que sur celui qu'on espérait.
   */
  const pause = useCallback(() => {
    if (jobId === null) return;
    void pauseJob(jobId).catch((cause: unknown) => setError(messageOf(cause)));
  }, [jobId]);

  const resume = useCallback(() => {
    if (jobId === null) return;
    void resumeJob(jobId).catch((cause: unknown) => setError(messageOf(cause)));
  }, [jobId]);

  const reset = useCallback(() => {
    handle.current?.abort();
    handle.current = null;
    setJobId(null);
    setUpload(null);
    setResult(null);
    setError(null);
    setErrorCode(null);
    setLaunchSignature(null);
  }, []);

  return {
    job,
    upload,
    result,
    preview,
    events,
    error,
    errorCode,
    starting,
    launchSignature,
    start,
    adopt,
    cancel,
    pause,
    resume,
    reset,
  };
}

function messageOf(cause: unknown): string {
  return cause instanceof Error ? cause.message : "L'analyse a échoué.";
}
