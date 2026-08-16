/**
 * Le tableau de résultats : les cartes de synthèse, en tête de colonne.
 *
 * Un principe traverse tous ces affichages : **chaque chiffre dit d'où il vient**.
 * « Cadence (serveur) » et non « Cadence », « Entrées au carrefour » et non
 * « Entrées », le nom du sens plutôt qu'une flèche. Sans ces précisions, deux
 * chiffres voisins qui ne mesurent pas la même chose se confondent, et l'utilisateur
 * tire une conclusion fausse sans jamais s'en douter.
 *
 * Deux unités cohabitent, et il ne faut jamais les diviser l'une par l'autre :
 *
 * - **véhicules** — `trackedVehicles`, `crossedUnique`. Un objet suivi, un véhicule ;
 * - **passages** — `crossings`, tous les `byLine`. Un aller-retour en vaut deux.
 *
 * C'est l'invariant 3, et il a déjà coûté un « taux de franchissement » à 200 %.
 *
 * Ce composant n'affiche plus que les cartes de tête. La répartition par type
 * (`ClassEntriesGrid`) et le tableau de bord par ligne (`LineFlowDashboard`)
 * vivent désormais dans leurs propres sections, sous la vidéo — voir
 * `StudioPage`.
 */

import type { AnalysisStats, CountingLine } from "@/shared/api/contracts";
import { MetricCard } from "@/shared/ui/MetricCard";

import { flowBalance } from "../model/directions";
import { formatFrameLatency, formatSceneTime } from "../model/labels";

interface ResultsDashboardProps {
  stats: AnalysisStats;
  lines: readonly CountingLine[];
  /** Cadence de traitement du **serveur**, distincte de la lecture vidéo. */
  processingFps: number;
}

export function ResultsDashboard({ stats, lines, processingFps }: ResultsDashboardProps) {
  const flow = flowBalance(stats, lines);

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
        <MetricCard
          // **« serveur » explicite** : ce n'est pas la cadence de lecture de la
          // vidéo, et les deux chiffres se confondraient sans cette étiquette.
          label="Cadence (serveur)"
          value={processingFps > 0 ? processingFps.toFixed(1) : "—"}
          hint="Images analysées par seconde"
        />
        <MetricCard
          label="Latence moyenne"
          value={formatFrameLatency(processingFps)}
          // Dit ce que le chiffre mesure : le traitement d'une image côté
          // serveur, et non un aller-retour réseau — en différé, il n'y en a
          // pas par image.
          hint="Temps de traitement par image"
        />
        <MetricCard
          label="Flux analysé"
          value={formatSceneTime(stats.analysedSceneMs)}
          // Temps de **scène**, pas temps mural : c'est la durée de vidéo déjà
          // traitée, pas le temps que le serveur a mis pour la traiter.
          hint="Durée de vidéo déjà traitée par le serveur"
        />
      </div>
    </section>
  );
}
