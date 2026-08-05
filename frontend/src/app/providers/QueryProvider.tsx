/**
 * Client React Query et ses défauts.
 *
 * `refetchOnWindowFocus: false` est le réglage important : une analyse ne doit
 * pas repartir parce que l'utilisateur a changé d'onglet et est revenu.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const client = new QueryClient({
  defaultOptions: {
    queries: {
      // Un seul réessai : au-delà, l'utilisateur attend sans comprendre pourquoi.
      retry: 1,
      refetchOnWindowFocus: false,
      // Défaut prudent ; chaque requête affine selon ce qu'elle observe (le
      // statut d'un job est volatil, le catalogue de modèles ne l'est pas).
      staleTime: 30_000,
      gcTime: 5 * 60_000,
    },
  },
});

export function QueryProvider({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
