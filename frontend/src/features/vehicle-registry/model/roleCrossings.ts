/**
 * Les franchissements d'un véhicule, **rangés par rôle de sens**.
 *
 * Ce que ce module rend possible dans le registre : deux colonnes « Entrée » et
 * « Sortie » portant l'**instant** du franchissement, là où « Lignes franchies »
 * ne donne que la liste des sens. La question à laquelle il répond est « à quelle
 * seconde ce véhicule est-il entré dans le carrefour, et à quelle seconde en est-il
 * ressorti » — jusqu'ici lisible seulement en survolant chaque puce une par une.
 *
 * Trois décisions qui ne se devinent pas :
 *
 * - **le rôle est lu sur la géométrie courante, pas sur le résultat archivé.** Le
 *   serveur ne connaît pas les rôles et ne les lit jamais (ADR 0016) : ils vivent
 *   dans le tracé. C'est ce qui rend la bascule d'un sens entrée ↔ sortie
 *   instantanée — même raison, même mécanique que `hasEnteredCrossroad` ;
 * - **une ligne retirée du tracé depuis l'analyse est ignorée**, jamais supposée
 *   « entrée ». Son rôle n'est plus lisible, et l'inventer fabriquerait une heure
 *   de franchissement fausse. Le franchissement reste visible dans « Lignes
 *   franchies », avec sa flèche brute ;
 * - **un rôle peut porter plusieurs franchissements**, et c'est le cas normal, pas
 *   un bord : un aller-retour, deux lignes d'entrée en travers de la même voie, ou
 *   une occlusion qui coupe la piste en donnent chacun deux (invariant 6). La
 *   cellule affiche donc le **premier** instant et annonce combien suivent — elle
 *   n'en cache aucun, et n'en fusionne aucun.
 */

import type { CountingLine, DirectionRole, VehicleRecord } from "@/shared/api/contracts";
import { directionRole, signOf } from "@/shared/lib/directions";

/** Un franchissement du registre, tel que le contrat le publie. */
export type VehicleCrossing = VehicleRecord["crossedLines"][number];

/**
 * Les franchissements de ce véhicule dont le sens porte ce rôle.
 *
 * L'ordre chronologique de `crossedLines` est conservé — c'est le contrat du champ,
 * et c'est lui qui fait du premier élément le **premier** franchissement et non un
 * quelconque.
 */
export function crossingsWithRole(
  vehicle: VehicleRecord,
  lines: readonly CountingLine[],
  role: DirectionRole,
): readonly VehicleCrossing[] {
  return vehicle.crossedLines.filter((crossing) => {
    const line = lines.find((candidate) => candidate.id === crossing.lineId);
    if (line === undefined) return false;
    return directionRole(line, signOf(crossing.direction)) === role;
  });
}
