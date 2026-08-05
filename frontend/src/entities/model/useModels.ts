/**
 * Le catalogue de modèles, en état serveur React Query.
 *
 * Dans `entities/` et non dans une feature : le sélecteur de modèles, la page de
 * benchmark et l'historique en ont tous besoin, et une feature n'importe jamais une
 * autre (règle FSD du projet).
 *
 * `refetchInterval` est court **volontairement** : `loaded` change quand une analyse
 * charge un modèle ou quand le benchmark en libère un. Sans réinterrogation, le
 * sélecteur afficherait « au catalogue » pour un modèle devenu résident — l'inverse
 * exact de ce que la distinction en trois états existe pour montrer.
 */

import { useQuery } from "@tanstack/react-query";

import type { ModelCatalogue } from "@/shared/api/contracts";
import { fetchOrNull } from "@/shared/api/httpClient";
import { queryKeys } from "@/shared/api/queryKeys";

/** L'état de résidence bouge au fil des analyses : 15 s suffit à le suivre. */
export const MODELS_REFETCH_INTERVAL_MS = 15_000;

export function useModels() {
  return useQuery({
    queryKey: queryKeys.models,
    // `fetchOrNull` comme pour `/health` : un serveur absent est un **état**, pas
    // une erreur. Le sélecteur affiche alors « catalogue indisponible » plutôt
    // qu'un écran rouge.
    queryFn: () => fetchOrNull<ModelCatalogue>("/api/v1/models"),
    refetchInterval: MODELS_REFETCH_INTERVAL_MS,
    staleTime: MODELS_REFETCH_INTERVAL_MS,
  });
}
