/**
 * Le texte d'une plaque, tel qu'il s'affiche.
 *
 * Trois surfaces l'utilisent — le journal des franchissements (`analysis-job`),
 * l'étiquette du canvas (`geometry-editor`) et le registre (`vehicle-registry`) —
 * donc il vit dans `shared/` : une feature n'importe jamais une autre.
 *
 * **Ce que ce module existe pour ne pas confondre : trois états, pas deux.** Aucune
 * plaque vue ; une plaque vue dont aucune lecture ne fait consensus ; une plaque lue.
 * Les deux premiers s'affichent presque pareil et ne veulent pas dire la même chose :
 * dans le second, le rectangle jaune est visible à l'écran, et une colonne vide en
 * face contredit ce que l'utilisateur voit. C'est le bug d'affichage le plus probable
 * de cette fonctionnalité, donc celui contre lequel ces fonctions sont écrites.
 *
 * Aucune ne rend du JSX : elles sont ici pour être testables sous `bun test`, qui n'a
 * ni jsdom ni testing-library dans ce projet.
 */

import type { PlateDetection } from "@/shared/api/contracts";

/**
 * Au-delà, la lecture n'est plus une plaque.
 *
 * L'OCR peut renvoyer une ligne entière de pare-chocs sur une mauvaise segmentation ;
 * tronquer garde le tableau et l'étiquette du canvas lisibles plutôt que de laisser
 * une cellule pousser la colonne voisine hors de l'écran.
 */
const MAX_PLATE_CHARS = 12;

function clean(text: string | null): string {
  return text === null ? "" : text.trim();
}

function truncate(text: string): string {
  return text.length > MAX_PLATE_CHARS ? `${text.slice(0, MAX_PLATE_CHARS)}…` : text;
}

function percent(score: number | null): string | null {
  return score === null ? null : `${Math.round(score * 100)} %`;
}

/**
 * Forme comparable d'une plaque : majuscules, sans séparateur.
 *
 * `2418 TBE`, `2418-tbe` et `2418tbe` désignent la même plaque, et l'utilisateur
 * tapera celle qu'il a en tête, pas celle que l'OCR a produite. Comparer les chaînes
 * brutes rendrait la recherche inutilisable exactement quand elle sert.
 */
export function normalisePlate(raw: string): string {
  return raw.replace(/[^0-9A-Za-z]/g, "").toUpperCase();
}

/**
 * L'étiquette du canvas : le texte lu et sa confiance, ou `null`.
 *
 * `null` et non `« — »` : une étiquette « — » posée sur le capot d'une voiture est du
 * bruit sur l'image, et il y en aurait une par véhicule. Sur le canvas, l'absence
 * d'information **est** l'absence d'étiquette — le rectangle jaune dit déjà « plaque
 * repérée ».
 */
export function plateLabel(text: string | null, textScore: number | null): string | null {
  const value = clean(text);
  if (value === "") return null;
  const confidence = percent(textScore);
  return confidence === null ? truncate(value) : `${truncate(value)} · ${confidence}`;
}

/**
 * Ce que la colonne « Plaque » et la puce du journal affichent.
 *
 * À l'inverse du canvas, une cellule ne peut pas être vide sans mentir : « rien » se
 * lirait « pas de plaque » alors que le score de détection prouve le contraire. D'où
 * « illisible », qui est une information et non un échec silencieux.
 */
export function plateCell(text: string | null, detectionScore: number | null): string {
  const value = clean(text);
  if (value !== "") return truncate(value);
  return detectionScore === null ? "—" : "illisible";
}

/**
 * L'infobulle : d'où vient le texte, ou pourquoi il manque.
 *
 * Les deux confiances y cohabitent parce qu'elles répondent à deux questions
 * différentes — « le détecteur a-t-il bien vu une plaque » et « la lecture est-elle
 * sûre ». N'en montrer qu'une laisserait l'autre inexplicable.
 *
 * `undefined` et non `""` quand il n'y a rien à dire : un `title` vide produit une
 * infobulle fantôme sur certains navigateurs.
 */
export function plateTitle(
  text: string | null,
  textScore: number | null,
  detectionScore: number | null,
): string | undefined {
  const value = clean(text);
  const detected = percent(detectionScore);
  const detectedPart = detected === null ? null : `détectée à ${detected}`;

  if (value !== "") {
    const read = percent(textScore);
    const readPart = read === null ? "lue" : `lue à ${read} de confiance`;
    return detectedPart === null
      ? `Plaque ${readPart} : ${value}`
      : `Plaque ${readPart} (${detectedPart}) : ${value}`;
  }
  if (detectedPart === null) return undefined;
  return `Plaque ${detectedPart}, mais aucune lecture ne fait consensus.`;
}

/**
 * La plaque à situer sur le canvas parmi celles d'une piste : **la mieux lue**.
 *
 * Un poids lourd porte deux plaques, une remorque en porte une troisième. Prendre la
 * première venue ancrerait l'étiquette au hasard sur celle que le détecteur a listée
 * en tête ; les étiqueter toutes empilerait trois rectangles de texte sur un véhicule
 * de 80 pixels de large. Rend `null` si aucune n'est lue.
 *
 * Ne sert qu'à choisir **où** poser l'étiquette : le texte affiché, lui, vient de
 * `TrackSnapshot.plateText`, qui est le vote et ne clignote pas.
 */
export function bestReadPlate(plates: readonly PlateDetection[]): PlateDetection | null {
  let best: PlateDetection | null = null;
  for (const plate of plates) {
    if (clean(plate.text) === "") continue;
    if (best === null || (plate.textScore ?? 0) > (best.textScore ?? 0)) best = plate;
  }
  return best;
}
