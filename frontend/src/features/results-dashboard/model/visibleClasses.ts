/**
 * Quelles cartes de type de véhicule s'affichent — le pont entre « Objets à
 * compter » et la Répartition.
 *
 * Dans `model/` et pas dans le composant : `ResultsDashboard` et
 * `ClassEntriesChart` doivent montrer **exactement** les mêmes classes, et deux
 * listes écrites séparément divergeraient sur un décochage — le camembert
 * afficherait une part que les KPI voisins ne montrent pas.
 */

import { VEHICLE_CLASSES } from "@/shared/lib/classes";

/**
 * Les classes qui méritent une carte : celles que l'utilisateur a cochées, plus
 * celles que le résultat porte déjà.
 *
 * **Deux règles, et la seconde est celle qui a coûté un bug.** La sélection
 * commande — un KPI « Moto » sous une analyse qui n'a jamais cherché de moto
 * annonce un zéro qui se lit comme « aucune moto n'est passée », alors que la
 * vérité est « on n'en a pas cherché ». Mais une classe **décochée après coup**
 * qui porte des entrées garde sa carte : rouvrir un résultat archivé puis
 * décocher une case effacerait une colonne de son propre contenu.
 *
 * L'ordre est celui de `VEHICLE_CLASSES` — l'ordre d'affichage voulu, pas celui
 * des clics — et les classes hors de cette liste (`bicycle`, `person`, `train`…)
 * suivent, dans l'ordre où l'appelant les donne. Une classe inconnue de
 * `VEHICLE_CLASSES` reste donc affichable sans avoir à toucher ce module.
 */
export function visibleClasses(
  selected: readonly string[],
  entries: Readonly<Record<string, number>>,
): readonly string[] {
  const wanted = new Set<string>(selected);
  for (const [klass, count] of Object.entries(entries)) {
    if (count > 0) wanted.add(klass);
  }
  const ordered = VEHICLE_CLASSES.filter((klass) => wanted.has(klass));
  const rest = [...selected, ...Object.keys(entries)].filter(
    (klass) => wanted.has(klass) && !VEHICLE_CLASSES.includes(klass as never),
  );
  return [...ordered, ...new Set(rest)];
}
