/**
 * Récupération du résultat complet, et annulation d'un job.
 *
 * Le résultat est servi en `json.gz`. **Aucune décompression manuelle** : le
 * navigateur gère `Content-Encoding: gzip` de façon transparente, et tenter de le
 * faire à la main (pako, DecompressionStream) doublerait le travail et la mémoire
 * sur un objet de plusieurs dizaines de mégaoctets.
 *
 * Le timeout est **désactivé** pour cette requête : une timeline de 30 minutes
 * pèse assez pour dépasser 30 s sur une connexion lente, et un abandon à mi-course
 * perdrait une analyse déjà payée en temps de calcul.
 */

import type { AnalysisResult, Job } from "@/shared/api/contracts";
import { request } from "@/shared/api/httpClient";

/** Charge le résultat complet d'un job terminé. */
export async function fetchResult(jobId: string): Promise<AnalysisResult> {
  return request<AnalysisResult>(`/api/v1/jobs/${jobId}/result`, { timeoutMs: null });
}

/**
 * Annule un job en cours, ou purge un job terminé.
 *
 * Une seule route pour les deux gestes côté serveur : du point de vue de
 * l'utilisateur, c'est le même — « je ne veux plus de ce job ».
 */
export async function cancelJob(jobId: string): Promise<Job> {
  return request<Job>(`/api/v1/jobs/${jobId}`, { method: "DELETE" });
}
