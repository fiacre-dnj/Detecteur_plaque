/**
 * Ce que la chronologie calcule, sans toucher au DOM.
 *
 * Deux fonctions pures et testables plutôt que deux expressions dans le JSX : la
 * mise en évidence de l'entrée courante est une règle — « le dernier franchissement
 * déjà passé » — et une règle se vérifie sur ses bords, pas à l'œil.
 */

import type { CrossingEvent } from "@/shared/api/contracts";

/**
 * Indice du **dernier franchissement déjà survenu** à `timeMs`, ou `-1`.
 *
 * « Déjà survenu » et non « le plus proche » : la mise en évidence doit avancer
 * *après* le passage, jamais l'annoncer. Un surlignage qui saute à l'entrée suivante
 * une demi-seconde avant qu'elle ait lieu ferait douter des horodatages eux-mêmes.
 *
 * `-1` avant le premier : au tout début d'une relecture, rien n'est encore passé, et
 * mettre la première entrée en évidence laisserait croire à un franchissement à
 * l'instant zéro.
 *
 * Recherche linéaire assumée : la liste est déjà rendue en entier dans le DOM, donc
 * elle est de l'ordre de la centaine d'entrées. Une dichotomie ici optimiserait ce
 * qui n'est pas le coût — et demanderait de garantir le tri, que l'appelant fournit
 * mais que rien ne vérifie.
 */
export function activeCrossingIndex(
  events: readonly CrossingEvent[],
  timeMs: number,
): number {
  let found = -1;
  for (const [index, event] of events.entries()) {
    if (event.timestampMs > timeMs) break;
    found = index;
  }
  return found;
}

/**
 * Horodatage de scène en `mm:ss.d`.
 *
 * Le dixième est **nécessaire** et non cosmétique : à 25 images par seconde, deux
 * franchissements séparés par trois images tombent dans la même seconde. Sans la
 * décimale, la chronologie afficherait deux lignes au même instant et le clic sur
 * l'une paraîtrait déplacer la vidéo au mauvais endroit.
 *
 * Les négatifs sont ramenés à zéro : un horodatage antérieur au début de la scène
 * n'existe pas, et `-00:01.-2` serait illisible.
 */
export function formatTimecode(ms: number): string {
  const safe = Math.max(0, ms);
  const totalSeconds = Math.floor(safe / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const tenths = Math.floor((safe % 1000) / 100);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${tenths}`;
}
