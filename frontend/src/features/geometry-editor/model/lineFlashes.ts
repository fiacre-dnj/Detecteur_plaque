/**
 * Le flash d'une ligne au moment où elle compte.
 *
 * Le problème qu'il résout : un compteur qui passe de 6 à 7 ne dit pas **quelle**
 * ligne a compté, ni dans quel sens, ni pour quel véhicule. Sur trois lignes
 * proches, c'est exactement l'information qui manque pour valider un tracé — et
 * celle qu'un total, aussi juste soit-il, ne donnera jamais.
 *
 * Ce que le flash n'est pas : une couleur nouvelle. La ligne clignote dans **sa
 * propre couleur** (halo qui s'élargit et s'estompe), et le sens est écrit en
 * toutes lettres à côté. Introduire une teinte « positive » ferait porter une
 * seconde signification à la couleur du canvas, qui encode déjà de quelle ligne
 * il s'agit — et le vert, lui, reste strictement fonctionnel (ADR 0004).
 */

import type { CrossingEvent } from "@/shared/api/contracts";

/**
 * Durée d'un flash.
 *
 * Assez long pour être vu si l'on regardait ailleurs une demi-seconde, assez
 * court pour que deux franchissements rapprochés restent deux flashs distincts.
 */
export const FLASH_DURATION_MS = 900;

/** Un flash vivant : son intensité décroissante et le sens qui l'a déclenché. */
export interface LineFlash {
  /** 1 au déclenchement, 0 à l'extinction. */
  intensity: number;
  direction: number;
}

/**
 * Intensité restante d'un flash, de 1 à 0.
 *
 * Décroissance **quadratique** et non linéaire : l'œil perçoit la luminosité de
 * façon non linéaire, et une extinction linéaire semble s'attarder puis
 * disparaître d'un coup.
 */
export function flashIntensity(elapsedMs: number, durationMs = FLASH_DURATION_MS): number {
  if (durationMs <= 0) return 0;
  const remaining = 1 - elapsedMs / durationMs;
  if (remaining <= 0) return 0;
  if (remaining >= 1) return 1;
  return remaining * remaining;
}

/** Un flash déclenché, avec l'instant — horloge locale — de son déclenchement. */
export interface FlashStart {
  lineId: string;
  direction: number;
  startedAt: number;
}

/**
 * Les flashs déclenchés par une salve de franchissements.
 *
 * `startedAt` est l'instant **d'affichage**, pas l'horodatage de scène de
 * l'événement : c'est une animation d'interface, elle se mesure sur l'horloge du
 * navigateur. C'est le seul endroit de la chaîne où l'horloge murale est
 * légitime, et pour la même raison que la mesure de performance côté serveur —
 * rien de ce qu'elle produit n'entre dans un compteur.
 *
 * Un seul flash par ligne et par salve : trois voitures franchissant la même
 * ligne dans la même image produiraient trois flashs superposés, donc un seul
 * flash visuellement — autant ne pas les empiler. Le journal, lui, garde les
 * trois événements.
 */
export function startFlashes(crossings: readonly CrossingEvent[], now: number): FlashStart[] {
  const byLine = new Map<string, FlashStart>();
  for (const crossing of crossings) {
    byLine.set(crossing.lineId, {
      lineId: crossing.lineId,
      direction: crossing.direction,
      startedAt: now,
    });
  }
  return [...byLine.values()];
}

/**
 * Les flashs encore vivants à l'instant `now`, et leur intensité.
 *
 * Rend une table vide — et non `null` — quand plus rien ne brûle : le canvas
 * n'a alors aucune branche à écrire, il dessine simplement zéro flash.
 */
export function activeFlashes(
  starts: readonly FlashStart[],
  now: number,
  durationMs = FLASH_DURATION_MS,
): Map<string, LineFlash> {
  const active = new Map<string, LineFlash>();
  for (const start of starts) {
    const intensity = flashIntensity(now - start.startedAt, durationMs);
    if (intensity > 0) active.set(start.lineId, { intensity, direction: start.direction });
  }
  return active;
}
