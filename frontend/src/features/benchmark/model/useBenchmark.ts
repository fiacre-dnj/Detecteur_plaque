/**
 * Lancement et suivi d'un run de benchmark.
 *
 * Le même protocole de suivi que les jobs — SSE doublé d'un sondage — pour la même
 * raison : le flux peut tomber sans prévenir, et un run de vingt modèles sur CPU dure
 * plusieurs minutes. Une page figée sur « en cours » alors que la mesure est finie
 * ferait croire à un blocage.
 *
 * **Le dernier run est rechargé à l'ouverture.** C'est la raison d'être de
 * `GET /benchmark/latest` : ouvrir la page sur un tableau vide alors qu'une mesure
 * existe en base se lit comme une panne.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { BenchmarkRun } from "@/shared/api/contracts";
import { isTerminal } from "@/shared/api/contracts";
import { fetchOrNull, request } from "@/shared/api/httpClient";

/** Même intervalle que le suivi des jobs : le SSE accélère, le sondage garantit. */
export const POLL_INTERVAL_MS = 3_000;

export interface BenchmarkRequest {
  modelIds?: string[];
  frames?: number;
}

export interface BenchmarkState {
  run: BenchmarkRun | null;
  /** Vrai pendant le chargement initial du dernier run. */
  loading: boolean;
  error: string | null;
  start: (options: BenchmarkRequest) => Promise<void>;
  cancel: () => void;
}

export function useBenchmark(): BenchmarkState {
  const [run, setRun] = useState<BenchmarkRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  /** Identifiant suivi. `null` quand aucun run n'est en cours ni affiché. */
  const [runId, setRunId] = useState<string | null>(null);

  /**
   * Le dernier run, chargé une seule fois à l'ouverture.
   *
   * `fetchOrNull` : un serveur absent est un **état** que la page affiche, pas une
   * erreur rouge. Et la route rend `null` quand aucun run n'existe — un cas normal
   * au premier usage, pas un échec.
   */
  useEffect(() => {
    let cancelled = false;
    void fetchOrNull<BenchmarkRun | null>("/api/v1/benchmark/latest", 5_000).then((latest) => {
      if (cancelled) return;
      setLoading(false);
      if (latest !== null) {
        setRun(latest);
        // On ne suit que s'il est encore en cours : rouvrir la page pendant un run
        // lancé depuis un autre onglet doit reprendre le suivi.
        if (!isTerminal(latest.status)) setRunId(latest.runId);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  /* ── Sondage ──────────────────────────────────────────────────────────── */

  const terminal = run !== null && isTerminal(run.status);

  useEffect(() => {
    if (runId === null || terminal) return;
    let cancelled = false;

    const poll = async (): Promise<void> => {
      try {
        const fresh = await request<BenchmarkRun>(`/api/v1/benchmark/${runId}`);
        if (!cancelled) setRun(fresh);
      } catch {
        // Un sondage raté n'est pas fatal : le suivant réessaiera. Signaler ici
        // ferait clignoter une erreur sur un run qui avance.
      }
    };

    void poll();
    const timer = setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [runId, terminal]);

  /* ── SSE ──────────────────────────────────────────────────────────────── */

  useEffect(() => {
    if (runId === null || terminal) return;

    const source = new EventSource(`/api/v1/benchmark/${runId}/events`);
    const handle = (event: MessageEvent<string>): void => {
      try {
        setRun(JSON.parse(event.data) as BenchmarkRun);
      } catch {
        // Trame illisible : le sondage rattrapera.
      }
    };

    source.addEventListener("progress", handle);
    source.addEventListener("end", (event) => {
      handle(event as MessageEvent<string>);
      source.close();
    });

    return () => source.close();
  }, [runId, terminal]);

  const start = useCallback(async (options: BenchmarkRequest) => {
    setError(null);
    try {
      const created = await request<{ runId: string }>("/api/v1/benchmark", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(options),
      });
      // Le run est vidé **avant** de suivre le nouveau : garder l'ancien tableau
      // pendant que le nouveau démarre ferait lire des mesures périmées comme si
      // elles étaient celles du run en cours.
      setRun(null);
      setRunId(created.runId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Le benchmark n'a pas pu démarrer.");
    }
  }, []);

  /** Référence stable pour l'annulation, hors du cycle de rendu. */
  const currentId = useRef<string | null>(null);
  currentId.current = runId;

  const cancel = useCallback(() => {
    const id = currentId.current;
    if (id === null) return;
    // Annulé **côté serveur** : oublier le run localement laisserait la mesure
    // continuer à occuper le sémaphore, et le run suivant attendrait sans raison.
    void request<BenchmarkRun>(`/api/v1/benchmark/${id}`, { method: "DELETE" })
      .then(setRun)
      .catch((cause: unknown) =>
        setError(cause instanceof Error ? cause.message : "L'annulation a échoué."),
      );
  }, []);

  return { run, loading, error, start, cancel };
}
