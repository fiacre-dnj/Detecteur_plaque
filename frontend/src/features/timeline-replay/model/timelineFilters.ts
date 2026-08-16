/**
 * Le filtrage, le regroupement et la densité de la chronologie — **sans DOM**.
 *
 * Tout ce qui décide *quoi* afficher vit ici, et pas dans le composant, pour la
 * raison qui a déjà valu à `timeline.ts` d'exister : ce sont des règles, et une règle
 * se vérifie sur ses bords plutôt qu'à l'œil. « Un filtre vide ne filtre rien » et
 * « une tranche sans franchissement reste visible » sont deux de ces bords, et les
 * deux se trompent facilement dans l'autre sens.
 */

import type { CountingLine, CrossingEvent } from "@/shared/api/contracts";
import { signOf } from "@/shared/lib/directions";

import { chooseBucketMs } from "./flowBuckets";

/** Ce sur quoi l'utilisateur peut restreindre la chronologie. */
export interface TimelineFilter {
  /** Identifiants de ligne retenus. **Vide = toutes** — jamais « aucune ». */
  lineIds: readonly string[];
  /** Sens retenus, par signe. Vide = les deux. */
  signs: readonly ("positive" | "negative")[];
  /** Classes votées retenues. Vide = toutes. */
  labels: readonly string[];
}

export const NO_FILTER: TimelineFilter = { lineIds: [], signs: [], labels: [] };

/**
 * Un ensemble vide signifie « tout », jamais « rien ».
 *
 * C'est la convention inverse d'une intersection naïve, et elle est délibérée : au
 * premier rendu aucune puce n'est active, et une intersection vide afficherait une
 * chronologie vide sur une analyse qui a compté. L'utilisateur conclurait à une panne.
 */
function accepts<T>(retained: readonly T[], value: T): boolean {
  return retained.length === 0 || retained.includes(value);
}

/** Applique le filtre, en conservant l'ordre chronologique de l'entrée. */
export function filterCrossings(
  events: readonly CrossingEvent[],
  filter: TimelineFilter,
): CrossingEvent[] {
  return events.filter(
    (event) =>
      accepts(filter.lineIds, event.lineId) &&
      accepts(filter.signs, signOf(event.direction)) &&
      accepts(filter.labels, event.label),
  );
}

/** Bascule une valeur dans un ensemble de filtre — c'est le geste d'une puce. */
export function toggle<T>(retained: readonly T[], value: T): T[] {
  return retained.includes(value)
    ? retained.filter((candidate) => candidate !== value)
    : [...retained, value];
}

/** Les classes réellement présentes, pour ne proposer que des puces utiles. */
export function presentLabels(events: readonly CrossingEvent[]): string[] {
  return [...new Set(events.map((event) => event.label))].sort();
}

/**
 * Les lignes réellement franchies, dans l'ordre de la géométrie.
 *
 * L'ordre de la géométrie et non celui des franchissements : les puces doivent rester
 * à la même place d'un rafraîchissement à l'autre, sinon celle qu'on visait bouge sous
 * le curseur pendant la lecture.
 */
export function presentLines(
  events: readonly CrossingEvent[],
  lines: readonly CountingLine[],
): CountingLine[] {
  const crossed = new Set(events.map((event) => event.lineId));
  return lines.filter((line) => crossed.has(line.id));
}

/** Une tranche du rail de densité, ventilée par sens. */
export interface DensityBucket {
  startMs: number;
  endMs: number;
  positive: number;
  negative: number;
  total: number;
}

/**
 * Le rail de densité : une barre par tranche, empilée par sens.
 *
 * **Ce que la liste ne peut pas donner.** Trois cents entrées défilantes ne montrent
 * pas où est la pointe de trafic ni où le flux s'interrompt ; une silhouette de douze
 * barres le montre d'un coup d'œil, et cliquer dedans déplace la vidéo.
 *
 * Les tranches vides sont **conservées**, comme dans `flowBuckets` et pour la même
 * raison : les retirer tasserait l'axe du temps et ferait paraître le trafic continu
 * là où il y a eu une interruption. Un creux est une information.
 *
 * La ventilation par sens est ce qui distingue ce rail de l'histogramme de l'onglet
 * « Flux » : ici on cherche « à quel moment ça passe, et dans quel sens ».
 */
export function densityBuckets(
  events: readonly CrossingEvent[],
  durationMs: number,
  target = 24,
): DensityBucket[] {
  if (durationMs <= 0) return [];

  const bucketMs = chooseBucketMs(durationMs, target);
  const count = Math.max(1, Math.ceil(durationMs / bucketMs));
  const buckets: DensityBucket[] = Array.from({ length: count }, (_, index) => ({
    startMs: index * bucketMs,
    endMs: (index + 1) * bucketMs,
    positive: 0,
    negative: 0,
    total: 0,
  }));

  for (const event of events) {
    // `Math.min` borne le dernier événement : un horodatage égal à la durée exacte
    // tomberait sinon dans une tranche qui n'existe pas.
    const index = Math.min(count - 1, Math.max(0, Math.floor(event.timestampMs / bucketMs)));
    const bucket = buckets[index];
    if (bucket === undefined) continue;
    if (event.direction > 0) bucket.positive += 1;
    else bucket.negative += 1;
    bucket.total += 1;
  }
  return buckets;
}

/** Un groupe de franchissements partageant la même tranche de temps. */
export interface TimelineGroup {
  startMs: number;
  label: string;
  events: CrossingEvent[];
}

/**
 * Découpe adaptative de la durée d'un groupe.
 *
 * Sur un clip de trente secondes, grouper à la minute ne produirait **qu'un seul**
 * en-tête, qui n'aiderait à rien ; sur une heure d'analyse, grouper à la seconde en
 * produirait 3 600, plus nombreux que les franchissements eux-mêmes. On réutilise
 * l'échelle de paliers lisibles de l'histogramme, avec une cible plus basse : une
 * dizaine de groupes est ce qu'un œil parcourt sans défiler.
 */
export function chooseGroupMs(durationMs: number): number {
  return chooseBucketMs(durationMs, 10);
}

/**
 * Regroupe les franchissements par tranche de temps, dans l'ordre chronologique.
 *
 * Les tranches **sans franchissement sont omises** — à l'inverse du rail de densité.
 * Ce n'est pas une incohérence : le rail est un axe du temps, où un creux se voit ;
 * la liste est un inventaire, où un en-tête vide serait une ligne à faire défiler
 * pour rien.
 */
export function groupByTime(
  events: readonly CrossingEvent[],
  durationMs: number,
  format: (ms: number) => string,
): TimelineGroup[] {
  if (events.length === 0) return [];

  const groupMs = chooseGroupMs(durationMs);
  const groups: TimelineGroup[] = [];
  for (const event of events) {
    const startMs = Math.floor(event.timestampMs / groupMs) * groupMs;
    const last = groups[groups.length - 1];
    if (last !== undefined && last.startMs === startMs) last.events.push(event);
    else groups.push({ startMs, label: format(startMs), events: [event] });
  }
  return groups;
}
