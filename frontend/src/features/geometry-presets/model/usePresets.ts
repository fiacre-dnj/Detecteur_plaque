/**
 * Les presets côté React Query : liste, enregistrement, suppression.
 *
 * Le chargement d'un preset **n'est pas** une requête React Query mais un appel
 * direct. C'est délibéré : charger est une action, pas une donnée affichée. La mettre
 * en cache signifierait qu'un preset modifié puis rechargé rendrait l'ancienne
 * version, et que la même géométrie serait rendue pour deux résolutions différentes
 * — précisément le bug que la mise à l'échelle sert à éviter.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Page, Preset, PresetDraft } from "@/shared/api/contracts";
import { queryKeys } from "@/shared/api/queryKeys";

import { createPreset, deletePreset, fetchPresets } from "./api";

/** La liste des presets enregistrés. */
export function usePresets(enabled: boolean) {
  return useQuery<Page<Preset>>({
    queryKey: queryKeys.presets,
    queryFn: fetchPresets,
    // Chargée seulement quand la modale est ouverte : la liste ne sert à rien
    // tant que personne ne la regarde, et l'interroger au montage du studio
    // ajouterait une requête à chaque visite pour une fonctionnalité optionnelle.
    enabled,
    // Un preset change rarement, mais il change **depuis cette page** : une
    // fraîcheur courte évite de montrer une liste sans le preset qu'on vient
    // d'enregistrer si l'invalidation manquait sa cible.
    staleTime: 30_000,
  });
}

export function useCreatePreset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (draft: PresetDraft) => createPreset(draft),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.presets }),
  });
}

export function useDeletePreset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (presetId: string) => deletePreset(presetId),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.presets }),
  });
}
