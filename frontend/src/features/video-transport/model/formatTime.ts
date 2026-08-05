/**
 * Formatage des durées de la timeline, et cadence supposée du pas-à-pas.
 *
 * Séparé du composant pour être testable sans DOM : le formatage d'un temps est
 * exactement le genre de fonction où les cas limites (durée infinie, NaN,
 * négatif) arrivent en vrai et produisent des affichages absurdes.
 */

/**
 * Cadence supposée pour le pas-à-pas image par image.
 *
 * **Le navigateur n'expose aucune cadence par fichier** — ni `HTMLVideoElement`,
 * ni `MediaSource` ne la donnent. 30 est donc une hypothèse, et être légèrement à
 * côté fait atterrir sur l'image voisine : acceptable pour un pas-à-pas
 * d'inspection visuelle, et bien préférable à l'absence de la fonction.
 *
 * Ne pas s'en servir pour un calcul métier : le temps de scène vient du serveur,
 * qui connaît la vraie cadence.
 */
export const ASSUMED_FPS = 30;

/** Un pas d'image, en secondes. */
export const FRAME_STEP_S = 1 / ASSUMED_FPS;

/** Vitesses de lecture proposées, dans l'ordre du sélecteur. */
export const PLAYBACK_RATES = [0.1, 0.25, 0.5, 0.75, 1, 1.5, 2] as const;

/**
 * Formate des secondes en `mm:ss`, ou `h:mm:ss` au-delà d'une heure.
 *
 * Rend `--:--` pour tout ce qui n'est pas un nombre fini. Ce cas n'est pas
 * théorique : `video.duration` vaut `NaN` avant `loadedmetadata` et `Infinity`
 * pour un flux caméra ou un clip issu de `MediaRecorder`. Afficher `NaN:NaN`
 * dans une interface est le genre de détail qui fait douter de tout le reste.
 */
export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "--:--";

  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;

  const pad = (value: number): string => value.toString().padStart(2, "0");
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(secs)}` : `${pad(minutes)}:${pad(secs)}`;
}

/**
 * La durée est-elle exploitable pour afficher une timeline ?
 *
 * `Infinity` pour un flux live, `NaN` avant les métadonnées, `0` pour un fichier
 * vide. Dans ces trois cas, la barre de progression n'a **aucune position
 * significative** : la spécification impose de la masquer plutôt que d'afficher
 * un curseur qui ne veut rien dire.
 */
export function hasSeekableDuration(duration: number): boolean {
  return Number.isFinite(duration) && duration > 0;
}

/** Étiquette d'une vitesse de lecture — virgule décimale, pas point. */
export function formatRate(rate: number): string {
  return `${rate.toString().replace(".", ",")}×`;
}
