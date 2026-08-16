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
 * libre à taper, et les deux sens d'une ligne sont toujours l'un et l'autre : c'est
 * ce qui garantit que le bilan entrées/sorties du carrefour est toujours exploitable,
 * sans dépendre d'un utilisateur qui penserait à cocher un rôle facultatif. Puisqu'il
 * n'y a jamais que deux états possibles pour la paire, un bouton qui les **inverse**
 * remplace le menu déroulant par sens : un geste au lieu de deux choix à faire
 * correspondre à l'œil.
 *
 * Le bloc des sens ne s'ouvre que sur la ligne **sélectionnée**, et c'est délibéré :
 * six lignes dépliées feraient douze menus dans une colonne de 24 rem, où on ne
 * retrouverait plus la ligne qu'on cherchait.
 */

import { ArrowUp, ArrowUpDown, Bookmark, Plus, Square, Trash2 } from "lucide-react";

import type { CountingLine, DirectionRole, DirectionSign, Zone } from "@/shared/api/contracts";
import { directionRole } from "@/shared/lib/directions";
import { arrowRotationDeg, positiveNormal } from "@/shared/lib/geometry";
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
 * Les deux sens de la ligne sélectionnée, et le bouton qui les inverse.
 *
 * Il n'y a plus de libellé libre : le rôle **est** le nom (`directionName`). Et
 * puisqu'une paire n'a jamais que deux états — « positif entrée, négatif sortie »
 * ou l'inverse — un bouton qui bascule de l'un à l'autre remplace deux menus
 * déroulants à faire correspondre l'un à l'autre à l'œil. Les deux rangées
 * restent lisibles pendant la bascule : c'est **elles** qui disent l'état actuel,
 * le bouton ne fait qu'agir dessus.
 */
function DirectionFields({
  line,
  onSetDirectionRole,
}: {
  line: CountingLine;
  onSetDirectionRole: (id: string, sign: DirectionSign, role: DirectionRole) => void;
}) {
  const normal = positiveNormal(line.a, line.b);
  const positiveRole = directionRole(line, "positive");
  const negativeRole = directionRole(line, "negative");
  // `neutral` n'est plus atteignable depuis ce panneau, mais une ligne tracée
  // avant qu'il le devienne peut encore le porter des deux côtés
  // (`withDirectionDefaults`). Il n'y a alors rien à inverser : le bouton pose
  // la paire par défaut plutôt que de deviner un bilan que personne n'a demandé.
  const undecided = positiveRole === "neutral" || negativeRole === "neutral";

  const swap = (): void => {
    onSetDirectionRole(line.id, "positive", undecided ? "entry" : negativeRole);
  };

  return (
    <div className="mt-1 ms-5 border-s border-line ps-2">
      <div className="flex items-stretch gap-1.5">
        <ul className="min-w-0 flex-1 space-y-1">
          {(["positive", "negative"] as const).map((sign) => (
            <DirectionRoleRow
              key={sign}
              line={line}
              sign={sign}
              role={sign === "positive" ? positiveRole : negativeRole}
              normal={normal}
            />
          ))}
        </ul>
        <button
          type="button"
          onClick={swap}
          title="Inverser entrée et sortie"
          aria-label={`Inverser les sens entrée et sortie de ${line.name}`}
          className="grid shrink-0 place-items-center rounded-input bg-surface-2 px-2 text-ink-muted transition-colors hover:bg-elevated hover:text-ink active:scale-95"
        >
          <ArrowUpDown aria-hidden="true" className="size-4" />
        </button>
      </div>
    </div>
  );
}

/**
 * Une rangée de sens, en **lecture seule** : la flèche réelle du tracé, son
 * libellé. Plus aucune interaction directe — `DirectionFields` porte le seul
 * geste possible, le bouton d'inversion.
 *
 * Pas d'icône de rôle : la flèche suffit à distinguer les deux rangées, et le
 * mot « Entrée »/« Sortie » à côté dit ce qu'elle signifie. Une icône
 * supplémentaire n'ajoutait qu'une convention à retenir.
 */
function DirectionRoleRow({
  line,
  sign,
  role,
  normal,
}: {
  line: CountingLine;
  sign: DirectionSign;
  role: DirectionRole;
  normal: { x: number; y: number };
}) {
  const direction = sign === "positive" ? normal : { x: -normal.x, y: -normal.y };

  return (
    <li className="flex items-center gap-1.5 rounded-input bg-surface-2 px-2 py-1">
      {/* La flèche dit **quel** sens dans la convention du canvas — pivotée à
          l'angle **exact** du tracé (`arrowRotationDeg`), pas arrondie au
          huitième de tour le plus proche comme le ferait un glyphe unicode.
          Sans elle, l'utilisateur ne saurait pas laquelle des deux rangées
          correspond à quel côté. */}
      <ArrowUp
        aria-hidden="true"
        className="size-3.5 shrink-0"
        style={{ color: line.color, transform: `rotate(${arrowRotationDeg(direction)}deg)` }}
      />
      <span className="min-w-0 truncate text-micro text-ink">
        {role === "entry" ? "Entrée" : role === "exit" ? "Sortie" : "À préciser"}
      </span>
    </li>
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
