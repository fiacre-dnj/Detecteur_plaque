/**
 * Tranches adaptatives de l'histogramme de flux.
 *
 * **Pourquoi adaptatives.** Avec une tranche fixe d'une minute, un clip de 30
 * secondes tiendrait dans **une seule barre** : l'histogramme n'apprendrait rien et
 * ressemblerait à un bug. Avec une tranche fixe d'une seconde, une analyse d'une
 * heure produirait 3 600 barres d'un pixel, illisibles.
 *
 * On vise donc une douzaine de barres, en choisissant le palier le plus proche dans
 * une échelle de durées **lisibles par un humain** — 1 s, 5 s, 15 s, 30 s, 1 min,
 * 5 min, 10 min. Des paliers arbitraires (« 7,4 s ») rendraient l'axe incompréhensible.
 */

import type { CrossingEvent } from "@/shared/api/contracts";

/** Paliers de tranche, en millisecondes. Tous lisibles à l'oral. */
export const BUCKET_STEPS_MS = [
  1_000,
  5_000,
  15_000,
  30_000,
  60_000,
  300_000,
  600_000,
] as const;

/** Nombre de barres visé. */
export const TARGET_BUCKETS = 12;

export interface FlowBucket {
  /** Début de la tranche, en millisecondes de scène. */
  startMs: number;
  endMs: number;
  count: number;
}

/**
 * Choisit la tranche la plus adaptée à une durée.
 *
 * Le premier palier qui donne **au plus** `TARGET_BUCKETS` barres. Si même le plus
 * grand palier en donne davantage — une analyse de plusieurs heures — on garde le
 * plus grand : mieux vaut trente barres de dix minutes qu'un histogramme illisible.
 */
export function chooseBucketMs(durationMs: number, target = TARGET_BUCKETS): number {
  for (const step of BUCKET_STEPS_MS) {
    if (durationMs / step <= target) return step;
  }
  return BUCKET_STEPS_MS[BUCKET_STEPS_MS.length - 1] ?? 600_000;
}

/**
 * Répartit les franchissements en tranches.
 *
 * Les tranches vides sont **conservées** : les retirer tasserait l'axe du temps et
 * ferait paraître le trafic continu là où il y a eu une interruption. Un creux est
 * une information.
 */
export function flowBuckets(
  crossings: readonly CrossingEvent[],
  durationMs: number,
  target = TARGET_BUCKETS,
): FlowBucket[] {
  if (durationMs <= 0) return [];

  const bucketMs = chooseBucketMs(durationMs, target);
  const count = Math.max(1, Math.ceil(durationMs / bucketMs));
  const buckets: FlowBucket[] = Array.from({ length: count }, (_, index) => ({
    startMs: index * bucketMs,
    endMs: (index + 1) * bucketMs,
    count: 0,
  }));

  for (const event of crossings) {
    // `Math.min` borne le dernier événement : un horodatage égal à la durée
    // exacte tomberait sinon dans une tranche qui n'existe pas.
    const index = Math.min(count - 1, Math.floor(event.timestampMs / bucketMs));
    const bucket = buckets[index];
    if (bucket !== undefined) bucket.count += 1;
  }
  return buckets;
}

/**
 * Libellé d'une tranche pour l'axe et le résumé accessible.
 *
 * En secondes sous la minute, en minutes au-delà : « 90 s » est moins lisible que
 * « 1 min 30 s », et « 0,5 min » ne se dit pas.
 */
export function formatBucketSpan(bucketMs: number): string {
  if (bucketMs < 60_000) return `${bucketMs / 1000} s`;
  const minutes = bucketMs / 60_000;
  return minutes === 1 ? "1 min" : `${minutes} min`;
}
