/**
 * Statistique — le tableau de bord du carrefour, ligne par ligne.
 *
 * Remplace l'ancien onglet « Par ligne & sens » (et sa matrice « Mouvements »,
 * retirée sans reconstruction) par une lecture **compacte, jamais en
 * accordéon** : tout est visible sans dépli. Trois étages —
 *
 * 1. un chiffre de tête, le total de véhicules ayant emprunté le carrefour ;
 * 2. une rangée compacte par ligne : nom, entrées/sorties/solde/part et une
 *    barre bidirectionnelle **unique** (un segment entrée, un segment sortie,
 *    côte à côte plutôt qu'empilés sur deux lignes) ;
 * 3. des comparatifs entre lignes (`highlights.ts`), regroupés dans **une
 *    seule carte** plutôt qu'une par comparatif — six `MetricCard` à 1,75 rem
 *    de chiffre et `p-4` de marge pour une phrase chacune laissaient la moitié
 *    de la section en vide.
 *
 * L'occupation de zone (présente dans l'ancien onglet) **n'a pas d'équivalent
 * ici** — décision assumée : ce tableau de bord ne parle que de lignes.
 */

import type { AnalysisStats, CountingLine, VehicleRecord } from "@/shared/api/contracts";

import { enteringVehicleCount } from "../model/crossedVehicles";
import { directionRows, isEntryRow } from "../model/directions";
import {
  busiestLine,
  busiestVsQuietestShareGap,
  mostEnteredLine,
  mostExitedLine,
  strongestInflowLine,
  strongestOutflowLine,
  type LineHighlight,
} from "../model/highlights";
import { crossroadFlowSentence } from "../model/labels";

interface LineFlowDashboardProps {
  stats: AnalysisStats;
  lines: readonly CountingLine[];
  /**
   * Les véhicules visibles à la tête de lecture — **déjà filtrés** sur « a
   * franchi au moins une ligne » par l'appelant, comme le registre.
   *
   * Le chiffre de tête en dérive plutôt que de lire `stats.trackedVehicles` :
   * ce dernier compte tout objet suivi confirmé, stationnement compris, et
   * affichait 106 sous 28 entrées sur la même analyse.
   */
  vehicles: readonly VehicleRecord[];
}

export function LineFlowDashboard({ stats, lines, vehicles }: LineFlowDashboardProps) {
  if (lines.length === 0) return null;

  const entered = enteringVehicleCount(vehicles, lines);

  const busiest = busiestLine(stats, lines);
  const mostEntered = mostEnteredLine(stats, lines);
  const mostExited = mostExitedLine(stats, lines);
  const inflow = strongestInflowLine(stats, lines);
  const outflow = strongestOutflowLine(stats, lines);
  const gap = busiestVsQuietestShareGap(stats, lines);

  const highlightItems: { label: string; highlight: LineHighlight | null; hint: (h: LineHighlight) => string }[] = [
    {
      label: "Ligne la plus fréquentée",
      highlight: busiest,
      hint: (h) => `${h.value} passages, tous sens confondus`,
    },
    {
      label: "Plus d'entrées",
      highlight: mostEntered !== null && mostEntered.value > 0 ? mostEntered : null,
      hint: (h) => `${h.value} entrées — la plus empruntée pour entrer`,
    },
    {
      label: "Plus de sorties",
      highlight: mostExited !== null && mostExited.value > 0 ? mostExited : null,
      hint: (h) => `${h.value} sorties — la plus empruntée pour sortir`,
    },
    {
      label: "Plus fort afflux",
      highlight: inflow !== null && inflow.value > 0 ? inflow : null,
      hint: (h) => `Solde +${h.value} — le carrefour s'y remplit le plus`,
    },
    {
      label: "Plus fort reflux",
      highlight: outflow !== null && outflow.value > 0 ? outflow : null,
      hint: (h) => `Solde -${h.value} — le carrefour s'y vide le plus`,
    },
  ];
  const shownHighlights = highlightItems.filter((item) => item.highlight !== null);

  return (
    <section aria-labelledby="statistique-title" className="space-y-3">
      <h2 id="statistique-title" className="label-micro">
        Statistique
      </h2>

      {/* **Des véhicules distincts entrés, pas des passages.** Un véhicule qui
          entre deux fois compte 1 ici et 2 dans « Entrées au carrefour » : deux
          questions, deux unités, et on ne les divise jamais l'une par l'autre
          (invariant 3). */}
      <div className="flex flex-wrap items-baseline justify-between gap-2 rounded-card bg-surface p-3 shadow-card">
        <span className="min-w-0">
          <span className="label-micro block">Véhicules ayant traversé le carrefour</span>
          <span className="text-micro text-ink-dim">
            Entrés par une ligne — le stationnement et les sorties seules sont exclus
          </span>
        </span>
        <span className="text-[1.75rem] font-bold leading-tight text-ink tabular">{entered}</span>
      </div>

      <ul className="overflow-hidden rounded-card bg-surface shadow-card">
        {lines.map((line, index) => (
          <LineFlowRow key={line.id} stats={stats} line={line} bordered={index > 0} />
        ))}
      </ul>

      {shownHighlights.length > 0 && (
        <div className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-card bg-surface p-3 shadow-card sm:grid-cols-3">
          {shownHighlights.map(({ label, highlight, hint }) => (
            <div key={label} className="min-w-0">
              <p className="label-micro">{label}</p>
              <p className="mt-0.5 truncate text-caption font-bold text-ink">{highlight?.lineName}</p>
              <p className="text-micro text-ink-dim">{highlight !== null ? hint(highlight) : null}</p>
            </div>
          ))}
          {gap !== null && (
            <div className="min-w-0">
              <p className="label-micro">Écart de fréquentation</p>
              <p className="mt-0.5 text-caption font-bold text-ink tabular">{Math.round(gap * 100)} %</p>
              <p className="text-micro text-ink-dim">Entre la ligne la plus et la moins empruntée</p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/**
 * Une ligne, en une seule rangée compacte : nom, solde, part, puis une barre
 * bidirectionnelle sur toute la largeur. La phrase-bilan complète
 * (`crossroadFlowSentence`) reste disponible pour les lecteurs d'écran via
 * `aria-label`, sans occuper de place à l'écran — c'est elle qui porte la
 * précision « entrer dans le carrefour, pas dans la rue ».
 */
function LineFlowRow({
  stats,
  line,
  bordered,
}: {
  stats: AnalysisStats;
  line: CountingLine;
  bordered: boolean;
}) {
  const rows = directionRows(stats, [line]);
  const entryRow = rows.find((row) => isEntryRow(row));
  const exitRow = rows.find((row) => row.role === "exit");
  const entries = entryRow?.tally.total ?? null;
  const exits = exitRow?.tally.total ?? null;
  const net = entries !== null && exits !== null ? entries - exits : null;
  const lineTotal = rows.reduce((sum, row) => sum + row.tally.total, 0);
  const share = stats.crossings === 0 ? null : lineTotal / stats.crossings;

  return (
    <li
      aria-label={crossroadFlowSentence(line.name, entries, exits)}
      className={`p-3 ${bordered ? "border-t border-line/40" : ""}`}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span
          aria-hidden="true"
          className="size-3 shrink-0 rounded-badge"
          style={{ backgroundColor: line.color }}
        />
        <span className="min-w-0 flex-1 truncate text-caption font-semibold text-ink">{line.name}</span>

        {entries !== null && (
          <span className="text-micro text-ink-dim tabular">
            <span className="font-bold text-ink">{entries}</span> entrées
          </span>
        )}
        {exits !== null && (
          <span className="text-micro text-ink-dim tabular">
            <span className="font-bold text-ink">{exits}</span> sorties
          </span>
        )}
        {net !== null && (
          <span className="text-micro font-bold tabular text-ink">{net > 0 ? `+${net}` : net}</span>
        )}
        {share !== null && (
          <span className="text-micro text-ink-dim tabular">{Math.round(share * 100)} % du trafic</span>
        )}
      </div>
      {entries !== null && exits !== null && (entries > 0 || exits > 0) && (
        <EntryExitBar entries={entries} exits={exits} />
      )}
    </li>
  );
}

/**
 * Une seule barre, deux segments côte à côte — remplace les deux barres
 * empilées d'avant : la même comparaison entrées/sorties en une ligne plutôt
 * que deux, sans perdre l'information puisque les chiffres sont déjà dans
 * l'en-tête de la rangée.
 */
function EntryExitBar({ entries, exits }: { entries: number; exits: number }) {
  const total = entries + exits;
  const entryShare = total === 0 ? 0 : (entries / total) * 100;
  return (
    <div
      aria-hidden="true"
      className="mt-2 flex h-1.5 overflow-hidden rounded-pill bg-elevated"
    >
      <span className="block h-full bg-ink" style={{ width: `${entryShare}%` }} />
      <span className="block h-full bg-ink-dim" style={{ width: `${100 - entryShare}%` }} />
    </div>
  );
}
