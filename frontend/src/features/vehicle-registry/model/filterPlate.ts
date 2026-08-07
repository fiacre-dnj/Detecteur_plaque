/**
 * La recherche par plaque, sur le registre déjà chargé.
 *
 * **Côté client, et c'est un choix mesuré.** Le registre rend `result.vehicles`, un
 * objet déjà entièrement en mémoire, et virtualise au-delà de 200 lignes : filtrer
 * 10 000 enregistrements coûte moins que le rendu qu'il déclenche.
 *
 * Passer par `GET /jobs/{id}/vehicles?plate_text=…` introduirait une **seconde source**
 * pour un tableau dont les compteurs voisins viennent, eux, de la timeline locale — deux
 * vérités à l'écran, sans moyen de savoir laquelle croire (voir `StudioPage`). Et cette
 * route échoue sur un job purgé, alors que l'utilisateur a le résultat sous les yeux.
 *
 * Le point de bascule, écrit ici pour que personne ne s'y trompe : le jour où un écran
 * **paginera** les véhicules — un historique des jobs, par exemple — c'est lui qui devra
 * utiliser la route, et il ne devra pas réutiliser ce filtre. **Le critère est la
 * pagination, pas la taille du job.**
 */

import type { VehicleRecord } from "@/shared/api/contracts";
import { normalisePlate } from "@/shared/lib/plate";

/**
 * Les véhicules dont la plaque **lue** contient la requête.
 *
 * Sous-chaîne et non égalité : on cherche « 2418 » parce qu'on a relevé quatre chiffres
 * au passage, pas une plaque complète. Les deux côtés sont normalisés, donc `2418tbe`,
 * `2418-TBE` et `2418 tbe` trouvent la même ligne.
 *
 * Rend le tableau **tel quel** quand la requête est vide — même discipline
 * référentielle qu'`appendCrossings` : recréer un tableau identique ferait recalculer la
 * fenêtre virtualisée à chaque frappe, y compris sur un champ qu'on vient de vider.
 */
export function filterByPlate(
  vehicles: readonly VehicleRecord[],
  query: string,
): readonly VehicleRecord[] {
  const needle = normalisePlate(query);
  if (needle === "") return vehicles;
  return vehicles.filter((vehicle) =>
    normalisePlate(vehicle.plateText ?? "").includes(needle),
  );
}
