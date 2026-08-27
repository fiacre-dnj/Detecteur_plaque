/**
 * Les infractions d'un véhicule, pour la colonne du registre.
 *
 * Le prédicat lui-même vit dans `shared/lib/lineViolations.ts` : les alertes le
 * signalent, le tableau de bord le compte, ce module ne fait que l'appliquer aux
 * franchissements d'un véhicule. Trois copies de « ce passage est-il en
 * infraction » finiraient par ranger le même passage différemment selon l'écran.
 *
 * **Les règles sont lues sur le tracé courant**, comme les rôles de sens : déclarer
 * un sens interdit après coup fait apparaître la colonne et ses pastilles sans
 * réanalyser.
 */

import type { VehicleRecord } from "@/shared/api/contracts";
import type { LineRule } from "@/shared/lib/lineRules";
import { violationOf, type ViolationKind } from "@/shared/lib/lineViolations";

/** Une infraction telle que la cellule l'affiche. */
export interface VehicleViolation {
  kind: ViolationKind;
  lineId: string;
  lineName: string;
  direction: number;
  timestampMs: number;
}

/**
 * Les infractions de ce véhicule, dans l'ordre chronologique de `crossedLines`.
 *
 * `crossedLines` ne porte ni classe ni plaque — seulement la ligne, le sens et
 * l'instant — alors que `violationOf` a besoin de la classe pour juger une voie
 * réservée. On la lui donne depuis `vehicle.label`, qui est la classe **votée** sur
 * la vie du véhicule (invariant 4) : c'est exactement ce que porte
 * `CrossingEvent.label`, donc le même verdict qu'ailleurs.
 */
export function vehicleViolations(
  vehicle: VehicleRecord,
  rules: ReadonlyMap<string, LineRule>,
): VehicleViolation[] {
  const found: VehicleViolation[] = [];
  for (const crossing of vehicle.crossedLines) {
    const violation = violationOf(
      {
        lineId: crossing.lineId,
        globalId: vehicle.globalId,
        trackId: vehicle.globalId,
        label: vehicle.label,
        category: "vehicle",
        direction: crossing.direction,
        timestampMs: crossing.timestampMs,
        frameIndex: 0,
        plateText: vehicle.plateText,
        plateTextScore: vehicle.plateTextScore,
      },
      rules,
    );
    if (violation === null) continue;
    found.push({
      kind: violation.kind,
      lineId: crossing.lineId,
      lineName: violation.rule.lineName,
      direction: crossing.direction,
      timestampMs: crossing.timestampMs,
    });
  }
  return found;
}
