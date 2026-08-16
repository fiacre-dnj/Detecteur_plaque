/**
 * Un camembert générique, en SVG maison — même patron que `LineFlowChart` et
 * l'ancien histogramme : un dessin minimal dans le SVG (des `<path>`, rien de
 * texte), la légende et les chiffres en HTML à côté, pour rester lisibles par
 * un lecteur d'écran sans dupliquer l'information dans un `aria-label` fragile.
 *
 * Remplace les barres (empilées pour les lignes, relatives pour les classes) :
 * une part du trafic total se lit plus vite dans un camembert que dans une
 * pile de barres qu'il faut comparer visuellement une à une.
 */

interface PieSlice {
  id: string;
  label: string;
  value: number;
  color: string;
}

interface PieChartProps {
  title: string;
  slices: readonly PieSlice[];
  /** Affiché quand aucune tranche n'a de valeur — jamais un camembert vide et muet. */
  emptyMessage: string;
}

/** Taille du dessin, en unités du `viewBox` — un cercle, donc largeur = hauteur. */
const SIZE = 120;
const RADIUS = SIZE / 2;

export function PieChart({ title, slices, emptyMessage }: PieChartProps) {
  const total = slices.reduce((sum, slice) => sum + slice.value, 0);
  const nonZero = slices.filter((slice) => slice.value > 0);

  return (
    <section aria-labelledby={`pie-${title}`}>
      <h3 id={`pie-${title}`} className="label-micro mb-3">
        {title}
      </h3>
      <div className="rounded-card bg-surface p-3 shadow-card">
        {total === 0 ? (
          <p className="text-micro text-ink-dim">{emptyMessage}</p>
        ) : (
          <div className="flex flex-wrap items-center gap-4">
            <svg
              viewBox={`0 0 ${SIZE} ${SIZE}`}
              role="img"
              aria-label={
                `${title} : ` +
                nonZero
                  .map((slice) => `${slice.label} ${Math.round((slice.value / total) * 100)} %`)
                  .join(", ")
              }
              className="size-28 shrink-0"
            >
              {nonZero.length === 1 ? (
                // Une seule tranche non nulle : un arc de 100 % dégénère en un point
                // (les deux extrémités coïncident), donc un cercle plein à la place.
                <circle cx={RADIUS} cy={RADIUS} r={RADIUS} fill={nonZero[0]?.color} />
              ) : (
                <Wedges slices={nonZero} total={total} />
              )}
            </svg>

            {/* Légende : jamais la seule couleur pour porter l'identité d'une
                tranche, toujours doublée du libellé et du chiffre. */}
            <ul className="min-w-0 flex-1 space-y-1">
              {slices.map((slice) => (
                <li key={slice.id} className="flex items-center gap-2 text-small">
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
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
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
