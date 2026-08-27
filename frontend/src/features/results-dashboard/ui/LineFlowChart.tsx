/**
 * Le flux total, **ventilé par ligne** — un camembert, une tranche par ligne.
 *
 * Remplaçait un histogramme empilé dans le temps (`FlowHistogram`, puis une
 * pile par tranche de temps) : les deux répondaient à « quand », alors que la
 * question la plus posée devant ce tableau de bord est « quelle part » — et
 * c'est justement ce que dit `busiestLine`/`busiestVsQuietestShareGap` en
 * texte. Un camembert la rend visible d'un coup d'œil, sans lire une légende
 * de tranches de temps.
 *
 * Compacte au possible : ni axe, ni tranches, ni geste de navigation — un
 * camembert ne porte plus de position temporelle sur laquelle se caler. Ce
 * n'est pas une perte lue en silence : la relecture standard (la barre de
 * lecture) reste le seul outil pour se déplacer dans le temps depuis le
 * 2026-08-17.
 */

import type { AnalysisStats, CountingLine } from "@/shared/api/contracts";

import { directionRows } from "../model/directions";
import { PieChart } from "./PieChart";

interface LineFlowChartProps {
  stats: AnalysisStats;
  lines: readonly CountingLine[];
}

export function LineFlowChart({ stats, lines }: LineFlowChartProps) {
  const totals = new Map<string, number>();
  for (const row of directionRows(stats, lines)) {
    totals.set(row.lineId, (totals.get(row.lineId) ?? 0) + row.tally.total);
  }

  const slices = lines.map((line) => ({
    id: line.id,
    label: line.name,
    value: totals.get(line.id) ?? 0,
    color: line.color,
  }));

  return (
    <PieChart
      title="Flux de passage par ligne"
      slices={slices}
      emptyMessage="Aucun franchissement sur la période analysée."
      // Rien ne borne le nombre de lignes qu'on peut tracer : au-delà de cinq, le
      // camembert replie le reste dans une part grise et la légende passe en deux
      // colonnes (voir `groupSlices`). Les passages, eux, ne sont pas regroupés —
      // ils restent lisibles rangée par rangée dans « Statistique » juste au-dessus.
      unit={{ one: "ligne", many: "lignes" }}
      metric="passage"
    />
  );
}

export default LineFlowChart;
