/**
 * Un camembert générique, en SVG maison — même patron que l'ancien histogramme :
 * un dessin minimal dans le SVG (des `<path>`, rien de texte), la légende et les
 * chiffres en HTML à côté, pour rester lisibles par un lecteur d'écran sans
 * dupliquer l'information dans un `aria-label` fragile.
 *
 * Remplace les barres (empilées pour les lignes, relatives pour les classes) :
 * une part du trafic total se lit plus vite dans un camembert que dans une pile
 * de barres qu'il faut comparer visuellement une à une.
 *
 * **Il tient maintenant le grand nombre de parts** (2026-08-27), parce que rien
 * ne borne le nombre de lignes tracées ni de types suivis. À douze lignes,
 * l'ancienne version rendait une roue de lamelles et une légende deux fois plus
 * haute que son dessin, qui poussait le graphique voisin en biais dans la
 * rangée. Quatre décisions, et aucune ne touche un chiffre :
 *
 * - **le surplus devient une part « N autres »** (`groupSlices`, testé), grise et
 *   jamais colorée comme une donnée. Un bouton déplie les repliées : rien ne
 *   disparaît, la lecture d'ensemble passe d'abord ;
 * - **la légende est une grille en `auto-fill`.** Au-delà de quelques rangées, la
 *   colonne unique dépassait le dessin ; deux colonnes de légende gardent la
 *   carte aussi haute que large sans qu'aucun point de rupture ait à savoir dans
 *   quelle moitié de rangée le graphique se trouve ;
 * - **les parts sans passage sont comptées, pas listées** — « 6 lignes sans
 *   passage », une ligne de texte. Six rangées à « 0 — 0 % » occupaient plus de
 *   place que les parts qui portent le trafic, et disaient moins ;
 * - **la carte s'étire** (`flex-1` dans une section en colonne, elle-même étirée
 *   par la grille) : les deux camemberts de « Statistique » sont dans la même
 *   rangée, et une carte plus courte que sa voisine laissait un décroché sous elle
 *   dès que les deux légendes n'avaient pas le même nombre de rangées.
 */

import { useState } from "react";

import { groupSlices, type PieSlice } from "../model/pieSlices";

interface PieChartProps {
  title: string;
  slices: readonly PieSlice[];
  /** Affiché quand aucune tranche n'a de valeur — jamais un camembert vide et muet. */
  emptyMessage: string;
  /**
   * Ce qu'une part **est** — « ligne » / « lignes », « type » / « types ».
   *
   * Les deux formes sont données plutôt que dérivées d'un `+ "s"` : le décompte
   * des parts muettes doit nommer ce qu'il compte (« 6 sans passage » ne dit pas
   * de quoi), et les phrases qui l'entourent sont écrites sans accord d'adjectif
   * pour que « ligne » et « type » y entrent tous les deux sans code de genre.
   */
  unit: { one: string; many: string };
  /**
   * Ce que la **valeur** d'une part mesure, au singulier — « passage », « entrée » ;
   * le pluriel s'obtient par un `s`, vrai pour les deux.
   *
   * Jamais deviné : un camembert de lignes compte des passages, un camembert de
   * types compte des entrées, et les confondre serait l'erreur d'unité que
   * l'invariant 3 interdit — invisible, les deux chiffres étant plausibles.
   */
  metric: string;
  /** Parts tracées au plus, part agrégée comprise. */
  maxSlices?: number;
}

/** Taille du dessin, en unités du `viewBox` — un cercle, donc largeur = hauteur. */
const SIZE = 120;
const RADIUS = SIZE / 2;

export function PieChart({
  title,
  slices,
  emptyMessage,
  unit,
  metric,
  maxSlices = 6,
}: PieChartProps) {
  const [expanded, setExpanded] = useState(false);

  const total = slices.reduce((sum, slice) => sum + slice.value, 0);
  const { shown, hidden, otherValue } = groupSlices(slices, maxSlices);

  // Les parts muettes sont **comptées, pas listées** : elles n'occupent aucun
  // angle sur le dessin, et six rangées à « 0 — 0 % » prenaient plus de place que
  // les parts qui portent le trafic. Le fait qu'une ligne tracée ne serve à rien
  // n'est pas perdu pour autant — il se lit dans sa rangée de « Statistique » et
  // dans les quasi-franchissements du tiroir Comptage, qui disent en plus
  // pourquoi.
  const silent = shown.filter((slice) => slice.value === 0).length;
  const legend = shown.filter((slice) => slice.value > 0);
  // Les repliées sans passage ne sont pas listées à l'ouverture non plus : elles
  // sont déjà dans le décompte de la phrase.
  const hiddenListed = hidden.filter((slice) => slice.value > 0);
  const hiddenSilent = hidden.length - hiddenListed.length;

  return (
    <section aria-labelledby={`pie-${title}`} className="flex min-w-0 flex-col">
      <h3 id={`pie-${title}`} className="label-micro mb-3">
        {title}
      </h3>
      <div className="flex-1 rounded-card bg-surface p-3 shadow-card">
        {total === 0 ? (
          <p className="text-micro text-ink-dim">{emptyMessage}</p>
        ) : (
          <div className="flex flex-wrap items-start gap-4">
            <svg
              viewBox={`0 0 ${SIZE} ${SIZE}`}
              role="img"
              aria-label={
                `${title} : ` +
                legend
                  .map((slice) => `${slice.label} ${Math.round((slice.value / total) * 100)} %`)
                  .join(", ")
              }
              className="size-28 shrink-0"
            >
              {legend.length === 1 ? (
                // Une seule tranche non nulle : un arc de 100 % dégénère en un point
                // (les deux extrémités coïncident), donc un cercle plein à la place.
                <circle cx={RADIUS} cy={RADIUS} r={RADIUS} fill={legend[0]?.color} />
              ) : (
                <Wedges slices={legend} total={total} />
              )}
            </svg>

            <div className="min-w-0 flex-1 space-y-2">
              {/* Légende : jamais la seule couleur pour porter l'identité d'une
                  tranche, toujours doublée du libellé et du chiffre. En grille
                  `auto-fill` — une colonne dans une demi-largeur d'écran, deux
                  quand la section occupe toute la page. */}
              <ul className="grid gap-x-4 gap-y-1 [grid-template-columns:repeat(auto-fill,minmax(11rem,1fr))]">
                {legend.map((slice) => (
                  <LegendRow key={slice.id} slice={slice} total={total} />
                ))}
              </ul>

              {/* Ce qui a été replié, et ce qui se tait : deux phrases courtes
                  plutôt que des rangées de zéros. Le bouton n'apparaît que s'il y
                  a quelque chose à lire. */}
              {(hiddenListed.length > 0 || silent > 0 || hiddenSilent > 0) && (
                <div className="space-y-1 border-t border-line/40 pt-2">
                  {hiddenListed.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setExpanded((open) => !open)}
                      aria-expanded={expanded}
                      className="rounded-input text-micro text-ink-muted underline decoration-line underline-offset-2 transition-colors hover:text-ink"
                    >
                      {expanded
                        ? "Masquer le détail"
                        : `Détail des ${hiddenListed.length} autres`}
                    </button>
                  )}

                  {expanded && hiddenListed.length > 0 && (
                    <ul className="grid gap-x-4 gap-y-1 [grid-template-columns:repeat(auto-fill,minmax(11rem,1fr))]">
                      {hiddenListed.map((slice) => (
                        <LegendRow key={slice.id} slice={slice} total={total} />
                      ))}
                    </ul>
                  )}

                  {silent + hiddenSilent > 0 && (
                    <p className="text-micro text-ink-dim">
                      {silent + hiddenSilent}{" "}
                      {silent + hiddenSilent > 1 ? unit.many : unit.one} sans {metric} sur la
                      période
                    </p>
                  )}
                </div>
              )}

              {/* `otherValue` est déjà dans la part grise ; le rappeler en clair
                  évite de faire deviner ce que « N autres » recouvre. */}
              {otherValue > 0 && (
                <p className="text-micro text-ink-dim">
                  Le regroupement totalise{" "}
                  <span className="font-bold text-ink tabular">{otherValue}</span> {metric}s,{" "}
                  {Math.round((otherValue / total) * 100)} % du total.
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

/** Une rangée de légende : pastille, libellé, valeur, part. */
function LegendRow({ slice, total }: { slice: PieSlice; total: number }) {
  return (
    <li className="flex items-center gap-2 text-small">
      <span
        aria-hidden="true"
        className="size-2.5 shrink-0 rounded-badge"
        style={{ backgroundColor: slice.color }}
      />
      <span className="min-w-0 flex-1 truncate text-ink-muted">{slice.label}</span>
      <span className="shrink-0 font-bold text-ink tabular">{slice.value}</span>
      <span className="w-10 shrink-0 text-end text-micro text-ink-dim tabular">
        {total === 0 ? "—" : `${Math.round((slice.value / total) * 100)} %`}
      </span>
    </li>
  );
}

/** Les parts du camembert, une tranche par valeur non nulle. */
function Wedges({ slices, total }: { slices: readonly PieSlice[]; total: number }) {
  let cursor = 0;
  return (
    <>
      {slices.map((slice) => {
        const start = cursor;
        const fraction = slice.value / total;
        cursor += fraction;
        return <path key={slice.id} d={wedgePath(start, cursor)} fill={slice.color} />;
      })}
    </>
  );
}

/**
 * Le chemin SVG d'une tranche, de `startFraction` à `endFraction` (0..1 de
 * tour complet). Part du haut du cercle (`-90°`), sens horaire, comme un
 * cadran — la lecture la plus naturelle pour un camembert.
 */
function wedgePath(startFraction: number, endFraction: number): string {
  const [x0, y0] = pointOnCircle(startFraction);
  const [x1, y1] = pointOnCircle(endFraction);
  const largeArc = endFraction - startFraction > 0.5 ? 1 : 0;
  return `M ${RADIUS} ${RADIUS} L ${x0} ${y0} A ${RADIUS} ${RADIUS} 0 ${largeArc} 1 ${x1} ${y1} Z`;
}

function pointOnCircle(fraction: number): [number, number] {
  const angle = fraction * 2 * Math.PI - Math.PI / 2;
  return [RADIUS + RADIUS * Math.cos(angle), RADIUS + RADIUS * Math.sin(angle)];
}

export default PieChart;
