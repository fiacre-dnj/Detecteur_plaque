/**
 * Coquille de l'application : entête compacte, navigation, contenu.
 *
 * Une entête compacte et non un bandeau : c'est un outil de travail, et chaque
 * pixel pris en haut est un pixel de moins pour la scène vidéo.
 *
 * **Fixée en haut** (`sticky top-0`) : sur le studio, la barre de réglages et la
 * vidéo défilent sous elle dès que la chronologie et les onglets allongent la
 * page — la navigation et l'état du serveur restent atteignables sans remonter.
 * `sticky` plutôt qu'un vrai `fixed` : le rendu est identique une fois la page
 * chargée, mais `sticky` reste dans le flux du document — un `fixed` aurait
 * exigé un espaceur pour que `<main>` ne parte pas sous l'entête, une source
 * de décalage à chaque changement de hauteur de l'entête (ex. un message
 * d'erreur du badge serveur qui passe sur deux lignes).
 */

import { Suspense } from "react";
import { NavLink, Outlet } from "react-router";

import { BackendStatusBadge } from "./BackendStatusBadge";
import { ThemeToggle } from "./ThemeToggle";

const LINKS = [
  { to: "/", label: "Studio" },
  { to: "/historique", label: "Historique" },
  { to: "/benchmark", label: "Benchmark" },
] as const;

export function AppShell() {
  return (
    <div className="min-h-dvh bg-base">
      <header className="sticky top-0 z-40 border-b border-line/40 bg-base/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-8 gap-y-3 px-6 py-4">
          <div className="min-w-0">
            <h1 className="text-heading font-bold leading-tight text-ink">
              Comptage de véhicules
            </h1>
            <p className="mt-0.5 text-small text-ink-dim">
              Détection, suivi, ré-identification et franchissement de lignes
            </p>
          </div>

          <nav aria-label="Navigation principale" className="flex items-center gap-1">
            {LINKS.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.to === "/"}
                className={({ isActive }) =>
                  [
                    "label-caps rounded-pill px-4 py-2 transition-colors",
                    // Actif = accent, inactif = gris : la couleur porte l'état,
                    // et c'est un usage fonctionnel de l'accent.
                    isActive
                      ? "bg-surface-2 text-accent"
                      : "text-ink-dim hover:bg-surface hover:text-ink",
                  ].join(" ")
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>

          {/* Le coin haut-droit de l'entête : l'état du serveur, puis la bascule
              de thème. Dans cet ordre — l'état du serveur est une information
              qu'on surveille, le thème un réglage qu'on pose une fois. */}
          <div className="ms-auto flex items-center gap-2">
            <BackendStatusBadge />
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] px-6 py-6">
        {/* Une frontière de suspense par coquille : une route paresseuse en cours
            de chargement n'efface pas l'entête ni la navigation. */}
        <Suspense fallback={<PageSkeleton />}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}

/** Squelette à la forme d'une page, pas un spinner centré. */
function PageSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Chargement de la page">
      <div className="h-9 w-64 animate-pulse rounded-input bg-surface" />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="aspect-video animate-pulse rounded-section bg-surface" />
        <div className="h-64 animate-pulse rounded-section bg-surface" />
      </div>
    </div>
  );
}
