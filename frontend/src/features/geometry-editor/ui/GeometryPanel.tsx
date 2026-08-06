/**
 * Le panneau « Géométrie » : la liste des lignes et des zones.
 *
 * Il double le canvas plutôt que de le remplacer, parce que deux gestes y sont
 * plus sûrs qu'à la souris : **renommer** (impossible sur un canvas) et
 * **supprimer** (un clic sur une croix ne risque pas de déplacer la forme, alors
 * qu'une touche Suppr après un glisser accidentel oui).
 *
 * Le sélecteur « portée » de chaque ligne est ici et pas sur le canvas : c'est une
 * relation entre deux objets, pas une propriété spatiale.
 */

import { Bookmark, Plus, Square, Trash2 } from "lucide-react";

import type { CountingLine, Zone } from "@/shared/api/contracts";
import type { Selection } from "@/entities/geometry";

interface GeometryPanelProps {
  lines: readonly CountingLine[];
  zones: readonly Zone[];
  selection: Selection;
  drawingZone: boolean;
  disabled: boolean;
  onAddLine: () => void;
  onToggleDrawZone: () => void;
  /**
   * Ouvre la modale des presets.
   *
   * Un rappel plutôt que la modale elle-même : la feature `geometry-editor` ne doit
   * pas connaître `geometry-presets` — deux features ne s'importent jamais. Le
   * studio, qui les câble toutes les deux, tient le lien.
   */
  onOpenPresets?: (() => void) | undefined;
  onSelect: (selection: Selection) => void;
  onRenameLine: (id: string, name: string) => void;
  onRenameZone: (id: string, name: string) => void;
  onSetLineZone: (id: string, zoneId: string | null) => void;
  onRemoveLine: (id: string) => void;
  onRemoveZone: (id: string) => void;
}

export function GeometryPanel(props: GeometryPanelProps) {
  const { lines, zones, selection, drawingZone, disabled } = props;
  const empty = lines.length === 0 && zones.length === 0;

  return (
    <div className="rounded-section bg-surface p-4 shadow-card">
      <div className="flex items-center justify-between">
        <h3 className="label-micro">Géométrie</h3>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={props.onAddLine}
            disabled={disabled}
            title="Ajouter une ligne de comptage"
            className="flex items-center gap-1 rounded-input px-2 py-1 text-small text-ink-muted transition-colors hover:bg-elevated hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Plus aria-hidden="true" className="size-3.5" />
            Ligne
          </button>
          <button
            type="button"
            onClick={props.onToggleDrawZone}
            disabled={disabled}
            aria-pressed={drawingZone}
            title={
              drawingZone
                ? "Terminer par un double-clic ou un clic sur le premier sommet ; Échap annule"
                : "Dessiner une zone : un clic par sommet"
            }
            className={[
              "flex items-center gap-1 rounded-input px-2 py-1 text-small transition-colors",
              drawingZone
                ? "bg-accent text-accent-ink"
                : "text-ink-muted hover:bg-elevated hover:text-ink",
              "disabled:cursor-not-allowed disabled:opacity-50",
            ].join(" ")}
          >
            <Square aria-hidden="true" className="size-3.5" />
            Zone
          </button>
          {props.onOpenPresets !== undefined && (
            <button
              type="button"
              onClick={props.onOpenPresets}
              disabled={disabled}
              title="Enregistrer cette géométrie, ou en charger une"
              className="flex items-center gap-1 rounded-input px-2 py-1 text-small text-ink-muted transition-colors hover:bg-elevated hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Bookmark aria-hidden="true" className="size-3.5" />
              Presets
            </button>
          )}
        </div>
      </div>

      {drawingZone && (
        <p className="mt-3 rounded-input bg-elevated p-2 text-small text-ink-muted">
          Un clic par sommet. Double-cliquez — ou cliquez le premier sommet — pour
          fermer. <kbd className="font-bold">Échap</kbd> annule.
        </p>
      )}

      {empty && !drawingZone && (
        // État vide qui dit **quoi faire ensuite**, pas seulement ce qui manque :
        // sans ligne ni zone, une analyse ne produirait aucun compteur.
        <p className="mt-3 text-small text-ink-dim">
          Aucune ligne ni zone. Ajoutez au moins une ligne : sans elle, l'analyse
          n'a rien à compter.
        </p>
      )}

      {lines.length > 0 && (
        <ul className="mt-3 space-y-1">
          {lines.map((line) => (
            <li key={line.id}>
              <div
                className={[
                  "flex items-center gap-2 rounded-input p-1.5 transition-colors",
                  selection.kind === "line" && selection.id === line.id
                    ? "bg-elevated"
                    : "hover:bg-surface-2",
                ].join(" ")}
              >
                <button
                  type="button"
                  onClick={() => props.onSelect({ kind: "line", id: line.id })}
                  aria-label={`Sélectionner ${line.name}`}
                  className="size-3 shrink-0 rounded-badge"
                  style={{ backgroundColor: line.color }}
                />
                <input
                  value={line.name}
                  onChange={(event) => props.onRenameLine(line.id, event.target.value)}
                  onFocus={() => props.onSelect({ kind: "line", id: line.id })}
                  aria-label={`Nom de la ligne ${line.name}`}
                  className="min-w-0 flex-1 rounded-input bg-transparent px-1 text-small text-ink focus:bg-base"
                />
                <select
                  value={line.zoneId ?? ""}
                  onChange={(event) =>
                    props.onSetLineZone(line.id, event.target.value || null)
                  }
                  aria-label={`Portée de ${line.name}`}
                  title="Restreindre cette ligne à une zone"
                  className="max-w-24 rounded-input bg-surface-2 px-1 py-0.5 text-micro text-ink-muted"
                >
                  <option value="">toute l'image</option>
                  {zones.map((zone) => (
                    <option key={zone.id} value={zone.id}>
                      {zone.name}
                    </option>
                  ))}
                </select>
                <IconAction
                  label={`Supprimer ${line.name}`}
                  onClick={() => props.onRemoveLine(line.id)}
                />
              </div>
            </li>
          ))}
        </ul>
      )}

      {zones.length > 0 && (
        <ul className="mt-2 space-y-1">
          {zones.map((zone) => (
            <li key={zone.id}>
              <div
                className={[
                  "flex items-center gap-2 rounded-input p-1.5 transition-colors",
                  selection.kind === "zone" && selection.id === zone.id
                    ? "bg-elevated"
                    : "hover:bg-surface-2",
                ].join(" ")}
              >
                <button
                  type="button"
                  onClick={() => props.onSelect({ kind: "zone", id: zone.id })}
                  aria-label={`Sélectionner ${zone.name}`}
                  className="size-3 shrink-0 rounded-badge"
                  style={{ backgroundColor: zone.color }}
                />
                <input
                  value={zone.name}
                  onChange={(event) => props.onRenameZone(zone.id, event.target.value)}
                  onFocus={() => props.onSelect({ kind: "zone", id: zone.id })}
                  aria-label={`Nom de la zone ${zone.name}`}
                  className="min-w-0 flex-1 rounded-input bg-transparent px-1 text-small text-ink focus:bg-base"
                />
                <span className="text-micro text-ink-dim">{zone.points.length} sommets</span>
                <IconAction
                  label={`Supprimer ${zone.name}`}
                  onClick={() => props.onRemoveZone(zone.id)}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function IconAction({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="grid size-6 shrink-0 place-items-center rounded-input text-ink-dim transition-colors hover:bg-base hover:text-negative"
    >
      <Trash2 aria-hidden="true" className="size-3.5" />
    </button>
  );
}
