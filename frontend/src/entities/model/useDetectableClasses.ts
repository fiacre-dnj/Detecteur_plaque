/**
 * Les classes que les détecteurs savent reconnaître, servies par le serveur.
 *
 * Dans `entities/` pour la même raison que `useModels` : les réglages d'analyse et
 * le direct en ont tous deux besoin, et une feature n'importe jamais une autre.
 *
 * **Pourquoi une requête plutôt qu'une constante.** La liste pourrait être écrite
 * ici en six lignes, et ce serait un piège : le serveur valide `classIds` contre
 * son propre catalogue. Deux listes qui divergent donnent soit une case cochable
 * refusée à l'envoi — un 422 sur un écran qui paraissait valide — soit une classe
 * détectable que personne ne peut cocher. Une seule source, et c'est celle qui
 * valide.
 *
 * Pas de `refetchInterval`, contrairement au catalogue de modèles : cette liste ne
 * dépend d'aucun état machine — ni poids téléchargé, ni instance résidente. Elle ne
 * change qu'avec une version du serveur, donc un rechargement de page.
 */

import { useQuery } from "@tanstack/react-query";

import type { DetectableClass } from "@/shared/api/contracts";
import { fetchOrNull } from "@/shared/api/httpClient";
import { queryKeys } from "@/shared/api/queryKeys";

export function useDetectableClasses() {
  return useQuery({
    // `fetchOrNull` : un serveur absent est un **état**, pas une erreur. Le groupe
    // de cases ne s'affiche alors pas, au lieu de faire tomber l'écran de réglages.
    queryFn: () => fetchOrNull<DetectableClass[]>("/api/v1/models/classes"),
    queryKey: queryKeys.detectableClasses,
    staleTime: Number.POSITIVE_INFINITY,
  });
}
