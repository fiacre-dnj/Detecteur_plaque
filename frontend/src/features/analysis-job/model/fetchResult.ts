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
 * URL de la vidéo analysée, à poser sur `video.src`.
 *
 * Une URL et non un téléchargement : la balise `<video>` la lit **par plages**
 * (`Accept-Ranges`), ce qui rend le déplacement dans la timeline immédiat au lieu de
 * retélécharger des centaines de mégaoctets à chaque clic. La charger par `fetch`
 * puis en faire un blob annulerait exactement cette propriété.
 *
 * Peut répondre 409 `input_missing` : la vidéo est purgée plus tôt que le résultat.
 * Ce n'est pas une panne — les chiffres restent affichables, c'est l'incrustation sur
 * l'image qui demande de redéposer le fichier. L'erreur remonte par l'événement
 * `error` de la balise, pas par une exception ici.
 */
export function inputVideoUrl(jobId: string): string {
  return `/api/v1/jobs/${jobId}/input`;
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

/**
 * Suspend une analyse en cours.
 *
 * L'analyse s'arrête **entre deux images** et garde tout : position du décodeur,
 * identités, compteurs. C'est ce qui distingue « reprendre » de « relancer » —
 * relancer créerait un autre job, avec d'autres identités et d'autres totaux.
 *
 * Le job suspendu **occupe toujours** sa place de calcul sur le serveur. C'est le
 * prix d'une reprise exacte, et l'interface le dit à l'utilisateur.
 */
export async function pauseJob(jobId: string): Promise<Job> {
  return request<Job>(`/api/v1/jobs/${jobId}/pause`, { method: "POST" });
}

/** Reprend une analyse suspendue, là où elle s'était arrêtée. */
export async function resumeJob(jobId: string): Promise<Job> {
  return request<Job>(`/api/v1/jobs/${jobId}/resume`, { method: "POST" });
}
