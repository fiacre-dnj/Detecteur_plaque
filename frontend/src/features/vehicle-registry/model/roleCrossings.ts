/**
 * Les franchissements d'un véhicule, **rangés par rôle de sens**.
 *
 * Ce que ce module rend possible dans le registre : deux colonnes « Entrée par » et
 * « Sortie par », portant chacune **la ligne et l'instant** du franchissement. Elles
 * remplacent « Lignes franchies », qui listait les deux sens dans une seule cellule
 * pendant que deux colonnes voisines n'en portaient que l'heure : lire « ce véhicule
 * est entré par la ligne 1 à 00:34 » demandait de recoller trois cellules, dont une
 * par survol.
 *
 * Trois décisions qui ne se devinent pas :
 *
 * - **le rôle est lu sur la géométrie courante, pas sur le résultat archivé.** Le
 *   serveur ne connaît pas les rôles et ne les lit jamais (ADR 0016) : ils vivent
 *   dans le tracé. C'est ce qui rend la bascule d'un sens entrée ↔ sortie
 *   instantanée — même raison, même mécanique que `hasEnteredCrossroad` ;
 * - **une ligne retirée du tracé depuis l'analyse est ignorée**, jamais supposée
 *   « entrée ». Son rôle n'est plus lisible, et l'inventer fabriquerait une heure
 *   de franchissement fausse. Ces franchissements-là sont rendus par
 *   `crossingsWithoutRole` dans une colonne à part, qui n'apparaît que s'il en
 *   existe : les ranger sous un rôle serait une invention, les taire ferait
 *   diverger le registre de la colonne « Passages », qui les compte ;
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

/**
 * Les franchissements de ce véhicule **qu'aucun rôle ne réclame**.
 *
 * Deux cas, et aucun n'est une anomalie du comptage :
 *
 * - la ligne a été **retirée du tracé** depuis l'analyse — son rôle n'existe plus
 *   nulle part, et le franchissement, lui, a bien eu lieu ;
 * - le sens est resté `neutral`, c'est-à-dire un tracé antérieur au 2026-08-16, où
 *   le rôle est devenu obligatoire (ADR 0021).
 *
 * Le complément exact des rôles que les colonnes portent : ce que ces fonctions
 * rendent, mises bout à bout, est `vehicle.crossedLines` — c'est ce qui empêche le
 * registre de perdre un passage en le rangeant par rôle.
 *
 * **Elle est écrite comme un complément et non comme une liste de cas**, et c'est
 * la seule forme correcte : `=== "neutral"` avait été écrite quand `neutral` était
 * le seul rôle sans colonne, et l'arrivée de « Interdit » et « Passage » aurait
 * fait disparaître ces franchissements des deux côtés — ni rangés sous un rôle, ni
 * comptés hors rôle. Un passage perdu, sans que rien ne plante.
 */
export function crossingsWithoutRole(
  vehicle: VehicleRecord,
  lines: readonly CountingLine[],
): readonly VehicleCrossing[] {
  return vehicle.crossedLines.filter((crossing) => {
    const line = lines.find((candidate) => candidate.id === crossing.lineId);
    if (line === undefined) return true;
    return !COLUMN_ROLES.includes(directionRole(line, signOf(crossing.direction)));
  });
}

/**
 * Les rôles qui ont **leur propre colonne** dans le registre.
 *
 * `forbidden` en fait partie via la colonne « Infraction », qui porte ses
 * franchissements : les ranger *aussi* dans « Autres passages » les compterait deux
 * fois dans une partition qui doit rester exacte.
 *
 * `transit` n'en fait **pas** partie, et c'est délibéré : il n'a pas de colonne, et
 * lui en inventer une pour une ligne de comptage seul — dont tout l'intérêt est de
 * ne rien classer — ajouterait une colonne vide sur tous les autres tracés. Ses
 * franchissements tombent donc dans « Autres passages », ce que ce nom dit
 * exactement.
 */
const COLUMN_ROLES: readonly DirectionRole[] = ["entry", "exit", "forbidden"];
