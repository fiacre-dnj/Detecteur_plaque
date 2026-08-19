/**
 * Le tableau de résultats : les chiffres du comptage, en tête de colonne.
 *
 * Un principe traverse tous ces affichages : **chaque chiffre dit d'où il vient**.
 * « Passages en entrée » et non « Entrées », le nom de la ligne plutôt qu'une
 * flèche. Sans ces précisions, deux chiffres voisins qui ne mesurent pas la même
 * chose se confondent, et l'utilisateur tire une conclusion fausse sans jamais
 * s'en douter.
 *
 * Deux unités cohabitent, et il ne faut jamais les diviser l'une par l'autre :
 *
 * - **véhicules** — `trackedVehicles`, `crossedUnique`. Un objet suivi, un véhicule ;
 * - **passages** — `crossings`, tous les `byLine`. Un aller-retour en vaut deux.
 *
 * C'est l'invariant 3, et il a déjà coûté un « taux de franchissement » à 200 %.
 *
 * **Trois étages, un seul chiffre de tête.**
 *
 * 1. **« Passages en entrée »**, sur toute la largeur et en `size="lg"`. Il
 *    s'appelait « Entrées au carrefour » : le mot nommait un lieu que
 *    l'utilisateur n'a pas forcément — sur une route à sens unique avec une seule
 *    ligne, il ne veut rien dire alors que le chiffre, lui, reste juste. Le nom
 *    retenu garde l'unité explicite (des **passages**, jamais des véhicules) ;
 * 2. **la Répartition par type de véhicule**, `size="sm"`, deux par rangée. Elle
 *    n'a plus de section en bas de page pour deux raisons, aucune décorative :
 *    elle répond à la **même** question que le chiffre de tête, découpée autrement
 *    — la somme de ses cartes lui est exactement égale (`entriesByClass` partage
 *    son prédicat avec `flowBalance`, verrouillé par un test) — et le titre
 *    « Répartition » ne disait rien de plus que « Voiture », « Bus » juste
 *    dessous ;
 * 3. **une carte par ligne tracée**, sur toute la largeur, avec le nom que
 *    l'utilisateur a saisi et son bilan entrées / sorties. Le détail par ligne
 *    n'existait qu'en bas de page (`LineFlowDashboard`), sous la vidéo : la
 *    question « combien sur *cette* ligne » demandait de défiler alors qu'elle se
 *    pose en même temps que le total.
 *
 * **« Objets suivis » n'est plus ici** : c'est un instantané de machine — les
 * pistes vivantes à cette image, un chiffre qui monte et descend — et il occupait
 * la moitié du meilleur emplacement de l'écran, à égalité visuelle avec le bilan
 * du comptage. Il a rejoint la cadence, la latence et le flux analysé dans la
 * barre du studio (`TechnicalMetrics`), à l'échelle qui leur revient.
 *
 * Le tableau de bord par ligne (`LineFlowDashboard`), plus détaillé et adossé aux
 * comparatifs, reste sous la vidéo — voir `StudioPage`.
 */

import type { AnalysisStats, CountingLine } from "@/shared/api/contracts";
import { VEHICLE_CLASSES, classLabel } from "@/shared/lib/classes";
import { MetricCard } from "@/shared/ui/MetricCard";

import { flowBalance } from "../model/directions";
import { entriesByClass } from "../model/entriesByClass";
import { crossroadFlowSentence, plural } from "../model/labels";
import { lineFlows, type LineFlow } from "../model/lineFlows";
import { EntryExitBar } from "./EntryExitBar";

interface ResultsDashboardProps {
  stats: AnalysisStats;
  lines: readonly CountingLine[];
  /**
   * La classe « personne » est-elle cochée dans les réglages de l'analyse ?
   * Calculé par l'appelant (`StudioPage`) : cette feature ne connaît ni les
   * réglages ni le catalogue de classes, seulement `AnalysisStats`/`CountingLine[]`.
   *
   * La carte s'affiche **aussi** quand le résultat relu porte des entrées
   * « person » sans que la case le soit — un résultat archivé rouvert garde alors
   * son chiffre au lieu de le faire disparaître (voir plus bas).
   */
  includePerson: boolean;
}

export function ResultsDashboard({ stats, lines, includePerson }: ResultsDashboardProps) {
  const flow = flowBalance(stats, lines);
  const entries = entriesByClass(stats, lines);
  // La case cochée **ou** un chiffre déjà compté : décocher « Personne » après
  // coup ne doit pas effacer une colonne du résultat qu'on est en train de lire.
  const showPerson = includePerson || (entries.person ?? 0) > 0;
  const classes: readonly string[] = showPerson ? [...VEHICLE_CLASSES, "person"] : VEHICLE_CLASSES;

  return (
    <section aria-labelledby="cards-title">
      <h3 id="cards-title" className="label-micro mb-3">
        Résultats
      </h3>
      <div className="grid grid-cols-2 gap-2">
        {/* La tête de lecture, sur les deux colonnes : c'est le chiffre qu'on
            vient chercher, et il est seul de son poids.

            « — » et non « 0 » quand aucun rôle n'est déclaré : deux zéros se
            liraient comme « personne n'entre », alors que la vérité est
            « personne ne l'a encore dit » — le seul cas restant est l'absence de
            toute ligne, le rôle étant obligatoire depuis ADR 0021. */}
        <div className="col-span-2">
          <MetricCard
            size="lg"
            label="Passages en entrée"
            value={flow.declared ? flow.entries.toString() : "—"}
            // Somme des passages sur tous les sens marqués « entrée », toutes
            // lignes confondues : le nombre de passages qui rentrent dans la zone
            // comptée, pas seulement sur une ligne prise isolément.
            hint={
              flow.declared
                ? "Total des passages sur les sens marqués « entrée », toutes lignes"
                : "Ajoutez une ligne dans Géométrie pour obtenir ce chiffre"
            }
          />
        </div>

        {/* Le détail du chiffre de tête, dans la même grille et sous son poids :
            un type de véhicule par carte, et **les entrées seulement** — jamais
            les détections ni les passages totaux, sinon la somme cesserait
            d'égaler « Passages en entrée ». */}
        {classes.map((klass) => (
          <MetricCard
            key={klass}
            size="sm"
            label={classLabel(klass)}
            value={(entries[klass] ?? 0).toString()}
            hint="Entrées"
          />
        ))}

        {/* Le même total, découpé par ligne cette fois — et la somme des entrées
            de ces cartes égale elle aussi le chiffre de tête. Le nom est celui
            que l'utilisateur a saisi dans le tiroir Géométrie : le renommer ou
            basculer un sens entrée ↔ sortie se voit ici **sans réanalyser**, tout
            étant dérivé de `stats.byLine` et du tracé courant. */}
        {lineFlows(stats, lines).map((line) => (
          <LineMetricCard key={line.lineId} flow={line} />
        ))}
      </div>
    </section>
  );
}

/**
 * Le bilan d'une ligne : sa pastille, son nom, sa fréquentation, puis entrées,
 * sorties et solde signé.
 *
 * **Pas de flèche de sens ici.** Les trois écrans qui en portent une la pivotent
 * à l'angle réel du tracé (`directionHeadingDeg`), précisément pour qu'on relie
 * une rangée au trait qu'on voit sur la vidéo ; un pictogramme conventionnel de
 * plus contredirait cette règle. Les mots « Entrées » et « Sorties » suffisent,
 * comme dans la rangée de « Statistique ».
 *
 * Un chiffre absent (`null`) n'est **pas** affiché à zéro : aucun sens de cette
 * ligne ne porte le rôle, ce qui n'est pas la même chose que « personne n'est
 * passé ». La phrase-bilan complète part en `aria-label`, comme en bas de page —
 * c'est elle qui porte la précision « entrer dans la zone, pas dans la rue ».
 */
function LineMetricCard({ flow }: { flow: LineFlow }) {
  const { entries, exits } = flow;
  const net = entries !== null && exits !== null ? entries - exits : null;

  return (
    <div
      aria-label={crossroadFlowSentence(flow.lineName, entries, exits)}
      className="col-span-2 rounded-card bg-surface p-3 shadow-card"
    >
      <div className="flex items-center gap-2">
        <span
          aria-hidden="true"
          className="size-3 shrink-0 rounded-badge"
          style={{ backgroundColor: flow.color }}
        />
        {/* `truncate` et `min-w-0` : la colonne fait 24 rem, et un nom de ligne
            long doit se couper au lieu de pousser le compteur hors de la carte. */}
        <span className="min-w-0 flex-1 truncate label-micro">{flow.lineName}</span>
        <span className="shrink-0 text-micro text-ink-dim tabular">
          {plural(flow.total, "passage", "passages")}
        </span>
      </div>

      <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        {entries !== null && (
          <span className="text-micro text-ink-dim">
            <span className="me-1 text-heading font-bold leading-tight text-ink tabular">
              {entries}
            </span>
            entrées
          </span>
        )}
        {exits !== null && (
          <span className="text-micro text-ink-dim">
            <span className="me-1 text-heading font-bold leading-tight text-ink tabular">
              {exits}
            </span>
            sorties
          </span>
        )}
        {net !== null && (
          <span className="ms-auto text-micro font-bold tabular text-ink">
            {net > 0 ? `+${net}` : net}
          </span>
        )}
      </div>

      {entries !== null && exits !== null && (entries > 0 || exits > 0) && (
        <EntryExitBar entries={entries} exits={exits} color={flow.color} />
      )}
    </div>
  );
}
