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
  alertFromRematch,
  alertFromVehicleMatch,
  alertFromViolation,
  crossingsBefore,
  firstCrossingOf,
  sortAlerts,
  type Alert,
} from "./alerts";
import { plateHits, type PlateBearer } from "./plateWatch";
// La règle de seuil vit dans `vehicle-search` et **n'est pas recopiée ici** : le
// tiroir de réglage, ce module et la colonne du registre la lisent tous les trois,
// et trois copies d'un seuil finiraient par diverger. Une feature n'importe jamais
// une autre feature — c'est donc `shared` qui la porte.
import { matches, matchStrength } from "@/shared/lib/vehicleMatch";

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
  /**
   * Seuil de ressemblance, ou `null` — aucune recherche par image en cours.
   *
   * `null` et non `0` : le second signalerait **tout** véhicule encodé, y compris
   * ceux dont le score est négatif. Confondre les deux remplirait le tiroir d'alertes
   * de la totalité du trafic.
   */
  matchThreshold: number | null;
  /**
   * Seuil de **re-détection**, ou `null` — l'analyse n'a pas été lancée avec.
   *
   * Distinct de `matchThreshold` et pas par symétrie : les deux ne posent pas la
   * même question, et la re-détection compare à un lot qui grandit avec le clip.
   * Voir `DEFAULT_REMATCH_THRESHOLD`.
   */
  rematchThreshold: number | null;
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

  const threshold = input.matchThreshold;
  if (threshold !== null) {
    for (const vehicle of input.vehicles) {
      // Bornée à la tête de lecture comme les infractions : signaler un véhicule que
      // la vidéo n'a pas encore atteint donnerait une alerte invérifiable, et cliquer
      // dessus reculerait la lecture.
      if (vehicle.firstSeenMs > input.timeMs) continue;
      if (!matches(vehicle.matchScore, threshold)) continue;
      found.push(
        alertFromVehicleMatch(vehicle, matchStrength(vehicle.matchScore as number, threshold)),
      );
    }
  }

  // La re-détection. Bornée sur l'instant du **franchissement** et non sur la
  // première apparition : c'est celui que la carte affiche et celui où le clic
  // amènera la vidéo, donc c'est lui qui doit être atteint.
  const rematchThreshold = input.rematchThreshold;
  if (rematchThreshold !== null) {
    for (const vehicle of input.vehicles) {
      if (vehicle.rematchOf == null) continue;
      if (!matches(vehicle.rematchScore, rematchThreshold)) continue;
      const crossing = firstCrossingOf(vehicle, input.rules);
      if (crossing.timestampMs > input.timeMs) continue;
      found.push(
        alertFromRematch(
          vehicle,
          crossing,
          matchStrength(vehicle.rematchScore as number, rematchThreshold),
        ),
      );
    }
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
