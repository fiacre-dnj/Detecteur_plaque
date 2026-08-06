/**
 * L'historique des analyses persistées.
 *
 * **« Relancer » crée un nouveau job, jamais une mutation de l'ancien.** C'est une
 * exigence du cahier des charges, et la raison est de traçabilité : un job muté
 * perdrait ses chiffres d'origine, et on ne pourrait plus comparer « avant » et
 * « après » un changement de réglage. La relance préremplit donc le studio et laisse
 * l'utilisateur déposer à nouveau — le serveur n'a plus la vidéo, dont le TTL est
 * plus court que celui du job.
 */

import { useCallback, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { AnalysisRequest, Job, JobStatus, Page } from "@/shared/api/contracts";
import { request } from "@/shared/api/httpClient";
import { queryKeys } from "@/shared/api/queryKeys";

/** Taille de page de l'historique. */
export const PAGE_SIZE = 20;

export interface HistoryFilters {
  status: JobStatus | null;
  modelId: string | null;
}

export const NO_FILTERS: HistoryFilters = { status: null, modelId: null };

export function useJobHistory(filters: HistoryFilters, offset: number) {
  const query = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(offset),
  });
  if (filters.status !== null) query.set("status", filters.status);
  if (filters.modelId !== null) query.set("modelId", filters.modelId);

  return useQuery({
    queryKey: queryKeys.jobs({
      ...(filters.status !== null ? { status: filters.status } : {}),
      ...(filters.modelId !== null ? { modelId: filters.modelId } : {}),
      // L'offset fait partie de la clé : sans lui, changer de page rendrait la
      // page précédente depuis le cache et l'utilisateur croirait à un bug.
      offset: String(offset),
    }),
    queryFn: () => request<Page<Job>>(`/api/v1/jobs?${query.toString()}`),
  });
}

/**
 * Supprime un job, et **invalide l'historique**.
 *
 * L'invalidation est ce qui fait disparaître la ligne : sans elle, la suppression
 * réussit côté serveur et la ligne reste affichée jusqu'au prochain rechargement —
 * l'utilisateur clique alors une seconde fois et reçoit un 404.
 */
export function useDeleteJob() {
  const client = useQueryClient();

  return useMutation({
    mutationFn: (jobId: string) => request<Job>(`/api/v1/jobs/${jobId}`, { method: "DELETE" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

/**
 * La configuration d'un job terminé, telle qu'il l'a reçue.
 *
 * Le serveur la conserve dans `config_json` précisément pour cela : rejouer une
 * analyse à l'identique, et recharger la géométrie dans le studio. Sans elle,
 * « relancer » demanderait à l'utilisateur de retracer ses lignes de mémoire.
 */
export interface JobConfigResult {
  config: AnalysisRequest | null;
  loading: boolean;
  error: string | null;
  load: (jobId: string) => Promise<AnalysisRequest | null>;
}

export function useJobConfig(): JobConfigResult {
  const [config, setConfig] = useState<AnalysisRequest | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (jobId: string): Promise<AnalysisRequest | null> => {
    setLoading(true);
    setError(null);
    try {
      // `/config` et non `/jobs/{id}` : cette dernière est la route de sondage,
      // interrogée toutes les 3 s pendant une analyse, et elle ne porte **pas** la
      // configuration — délibérément, pour ne pas faire voyager la géométrie des
      // centaines de fois. Un test backend garantit cette séparation.
      const detail = await request<Job & { configJson: AnalysisRequest }>(
        `/api/v1/jobs/${jobId}/config`,
      );
      const loaded = detail.configJson;
      setConfig(loaded);
      return loaded;
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "La configuration de cette analyse n'a pas pu être relue.",
      );
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  return { config, loading, error, load };
}

/** Libellé français d'un statut, avec sa couleur sémantique. */
export function statusTone(status: JobStatus): { label: string; className: string } {
  switch (status) {
    case "done":
      return { label: "Terminée", className: "text-ink-muted" };
    case "running":
      return { label: "En cours", className: "text-info" };
    case "paused":
      // Même teinte que « en cours » : une analyse suspendue est vivante, elle
      // occupe toujours le serveur. La griser la ferait passer pour terminée.
      return { label: "Suspendue", className: "text-info" };
    case "queued":
      return { label: "En attente", className: "text-ink-dim" };
    case "error":
      return { label: "Échec", className: "text-negative" };
    case "cancelled":
      // **Pas rouge** : une annulation n'est pas un échec. L'utilisateur sait ce
      // qu'il a fait, et le rouge est réservé à ce qui a mal tourné.
      return { label: "Annulée", className: "text-ink-dim" };
  }
}

/** Formate une date ISO en date/heure locale française. */
export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Durée d'une analyse, en secondes.
 *
 * Rend `null` tant qu'elle n'est pas finie : afficher une durée partielle qui ne
 * bouge pas ferait croire que l'analyse a duré ce temps-là.
 */
export function durationSeconds(job: Job): number | null {
  if (job.finishedAt === null) return null;
  const start = new Date(job.createdAt).getTime();
  const end = new Date(job.finishedAt).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return null;
  return Math.max(0, Math.round((end - start) / 1000));
}
