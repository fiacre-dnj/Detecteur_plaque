/**
 * L'intervalle analysé d'une vidéo — le « de 00:34 à 05:00 » de l'écran.
 *
 * **Pourquoi une entité et pas un bout de `features/`.** Trois features en ont
 * besoin et aucune ne peut importer les autres : `video-transport` le dessine et le
 * laisse déplacer sur la barre de lecture, `analysis-job` le fait choisir dans la
 * modale de lancement, `counting-studio` le détient et l'envoie. Le seul endroit
 * qu'elles ont en commun est `entities/`.
 *
 * **En millisecondes, comme le contrat.** Le lecteur du navigateur parle en
 * secondes flottantes, le serveur en millisecondes de temps de scène. La conversion
 * se fait donc aux frontières — `secondsToMs` / `msToSeconds` — et jamais au milieu
 * d'un calcul, sinon deux arrondis successifs finiraient par décaler une borne
 * d'une image sans que personne ne sache où.
 *
 * **`endMs: null` veut dire « jusqu'à la fin », pas « zéro ».** La distinction
 * compte : une vidéo peut être remplacée par une plus longue, et une fin figée en
 * chiffres tronquerait silencieusement l'analyse de la nouvelle. `null` traverse
 * jusqu'au serveur, qui l'interprète pareil.
 */

/** Un intervalle de la vidéo, en millisecondes de temps de scène. */
export interface AnalysisRange {
  /** Début, inclus. `0` = le début du fichier. */
  startMs: number;
  /** Fin, **exclue**. `null` = jusqu'à la dernière image. */
  endMs: number | null;
}

/** La vidéo entière — la valeur par défaut, et celle que le serveur reçoit sans réglage. */
export const FULL_RANGE: AnalysisRange = { startMs: 0, endMs: null };

/**
 * Durée minimale d'un intervalle, en millisecondes.
 *
 * Une seconde et non une image : en dessous, l'intervalle ne contient pas de quoi
 * confirmer une piste (`minHits`), donc il ne compterait rien même avec un véhicule
 * en plein cadre — un résultat vide qui se lit comme une panne. La borne empêche
 * aussi les deux poignées de se croiser au glissé, où un intervalle de largeur nulle
 * devient impossible à rattraper à la souris.
 */
export const MIN_RANGE_MS = 1_000;

export function secondsToMs(seconds: number): number {
  return Math.round(seconds * 1000);
}

export function msToSeconds(ms: number): number {
  return ms / 1000;
}

/** L'intervalle couvre-t-il toute la vidéo ? */
export function isFullRange(range: AnalysisRange): boolean {
  return range.startMs <= 0 && range.endMs === null;
}

/** Durée effective de l'intervalle, en millisecondes. */
export function rangeDurationMs(range: AnalysisRange, durationMs: number): number {
  const end = range.endMs ?? durationMs;
  return Math.max(0, end - range.startMs);
}

/**
 * Ramène un intervalle dans les bornes de la vidéo courante.
 *
 * Appelé à chaque changement de source **et** à chaque manipulation des poignées.
 * Les trois cas qu'il rattrape sont tous réels :
 *
 * - une vidéo plus courte que la précédente — l'intervalle survivait au changement
 *   de fichier et pointait au-delà de la fin, ce que le serveur refuse en 422 sur un
 *   écran dont les deux champs paraissent valides ;
 * - des bornes croisées, quand on pousse une poignée au-delà de l'autre ;
 * - une durée pas encore connue (`NaN` avant `loadedmetadata`, `Infinity` pour un
 *   flux) — l'intervalle est alors rendu tel quel plutôt que ramené à zéro.
 */
export function clampRange(range: AnalysisRange, durationMs: number): AnalysisRange {
  if (!Number.isFinite(durationMs) || durationMs <= 0) return range;

  const limit = Math.max(0, durationMs);
  const end = range.endMs === null ? null : Math.min(limit, Math.max(MIN_RANGE_MS, range.endMs));
  const ceiling = (end ?? limit) - MIN_RANGE_MS;
  const start = Math.min(Math.max(0, range.startMs), Math.max(0, ceiling));
  // La fin est **renormalisée en `null`** dès qu'elle atteint la durée : sans cela,
  // « toute la vidéo » se distinguerait de « de 0 à la fin » sur un chiffre invisible,
  // et l'écran afficherait un intervalle là où l'utilisateur n'en a demandé aucun.
  return { startMs: start, endMs: end !== null && end >= limit ? null : end };
}

/**
 * Formate une position en `mm:ss` — ou `h:mm:ss` au-delà d'une heure.
 *
 * Jumeau de `formatTime` de `video-transport`, mais en millisecondes et sur une
 * autre couche : celui-là affiche une tête de lecture qui bouge soixante fois par
 * seconde, celui-ci des bornes qu'on saisit et qu'on relit. Les fusionner
 * obligerait une entité à importer une feature, ce que l'architecture interdit.
 *
 * Rend `--:--` pour tout ce qui n'est pas un nombre fini : `duration` vaut `NaN`
 * avant `loadedmetadata` et `Infinity` sur un flux caméra, et « NaN:NaN » dans une
 * interface fait douter de tout le reste.
 */
export function formatTimecode(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "--:--";

  const total = Math.floor(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;

  const pad = (value: number): string => value.toString().padStart(2, "0");
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(seconds)}`
    : `${pad(minutes)}:${pad(seconds)}`;
}

/**
 * Lit un code temporel saisi à la main, et rend `null` s'il ne veut rien dire.
 *
 * Les quatre formes acceptées sont celles qu'on tape réellement devant une vidéo :
 * `90` (des secondes), `1:30`, `01:30`, `1:02:03`. La virgule décimale est acceptée
 * comme le point, parce qu'un clavier français produit une virgule et qu'un refus à
 * cet endroit se lirait comme un champ cassé.
 *
 * **`null` et non `0` en cas d'échec.** Un `0` silencieux ramènerait la borne au
 * début du fichier sur une simple faute de frappe, et l'analyse partirait sur toute
 * la vidéo en affichant l'intervalle demandé — exactement le genre de désaccord
 * entre l'écran et le calcul que ce projet paie cher.
 */
export function parseTimecode(text: string): number | null {
  const cleaned = text.trim().replace(",", ".");
  if (cleaned === "") return null;

  const parts = cleaned.split(":");
  if (parts.length > 3) return null;

  let total = 0;
  for (const [index, part] of parts.entries()) {
    if (!/^\d*\.?\d+$/.test(part)) return null;
    const value = Number(part);
    if (!Number.isFinite(value)) return null;
    // Seul le dernier champ peut être fractionnaire ; les autres sont des minutes
    // et des heures entières, et `1.5:30` ne veut rien dire.
    if (index < parts.length - 1 && !Number.isInteger(value)) return null;
    total = total * 60 + value;
  }
  return Math.round(total * 1000);
}

/**
 * Phrase qui décrit l'intervalle, pour l'infobulle et les lecteurs d'écran.
 *
 * Elle dit les **deux** bornes et la durée : « de 00:34 à 05:00 » seul oblige à
 * faire la soustraction de tête, et c'est la durée qui répond à la vraie question —
 * combien de temps cette analyse va-t-elle prendre.
 */
export function describeRange(range: AnalysisRange, durationMs: number): string {
  if (isFullRange(range)) return `Toute la vidéo — ${formatTimecode(durationMs)}`;
  const end = range.endMs ?? durationMs;
  const span = formatTimecode(rangeDurationMs(range, durationMs));
  return `De ${formatTimecode(range.startMs)} à ${formatTimecode(end)} — ${span} analysées`;
}
