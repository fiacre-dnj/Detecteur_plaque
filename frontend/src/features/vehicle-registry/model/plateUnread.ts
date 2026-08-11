/**
 * Ce qu'on dit d'un véhicule sans plaque publiée.
 *
 * **Pourquoi ce module existe.** Le serveur étrangle sa détection de plaques et
 * refuse de lire sous ~64 px de large — les deux à raison, mesures à l'appui. La
 * conséquence est que le silence devient plus fréquent, et un silence non expliqué
 * se lit comme une panne : l'utilisateur voit une colonne vide et conclut que
 * l'ANPR ne marche pas, alors qu'elle refuse d'inventer.
 *
 * Chaque raison appelle un **geste différent** — installer un modèle, resserrer le
 * plan, stabiliser la caméra, ou ne rien faire — et c'est pour cela qu'il y a cinq
 * valeurs et non un booléen.
 *
 * Deux formes par raison : une étiquette courte pour la cellule du tableau, où la
 * place est comptée, et une phrase complète pour l'infobulle. Des fonctions
 * **pures**, testées : une phrase testée est une phrase qu'on peut corriger sans
 * rouvrir l'écran.
 */

import type { PlateUnreadReason } from "@/shared/api/contracts";

/** Plancher de lecture, en pixels — mesuré, pas supposé. */
export const READING_FLOOR_PX = 64;

/** L'étiquette de la cellule « Plaque » : courte, la place est comptée. */
export function plateUnreadLabel(reason: PlateUnreadReason | null): string {
  switch (reason) {
    case "ocr_disabled":
      return "lecture désactivée";
    case "not_detected":
      return "non détectée";
    case "too_small":
      return "trop petite";
    case "too_blurry":
      return "trop floue";
    case "no_consensus":
      return "lecture incertaine";
    default:
      // `null` : il y a une plaque, la cellule affiche son texte.
      return "";
  }
}

/**
 * La phrase complète, pour l'infobulle.
 *
 * `widthPx` n'est cité que lorsqu'il change quelque chose : sur `too_small`, il
 * dit **de combien** on est sous le plancher, donc si un plan un peu plus serré
 * suffirait ou s'il faut un autre capteur. Sur « non détectée », il n'existe pas.
 */
export function plateUnreadMessage(
  reason: PlateUnreadReason | null,
  widthPx: number | null,
): string {
  switch (reason) {
    case "ocr_disabled":
      return (
        "La lecture du texte n'a pas été demandée, ou son modèle n'est pas installé " +
        "sur ce serveur. Les plaques sont encadrées, leur texte n'est pas lu."
      );
    case "not_detected":
      return (
        "Aucune plaque n'a été localisée sur ce véhicule. Angle de vue, occlusion " +
        "ou véhicule vu de côté — ce n'est pas une question de résolution."
      );
    case "too_small":
      return (
        `Plaque vue à ${formatWidth(widthPx)} de large — sous le plancher de lecture ` +
        `(~${READING_FLOOR_PX} px). Un plan plus serré ou un capteur plus défini la ` +
        "rendrait lisible."
      );
    case "too_blurry":
      return (
        `Plaque vue à ${formatWidth(widthPx)} de large, mais trop floue pour être lue. ` +
        "Une vitesse d'obturation plus courte réduirait le flou de mouvement."
      );
    case "no_consensus":
      return (
        "Plusieurs lectures ont été tentées, aucune ne fait majorité. Le serveur " +
        "préfère ne rien afficher plutôt qu'une plaque incertaine."
      );
    default:
      return "";
  }
}

/**
 * L'infobulle quand un candidat non confirmé existe (`no_consensus` avec
 * `plateBestGuess`) : la même explication que `plateUnreadMessage`, plus le
 * candidat rapporté, pour que l'utilisateur comprenne *ce qu'il voit* dans la
 * cellule plutôt que seulement *pourquoi elle n'est pas plus affirmative*.
 */
export function plateBestGuessMessage(bestGuess: string, bestGuessScore: number | null): string {
  const confidence =
    bestGuessScore === null ? "" : ` (confiance ${Math.round(bestGuessScore * 100)} %)`;
  return (
    `Plusieurs lectures ont été tentées, aucune ne fait majorité. La plus vue est ` +
    `« ${bestGuess} »${confidence} — un indice, pas une plaque confirmée.`
  );
}

function formatWidth(widthPx: number | null): string {
  return widthPx === null ? "une largeur inconnue" : `${Math.round(widthPx)} px`;
}

/**
 * La synthèse du panneau de diagnostic, quand le silence est **massif**.
 *
 * Le seuil n'est pas décoratif : tant qu'une minorité de véhicules est muette, la
 * raison par ligne suffit. Quand la grande majorité l'est, la lecture par ligne
 * fait conclure à une panne, et une phrase d'ensemble évite vingt minutes passées
 * à déplacer des curseurs qui n'y changeront rien.
 *
 * `null` quand il n'y a rien à dire — l'appelant n'a pas à distinguer une chaîne
 * vide d'une absence de synthèse.
 */
export function plateSilenceSummary(
  belowFloor: number,
  published: number,
): string | null {
  if (belowFloor === 0) return null;
  if (belowFloor <= published * 3) return null;
  return (
    "La plupart des plaques de cette vidéo sont trop petites pour être lues " +
    `(plancher ~${READING_FLOOR_PX} px). Ce n'est pas une panne : la chaîne refuse ` +
    "d'inventer un texte qu'elle ne distingue pas."
  );
}
