/**
 * État du backend, en état serveur React Query.
 *
 * Dans son propre module et non dans `BackendStatusBadge.tsx` : un fichier qui
 * exporte à la fois un composant et un hook casse le rafraîchissement à chaud de
 * Vite, et l'avertissement d'oxlint est mérité.
 */

import { useQuery } from "@tanstack/react-query";

import type { Health } from "@/shared/api/contracts";
import { fetchOrNull } from "@/shared/api/httpClient";
import { queryKeys } from "@/shared/api/queryKeys";

/** Le badge se réinterroge : il doit refléter un serveur relancé entre-temps. */
export const HEALTH_REFETCH_INTERVAL_MS = 10_000;

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    // `fetchOrNull` : un backend absent est un **état**, pas une erreur. Le
    // traiter en erreur ferait remonter un écran rouge sur chaque page.
    queryFn: () => fetchOrNull<Health>("/api/v1/health"),
    refetchInterval: HEALTH_REFETCH_INTERVAL_MS,
    staleTime: HEALTH_REFETCH_INTERVAL_MS,
  });
}
