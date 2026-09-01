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
