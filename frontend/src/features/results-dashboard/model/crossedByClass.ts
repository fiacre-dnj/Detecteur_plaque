/**
 * Les véhicules ayant franchi, **par type**, en véhicules distincts.
 *
 * Le pendant par classe de « Passages globaux » : sa somme lui est exactement
 * égale, par construction, parce que les deux comptent la même population — les
 * véhicules du registre — et que chacun n'y porte qu'une seule classe.
 *
 * **C'est le remplaçant d'`entriesByClass`, et il change d'unité.** L'ancien
 * sommait `stats.byLine[*].byDirection[*].byClass` sur les sens marqués
 * « entrée » : des **passages**, où un aller-retour valait deux. Il découpait
 * fidèlement « Passages en entrée », qui n'existe plus. Sous « Passages globaux »
 * il produirait des cartes dont la somme dépasserait le chiffre de tête, et deux
 * chiffres plausibles qui ne s'additionnent pas sont pires que pas de chiffre du
 * tout.
 *
 * **La classe est celle qui est votée** (`vehicle.label`, invariant 4) et non la
 * lecture d'une image : c'est la même clé que les `byClass` du serveur, donc les
 * cartes, le camembert et le résumé d'alertes parlent tous de la même population.
 *
 * **Calculé côté client, comme tout ce qui dérive du registre.** Le serveur ne
 * connaît pas les rôles de sens et ne les lira jamais ; ici il n'y en a même plus
 * besoin — un véhicule compte dès qu'il a franchi quelque chose, quel que soit le
 * rôle du sens. C'est ce qui rend le chiffre insensible au fait de basculer un sens
 * entrée ↔ sortie après coup.
 */

import type { VehicleRecord } from "@/shared/api/contracts";

import { hasCrossedAnyLine } from "./crossedVehicles";

/**
 * Véhicules distincts ayant franchi au moins une ligne, par nom COCO.
 *
 * Même forme de retour qu'`entriesByClass` — un `Record<string, number>` — pour
 * que `visibleClasses` et le camembert le consomment sans rien savoir du
 * changement d'unité.
 *
 * Une classe sans véhicule n'a **pas** d'entrée : `visibleClasses` décide seul de
 * ce qui s'affiche, en réunissant les classes cochées et celles qui portent un
 * compte. Poser des zéros ici ferait entrer dans cette réunion des classes que
 * personne n'a cochées et que personne n'a vues.
 */
export function crossedByClass(
  vehicles: readonly VehicleRecord[],
): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const vehicle of vehicles) {
    // Le prédicat est réappliqué alors que l'appelant passe déjà, en pratique, la
    // liste du registre : `crossedVehicles.ts` reste le seul juge de ce qu'est un
    // véhicule compté, et un parcours de plus ne coûte rien face à deux définitions
    // qui divergeraient.
    if (!hasCrossedAnyLine(vehicle)) continue;
    counts[vehicle.label] = (counts[vehicle.label] ?? 0) + 1;
  }
  return counts;
}
