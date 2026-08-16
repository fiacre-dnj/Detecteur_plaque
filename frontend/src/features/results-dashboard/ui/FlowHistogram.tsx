/**
 * L'histogramme de flux — **SVG maison, chargé paresseusement**.
 *
 * Maison parce qu'une bibliothèque de graphiques pèse 50 à 150 Ko compressés pour
 * dessiner une douzaine de rectangles. Ici, le composant fait quarante lignes et
 * n'ajoute rien au bundle principal.
 *
 * Paresseusement parce qu'il n'est visible qu'après une analyse : le faire payer au
 * premier chargement de la page serait le taxer pour tous ceux qui n'analysent rien.
 *
 * **Accessible** : `role="img"` avec un `aria-label` qui résume le maximum et sa
 * tranche. Un graphique sans description est un trou noir pour un lecteur d'écran —
 * et le résumé est aussi ce qu'un voyant retient en un coup d'œil.
 */

import { formatBucketSpan, type FlowBucket } from "@/features/timeline-replay";

import { formatSceneTime } from "../model/labels";

interface FlowHistogramProps {
  buckets: readonly FlowBucket[];
  /** Largeur d'une tranche, pour libeller l'axe et le résumé. */
  bucketMs: number;
  /**
   * Déplace la lecture au début d'une tranche. `undefined` laisse le graphique
   * inerte, comme il l'était.
   *
   * Le même geste que la chronologie, sur l'autre représentation des mêmes
   * événements : le pic d'activité est justement l'endroit qu'on veut aller voir, et
   * le lire sans pouvoir s'y rendre obligeait à chercher l'instant à la main dans la
   * barre de transport.
   */
  onSeek?: ((timestampMs: number) => void) | undefined;
}

/** Hauteur du dessin, en unités du `viewBox`. */
const HEIGHT = 90;
const BAR_GAP = 2;

export function FlowHistogram({ buckets, bucketMs, onSeek }: FlowHistogramProps) {
  if (buckets.length === 0) return null;

  const max = Math.max(...buckets.map((bucket) => bucket.count));
  const width = buckets.length * 10;
  const barWidth = Math.max(1, 10 - BAR_GAP);

  const peak = buckets.reduce(
    (best, bucket) => (bucket.count > best.count ? bucket : best),
    buckets[0] ?? { startMs: 0, endMs: 0, count: 0 },
  );

  return (
    <section aria-labelledby="flow-title">
      <h3 id="flow-title" className="label-micro mb-3">
        Flux dans le temps
      </h3>
      <div className="rounded-card bg-surface p-3 shadow-card">
        <svg
          viewBox={`0 0 ${width} ${HEIGHT}`}
          // `role` et `aria-label` : sans eux, un lecteur d'écran annonce un
          // graphique vide. Le résumé donne l'information que l'œil retient.
          role="img"
          aria-label={
            max === 0
              ? "Aucun franchissement sur la période analysée."
              : `Histogramme du flux par tranches de ${formatBucketSpan(bucketMs)}. ` +
                `Maximum de ${max} franchissements autour de ${formatSceneTime(peak.startMs)}.`
          }
          className="h-24 w-full"
          preserveAspectRatio="none"
        >
          {buckets.map((bucket, index) => {
            // Hauteur minimale d'un pixel pour une tranche non vide : sinon un
            // franchissement isolé sur un pic élevé serait invisible, et le
            // graphique dirait « rien » là où il y a eu quelque chose.
            const height = bucket.count === 0 ? 0 : Math.max(1, (bucket.count / max) * HEIGHT);
            const bar = (
              <rect
                x={index * 10}
                y={HEIGHT - height}
                width={barWidth}
                height={height}
                // L'accent est fonctionnel ; ici il encode « activité », ce qui est
                // une donnée et non une décoration.
                className="fill-accent"
              />
            );
            if (onSeek === undefined) return <g key={bucket.startMs}>{bar}</g>;
            return (
              <g
                key={bucket.startMs}
                role="button"
                tabIndex={0}
                aria-label={`Aller à ${formatSceneTime(bucket.startMs)} — ${bucket.count} franchissements`}
                className="cursor-pointer focus-visible:outline-none"
                onClick={() => onSeek(bucket.startMs)}
                onKeyDown={(event) => {
                  if (event.key !== "Enter" && event.key !== " ") return;
                  // `preventDefault` sur l'espace : sans lui, la page défile en même
                  // temps que la lecture se déplace, et on perd le graphique de vue.
                  event.preventDefault();
                  onSeek(bucket.startMs);
                }}
              >
                {/* Une cible pleine hauteur derrière la barre : viser une tranche
                    vide, ou une barre d'un pixel, serait autrement impossible. Elle
                    est transparente au repos et se révèle au survol. */}
                <rect
                  x={index * 10}
                  y={0}
                  width={barWidth}
                  height={HEIGHT}
                  className="fill-ink/0 hover:fill-ink/10"
                />
                {bar}
              </g>
            );
          })}
        </svg>

        <div className="mt-1 flex justify-between text-micro text-ink-dim tabular">
          <span>{formatSceneTime(0)}</span>
          <span>tranches de {formatBucketSpan(bucketMs)}</span>
          <span>{formatSceneTime(buckets[buckets.length - 1]?.endMs ?? 0)}</span>
        </div>
      </div>
    </section>
  );
}

export default FlowHistogram;
