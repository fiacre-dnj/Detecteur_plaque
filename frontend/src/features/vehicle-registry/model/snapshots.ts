/**
 * Ce que le registre sait des captures, sans rien afficher.
 *
 * En modèle et non dans le composant : ce sont trois décisions qui se testent sans
 * DOM — la colonne existe-t-elle, quelle hauteur de rangée, et entre quels véhicules
 * la modale navigue.
 */

import type { VehicleRecord } from "@/shared/api/contracts";

import { ROW_HEIGHT, SNAPSHOT_ROW_HEIGHT } from "./virtualise";

/** Ce véhicule a-t-il une photo ? La non-nullité du score **est** le drapeau. */
export function hasSnapshot(vehicle: VehicleRecord): boolean {
  return (vehicle.snapshotScore ?? null) !== null;
}

/**
 * Une capture existe-t-elle **quelque part** dans ce registre ?
 *
 * À calculer sur la liste **entière** et jamais sur les rangées rendues ni sur le
 * jeu filtré : une colonne qui apparaîtrait au défilement d'un tableau virtualisé —
 * ou au changement d'un filtre — décalerait toutes les autres sous le curseur. Elle
 * existe pour tout le tableau, ou pour aucun. C'est la règle déjà appliquée aux
 * colonnes « Autres passages » et « Infraction ».
 */
export function hasSnapshots(vehicles: readonly VehicleRecord[]): boolean {
  return vehicles.some(hasSnapshot);
}

/** La hauteur de rangée qu'impose la présence — ou non — de la colonne. */
export function snapshotRowHeight(withSnapshots: boolean): number {
  return withSnapshots ? SNAPSHOT_ROW_HEIGHT : ROW_HEIGHT;
}

/**
 * Les véhicules entre lesquels la modale navigue, dans l'ordre du tableau.
 *
 * Seulement ceux qui ont une photo : passer par les autres afficherait une modale
 * vide, et l'utilisateur devrait deviner qu'il faut continuer à cliquer.
 *
 * Sur la liste **affichée** — filtres compris — et non sur le registre entier :
 * quand on a filtré sur une ligne, « suivant » doit rester dans ce qu'on regarde.
 */
export function capturedVehicles(
  vehicles: readonly VehicleRecord[],
): readonly VehicleRecord[] {
  return vehicles.filter(hasSnapshot);
}

/**
 * Le véhicule voisin dans cette liste, ou `null` au bout.
 *
 * `null` et non un bouclage : revenir au premier après le dernier fait perdre le fil
 * sur un registre long — on ne sait plus si on a tout vu.
 */
export function neighbourVehicle(
  vehicles: readonly VehicleRecord[],
  globalId: number,
  step: 1 | -1,
): VehicleRecord | null {
  const index = vehicles.findIndex((vehicle) => vehicle.globalId === globalId);
  if (index < 0) return null;
  return vehicles[index + step] ?? null;
}
