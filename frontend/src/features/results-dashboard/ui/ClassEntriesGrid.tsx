/**
 * La Répartition — une carte par type de véhicule, **rien de plus**.
 *
 * Remplace l'ancien `ClassBreakdown`, qui affichait détections, passages, une
 * barre de part et une sous-liste par sens pour chaque classe — trop dense pour
 * une lecture d'ensemble. Ici : un chiffre par carte, le même que celui déjà
 * pratiqué pour les KPI de tête (`MetricCard`), et un seul chiffre : les
 * **entrées** de cette classe, pas les détections ni les passages totaux.
 *
 * Ce choix n'est pas arbitraire : la somme des cartes, toutes classes
 * confondues, égale exactement le KPI « Entrées au carrefour » des Résultats
 * (`entriesByClass` le garantit par construction, verrouillé par un test). Les
 * deux nombres ne peuvent donc jamais se contredire.
 */

import type { AnalysisStats, CountingLine } from "@/shared/api/contracts";
import { VEHICLE_CLASSES, classLabel } from "@/shared/lib/classes";
import { MetricCard } from "@/shared/ui/MetricCard";

import { entriesByClass } from "../model/entriesByClass";

interface ClassEntriesGridProps {
  stats: AnalysisStats;
  lines: readonly CountingLine[];
  /**
   * Affiche une carte « Personnes » en plus des quatre véhicules — seulement si
   * la classe personne a été cochée dans les réglages de l'analyse. Calculé par
   * l'appelant (`StudioPage`) : cette feature ne connaît ni les réglages ni le
   * catalogue de classes, seulement `AnalysisStats`/`CountingLine[]`.
   */
  includePerson: boolean;
}

export function ClassEntriesGrid({ stats, lines, includePerson }: ClassEntriesGridProps) {
  const entries = entriesByClass(stats, lines);
  const classes: readonly string[] = includePerson ? [...VEHICLE_CLASSES, "person"] : VEHICLE_CLASSES;

  return (
    <section aria-labelledby="repartition-title">
      <h2 id="repartition-title" className="label-micro mb-3">
        Répartition
      </h2>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {classes.map((klass) => (
          <MetricCard
            key={klass}
            label={classLabel(klass)}
            value={(entries[klass] ?? 0).toString()}
            hint="Entrées au carrefour"
          />
        ))}
      </div>
    </section>
  );
}
