/**
 * Le panneau « Géométrie » : la liste des lignes et des zones.
 *
 * Il double le canvas plutôt que de le remplacer, parce que deux gestes y sont
 * plus sûrs qu'à la souris : **renommer** (impossible sur un canvas) et
 * **supprimer** (un clic sur une croix ne risque pas de déplacer la forme, alors
 * qu'une touche Suppr après un glisser accidentel oui).
 *
 * Le sélecteur « portée » de chaque ligne est ici et pas sur le canvas : c'est une
 * relation entre deux objets, pas une propriété spatiale. Le **rôle des sens** suit
 * le même raisonnement : le canvas montre où va chaque sens, mais le déclarer n'est
 * pas un geste de pointage.
 *
 * Chaque sens est **obligatoirement** « Entrée » ou « Sortie » — il n'y a plus de nom
 * libre à taper. Un menu déroulant à deux choix plutôt qu'un champ de texte : c'est
 * ce qui garantit que le bilan entrées/sorties du carrefour est toujours exploitable,
 * sans dépendre d'un utilisateur qui penserait à cocher un rôle facultatif.
 *
 * Le bloc des sens ne s'ouvre que sur la ligne **sélectionnée**, et c'est délibéré :
 * six lignes dépliées feraient douze menus dans une colonne de 24 rem, où on ne
 * retrouverait plus la ligne qu'on cherchait.
 */

import { Bookmark, Plus, Square, Trash2 } from "lucide-react";

import type { CountingLine, DirectionRole, DirectionSign, Zone } from "@/shared/api/contracts";
import { compassArrow, positiveNormal } from "@/shared/lib/geometry";
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
  onSetDirectionRole: (id: string, sign: DirectionSign, role: DirectionRole) => void;
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
          {/* La règle de décision, dite **pendant** le tracé.
              Un véhicule appartient à la zone quand le **centre** de sa boîte y
              est. Une zone collée aux bords de la chaussée laisse donc échapper
              les véhicules de bord, dont le centre tombe juste dehors — un
              sous-comptage discret, sans erreur, que rien n'explique après coup.
              Le dire ici plutôt que dans une infobulle : c'est maintenant que
              l'utilisateur place ses sommets (piège 10 de prompt/13). */}
          <span className="mt-1 block text-micro text-ink-dim">
            Un véhicule compte quand le <strong>centre</strong> de sa boîte est dans
            la zone. Tracez donc <strong>large</strong> : une zone serrée laisse
            échapper les véhicules de bord.
          </span>
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

              {selection.kind === "line" && selection.id === line.id && (
                <DirectionFields line={line} onSetDirectionRole={props.onSetDirectionRole} />
              )}
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

/**
 * Les deux sens de la ligne sélectionnée, chacun étiqueté entrée ou sortie.
 *
 * Il n'y a plus de libellé libre : le rôle **est** le nom (`directionName`), et le
 * choisir est obligatoire — un menu déroulant à deux options, jamais vide.
 */
function DirectionFields({
  line,
  onSetDirectionRole,
}: {
  line: CountingLine;
  onSetDirectionRole: (id: string, sign: DirectionSign, role: DirectionRole) => void;
}) {
  const normal = positiveNormal(line.a, line.b);

  return (
    <ul className="mt-1 ms-5 space-y-1 border-s border-line ps-2">
      {(["positive", "negative"] as const).map((sign) => (
        <li key={sign} className="flex flex-wrap items-center gap-1">
          {/* La flèche dit **quel** sens dans la convention du canvas — la même que
              celle dessinée sur le trait, à la même **direction réelle** de la
              ligne plutôt qu'un « ↑ »/« ↓ » figé. Sans elle, l'utilisateur ne
              saurait pas lequel des deux menus correspond à quel côté. */}
          <span
            aria-hidden="true"
            className="w-3 shrink-0 text-center text-micro"
            style={{ color: line.color }}
          >
            {compassArrow(sign === "positive" ? normal : { x: -normal.x, y: -normal.y })}
          </span>
          <RoleSelect line={line} sign={sign} onSetDirectionRole={onSetDirectionRole} />
        </li>
      ))}
      <li className="text-micro text-ink-dim">
        Entrée ou sortie : c'est ce qui donne le bilan du carrefour dans les
        résultats.
      </li>
    </ul>
  );
}

/** Les deux seuls rôles proposables — « ni l'un ni l'autre » a disparu du panneau. */
const ROLES: readonly { role: DirectionRole; label: string }[] = [
  { role: "entry", label: "Entrée" },
  { role: "exit", label: "Sortie" },
];

/**
 * Le rôle d'un sens, en `<select>` **obligatoire**.
 *
 * Un menu déroulant convient ici, contrairement au reste de l'écran qui préfère des
 * boutons visibles ensemble : il n'y a plus que deux choix à comparer, et l'un des
 * deux est toujours sélectionné — rien à cacher derrière un clic.
 *
 * `neutral` n'est plus atteignable depuis ce panneau, mais une ligne tracée avant ce
 * changement peut encore le porter (`withDirectionDefaults`). Une option masquée le
 * représente le temps que l'utilisateur tranche, plutôt que de deviner à sa place —
 * deviner fausserait un bilan que personne n'a demandé.
 */
function RoleSelect({
  line,
  sign,
  onSetDirectionRole,
}: {
  line: CountingLine;
  sign: DirectionSign;
  onSetDirectionRole: (id: string, sign: DirectionSign, role: DirectionRole) => void;
}) {
  const current = (sign === "positive" ? line.positiveRole : line.negativeRole) ?? "neutral";

  return (
    <select
      value={current}
      required
      onChange={(event) =>
        onSetDirectionRole(line.id, sign, event.target.value as DirectionRole)
      }
      aria-label={`Rôle du sens ${sign === "positive" ? "A vers B" : "B vers A"} de ${line.name}`}
      className="min-w-0 flex-1 rounded-input bg-transparent px-1 text-micro text-ink focus:bg-base"
    >
      {ROLES.map((entry) => (
        <option key={entry.role} value={entry.role}>
          {entry.label}
        </option>
      ))}
      {current === "neutral" && (
        <option value="neutral" disabled hidden>
          — à préciser —
        </option>
      )}
    </select>
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
