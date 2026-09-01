/**
 * Le filtre par ligne du registre, sur les véhicules déjà chargés.
 *
 * Jumeau de `filterPlate.ts`, et pour les mêmes raisons : le registre tient
 * `result.vehicles` entièrement en mémoire et virtualise au-delà de 200 lignes,
 * donc filtrer coûte moins que le rendu que cela déclenche. Le point de bascule
 * reste le même — le jour où un écran **paginera** les véhicules, c'est lui qui
 * devra interroger le serveur, et il ne devra pas réutiliser ce filtre.
 *
 * Le nom affiché dans le menu vient du tracé **courant**, jamais d'une copie : une
 * ligne renommée après l'analyse change de nom dans le filtre sans qu'on relance
 * quoi que ce soit, comme partout ailleurs dans cette interface.
 */

import type { VehicleRecord } from "@/shared/api/contracts";

/**
 * Les véhicules ayant franchi cette ligne, **dans n'importe quel sens**.
 *
 * Les deux sens et non un seul : la question posée par ce filtre est « qui est
 * passé par là », pas « qui est entré ». Le sens se lit dans les colonnes
 * « Entrée par » et « Sortie par », qui restent affichées.
 *
 * Rend le tableau **tel quel** quand aucune ligne n'est choisie — même discipline
 * référentielle que `filterByPlate` : recréer un tableau identique ferait
 * recalculer la fenêtre virtualisée à chaque frappe dans le champ voisin.
 */
export function filterByLine(
  vehicles: readonly VehicleRecord[],
  lineId: string | null,
): readonly VehicleRecord[] {
  if (lineId === null) return vehicles;
  return vehicles.filter((vehicle) =>
    vehicle.crossedLines.some((crossing) => crossing.lineId === lineId),
  );
}
