/**
 * Le chemin retour : remettre les pistes reçues à l'échelle **source**.
 *
 * Le canvas ne connaît qu'un seul repère, celui de la vidéo source (invariant 2). Il
 * dessine la géométrie, les pistes de relecture et les pistes du direct avec le même
 * code, et c'est précisément ce qui garde ce code juste : une branche « si direct,
 * multiplier » finirait par diverger de la branche relecture.
 *
 * La conversion a donc lieu **ici**, une fois, à la frontière. Le serveur renvoie des
 * boîtes en pixels de l'image réduite qu'il a reçue ; on les redilate avant de les
 * confier au dessin.
 *
 * Ce qui est converti et ce qui ne l'est pas mérite d'être explicite, parce que
 * l'oubli d'un champ est silencieux :
 *
 * - `box` — une longueur, convertie ;
 * - `plates[].box` — une longueur aussi, et c'est l'oubli classique : les plaques
 *   sont un tableau imbriqué, et une copie superficielle de la piste les laisserait
 *   à l'échelle d'envoi, donc dessinées trop petites et décalées vers le coin ;
 * - `speedPxS` — **converti**, parce que c'est une vitesse en pixels : sur une image
 *   réduite de 25 %, un véhicule parcourt 25 % de pixels en moins par seconde. Le
 *   laisser tel quel afficherait des vitesses sous-estimées d'un tiers ;
 * - `score`, `hits`, les identifiants et les libellés — sans dimension.
 */

import type { TrackSnapshot } from "@/shared/api/contracts";

import { unscaleBox } from "./scale";

/**
 * Remet une piste à l'échelle source.
 *
 * Rend l'objet **tel quel** quand le facteur vaut 1 : c'est le cas de toute source
 * déjà sous 960 px, et éviter la copie évite de recréer des objets à 15 Hz pour rien
 * — ce que React interpréterait comme un changement à chaque frame.
 */
export function unscaleTrack(track: TrackSnapshot, factor: number): TrackSnapshot {
  if (factor === 1 || !Number.isFinite(factor) || factor <= 0) return track;

  return {
    ...track,
    box: unscaleBox(track.box, factor),
    speedPxS: track.speedPxS === null ? null : track.speedPxS / factor,
    plates: track.plates.map((plate) => ({ ...plate, box: unscaleBox(plate.box, factor) })),
  };
}

/** Le même pour une frame entière. */
export function unscaleTracks(
  tracks: readonly TrackSnapshot[],
  factor: number,
): readonly TrackSnapshot[] {
  if (factor === 1 || !Number.isFinite(factor) || factor <= 0) return tracks;
  return tracks.map((track) => unscaleTrack(track, factor));
}
