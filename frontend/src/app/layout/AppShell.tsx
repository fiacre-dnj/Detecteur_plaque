/**
 * Coquille de l'application : un **rail** de navigation, puis le contenu.
 *
 * La navigation a été une entête horizontale, et elle coûtait ~76 px de hauteur
 * au-dessus de la barre du studio, qui en prend ~64 : ~140 px de chrome avant la
 * première image de vidéo, sous deux bordures et deux fonds translucides presque
 * identiques dont rien ne disait lequel était le principal. Or **la hauteur est la
 * ressource rare de cet écran** — une scène vidéo, un lecteur, une colonne de
 * résultats — et la largeur ne l'est pas : le cadre est borné à 1600 px et tout
 * écran plus large affiche déjà du vide sur les côtés. Le rail prend donc 56 px là
 * où il y en a, et rend les ~84 px de l'entête là où il en manque.
 *
 * ## L'invariant : le document défile sur `window`
 *
 * **Aucun `overflow` sur cette coquille, ni sur l'enveloppe du contenu.** Trois
 * mécanismes lisent le défilement du document, et **aucun ne casse bruyamment** si
 * on le déplace dans un conteneur :
 *
 * - `useScrollMemory` (`KeepAlivePages`) relève `window.scrollY` et rend la position
 *   de chaque page. Dans un conteneur défilant, il enregistrerait `0` pour les trois
 *   et ne restituerait jamais rien — le symptôme est un studio qui remonte en haut en
 *   revenant de l'historique, ce qui se lit comme un caprice, pas comme un bug ;
 * - la barre du studio (`sticky`) se cale sur son plus proche ancêtre **défilant** :
 *   elle se collerait au mauvais repère et cesserait de suivre la page ;
 * - `100dvh` de la colonne des résultats suppose que la fenêtre **est** la zone utile.
 *
 * D'où `sticky top-0 h-dvh` sur le rail et non `position: fixed` : `sticky` reste
 * dans le flux, donc le contenu n'a aucune compensation à porter — c'est le même
 * arbitrage que l'ancienne entête faisait déjà, pour la même raison.
 *
 * ## Ce qui ne se devine pas
 *
 * - **`<header>` et non `<aside>`.** Le point de repère `banner` est conservé ; un
 *   `<aside>` deviendrait `complementary`, et l'application n'aurait plus de bannière
 *   du tout. Invisible en développement, réel au lecteur d'écran ;
 * - **`h-dvh` est ce qui rend `sticky` utile.** Sur un enfant de flex, `align-self:
 *   stretch` ne s'applique qu'à une hauteur `auto` : sans hauteur explicite, le rail
 *   serait étiré à la hauteur du document et n'aurait plus aucune course à parcourir ;
 * - **56 / 40 / 44 px** : le rail est dimensionné par l'anneau de focus.
 *   `:focus-visible` dessine 2 px de contour à 2 px d'écart, soit 44 px autour d'un
 *   bouton de 40 — six de marge de chaque côté dans 56. À 48 px de rail, l'anneau
 *   toucherait les bords ;
 * - **le rail reste en icônes, toujours.** Il n'a ni déploiement au survol ni bouton
 *   d'épinglage : trois destinations tiennent dans trois glyphes, le libellé vit dans
 *   `aria-label` et l'infobulle, et tout élargissement — même flottant — poserait un
 *   panneau au-dessus de la scène de tracé, que le curseur longe en permanence ;
 * - **`min-w-0` sur `<main>` est obligatoire.** Sans lui, la largeur minimale du
 *   contenu du studio (canvas, registre) déborde l'élément flex et pousse le rail hors
 *   de l'écran, ou fait apparaître un défilement horizontal du document ;
 * - **le rail n'est ancêtre d'aucun calque positionné.** Le tiroir `absolute` du
 *   studio garde pour bloc conteneur la barre `sticky` de `SettingsPanels` : rien à y
 *   changer. `max-w-[1600px]` se centre dans l'espace **restant**, ce qui est voulu.
 *
 * ## Le repli
 *
 * Sous 48rem le rail redevient une barre horizontale, de hauteur `--app-header-h`
 * (index.css) — c'est **la même déclaration** qui lui donne sa hauteur et qui décale
 * la barre du studio, donc les deux ne peuvent pas diverger. Le point de rupture
 * `md:` et la requête média du jeton sont en revanche deux écritures de 48rem qui
 * doivent bouger ensemble ; le commentaire du jeton le dit aussi.
 *
 * Le `<h1>` est `sr-only` et non supprimé : les trois pages n'ont que des `<h2>`, qui
 * pendraient sous rien. Le sous-titre qui l'accompagnait, lui, a disparu pour de bon —
 * il annonçait une « ré-identification » retirée par ADR 0016.
 */

import { Gauge, History, ScanLine, type LucideIcon } from "lucide-react";
import { NavLink } from "react-router";

import { BackendStatusBadge } from "./BackendStatusBadge";
import { KeepAlivePages } from "./KeepAlivePages";
import { NAV_ITEMS } from "./navigation";
import { ThemeToggle } from "./ThemeToggle";
import type { PageId } from "./keepAlive";

/**
 * Le glyphe de chaque page. `Record` exhaustif : une page ajoutée sans icône ne
 * compile pas, ce qu'aucun test ne peut vérifier.
 *
 * - `ScanLine` — un cadre traversé d'une ligne : littéralement ce que le studio fait,
 *   là où `Video` ou `Film` diraient « vidéo », que l'historique montre aussi ;
 * - `History` — l'horloge à flèche arrière, glyphe usuel des exécutions passées.
 *   `Clock` dirait une durée ;
 * - `Gauge` — la page mesure la vitesse de la machine. `ChartColumn` dirait
 *   « graphiques », qui est déjà le sens de la Statistique du studio.
 */
const NAV_ICONS: Readonly<Record<PageId, LucideIcon>> = {
  studio: ScanLine,
  history: History,
  benchmark: Gauge,
};

export function AppShell() {
  return (
    <div className="flex min-h-dvh flex-col bg-base md:flex-row">
      <h1 className="sr-only">Comptage de véhicules</h1>

      <header
        className={[
          // Replié : barre horizontale translucide — le contenu défile dessous, donc
          // le flou et le fond à 95 % ont un sens.
          "sticky top-0 z-40 flex shrink-0 items-center gap-1",
          "h-[var(--app-header-h)] w-full flex-row border-b border-line/40 bg-base/95 px-2 backdrop-blur",
          // Déployé : colonne pleine hauteur, **opaque et sans flou**. Rien ne passe
          // sous une colonne qui est dans le flux, et un calque flouté de la hauteur
          // de l'écran se repeindrait à chaque frame, au-dessus d'une page qui joue
          // une vidéo. `bg-surface` plutôt que `bg-base` : le rail est une surface, la
          // bordure seule ne le détacherait pas du contenu.
          "md:h-dvh md:w-14 md:flex-col md:border-b-0 md:border-e md:bg-surface md:px-0 md:py-3 md:backdrop-blur-none",
        ].join(" ")}
      >
        {/* La marque du produit, la même que l'onglet du navigateur. `alt=""` :
            décorative, le nom de l'application est dans le `<h1>` ci-dessus. La marge
            basse la sépare du groupe de navigation — elle dessine une ligne, comme
            l'icône du studio, et collées les deux se liraient comme une paire. */}
        <img src="/favicon.svg" alt="" className="size-7 shrink-0 rounded-card md:mb-2" />

        <nav aria-label="Navigation principale" className="flex items-center gap-1 md:flex-col">
          {NAV_ITEMS.map(({ id, to, label }) => {
            const Icon = NAV_ICONS[id];
            return (
              <NavLink
                key={id}
                to={to}
                // `end` sur les trois et non sur « / » seul : c'est exactement la
                // comparaison de `activePageId`, donc le lien surligné et la page
                // affichée ne peuvent pas diverger.
                end
                // Le libellé porte le nom accessible ; `title` ne fait que doubler,
                // il n'existe ni au clavier ni au toucher. `aria-current="page"` est
                // posé par `NavLink` lui-même : ne pas le passer à la main, ce serait
                // écraser son calcul.
                aria-label={label}
                title={label}
                className={({ isActive }) =>
                  [
                    "grid size-10 shrink-0 place-items-center rounded-pill transition-colors",
                    // L'actif est **rempli** et pas seulement teinté : un écart de
                    // luminance se lit sans distinguer les couleurs. Le survol prend
                    // le cran en dessous, pour que « survolé » et « actif » ne se
                    // confondent pas.
                    isActive
                      ? "bg-elevated text-accent"
                      : "text-ink-dim hover:bg-surface-2 hover:text-ink",
                  ].join(" ")
                }
              >
                <Icon aria-hidden="true" className="size-5" />
              </NavLink>
            );
          })}
        </nav>

        {/* Poussé à l'autre extrémité : à droite quand la barre est horizontale, en
            bas quand elle est verticale. Dans cet ordre — l'état du serveur est une
            information qu'on surveille, le thème un réglage qu'on pose une fois. */}
        <div className="ms-auto flex items-center gap-1 md:ms-0 md:mt-auto md:flex-col">
          <BackendStatusBadge />
          <ThemeToggle />
        </div>
      </header>

      <main className="min-w-0 flex-1">
        <div className="mx-auto max-w-[1600px] px-[var(--app-gutter)] py-6">
          {/* Les trois pages restent **montées**, seule la visible est affichée :
              changer d'onglet ne doit pas coûter la vidéo importée, le tracé et le
              résultat en cours. Chacune porte sa propre frontière de suspense, donc
              une page qu'on ouvre pour la première fois n'efface ni le rail, ni les
              pages déjà chargées. */}
          <KeepAlivePages />
        </div>
      </main>
    </div>
  );
}
