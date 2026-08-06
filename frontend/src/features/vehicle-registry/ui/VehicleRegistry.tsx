/**
 * Le registre des véhicules.
 *
 * **Pourquoi ce tableau existe** : les cartes disent *combien*, le registre dit
 * *lesquels*. C'est ce qui rend un total **vérifiable** plutôt que croyable — on
 * peut pointer une ligne, retrouver le véhicule dans la vidéo, et confirmer. Sans
 * lui, « 47 véhicules » est un acte de foi.
 *
 * Trois comportements d'affichage, chacun pour une raison mesurée :
 * - **12 lignes puis « Afficher les N restants »** : le registre est sous les
 *   cartes, et déployer 400 lignes par défaut repousserait tout le reste hors écran ;
 * - **virtualisation au-delà de 200 lignes** : 10 000 lignes de tableau bloquent
 *   l'onglet plusieurs secondes à chaque rendu ;
 * - **note de bas de tableau quand aucune échelle px/m n'est fournie** : sinon la
 *   colonne « Vitesse » en px/s se lit comme une valeur inutilisable, alors qu'elle
 *   est simplement dans une autre unité.
 */

import { useCallback, useMemo, useRef, useState } from "react";

import { directionLabel, formatSceneTime, formatScore, formatSpeed } from "@/features/results-dashboard";
import type { AnalysisResult, VehicleRecord } from "@/shared/api/contracts";
import { classColor } from "@/shared/config/palettes";
import { Button } from "@/shared/ui/Button";

import {
  crossingsCsv,
  downloadText,
  exportFilename,
  resultJson,
  vehiclesCsv,
} from "../model/exportCsv";
import { INITIAL_ROWS, ROW_HEIGHT, shouldVirtualise, visibleWindow } from "../model/virtualise";

interface VehicleRegistryProps {
  result: AnalysisResult;
  /** Véhicules à afficher — filtrés par la tête de lecture en relecture. */
  vehicles: readonly VehicleRecord[];
  /** Noms des lignes, pour libeller les puces de franchissement. */
  lineNames: ReadonlyMap<string, string>;
  /** Vrai si une échelle px/m a été fournie : change l'unité de la colonne vitesse. */
  hasScale: boolean;
}

/** Hauteur du conteneur virtualisé. */
const VIEWPORT_HEIGHT = 420;

export function VehicleRegistry({
  result,
  vehicles,
  lineNames,
  hasScale,
}: VehicleRegistryProps) {
  const [expanded, setExpanded] = useState(false);
  const [scrollTop, setScrollTop] = useState(0);
  const scroller = useRef<HTMLDivElement>(null);

  const virtualised = expanded && shouldVirtualise(vehicles.length);
  const shown = expanded ? vehicles : vehicles.slice(0, INITIAL_ROWS);
  const remaining = vehicles.length - shown.length;

  const window = useMemo(
    () =>
      virtualised
        ? visibleWindow(vehicles.length, scrollTop, VIEWPORT_HEIGHT)
        : { start: 0, end: shown.length, totalHeight: 0, offsetTop: 0 },
    [virtualised, vehicles.length, scrollTop, shown.length],
  );

  const rows = virtualised ? vehicles.slice(window.start, window.end) : shown;

  const handleScroll = useCallback(() => {
    const element = scroller.current;
    if (element !== null) setScrollTop(element.scrollTop);
  }, []);

  if (vehicles.length === 0) {
    return (
      <section aria-labelledby="registry-title">
        <h3 id="registry-title" className="label-micro mb-3">
          Registre des véhicules
        </h3>
        <p className="rounded-card bg-surface p-4 text-caption text-ink-dim shadow-card">
          Aucun véhicule identifié pour l'instant. Le registre se remplit au fil de
          l'analyse.
        </p>
      </section>
    );
  }

  const table = (
    <table className="w-full border-collapse text-small">
      <thead>
        <tr className="text-start">
          <Th className="w-12">#</Th>
          <Th className="w-24">Type</Th>
          <Th className="w-32">Vu de / à</Th>
          <Th>Lignes franchies</Th>
          <Th className="w-24">Vitesse</Th>
          <Th className="w-16">Ré-id</Th>
          <Th className="w-20">Plaque</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((vehicle) => (
          <tr
            key={vehicle.globalId}
            style={{ height: ROW_HEIGHT }}
            className="border-t border-line/40"
          >
            <Td className="font-bold text-ink tabular">{vehicle.globalId}</Td>
            <Td>
              <span className="flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className="size-2 rounded-badge"
                  style={{ backgroundColor: classColor(vehicle.label) }}
                />
                {vehicle.label}
              </span>
            </Td>
            <Td className="tabular">
              {formatSceneTime(vehicle.firstSeenMs)} → {formatSceneTime(vehicle.lastSeenMs)}
            </Td>
            <Td>
              {vehicle.crossedLines.length === 0 ? (
                <span className="text-ink-dim">—</span>
              ) : (
                <span className="flex flex-wrap gap-1">
                  {vehicle.crossedLines.map((crossing, index) => (
                    <span
                      key={`${crossing.lineId}-${crossing.timestampMs}-${index}`}
                      // L'infobulle donne la ligne, l'instant **et** le sens :
                      // c'est ce qui permet de retrouver le passage dans la vidéo.
                      title={`${lineNames.get(crossing.lineId) ?? crossing.lineId} à ${formatSceneTime(crossing.timestampMs)}, sens ${directionLabel(crossing.direction)}`}
                      className="rounded-badge bg-elevated px-1.5 py-0.5 text-micro"
                    >
                      {crossing.direction > 0 ? "↑" : "↓"}{" "}
                      {lineNames.get(crossing.lineId) ?? crossing.lineId}
                    </span>
                  ))}
                </span>
              )}
            </Td>
            <Td className="tabular">
              {formatSpeed(vehicle.avgSpeedKmh, vehicle.avgSpeedPxS)}
            </Td>
            <Td className="tabular">
              {vehicle.reidCount > 0 ? `↻ ${vehicle.reidCount}` : "—"}
            </Td>
            <Td className="tabular">{formatScore(vehicle.bestPlateScore)}</Td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <section aria-labelledby="registry-title">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 id="registry-title" className="label-micro">
          Registre des véhicules
        </h3>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              downloadText(
                exportFilename(result.jobId, "vehicules", "csv"),
                vehiclesCsv(result),
                "text/csv",
              )
            }
          >
            CSV véhicules
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              downloadText(
                exportFilename(result.jobId, "franchissements", "csv"),
                crossingsCsv(result),
                "text/csv",
              )
            }
          >
            CSV franchissements
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              downloadText(
                exportFilename(result.jobId, "resultat", "json"),
                resultJson(result),
                "application/json",
              )
            }
          >
            JSON
          </Button>
        </div>
      </div>

      <div className="overflow-hidden rounded-card bg-surface shadow-card">
        {virtualised ? (
          <div
            ref={scroller}
            onScroll={handleScroll}
            style={{ height: VIEWPORT_HEIGHT }}
            className="overflow-y-auto"
          >
            {/* Le conteneur porte la hauteur totale pour que la barre de
                défilement soit juste ; le contenu est décalé de `offsetTop`. */}
            <div style={{ height: window.totalHeight, position: "relative" }}>
              <div style={{ transform: `translateY(${window.offsetTop}px)` }}>{table}</div>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">{table}</div>
        )}
      </div>

      {remaining > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mt-2 text-small text-ink-muted underline transition-colors hover:text-ink"
        >
          Afficher les {remaining} véhicules restants
        </button>
      )}

      {!hasScale && (
        // Sans cette note, une colonne en px/s se lit comme inutilisable — alors
        // qu'elle est simplement dans une autre unité, faute d'échelle.
        <p className="mt-2 text-small text-ink-dim">
          Les vitesses sont en pixels par seconde : renseignez l'échelle (px/m) dans
          les réglages pour les obtenir en km/h.
        </p>
      )}
    </section>
  );
}

function Th({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <th
      scope="col"
      className={`px-3 py-2 text-start text-micro font-semibold uppercase tracking-wider text-ink-dim ${className}`}
    >
      {children}
    </th>
  );
}

function Td({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <td className={`px-3 py-1.5 text-ink-muted ${className}`}>{children}</td>;
}
