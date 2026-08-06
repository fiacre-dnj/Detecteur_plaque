/**
 * Suivi de la progression d'un job : **SSE, doublé d'un sondage de secours**.
 *
 * Pourquoi les deux. Le SSE est un accélérateur : il donne la progression à la
 * fraction de seconde. Mais un flux SSE peut tomber sans prévenir — proxy qui
 * coupe une connexion inactive, onglet mis en veille par le système, VPN qui se
 * reconnecte. Quand cela arrive, `EventSource` retente tout seul, mais rien ne
 * garantit qu'il y parvienne, et l'interface resterait figée sur la dernière
 * valeur reçue **en affichant une analyse en cours qui est peut-être terminée**.
 *
 * Le sondage toutes les 3 s est donc la vérité, et le SSE l'accélère. Cette
 * hiérarchie est celle que le backend documente lui aussi : « Ce flux est un
 * accélérateur : le client doit aussi sonder `GET /jobs/{id}` toutes les 3 s. »
 *
 * Conséquence de conception : la fonction qui applique une mise à jour doit être
 * **idempotente et monotone** — recevoir deux fois le même état, ou un état plus
 * ancien que celui affiché, ne doit rien casser. C'est ce que garantit
 * `mergeProgress`.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { CrossingEvent, Job, JobPreview, JobStatus } from "@/shared/api/contracts";
import { isTerminal } from "@/shared/api/contracts";
import { request } from "@/shared/api/httpClient";

import { appendCrossings } from "./previewLog";

/** Intervalle du sondage de secours, imposé par la spécification. */
export const POLL_INTERVAL_MS = 3_000;

/**
 * Fusionne un état reçu avec celui affiché, **sans jamais reculer**.
 *
 * Le cas concret : le sondage et le SSE arrivent dans un ordre non garanti. Un
 * sondage lancé avant une frame peut répondre après elle, avec une progression
 * inférieure. Sans cette garde, la barre reculerait visiblement — ce que
 * l'utilisateur lit comme un bug, à raison.
 *
 * Un statut terminal, lui, gagne **toujours** : c'est l'information la plus
 * importante, et elle ne peut pas être invalidée par une frame en retard.
 */
export function mergeProgress(current: Job | null, incoming: Job): Job {
  if (current === null) return incoming;
  if (isTerminal(incoming.status)) return incoming;
  if (isTerminal(current.status)) return current;
  // **Un changement de statut passe toujours**, en gardant la progression la plus
  // avancée des deux. Sans cette règle, une suspension serait perdue : le serveur
  // ne persiste la progression que toutes les deux secondes, donc la trame qui
  // annonce « suspendue » porte souvent un chiffre *inférieur* à la dernière
  // frame reçue — et la garde de monotonie la rejetterait. L'interface afficherait
  // « analyse en cours » sur une analyse arrêtée, jusqu'à la reprise.
  if (incoming.status !== current.status) {
    return { ...incoming, progress: Math.max(incoming.progress, current.progress) };
  }
  return incoming.progress >= current.progress ? incoming : current;
}

export interface JobProgressState {
  job: Job | null;
  /** Erreur de suivi — distincte de `job.error`, qui est l'échec de l'analyse. */
  error: string | null;
  /**
   * Dernier aperçu reçu, `null` hors analyse en cours.
   *
   * Remis à `null` au statut terminal : passé ce point, la relecture du résultat
   * complet prend le relais, et laisser un aperçu vivant donnerait deux sources
   * de vérité à l'écran — dont une figée sur l'avant-dernière image.
   */
  preview: JobPreview | null;
  /** Franchissements observés depuis le début de l'analyse, le plus récent en tête. */
  events: readonly CrossingEvent[];
}

/**
 * Suit un job jusqu'à son statut terminal.
 *
 * @param jobId `null` désactive le suivi (aucun job en cours).
 * @param onDone Appelé une seule fois, au premier statut terminal.
 */
export function useJobProgress(
  jobId: string | null,
  onDone?: (job: Job) => void,
): JobProgressState {
  const [state, setState] = useState<Pick<JobProgressState, "job" | "error">>({
    job: null,
    error: null,
  });

  /**
   * L'aperçu vit dans son **propre** état.
   *
   * Le mélanger à celui de la progression ferait passer chaque image reçue par
   * `mergeProgress`, qui n'a rien à en dire, et rendrait sa monotonie — la
   * propriété qui empêche la barre de reculer — beaucoup plus difficile à tenir.
   */
  const [preview, setPreview] = useState<JobPreview | null>(null);
  const [events, setEvents] = useState<readonly CrossingEvent[]>([]);

  /** `onDone` dans un `ref` : sinon changer la callback relance tout le suivi. */
  const doneCallback = useRef(onDone);
  doneCallback.current = onDone;

  /** Garde d'appel unique : le SSE et le sondage peuvent voir la fin tous les deux. */
  const notified = useRef<string | null>(null);

  const apply = useCallback((incoming: Job) => {
    setState((previous) => {
      const merged = mergeProgress(previous.job, incoming);
      if (isTerminal(merged.status) && notified.current !== merged.jobId) {
        notified.current = merged.jobId;
        doneCallback.current?.(merged);
        // Fin de l'analyse : l'aperçu s'efface au profit de la relecture du
        // résultat complet, qui dit la même chose en mieux.
        setPreview(null);
      }
      return { job: merged, error: null };
    });
  }, []);

  // Nouveau job : on repart d'un état vide, sinon la barre afficherait la
  // progression du job précédent pendant la première seconde — et le canvas
  // dessinerait les boîtes de l'analyse précédente sur la nouvelle vidéo.
  useEffect(() => {
    notified.current = null;
    setState({ job: null, error: null });
    setPreview(null);
    setEvents([]);
  }, [jobId]);

  /* ── Le sondage : la vérité ────────────────────────────────────────────── */

  useEffect(() => {
    if (jobId === null) return;
    let cancelled = false;

    const poll = async (): Promise<void> => {
      try {
        const job = await request<Job>(`/api/v1/jobs/${jobId}`);
        if (!cancelled) apply(job);
      } catch (cause) {
        // Un sondage raté n'est pas fatal : le suivant réessaiera. On ne signale
        // que si l'on n'a **jamais** rien reçu, sinon un réseau instable
        // ferait clignoter un message d'erreur sur une analyse qui avance.
        if (!cancelled) {
          setState((previous) =>
            previous.job === null
              ? { job: null, error: messageOf(cause) }
              : previous,
          );
        }
      }
    };

    void poll();
    const timer = setInterval(() => {
      // On arrête de sonder une fois le job terminal : continuer interrogerait le
      // serveur indéfiniment pour un état qui ne changera plus.
      setState((previous) => {
        if (previous.job !== null && isTerminal(previous.job.status)) {
          clearInterval(timer);
        } else {
          void poll();
        }
        return previous;
      });
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [jobId, apply]);

  /* ── Le SSE : l'accélérateur ───────────────────────────────────────────── */

  useEffect(() => {
    if (jobId === null) return;

    const source = new EventSource(`/api/v1/jobs/${jobId}/events`);

    const handle = (event: MessageEvent<string>): void => {
      try {
        apply(JSON.parse(event.data) as Job);
      } catch {
        // Une trame illisible est ignorée : le sondage rattrapera. Lever ici
        // fermerait le flux pour un octet malformé.
      }
    };

    /**
     * L'aperçu : ce que le serveur voit, pendant qu'il le voit.
     *
     * Ignoré silencieusement s'il est illisible, comme la progression : un octet
     * malformé ne doit pas fermer le flux ni interrompre l'analyse à l'écran.
     */
    const handlePreview = (event: MessageEvent<string>): void => {
      try {
        const incoming = JSON.parse(event.data) as JobPreview;
        setPreview(incoming);
        setEvents((log) => appendCrossings(log, incoming.crossings));
      } catch {
        // Rien à rattraper : le prochain aperçu arrive dans 200 ms.
      }
    };

    source.addEventListener("progress", handle);
    source.addEventListener("preview", handlePreview as EventListener);
    source.addEventListener("end", (event) => {
      handle(event as MessageEvent<string>);
      // Fermé explicitement : sans cela, `EventSource` retenterait de se
      // reconnecter à un flux que le serveur a délibérément clos.
      source.close();
    });
    // Aucun traitement de `onerror` : `EventSource` retente seul, et le sondage
    // couvre le cas où il n'y parvient pas. Afficher une erreur ici alarmerait
    // pour une reconnexion parfaitement normale.

    return () => source.close();
  }, [jobId, apply]);

  return { ...state, preview, events };
}

/** Libellé français d'un statut, pour l'affichage. */
export function statusLabel(status: JobStatus): string {
  switch (status) {
    case "queued":
      return "En file d'attente";
    case "running":
      return "Analyse en cours";
    case "paused":
      return "Analyse suspendue";
    case "done":
      return "Analyse terminée";
    case "error":
      return "Analyse en échec";
    case "cancelled":
      return "Analyse annulée";
  }
}

function messageOf(cause: unknown): string {
  return cause instanceof Error ? cause.message : "Le suivi de l'analyse a échoué.";
}
