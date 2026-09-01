/**
 * Le graphique de répartition — le pendant visuel des cartes par type de
 * `ResultsDashboard`, mêmes chiffres (`crossedByClass`, passé en prop par
 * l'appelant pour ne calculer qu'une fois — voir `StudioPage`).
 *
 * Un camembert, comme `LineFlowChart` désormais : la question posée par cette
 * section est « quelle part du trafic est de quel type », et une part se lit plus
 * vite dans une tranche de cercle que dans une barre relative qu'il faut comparer
 * aux autres barres une à une.
 *
 * **Il compte des véhicules distincts depuis ADR 0045**, comme le chiffre de tête
 * et comme les cartes par type. Il découpait auparavant « Passages en entrée » ;
 * garder cette unité ici pendant que les cartes changeaient aurait posé deux
 * découpes du même camembert côte à côte, avec des chiffres différents et tous
 * les deux plausibles.
 */

import { classColor } from "@/shared/config/palettes";
import { classLabel } from "@/shared/lib/classes";

import { PieChart } from "./PieChart";

interface ClassEntriesChartProps {
  /** `crossedByClass(vehicles)`, déjà calculé par l'appelant. */
  entries: Record<string, number>;
  /** Les classes à tracer, dans l'ordre d'affichage — véhicules puis, si cochée, personnes. */
  classes: readonly string[];
}

export function ClassEntriesChart({ entries, classes }: ClassEntriesChartProps) {
  const slices = classes.map((klass) => ({
    id: klass,
    label: classLabel(klass),
    value: entries[klass] ?? 0,
    color: classColor(klass),
  }));

  return (
    <PieChart
      title="Répartition par type"
      slices={slices}
      emptyMessage="Aucun véhicule n'a franchi de ligne sur la période analysée."
      // « véhicule » et non « passage » : ce camembert découpe « Passages globaux »
      // et rien d'autre. Le camembert voisin, lui, découpe des **passages** par
      // ligne. Deux unités dans la même rangée, c'est l'erreur que l'invariant 3
      // interdit — et elle serait invisible, les deux chiffres étant plausibles.
      // C'est précisément pour cela que `metric` est une prop et non une devinette.
      unit={{ one: "type", many: "types" }}
      metric="véhicule"
    />
  );
}

export default ClassEntriesChart;
