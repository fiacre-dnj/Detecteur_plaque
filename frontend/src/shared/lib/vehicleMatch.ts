/**
 * « Ce véhicule ressemble-t-il à celui qu'on cherche ? » — un seul juge.
 *
 * Dans `shared/lib/` et non dans une feature, pour la raison exacte qui y a mis
 * `lineRules.ts`, `lineViolations.ts` et `violationTally.ts` : **trois** features en
 * ont besoin, et une feature n'importe jamais une autre.
 *
 * - `vehicle-search` s'en sert pour son curseur ;
 * - `alerts` pour décider ce qu'elle signale ;
 * - `vehicle-registry` pour teinter sa colonne « Ressemblance ».
 *
 * Trois copies d'un seuil finiraient par diverger, et l'écart serait de la pire
 * espèce : un véhicule signalé dans le tiroir d'alertes et non teinté dans le
 * registre, ou l'inverse. Même mode de panne que celui qui a fait naître
 * `shared/lib/directions.ts`.
 *
 * **Ce que ces fonctions ne font pas** : trancher. Mesuré (ADR 0048), les
 * distributions de similarité se recouvrent — deux vues du même véhicule descendent à
 * 0,387, deux véhicules différents montent à 0,891. Ce module classe et teinte ; c'est
 * l'opérateur qui décide, sur la capture.
 */

/**
 * Seuil de ressemblance par défaut, en similarité cosinus.
 *
 * Posé entre les deux moyennes mesurées (0,816 pour le même véhicule, 0,249 pour deux
 * véhicules différents), **du côté du rappel** : mieux vaut un candidat de trop qu'un
 * véhicule manqué, puisque chaque candidat est vérifiable sur sa capture.
 */
export const DEFAULT_MATCH_THRESHOLD = 0.55;

/**
 * Seuil de **re-détection** — « ce véhicule est-il déjà passé ? ».
 *
 * Plus haut que celui de la recherche par image, et pas par prudence décorative : les
 * deux ne posent pas la même question. Là-bas l'utilisateur a fourni une photo, donc
 * il **attend** des candidats et un faux positif se balaie d'un coup d'œil ; ici
 * personne n'a rien demandé, et la carte affirme d'elle-même une identité entre deux
 * véhicules. Se tromper y coûte plus cher, d'où le côté de la précision plutôt que
 * celui du rappel.
 *
 * L'autre raison est structurelle : la re-détection compare chaque franchisseur à
 * **tous** les précédents, donc le nombre de comparaisons croît avec le clip. Le
 * meilleur score d'un lot de cent est mécaniquement plus haut que celui d'un lot de
 * deux, et un seuil calé sur la recherche par image dériverait avec la durée de la
 * vidéo.
 *
 * **À mesurer sur le métrage réel** (`scripts/reid_bench.py`) : la valeur ci-dessous
 * est un point de départ raisonné, pas un chiffre mesuré, et l'écran promet de toute
 * façon des candidats à vérifier sur la capture.
 */
export const DEFAULT_REMATCH_THRESHOLD = 0.75;

/**
 * Le score dépasse-t-il le seuil ?
 *
 * `null` et `undefined` ne sont **jamais** des correspondances, et leurs deux causes se
 * confondent ici volontairement : aucune image de requête, ou véhicule jamais encodé
 * parce que trop petit ou trop flou. Dans les deux cas il n'y a rien à classer, et
 * l'écran n'a pas à faire la différence.
 */
export function matches(
  score: number | null | undefined,
  threshold: number | null,
): boolean {
  if (threshold === null || score === null || score === undefined) return false;
  return score >= threshold;
}

/**
 * Sûre ou probable — deux niveaux, jamais un score continu affiché tel quel.
 *
 * Même raison que pour les plaques recherchées : la couleur encode la gravité, et
 * « 0,63 » ne se lit pas d'un coup d'œil dans une pile de vingt cartes.
 *
 * Le seuil haut est à **mi-chemin entre le seuil de l'utilisateur et 1**, donc il suit
 * le curseur. Un second seuil fixe serait un réglage caché : à curseur 0,80 il
 * classerait tout en « sûr », et à 0,30 tout en « probable ».
 */
export function matchStrength(score: number, threshold: number): "exact" | "partial" {
  return score >= threshold + (1 - threshold) / 2 ? "exact" : "partial";
}
