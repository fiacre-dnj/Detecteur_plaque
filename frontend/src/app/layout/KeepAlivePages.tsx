/**
 * Les trois pages restent **montées** ; seule la visible est affichée.
 *
 * Un `<Outlet />` démonte la page qu'on quitte. Sur le Studio, cela veut dire
 * perdre en un clic la vidéo importée, le tracé, l'intervalle choisi, la position
 * de lecture, le résultat relu et le suivi SSE en cours — pour être allé regarder
 * l'historique dix secondes. Rien de tout cela ne se reconstruit depuis l'URL : la
 * source est un `File` local et son `blob:`, la géométrie est en pixels de cette
 * vidéo-là. Le seul état qui survivait est celui qui est persisté (les réglages
 * d'analyse), et c'est précisément celui qu'on ne perdait pas.
 *
 * D'où ce commutateur : une page **visitée** reste dans l'arbre React, cachée par
 * l'attribut `hidden`, et retrouve exactement l'état qu'elle avait — jusqu'à la
 * position du curseur dans la vidéo, puisque la balise `<video>` elle-même n'est
 * jamais recréée.
 *
 * Quatre points qui ne se devinent pas :
 *
 * - **une page n'est montée qu'à sa première visite.** Les trois restent chargées
 *   paresseusement : qui n'ouvre jamais le benchmark n'en paie jamais le code. Le
 *   `Suspense` est **par page** et non partagé — sinon ouvrir le benchmark pour la
 *   première fois masquerait le studio derrière un squelette ;
 * - **`hidden` et non un démontage conditionnel** : `display: none` conserve l'état
 *   React *et* le DOM, retire la page de l'ordre de tabulation et de l'arbre
 *   d'accessibilité. Ne jamais poser de classe d'affichage sur ces conteneurs, elle
 *   l'emporterait sur l'attribut ;
 * - **ce qui tourne continue de tourner.** Une analyse suivie en SSE, une session
 *   caméra, une requête en vol : quitter la page ne les interrompt plus. C'est le
 *   but — mais cela veut dire qu'une page cachée n'est pas une page inerte ;
 * - **les gardes « une seule fois » des pages doivent être indexés sur l'état de
 *   navigation, pas sur le montage.** `StudioPage` applique la configuration reçue
 *   de l'historique une fois par `location.state` ; un garde par montage ne se
 *   réarmerait plus jamais, et le deuxième « Ouvrir » ne ferait plus rien.
 *
 * **La position de défilement est rendue à chaque page**, et ce n'est pas un
 * raffinement : masquer une page longue raccourcit le document, le navigateur
 * ramène le défilement dans les nouvelles bornes, et revenir affiche le Studio
 * revenu en haut alors que rien d'autre n'a bougé. Cacher une page perd donc son
 * défilement exactement là où la démonter perdait son état.
 */

import { Suspense, lazy, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router";

import { PAGE_IDS, activePageId, type PageId } from "./keepAlive";
import { RouteError } from "./RouteError";

const StudioPage = lazy(async () => ({
  default: (await import("@/features/counting-studio")).StudioPage,
}));
const HistoryPage = lazy(async () => ({
  default: (await import("@/features/job-history")).HistoryPage,
}));
const BenchmarkPage = lazy(async () => ({
  default: (await import("@/features/benchmark")).BenchmarkPage,
}));

/** L'écran de chaque page. Les chemins, eux, vivent dans `keepAlive.ts`. */
const ELEMENTS: Readonly<Record<PageId, ReactNode>> = {
  studio: <StudioPage />,
  history: <HistoryPage />,
  benchmark: <BenchmarkPage />,
};

export function KeepAlivePages() {
  const { pathname } = useLocation();
  const active = activePageId(pathname);

  /**
   * Les pages déjà ouvertes, dans l'ordre de leur première visite.
   *
   * Un tableau et non un `Set` : l'ordre de rendu doit être stable d'une
   * navigation à l'autre, sinon React réconcilierait les conteneurs entre eux et
   * remonterait les pages — exactement ce que ce composant existe pour éviter.
   */
  const [visited, setVisited] = useState<readonly PageId[]>(() =>
    active === null ? [] : [active],
  );

  useEffect(() => {
    if (active === null) return;
    setVisited((previous) => (previous.includes(active) ? previous : [...previous, active]));
  }, [active]);

  useScrollMemory(active);

  return (
    <>
      {PAGE_IDS.filter((id) => visited.includes(id)).map((id) => (
        <div key={id} hidden={id !== active}>
          <Suspense fallback={<PageSkeleton />}>{ELEMENTS[id]}</Suspense>
        </div>
      ))}

      {/* Une URL inconnue : la page d'erreur **en plus** des pages ouvertes, qui
          sont alors toutes masquées. Les démonter pour afficher un message d'erreur
          punirait une faute de frappe dans la barre d'adresse du travail en cours,
          alors que le bouton « Revenir » est juste là. */}
      {active === null && <RouteError />}
    </>
  );
}

/**
 * Retient le défilement de chaque page et le lui rend en revenant.
 *
 * Trois précautions, chacune pour un piège réel :
 *
 * - **la position est relevée en continu**, à l'écoute du défilement, et non au
 *   moment de quitter la page : quand l'effet de bascule s'exécute, la page longue
 *   est déjà masquée et le navigateur a déjà ramené `scrollY` dans les bornes du
 *   document raccourci. On enregistrerait la valeur tronquée ;
 * - **`useLayoutEffect` pour restaurer**, avant la peinture : après, la page
 *   apparaîtrait une frame en haut avant de sauter à sa position ;
 * - **le drapeau `restoring`** ignore les événements de défilement de la bascule
 *   elle-même — le recadrage du navigateur et notre propre `scrollTo` — qui
 *   seraient sinon enregistrés au crédit de la page qu'on vient d'afficher.
 */
function useScrollMemory(active: PageId | null): void {
  const positions = useRef(new Map<PageId, number>());
  const current = useRef<PageId | null>(active);
  const restoring = useRef(false);

  useEffect(() => {
    const remember = (): void => {
      const page = current.current;
      if (restoring.current || page === null) return;
      positions.current.set(page, window.scrollY);
    };
    window.addEventListener("scroll", remember, { passive: true });
    return () => window.removeEventListener("scroll", remember);
  }, []);

  useLayoutEffect(() => {
    if (current.current === active) return;
    current.current = active;
    restoring.current = true;
    window.scrollTo(0, active === null ? 0 : (positions.current.get(active) ?? 0));
    // Relâché à la frame suivante : le recadrage du navigateur arrive après la
    // mise en page, donc après cet effet.
    const frame = requestAnimationFrame(() => {
      restoring.current = false;
    });
    return () => cancelAnimationFrame(frame);
  }, [active]);
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
