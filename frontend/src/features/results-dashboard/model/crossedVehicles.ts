/**
 * Ce qui distingue un **véhicule du trafic** d'un objet suivi.
 *
 * Le serveur compte tout ce que le tracker confirme : une voiture en
 * stationnement, un véhicule à l'arrêt dans un coin du champ et un véhicule qui
 * traverse le carrefour pèsent tous `1` dans `trackedVehicles`. Sur une scène
 * réelle l'écart est énorme — **106 objets suivis pour 28 entrées** relevés sur
 * une seule analyse — et les deux chiffres, posés l'un sous l'autre, se lisaient
 * comme une contradiction.
 *
 * Ce module donne les deux prédicats qui rendent les compteurs comparables, et
 * il est le **seul** endroit qui les définit — même raison qu'`isEntryRow` dans
 * `directions.ts` : deux fichiers qui décident chacun ce qu'est un véhicule
 * compté finiraient par diverger, et un véhicule changerait de total selon
 * l'écran qui le montre.
 *
 * **Tout est dérivé de `VehicleRecord.crossedLines`**, jamais d'un compteur
 * parallèle (invariant 3), et **tout est calculé côté client**. C'est ce qui
 * rend le basculement d'un sens entrée ↔ sortie *instantané* : le serveur ne
 * connaît pas les rôles, il ne les lit jamais, donc corriger un rôle après coup
 * recalcule tout sans relancer la moindre analyse. Déplacer ce calcul côté
 * serveur figerait les rôles dans le résultat archivé et rendrait la bascule
 * inopérante.
 */

import type { CountingLine, VehicleRecord } from "@/shared/api/contracts";
import { directionRole, signOf } from "@/shared/lib/directions";

/**
 * Ce véhicule a-t-il franchi au moins une ligne, **tous sens confondus** ?
 *
 * Le filtre du registre. Un véhicule qui n'a franchi aucune ligne n'a pas
 * participé au trafic mesuré : il stationnait, il attendait, ou le détecteur
 * l'a tenu quelques images sans qu'il aille nulle part. Le publier remplissait
 * le registre de lignes à « — » que rien ne permettait de vérifier — et c'est
 * précisément ce que le registre existe pour permettre.
 */
export function hasCrossedAnyLine(vehicle: VehicleRecord): boolean {
  return vehicle.crossedLines.length > 0;
}

/**
 * Ce véhicule est-il **entré dans le carrefour** ?
 *
 * La définition retenue : *un véhicule qui traverse le carrefour est un véhicule
 * qui est passé dans le sens « entrée » d'une ligne*. Un véhicule qui n'a été vu
 * que sortir n'est pas compté ici — il est entré hors champ, et le compter
 * doublerait le trafic d'un carrefour dont toutes les branches sont
 * instrumentées.
 *
 * Une ligne retirée du tracé depuis l'analyse est **ignorée** plutôt que
 * comptée : on ne peut plus lire son rôle, et supposer « entrée » inventerait un
 * chiffre. Même garde que `flowBucketsByLine` avant sa suppression.
 */
export function hasEnteredCrossroad(
  vehicle: VehicleRecord,
  lines: readonly CountingLine[],
): boolean {
  return vehicle.crossedLines.some((crossing) => {
    const line = lines.find((candidate) => candidate.id === crossing.lineId);
    if (line === undefined) return false;
    return directionRole(line, signOf(crossing.direction)) === "entry";
  });
}

/** Les véhicules du registre : ceux qui ont réellement franchi quelque chose. */
export function crossingVehicles(
  vehicles: readonly VehicleRecord[],
): readonly VehicleRecord[] {
  return vehicles.filter(hasCrossedAnyLine);
}

/**
 * Combien de véhicules **distincts** sont entrés dans le carrefour.
 *
 * Un nombre de *véhicules*, jamais de passages : un véhicule qui entre deux fois
 * — deux lignes d'entrée franchies, ou un aller-retour — compte **1** ici et
 * **2** dans les passages en entrée de sa ligne. Les deux chiffres répondent à
 * deux questions (« combien de véhicules », « combien de passages ») et ne
 * doivent jamais être divisés l'un par l'autre : c'est l'invariant 3, et il a
 * déjà coûté un taux à 200 %.
 *
 * **Ce n'est plus le chiffre de tête**, qui compte depuis ADR 0045 les véhicules
 * ayant franchi **n'importe quelle** ligne (`crossingVehicles`) et non les seuls
 * entrants. Cette fonction reste le compteur du bilan de carrefour, dans
 * `LineFlowDashboard`.
 */
export function enteringVehicleCount(
  vehicles: readonly VehicleRecord[],
  lines: readonly CountingLine[],
): number {
  return vehicles.filter((vehicle) => hasEnteredCrossroad(vehicle, lines)).length;
}
