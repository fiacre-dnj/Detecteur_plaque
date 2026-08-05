/**
 * Routeur — **toutes les routes sont paresseuses**.
 *
 * Le Studio pèse le canvas d'édition et la relecture de timeline ; le benchmark
 * son tableau ; l'historique sa pagination. Les charger d'emblée ferait payer à
 * chaque visiteur trois écrans dont il n'en ouvrira qu'un.
 */

import { lazy } from "react";
import { createBrowserRouter } from "react-router";

import { AppShell } from "./layout/AppShell";
import { RouteError } from "./layout/RouteError";

const StudioPage = lazy(async () => ({
  default: (await import("@/features/counting-studio")).StudioPage,
}));
const HistoryPage = lazy(async () => ({
  default: (await import("@/features/job-history")).HistoryPage,
}));
const BenchmarkPage = lazy(async () => ({
  default: (await import("@/features/benchmark")).BenchmarkPage,
}));

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    // Une frontière d'erreur par route : un panneau qui casse ne blanchit pas
    // l'application entière.
    errorElement: <RouteError />,
    children: [
      { index: true, element: <StudioPage /> },
      { path: "historique", element: <HistoryPage /> },
      { path: "benchmark", element: <BenchmarkPage /> },
      { path: "*", element: <RouteError /> },
    ],
  },
]);
