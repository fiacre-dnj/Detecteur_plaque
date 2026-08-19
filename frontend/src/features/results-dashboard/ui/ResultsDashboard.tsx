/**
 * Le tableau de résultats : les chiffres du carrefour, en tête de colonne.
 *
 * Un principe traverse tous ces affichages : **chaque chiffre dit d'où il vient**.
 * « Entrées au carrefour » et non « Entrées », le nom du sens plutôt qu'une flèche.
 * Sans ces précisions, deux chiffres voisins qui ne mesurent pas la même chose se
 * confondent, et l'utilisateur tire une conclusion fausse sans jamais s'en douter.
 *
 * Deux unités cohabitent, et il ne faut jamais les diviser l'une par l'autre :
 *
 * - **véhicules** — `trackedVehicles`, `crossedUnique`. Un objet suivi, un véhicule ;
 * - **passages** — `crossings`, tous les `byLine`. Un aller-retour en vaut deux.
 *
 * C'est l'invariant 3, et il a déjà coûté un « taux de franchissement » à 200 %.
 *
 * **La Répartition par type de véhicule est ici**, et non plus dans une section
 * `Répartition` en bas de page. Deux raisons, aucune décorative :
 *
 * - elle répond à la **même** question que le chiffre de tête, découpée autrement.
 *   La somme de ses cartes égale exactement « Entrées au carrefour »
 *   (`entriesByClass` partage son prédicat avec `flowBalance`, verrouillé par un
 *   test) : les séparer par un écran de défilement obligeait à retenir un nombre
 *   pour vérifier l'autre ;
 * - le titre « Répartition » ne disait rien de plus que les libellés des cartes
 *   qu'il coiffait — « Voiture », « Bus » —, et une section à titre pour quatre
 *   chiffres coûtait une rangée de hauteur pour zéro information.
 *
 * Elles restent visuellement **secondes** (`size="sm"`) : neuf cartes de même poids
 * ne diraient plus laquelle on vient lire.
 *
 * **La cadence, la latence et le flux analysé n'y sont plus** : ce sont des chiffres
 * de machine, pas de carrefour, et ils occupaient trois des cinq cartes de tête.
 * Ils vivent maintenant dans la barre du studio (`TechnicalMetrics`), à l'échelle
 * qui leur revient.
 *
 * Le tableau de bord par ligne (`LineFlowDashboard`) reste sous la vidéo — voir
 * `StudioPage`.
 */

import type { AnalysisStats, CountingLine } from "@/shared/api/contracts";
import { VEHICLE_CLASSES, classLabel } from "@/shared/lib/classes";
import { MetricCard } from "@/shared/ui/MetricCard";

import { flowBalance } from "../model/directions";
import { entriesByClass } from "../model/entriesByClass";

interface ResultsDashboardProps {
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

export function ResultsDashboard({ stats, lines, includePerson }: ResultsDashboardProps) {
  const flow = flowBalance(stats, lines);
  const entries = entriesByClass(stats, lines);
  const classes: readonly string[] = includePerson
    ? [...VEHICLE_CLASSES, "person"]
    : VEHICLE_CLASSES;

  return (
    <section aria-labelledby="cards-title">
      <h3 id="cards-title" className="label-micro mb-3">
        Résultats
      </h3>
      <div className="grid grid-cols-2 gap-2">
        {/* « — » et non « 0 » quand aucun rôle n'est déclaré : deux zéros se
            liraient comme « personne n'entre », alors que la vérité est
            « personne ne l'a encore dit » — le seul cas restant est l'absence de
            toute ligne, le rôle étant obligatoire depuis ADR 0021. */}
        <MetricCard
          label="Entrées au carrefour"
          value={flow.declared ? flow.entries.toString() : "—"}
          // Somme des passages sur tous les sens marqués « entrée », toutes lignes
          // confondues : c'est le nombre de véhicules qui rentrent dans le
          // carrefour, pas seulement sur une ligne prise isolément.
          hint={
            flow.declared
              ? "Total des passages sur les sens marqués « entrée », toutes lignes"
              : "Ajoutez une ligne dans Géométrie pour obtenir ce chiffre"
          }
        />
        <MetricCard
          label="Objets suivis"
          value={stats.activeTracks.toString()}
          hint="Pistes vivantes à cet instant"
        />

        {/* Le détail du chiffre de tête, dans la même grille et sous son poids :
            un type de véhicule par carte, et **les entrées seulement** — jamais
            les détections ni les passages totaux, sinon la somme cesserait
            d'égaler « Entrées au carrefour ». */}
        {classes.map((klass) => (
          <MetricCard
            key={klass}
            size="sm"
            label={classLabel(klass)}
            value={(entries[klass] ?? 0).toString()}
            hint="Entrées"
          />
        ))}
      </div>
    </section>
  );
}
