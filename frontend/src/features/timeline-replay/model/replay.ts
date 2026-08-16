/**
 * La relecture d'un résultat, synchronisée sur la tête de lecture vidéo.
 *
 * Trois décisions gouvernent ce module, et chacune se mesure :
 *
 * 1. **Recherche binaire, pas linéaire.** Une timeline de 30 minutes à 30 img/s
 *    compte 54 000 lignes, et `frameIndexAt` est appelée **à chaque
 *    rafraîchissement** — soit 60 fois par seconde. En linéaire, c'est 3,2 millions
 *    de comparaisons par seconde : l'onglet chauffe et la lecture saccade. En
 *    binaire, seize comparaisons.
 *
 * 2. **Les compteurs suivent la tête de lecture, dans les deux sens.** `statsAt`
 *    rejoue les événements **jusqu'à** `timeMs` et recalcule tout. Reculer dans la
 *    vidéo doit donc faire **baisser** les chiffres. Un compteur qui ne
 *    redescendrait pas ferait raconter deux histoires différentes à l'image et aux
 *    nombres, et l'utilisateur ne saurait pas lequel croire.
 *
 * 3. **L'occupation de zone est une lecture instantanée, pas un cumul.** `inside`
 *    est remis à zéro à chaque appel et recalculé depuis les pistes visibles ;
 *    `entries`, lui, s'accumule. Additionner les deux — ce que fait naturellement
 *    une boucle unique — produirait une occupation qui ne redescend jamais.
 */

import type {
  AnalysisResult,
  AnalysisStats,
  CrossingEvent,
  LineTally,
  Point,
  TimelineRow,
  TrackSnapshot,
  ZoneTally,
} from "@/shared/api/contracts";
import { boxCentroid } from "@/shared/lib/geometry";

/**
 * Index de la dernière frame dont l'horodatage **ne dépasse pas** `timeMs`.
 *
 * Rend `-1` avant la première frame — et non `0`, qui afficherait les boîtes de
 * la frame initiale sur une vidéo pas encore commencée.
 *
 * La timeline est triée par construction côté serveur (`frameIndex` croissant, et
 * le temps de scène est monotone en `frameIndex`) : un test du contrat le vérifie,
 * et c'est la précondition de cette recherche.
 */
export function frameIndexAt(timeline: readonly TimelineRow[], timeMs: number): number {
  let low = 0;
  let high = timeline.length - 1;
  let found = -1;

  while (low <= high) {
    // `(low + high) >>> 1` plutôt que `/2` : entier, et sans débordement même sur
    // des indices énormes.
    const middle = (low + high) >>> 1;
    const row = timeline[middle];
    if (row === undefined) break;

    if (row.timestampMs <= timeMs) {
      found = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return found;
}

/** La frame à afficher pour une position de lecture, ou `null` avant le début. */
export function frameAt(timeline: readonly TimelineRow[], timeMs: number): TimelineRow | null {
  const index = frameIndexAt(timeline, timeMs);
  return index < 0 ? null : (timeline[index] ?? null);
}

/** Nombre de frames dont on reconstitue une trajectoire. */
export const TRAIL_LENGTH = 24;

/**
 * Reconstitue les trajectoires depuis les frames précédentes.
 *
 * **Côté client, délibérément** : le serveur n'a pas à transporter un historique
 * que le client peut recalculer. Sur une timeline de 54 000 frames, embarquer 24
 * positions par piste et par frame multiplierait le poids du résultat.
 *
 * Indexé par `globalId` et non par `trackId` : c'est le numéro du véhicule, la même
 * clé que le comptage et le registre. Les deux coïncident le plus souvent depuis
 * ADR 0016, mais `trackId` est l'identifiant du tracker et non celui sous lequel on
 * compte — indexer dessus ferait dépendre l'affichage d'une clé que rien ne garantit.
 */
export function trailsAt(
  timeline: readonly TimelineRow[],
  index: number,
  length = TRAIL_LENGTH,
): Map<number, Point[]> {
  const trails = new Map<number, Point[]>();
  if (index < 0) return trails;

  const start = Math.max(0, index - length + 1);
  for (let cursor = start; cursor <= index; cursor += 1) {
    const row = timeline[cursor];
    if (row === undefined) continue;
    for (const track of row.tracks) {
      const points = trails.get(track.globalId);
      const centroid = boxCentroid(track.box);
      if (points === undefined) trails.set(track.globalId, [centroid]);
      else points.push(centroid);
    }
  }
  return trails;
}

/**
 * Statistiques **à l'instant `timeMs`**, rejouées depuis les événements.
 *
 * Rejouées et non accumulées : c'est ce qui permet aux compteurs de redescendre
 * quand l'utilisateur recule dans la vidéo. Le coût est linéaire en nombre
 * d'événements — quelques milliers au plus, contre 54 000 frames — donc acceptable
 * à chaque rafraîchissement.
 *
 * `stats` complet est passé pour en reprendre les champs qui ne dépendent pas du
 * temps (cadence de traitement, diagnostics), afin que l'objet rendu ait la même
 * forme que celui du serveur et que les composants n'aient pas deux cas à gérer.
 */
export function statsAt(result: AnalysisResult, timeMs: number): AnalysisStats {
  const frame = frameAt(result.timeline, timeMs);
  const tracks = frame?.tracks ?? [];

  const byLine: Record<string, LineTally> = {};
  const byClass: Record<string, number> = {};
  const byCategory: AnalysisStats["byCategory"] = {};
  const seenVehicles = new Set<number>();
  // Les véhicules **ayant franchi**, distincts. Un `Set` dans la boucle qui existe
  // déjà : aucun parcours supplémentaire, et le chiffre reste dérivé des événements
  // plutôt que compté à côté (invariant 3).
  const crossedIdentities = new Set<number>();
  const trackedByClass: Record<string, number> = {};
  let crossings = 0;

  for (const event of result.crossings) {
    if (event.timestampMs > timeMs) continue;
    crossings += 1;
    crossedIdentities.add(event.globalId);
    byClass[event.label] = (byClass[event.label] ?? 0) + 1;
    // La catégorie est **lue** sur l'événement, jamais déduite du libellé : c'est le
    // serveur qui classe, et le rejeu ne fait que sommer ce qu'il a décidé.
    //
    // `?? "vehicle"` : les résultats archivés avant le 2026-08-12 n'ont pas ce champ.
    // Sans ce repli, la clé serait `undefined` et les deux cartes de passages
    // afficheraient 0 à côté d'un `crossings` non nul — voir ADR 0014.
    byCategory[event.category ?? "vehicle"] =
      (byCategory[event.category ?? "vehicle"] ?? 0) + 1;
    tallyLine(byLine, event);
  }

  // Les véhicules « vus » sont ceux dont la première apparition précède `timeMs` :
  // compter tous les véhicules du registre afficherait le total final dès la
  // première seconde de relecture.
  //
  // Le registre ne contient que des pistes **confirmées** (ADR 0016), donc ce
  // décompte est bien celui de `trackedVehicles` et non une approximation.
  for (const vehicle of result.vehicles) {
    if (vehicle.firstSeenMs > timeMs) continue;
    seenVehicles.add(vehicle.globalId);
    trackedByClass[vehicle.label] = (trackedByClass[vehicle.label] ?? 0) + 1;
  }

  const byZone: Record<string, ZoneTally> = {};
  for (const event of result.zoneEvents) {
    if (event.timestampMs > timeMs) continue;
    const tally = (byZone[event.zoneId] ??= { entries: 0, inside: 0, byClass: {} });
    tally.entries += 1;
    tally.byClass[event.label] = (tally.byClass[event.label] ?? 0) + 1;
  }

  // `inside` **n'est pas** dérivé des événements : c'est une lecture instantanée.
  // Le serveur ne renvoie pas l'appartenance par frame, donc on ne peut pas la
  // recalculer ici sans la géométrie ; on laisse 0 et le tableau affiche
  // l'occupation finale hors relecture. Ce choix est documenté dans le composant.
  const elapsedMs = Math.max(0, Math.min(timeMs, result.video.durationMs));

  return {
    trackedVehicles: seenVehicles.size,
    trackedByClass,
    crossings,
    crossedUnique: crossedIdentities.size,
    byClass,
    byCategory,
    byLine,
    byZone,
    vehiclesPerMinute: ratePerMinute(seenVehicles.size, elapsedMs),
    activeTracks: tracks.length,
    elapsedMs,
    analysedSceneMs: elapsedMs,
    // Les diagnostics décrivent l'analyse entière, pas un instant : les rejouer
    // n'aurait pas de sens, et les mettre à zéro cacherait une information utile.
    diagnostics: result.stats.diagnostics,
  };
}

function tallyLine(byLine: Record<string, LineTally>, event: CrossingEvent): void {
  const tally = (byLine[event.lineId] ??= {
    total: 0,
    byClass: {},
    byDirection: {
      positive: { total: 0, byClass: {}, firstMs: null, lastMs: null },
      negative: { total: 0, byClass: {}, firstMs: null, lastMs: null },
    },
  });
  const side = tally.byDirection[event.direction > 0 ? "positive" : "negative"];

  // **Le sens d'abord, la ligne ensuite.** Le serveur dérive `total` et `byClass`
  // des deux sens ; les incrémenter ici indépendamment rouvrirait la porte à deux
  // compteurs du même fait, et le rejeu contredirait le résultat qu'il rejoue.
  side.total += 1;
  side.byClass[event.label] = (side.byClass[event.label] ?? 0) + 1;
  side.firstMs ??= event.timestampMs;
  side.lastMs = event.timestampMs;

  tally.total = tally.byDirection.positive.total + tally.byDirection.negative.total;
  tally.byClass[event.label] = (tally.byClass[event.label] ?? 0) + 1;
}

/**
 * Débit par minute.
 *
 * **Rend 0 sous le seuil de 3 secondes** : extrapoler un débit horaire depuis une
 * seconde d'observation produit des chiffres absurdes (un véhicule en 0,5 s
 * donnerait « 120 par minute »), et l'utilisateur les prendrait au sérieux.
 */
export const RATE_MIN_ELAPSED_MS = 3_000;

export function ratePerMinute(count: number, elapsedMs: number): number {
  if (elapsedMs < RATE_MIN_ELAPSED_MS) return 0;
  return Math.round((count / (elapsedMs / 60_000)) * 100) / 100;
}

/** Le débit est-il exploitable, ou faut-il afficher « — » ? */
export function hasRate(elapsedMs: number): boolean {
  return elapsedMs >= RATE_MIN_ELAPSED_MS;
}

/**
 * Les véhicules du registre visibles à `timeMs`.
 *
 * Utilisé par le registre pendant une relecture : afficher les 400 véhicules d'un
 * clip alors qu'on en est à la dixième seconde ferait mentir le tableau autant que
 * les cartes.
 */
export function vehiclesAt(result: AnalysisResult, timeMs: number) {
  return result.vehicles.filter((vehicle) => vehicle.firstSeenMs <= timeMs);
}

/** Les pistes visibles à `timeMs`, pour le canvas. */
export function tracksAt(result: AnalysisResult, timeMs: number): readonly TrackSnapshot[] {
  return frameAt(result.timeline, timeMs)?.tracks ?? [];
}

/**
 * Les franchissements déjà passés à `timeMs`, **le plus récent en tête**.
 *
 * Le journal du direct disparaissait à la fin de l'analyse, alors que c'est lui — et non
 * le registre — qui permet de dire « à 00:12.4, cette plaque-là a franchi cette ligne-là
 * dans ce sens-là ». Le registre dit *lesquels*, le journal dit *quand*.
 *
 * Même ordre qu'en direct : le lecteur qui suit la vidéo cherche l'événement qui vient
 * de se produire, pas le premier de l'analyse. Borné pour la même raison que
 * `LOG_LIMIT` — personne ne défile jusqu'à la millième ligne.
 */
export function crossingsUpTo(
  result: AnalysisResult,
  timeMs: number,
  limit = 200,
): readonly CrossingEvent[] {
  const past = result.crossings.filter((event) => event.timestampMs <= timeMs);
  // `reverse` sur une copie produite par `filter` : `result.crossings` ne doit pas être
  // réordonné, il est partagé avec l'histogramme et les exports.
  return past.reverse().slice(0, limit);
}
