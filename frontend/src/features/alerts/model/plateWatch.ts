/**
 * La recherche de plaque : confronter un texte **voté** à une liste de surveillance.
 *
 * **Côté client, et c'est la décision structurante.** Le serveur accepte la liste,
 * la persiste avec la configuration du job et la rend telle quelle sans jamais la
 * comparer à quoi que ce soit. Deux conséquences voulues :
 *
 * - corriger ou compléter la liste ne demande pas de relancer l'analyse ;
 * - la règle de correspondance n'existe **qu'ici**, donc elle ne peut pas diverger
 *   entre l'aperçu vivant et un résultat rouvert. Une plaque qui correspondrait
 *   pendant l'analyse et plus après serait le pire des deux résultats.
 *
 * Le texte comparé est toujours le **vote sur la vie du véhicule** (invariant 4),
 * jamais la lecture d'une image : deux relectures du même clip donneraient sinon
 * deux plaques, donc deux alertes différentes.
 */

import { normalisePlate } from "@/shared/lib/plate";

/**
 * La qualité d'une correspondance.
 *
 * - `exact` — les deux formes normalisées sont identiques ;
 * - `partial` — l'une contient l'autre.
 *
 * **La correspondance partielle n'est pas du confort.** ADR 0029 documente que
 * l'OCR perd régulièrement le premier caractère d'une plaque (`AR606L` lu
 * `R606L`) : l'exact seul raterait le cas le plus fréquent, en silence, sur
 * précisément la fonctionnalité qu'on a demandée. Elle est signalée comme
 * *probable* et jamais présentée comme une certitude.
 */
export type PlateMatch = "exact" | "partial";

/**
 * Ce qu'il faut d'un objet pour y chercher une plaque.
 *
 * Structurel plutôt que nominal, pour que `TrackSnapshot` et `VehicleRecord`
 * conviennent tous deux sans conversion : les deux portent le même vote, publié par
 * le même sérialiseur.
 */
export interface PlateBearer {
  globalId: number;
  /** Classe **votée**, pour colorer la pastille sans la faire clignoter. */
  label: string;
  plateText: string | null;
  plateTextScore: number | null;
}

/** Un véhicule dont la plaque correspond à une entrée surveillée. */
export interface PlateHit {
  globalId: number;
  label: string;
  /** Le texte tel que le serveur l'a publié, jamais la forme normalisée. */
  plateText: string;
  plateTextScore: number | null;
  /** L'entrée de la liste qui correspond, telle que l'utilisateur l'a tapée. */
  watched: string;
  match: PlateMatch;
}

/**
 * En dessous, une sous-chaîne ne désigne plus une plaque.
 *
 * Trois caractères communs entre deux plaques quelconques sont un hasard fréquent ;
 * la borne du serveur sur les entrées de la liste (4 caractères) vaut donc aussi
 * pour le texte lu, sans quoi une lecture tronquée à deux caractères
 * correspondrait à presque tout.
 */
const MIN_PARTIAL_CHARS = 4;

/**
 * L'entrée surveillée qui correspond à ce texte, ou `null`.
 *
 * **La première correspondance exacte l'emporte sur toute correspondance
 * partielle**, quel que soit l'ordre de la liste : afficher « probable » alors
 * qu'une entrée correspond exactement ferait douter d'une certitude.
 */
export function matchPlate(
  plateText: string | null,
  watchlist: readonly string[],
): { watched: string; match: PlateMatch } | null {
  const read = normalisePlate(plateText ?? "");
  if (read.length < MIN_PARTIAL_CHARS) return null;

  let partial: { watched: string; match: PlateMatch } | null = null;
  for (const watched of watchlist) {
    const wanted = normalisePlate(watched);
    if (wanted.length < MIN_PARTIAL_CHARS) continue;
    if (wanted === read) return { watched, match: "exact" };
    if (partial === null && (read.includes(wanted) || wanted.includes(read))) {
      partial = { watched, match: "partial" };
    }
  }
  return partial;
}

/**
 * Les véhicules dont la plaque correspond, dans l'ordre reçu.
 *
 * Rend un tableau **vide** — et non l'entrée — quand la liste est vide : c'est le
 * cas de très loin le plus fréquent, et le sortir en tête évite de normaliser une
 * plaque par véhicule et par image d'aperçu pour rien.
 */
export function plateHits(
  bearers: readonly PlateBearer[],
  watchlist: readonly string[],
): PlateHit[] {
  if (watchlist.length === 0) return [];

  const hits: PlateHit[] = [];
  for (const bearer of bearers) {
    if (bearer.plateText === null) continue;
    const matched = matchPlate(bearer.plateText, watchlist);
    if (matched === null) continue;
    hits.push({
      globalId: bearer.globalId,
      label: bearer.label,
      plateText: bearer.plateText,
      plateTextScore: bearer.plateTextScore,
      watched: matched.watched,
      match: matched.match,
    });
  }
  return hits;
}
