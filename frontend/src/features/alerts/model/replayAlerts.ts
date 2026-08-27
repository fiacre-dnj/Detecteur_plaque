/**
 * Les alertes d'un résultat **complet**, à la tête de lecture.
 *
 * C'est la source dès que l'analyse est terminée, et elle remplace le journal
 * vivant plutôt que de s'y ajouter. Trois propriétés qui n'appartiennent qu'à elle :
 *
 * - **rien n'est perdu** : le journal vivant est borné à 200 entrées, le résultat
 *   ne l'est pas. On filtre les infractions **avant** de borner, jamais l'inverse —
 *   borner d'abord garderait 200 franchissements quelconques dont peut-être aucune
 *   infraction ;
 * - **les règles sont relues sur le tracé courant** : déclarer un sens interdit
 *   après coup fait apparaître les alertes correspondantes sans réanalyser, comme
 *   basculer un sens entrée ↔ sortie ;
 * - **rien n'est montré que la vidéo n'a pas atteint**, exactement comme les
 *   sections voisines. Une alerte visible avant son instant se lirait comme un
 *   décalage du comptage.
 */

import type { CrossingEvent, VehicleRecord } from "@/shared/api/contracts";
import type { LineRule } from "@/shared/lib/lineRules";
import { violations } from "@/shared/lib/lineViolations";

import {
  alertFromPlateHit,
  alertFromViolation,
  crossingsBefore,
  sortAlerts,
  type Alert,
} from "./alerts";
import { plateHits, type PlateBearer } from "./plateWatch";

/** Ce qu'un résultat rejoué fournit aux alertes. */
export interface ReplayAlertInput {
  crossings: readonly CrossingEvent[];
  /**
   * Les véhicules déjà apparus à la tête de lecture — **tous**, pas seulement ceux
   * qui ont franchi une ligne.
   *
   * Une plaque recherchée peut appartenir à un véhicule à l'arrêt, qui ne coupe
   * aucun trait : le restreindre aux franchisseurs, comme le font le registre et la
   * statistique depuis ADR 0023, ferait manquer exactement le cas qu'on cherche.
   */
  vehicles: readonly VehicleRecord[];
  timeMs: number;
  rules: ReadonlyMap<string, LineRule>;
  watchlist: readonly string[];
}

/** Les alertes du résultat, la plus récente en tête. */
export function alertsFromResult(input: ReplayAlertInput): Alert[] {
  const found: Alert[] = violations(
    crossingsBefore(input.crossings, input.timeMs),
    input.rules,
  ).map(alertFromViolation);

  for (const hit of plateHits(input.vehicles.map(asPlateBearer), input.watchlist)) {
    const vehicle = input.vehicles.find((entry) => entry.globalId === hit.globalId);
    // Datée de la **première apparition** du véhicule : le vote de plaque porte sur
    // toute sa vie et n'a donc pas d'instant propre (invariant 4). C'est aussi
    // l'endroit où amener la vidéo — celui où on le voit arriver.
    found.push(alertFromPlateHit(hit, vehicle?.firstSeenMs ?? 0));
  }

  return sortAlerts(found);
}

function asPlateBearer(vehicle: VehicleRecord): PlateBearer {
  return {
    globalId: vehicle.globalId,
    label: vehicle.label,
    plateText: vehicle.plateText,
    plateTextScore: vehicle.plateTextScore,
  };
}
