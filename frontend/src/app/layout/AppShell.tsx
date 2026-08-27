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
 *
 * **Ses gouttières viennent d'un jeton, pas d'une classe** : `--app-gutter`
 * (index.css) est lu ici, par le contenu et par le fond débordé de la barre du
 * studio. Écrite trois fois en dur, la valeur finissait par diverger — et le
 * symptôme est une barre collante qui peint son fond à côté des gouttières
 * qu'elle couvre.
 *
 * **Ni la gouttière ni `max-w` ne servent à gagner de la place**, et les deux ont
 * été essayés : 0,75 rem de gouttière puis un cadre à 2100 px, tous deux annulés le
 * jour même. Les marges de la page sont ce qui l'empêche d'étouffer ; la place d'une
 * colonne se prend sur la **largeur des colonnes elles-mêmes**, dans `StudioPage`.
 *
 * Sa hauteur **mesurée** est publiée dans `--app-header-h` (`useHeaderHeight`) :
 * la barre de réglages du studio s'y colle à son tour, et une entête qui s'enroule
 * ou qui grandit d'un message d'erreur déplacerait sinon la barre derrière elle.
 */

import { useLayoutEffect, useRef } from "react";
import { NavLink } from "react-router";

import { BackendStatusBadge } from "./BackendStatusBadge";
import { KeepAlivePages } from "./KeepAlivePages";
import { ThemeToggle } from "./ThemeToggle";

const LINKS = [
  { to: "/", label: "Studio" },
  { to: "/historique", label: "Historique" },
  { to: "/benchmark", label: "Benchmark" },
] as const;

export function AppShell() {
  const header = useHeaderHeight();

  return (
    <div className="min-h-dvh bg-base">
      <header
        ref={header}
        className="sticky top-0 z-40 border-b border-line/40 bg-base/95 backdrop-blur"
      >
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-8 gap-y-3 px-[var(--app-gutter)] py-4">
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

      <main className="mx-auto max-w-[1600px] px-[var(--app-gutter)] py-6">
        {/* Les trois pages restent **montées**, seule la visible est affichée :
            changer d'onglet ne doit pas coûter la vidéo importée, le tracé et le
            résultat en cours. Chacune porte sa propre frontière de suspense, donc
            une page qu'on ouvre pour la première fois n'efface ni l'entête, ni la
            navigation, ni les pages déjà chargées. */}
        <KeepAlivePages />
      </main>
    </div>
  );
}

/**
 * Publie la hauteur **mesurée** de l'entête dans `--app-header-h`.
 *
 * La barre du studio se colle sous elle (`sticky top-[var(--app-header-h)]`), et
 * il n'existe aucune façon honnête de deviner ce décalage : l'entête s'enroule sur
 * deux lignes en fenêtre étroite, et le badge serveur grandit quand il porte un
 * message d'erreur. Une valeur écrite en dur laisserait la barre flotter dans le
 * vide ou disparaître derrière l'entête — sans rien qui l'explique, puisque les
 * deux sont opaques.
 *
 * `useLayoutEffect` et non `useEffect` : la valeur est lue par la mise en page du
 * rendu qui suit, et la poser après la peinture ferait sauter la barre d'une
 * frame à chaque chargement.
 */
function useHeaderHeight(): React.RefObject<HTMLElement | null> {
  const element = useRef<HTMLElement>(null);

  useLayoutEffect(() => {
    const header = element.current;
    if (header === null) return;

    const publish = (): void => {
      document.documentElement.style.setProperty(
        "--app-header-h",
        `${Math.round(header.getBoundingClientRect().height)}px`,
      );
    };

    publish();
    // **Un second relevé à la frame suivante**, et il n'est pas redondant : le
    // `ResizeObserver` ne se déclenche qu'au *changement*, donc une première mesure
    // prise avant que la mise en page se stabilise ne serait jamais corrigée — la
    // barre resterait décalée de la hauteur d'un entête qui n'a jamais existé. Vu
    // en dev sur un arbre rechargé à chaud (344 px relevés pour un entête de 76).
    const settled = requestAnimationFrame(publish);
    const observer = new ResizeObserver(publish);
    observer.observe(header);
    return () => {
      cancelAnimationFrame(settled);
      observer.disconnect();
    };
  }, []);

  return element;
}
