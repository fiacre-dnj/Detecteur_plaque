/**
 * Le graphique de répartition — le pendant visuel des cartes de
 * `ClassEntriesGrid`, mêmes chiffres (`entriesByClass`, passé en prop par
 * l'appelant pour ne calculer qu'une fois — voir `StudioPage`).
 *
 * Un camembert, comme `LineFlowChart` désormais : la question posée par cette
 * section est « quelle part du trafic entrant est de quel type », et une part
 * se lit plus vite dans une tranche de cercle que dans une barre relative
 * qu'il faut comparer aux autres barres une à une.
 */

import { classColor } from "@/shared/config/palettes";
import { classLabel } from "@/shared/lib/classes";

import { PieChart } from "./PieChart";

interface ClassEntriesChartProps {
  /** `entriesByClass(stats, lines)`, déjà calculé par l'appelant. */
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
      title="Répartition des entrées"
      slices={slices}
      emptyMessage="Aucune entrée sur la période analysée."
    />
  );
}

export default ClassEntriesChart;
