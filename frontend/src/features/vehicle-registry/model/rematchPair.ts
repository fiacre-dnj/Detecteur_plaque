/**
 * Les deux véhicules d'une re-détection, à comparer côte à côte (ADR 0055).
 *
 * Un module à part et non trois lignes dans le composant, pour la règle qu'il porte :
 * **l'antécédent se cherche dans TOUS les véhicules, jamais dans le jeu filtré.** Il
 * peut très bien être masqué par le filtre courant — une ligne choisie, une recherche
 * de plaque — et refuser de le montrer viderait la comparaison de son sens
 * précisément quand on en a besoin. Le filtre décide de ce qu'on **parcourt**, pas de
 * ce qu'on a le droit de regarder de plus près.
 */

import type { VehicleRecord } from "@/shared/api/contracts";
import { matches } from "@/shared/lib/vehicleMatch";

/**
 * Ce véhicule porte-t-il une re-détection **à laquelle on croit** ?
 *
 * Le seuil entre dans le prédicat, et c'est un changement de doctrine assumé. La
 * colonne affichait les scores sous le curseur en gris, au motif qu'on voulait
 * « voir qu'on est passé à côté de peu ». Mesuré à l'usage, le résultat est
 * l'inverse : sur une vidéo doublée, les sept véhicules de la première moitié —
 * qui n'ont par construction **aucun** jumeau antérieur — affichaient tous un
 * numéro à 2, 27 ou 38 %, et l'écran se lisait comme « le système se trompe partout ».
 *
 * Une identité affirmée à 2 % n'est pas une information nuancée, c'est une
 * affirmation fausse. Le score brut reste dans l'infobulle, où il sert au réglage
 * sans rien prétendre.
 *
 * Aligne du même coup le registre sur le tiroir d'alertes, qui applique déjà le
 * seuil : les deux surfaces disaient deux choses différentes des mêmes données.
 */
export function isRematched(vehicle: VehicleRecord, threshold: number): boolean {
  return vehicle.rematchOf != null && matches(vehicle.rematchScore, threshold);
}

/**
 * Le registre porte-t-il **au moins une** re-détection crédible ?
 *
 * Décidé sur `vehicles` entier et jamais sur les rangées rendues, même règle que
 * « Capture » et « Ressemblance » : une colonne qui apparaîtrait au défilement
 * décalerait toutes les autres sous le curseur.
 */
export function hasRematch(vehicles: readonly VehicleRecord[], threshold: number): boolean {
  return vehicles.some((vehicle) => isRematched(vehicle, threshold));
}

/**
 * Les deux côtés, **dans l'ordre chronologique**.
 *
 * `earlier` est le véhicule déposé dans la galerie, `later` celui qui vient de le
 * reconnaître. L'ordre est celui du temps et non celui du clic : on lit de gauche à
 * droite, et « le même véhicule est repassé » se raconte dans ce sens. L'inverser
 * selon la rangée cliquée ferait changer la disposition d'une comparaison à l'autre,
 * alors que c'est la stabilité qui permet de comparer.
 */
export interface RematchPair {
  earlier: VehicleRecord;
  later: VehicleRecord;
}

/**
 * La paire à comparer pour ce véhicule, ou `null`.
 *
 * `null` couvre trois cas que l'écran n'a pas à distinguer — il n'ouvre simplement
 * pas de modale : le véhicule n'existe pas dans la liste, il n'a pas été re-détecté,
 * ou son antécédent est introuvable.
 *
 * **Le troisième ne devrait pas arriver** — le serveur ne désigne que des véhicules
 * de la même analyse — mais un résultat rouvert n'a pas à faire confiance à cette
 * invariance pour décider d'afficher deux images. Une comparaison avec un côté vide
 * ne compare rien.
 */
export function rematchPair(
  vehicles: readonly VehicleRecord[],
  globalId: number,
): RematchPair | null {
  const later = vehicles.find((entry) => entry.globalId === globalId);
  if (later === undefined || later.rematchOf == null) return null;
  const earlier = vehicles.find((entry) => entry.globalId === later.rematchOf);
  return earlier === undefined ? null : { earlier, later };
}
