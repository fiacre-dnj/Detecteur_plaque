/**
 * La page de benchmark : lancement, progression, tableau triable.
 *
 * Deux affichages non négociables, parce qu'un chiffre de performance sans son
 * contexte est trompeur :
 *
 * - **le contexte matériel est toujours visible** — device, version d'Ultralytics,
 *   hash de l'image de référence. 40 ms sur GPU et 40 ms sur CPU ne racontent pas la
 *   même histoire, et deux runs ne sont comparables que s'ils portent le même hash ;
 * - **`released` est expliqué en infobulle**. Sans l'explication, un utilisateur qui
 *   voit « libéré : non » croit à un échec, alors que c'est le comportement voulu :
 *   le registre refuse de décharger un modèle qui sert une analyse en cours.
 */

import { ArrowDown, ArrowUp, X } from "lucide-react";
import { useMemo, useState } from "react";

import { isTerminal } from "@/shared/api/contracts";
import { Button } from "@/shared/ui/Button";

import {
  DEFAULT_SORT,
  formatMs,
  maxOf,
  nextSort,
  relativeWidth,
  sortEntries,
  type SortColumn,
  type SortState,
} from "../model/sorting";
import { useBenchmark } from "../model/useBenchmark";

export function BenchmarkPage() {
  const { run, loading, error, start, cancel } = useBenchmark();
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);
  const [frames, setFrames] = useState(5);

  const rows = useMemo(() => sortEntries(run?.entries ?? [], sort), [run, sort]);
  const maxMedian = useMemo(() => maxOf(run?.entries ?? [], "medianMs"), [run]);
  const running = run !== null && !isTerminal(run.status);

  if (loading) {
    // Squelette de la forme finale, pas un spinner centré : l'utilisateur voit
    // arriver ce qu'il attend au lieu d'une roue qui tourne.
    return (
      <div className="space-y-3">
        <div className="h-10 w-64 rounded-card bg-surface" />
        <div className="h-48 rounded-section bg-surface" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section className="rounded-section bg-surface p-4 shadow-card">
        <h2 className="label-micro">Mesurer les modèles sur ce serveur</h2>
        <p className="mt-2 max-w-2xl text-small text-ink-muted">
          Chaque modèle est mesuré sur une <strong>image de référence unique</strong>,
          après un run de chauffe écarté. Chaque modèle est{" "}
          <span title="Vingt modèles résidents épuiseraient la mémoire du serveur. Un modèle occupé par une analyse en cours n'est pas déchargé, et la ligne le dit.">
            <strong>libéré après sa mesure</strong>
          </span>
          . Le premier appel d'un modèle inclut son téléchargement.
        </p>

        <div className="mt-4 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-small text-ink-muted">
            Mesures par modèle
            <input
              type="number"
              min={1}
              max={20}
              value={frames}
              disabled={running}
              onChange={(event) => setFrames(Number(event.target.value))}
              className="w-20 rounded-input bg-elevated px-2 py-1 text-small text-ink tabular disabled:opacity-50"
            />
          </label>

          <Button variant="primary" disabled={running} onClick={() => void start({ frames })}>
            Lancer le benchmark
          </Button>

          {running && (
            <Button variant="ghost" icon={<X className="size-4" />} onClick={cancel}>
              Annuler
            </Button>
          )}
        </div>

        {error !== null && (
          <p role="alert" className="mt-3 text-small text-negative">
            {error}
          </p>
        )}
      </section>

      {run === null ? (
        <section className="rounded-section bg-surface p-8 text-center shadow-card">
          <h3 className="text-heading font-bold text-ink">Aucune mesure enregistrée</h3>
          <p className="mx-auto mt-2 max-w-md text-caption text-ink-muted">
            Lancez un benchmark pour comparer les modèles sur le matériel de ce
            serveur. Un chiffre lu hors de son contexte matériel ne veut rien dire :
            le device et la version d'Ultralytics accompagnent toujours le résultat.
          </p>
        </section>
      ) : (
        <>
          {running && (
            <div className="rounded-card bg-surface-2 p-3">
              <div className="flex items-baseline justify-between">
                <p className="text-caption font-bold text-ink">
                  Mesure en cours — {run.completed} / {run.total} modèles
                </p>
                <output className="text-small text-ink-muted tabular">
                  {Math.round(run.progress * 100)} %
                </output>
              </div>
              <div
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(run.progress * 100)}
                aria-label="Progression du benchmark"
                className="mt-2 h-1 overflow-hidden rounded-pill bg-line"
              >
                <div
                  className="h-full rounded-pill bg-accent transition-[width]"
                  style={{ width: `${run.progress * 100}%` }}
                />
              </div>
            </div>
          )}

          {/* Le contexte matériel, toujours visible : sans lui les chiffres sont
              trompeurs, et deux runs ne sont comparables que s'ils partagent le
              hash de l'image de référence. */}
          <dl className="flex flex-wrap gap-x-6 gap-y-1 rounded-card bg-surface p-3 text-small shadow-card">
            <Context label="Device" value={run.device} />
            <Context label="fp16" value={run.half ? "oui" : "non"} />
            <Context label="Ultralytics" value={run.ultralyticsVersion} />
            <Context
              label="Image"
              value={`${run.imageSource === "sample" ? "échantillon" : "frame de job"} ${run.imageWidth}×${run.imageHeight}`}
            />
            <Context label="Mesures" value={`${run.frames} par modèle`} />
            <Context
              label="Hash"
              value={run.imageHash.slice(0, 12)}
              title={`sha256 complet : ${run.imageHash}. Deux runs ne sont comparables que s'ils portent le même hash.`}
            />
            <Context
              label="Seuils"
              value={`conf ${run.confidenceThreshold} · IoU ${run.iouThreshold}`}
              title="Les seuils de la requête, et non ceux du catalogue : la colonne « détections » correspond donc à ce que vous verriez à l'écran."
            />
          </dl>

          {run.error !== null && (
            <p role="alert" className="text-small text-negative">
              {run.error}
            </p>
          )}

          <div className="overflow-x-auto rounded-card bg-surface shadow-card">
            <table className="w-full border-collapse text-small">
              <thead>
                <tr>
                  <SortableTh column="label" sort={sort} onSort={setSort}>
                    Modèle
                  </SortableTh>
                  <SortableTh column="tier" sort={sort} onSort={setSort}>
                    Palier
                  </SortableTh>
                  <SortableTh column="loadMs" sort={sort} onSort={setSort} title="0 signifie que le modèle était déjà résident : il n'y avait rien à charger.">
                    Chargement
                  </SortableTh>
                  <SortableTh column="medianMs" sort={sort} onSort={setSort} title="Médiane des mesures retenues, chauffe exclue.">
                    Inférence
                  </SortableTh>
                  <SortableTh column="p95Ms" sort={sort} onSort={setSort} title="Centile 95 : ce que la médiane a écarté reste visible ici.">
                    p95
                  </SortableTh>
                  <SortableTh column="detections" sort={sort} onSort={setSort}>
                    Détections
                  </SortableTh>
                  <th
                    scope="col"
                    title="Le modèle a-t-il été libéré après sa mesure ? « non » signifie qu'il servait une analyse en cours — le registre refuse alors de le décharger, et c'est voulu."
                    className="px-3 py-2 text-start text-micro font-semibold uppercase tracking-wider text-ink-dim"
                  >
                    Libéré
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((entry) => (
                  <tr
                    key={entry.modelId}
                    className={[
                      "border-t border-line/40",
                      entry.modelId === run.fastestModelId ? "bg-elevated/40" : "",
                    ].join(" ")}
                  >
                    <td className="px-3 py-1.5 font-bold text-ink">
                      {entry.label}
                      {entry.modelId === run.fastestModelId && (
                        <span className="ms-2 text-micro font-normal text-ink-dim">
                          le plus rapide
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-1.5 text-ink-muted">{entry.tier}</td>
                    <td className="px-3 py-1.5 text-ink-muted tabular">
                      {formatMs(entry.loadMs)}
                    </td>
                    <td className="px-3 py-1.5 text-ink-muted tabular">
                      {entry.error !== null ? (
                        <span className="text-negative">échec</span>
                      ) : (
                        <span className="flex items-center gap-2">
                          <span className="w-16 shrink-0">{formatMs(entry.medianMs)}</span>
                          {/* Barre relative au maximum de la colonne : c'est ce qui
                              rend la comparaison lisible d'un coup d'œil quel que
                              soit le matériel. */}
                          <span
                            aria-hidden="true"
                            className="h-1 rounded-pill bg-accent"
                            style={{ width: `${relativeWidth(entry.medianMs, maxMedian)}%` }}
                          />
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-1.5 text-ink-muted tabular">{formatMs(entry.p95Ms)}</td>
                    <td className="px-3 py-1.5 text-ink-muted tabular">{entry.detections}</td>
                    <td className="px-3 py-1.5 text-ink-muted">
                      {entry.error !== null ? "—" : entry.released ? "oui" : "non"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {rows.some((entry) => entry.error !== null) && (
            <ul className="space-y-1">
              {rows
                .filter((entry) => entry.error !== null)
                .map((entry) => (
                  <li key={entry.modelId} className="text-small text-negative">
                    <strong>{entry.label}</strong> : {entry.error}
                  </li>
                ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function Context({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div title={title} className="flex gap-2">
      <dt className="text-ink-dim">{label}</dt>
      <dd className="font-bold text-ink-muted tabular">{value}</dd>
    </div>
  );
}

interface SortableThProps {
  column: SortColumn;
  sort: SortState;
  onSort: (sort: SortState) => void;
  title?: string;
  children: React.ReactNode;
}

function SortableTh({ column, sort, onSort, title, children }: SortableThProps) {
  const active = sort.column === column;

  return (
    <th
      scope="col"
      // `aria-sort` : c'est ce qui permet à un lecteur d'écran d'annoncer l'état du
      // tri. Sans lui, la colonne triée est indiscernable des autres.
      aria-sort={active ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}
      className="px-3 py-2 text-start"
    >
      <button
        type="button"
        onClick={() => onSort(nextSort(sort, column))}
        title={title}
        className="flex items-center gap-1 text-micro font-semibold uppercase tracking-wider text-ink-dim transition-colors hover:text-ink"
      >
        {children}
        {active &&
          (sort.direction === "asc" ? (
            <ArrowUp aria-hidden="true" className="size-3" />
          ) : (
            <ArrowDown aria-hidden="true" className="size-3" />
          ))}
      </button>
    </th>
  );
}

export default BenchmarkPage;
