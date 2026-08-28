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
 *
 * **Il ne porte plus ni carte ni titre**, depuis qu'il vit dans le quatrième tiroir
 * de la barre du studio au lieu d'occuper en permanence la colonne de droite. Le
 * tiroir est déjà une surface élevée nommée « Géométrie » (`role="region"`), et un
 * `<h3>Géométrie</h3>` dans une région qui porte ce nom se lisait deux fois. Ce
 * composant rend donc son contenu nu : c'est son conteneur qui décide de l'écrin.
 */

import { ArrowUp, ArrowUpDown, Ban, Bookmark, Plus, ShieldCheck, Square, Trash2 } from "lucide-react";

import type {
  CountingLine,
  DetectableClass,
  DirectionRole,
  DirectionSign,
  Zone,
} from "@/shared/api/contracts";
import {
  LINE_KINDS,
  directionHeadingDeg,
  directionName,
  directionRole,
  isForbiddenRole,
  lineKind,
  type LineKind,
} from "@/shared/lib/directions";
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
  /**
   * Le catalogue des classes détectables, servi par le serveur.
   *
   * Fourni par le studio et jamais lu ici : cette feature ne connaît ni
   * `analysis-settings` ni la route qui le publie. Vide tant que le serveur n'a pas
   * répondu — la voie réservée est alors masquée plutôt que proposée sans noms,
   * parce qu'une case sans libellé ne se coche pas.
   */
  classes: readonly DetectableClass[];
  onSetLineKind: (id: string, kind: LineKind) => void;
  onSwapDirections: (id: string) => void;
  onSetLineClasses: (id: string, classIds: number[] | null) => void;
  onSetLineZone: (id: string, zoneId: string | null) => void;
  onRemoveLine: (id: string) => void;
  onRemoveZone: (id: string) => void;
}

export function GeometryPanel(props: GeometryPanelProps) {
  const { lines, zones, selection, drawingZone, disabled } = props;
  const empty = lines.length === 0 && zones.length === 0;

  return (
    <div>
      {/* Les trois actions en tête, alignées à gauche : dans un tiroir, il n'y a
          plus de titre à leur droite pour équilibrer la rangée. */}
      <div className="flex flex-wrap gap-1">
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
                <LineRules
                  line={line}
                  classes={props.classes}
                  onSetLineKind={props.onSetLineKind}
                  onSwapDirections={props.onSwapDirections}
                  onSetLineClasses={props.onSetLineClasses}
                />
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
 * Les règles de la ligne sélectionnée : son **type**, ses deux sens, sa voie
 * réservée.
 *
 * Deux réglages et non un seul, parce qu'ils sont **orthogonaux** : une voie de bus
 * peut être à sens unique *et* réservée. Les fondre dans un même sélecteur rendrait
 * ce cas inexprimable, alors qu'il est le cas d'usage le plus courant des deux.
 *
 * Le type est un choix de **paire** : c'est lui qui pose les deux rôles d'un coup
 * (`rolesForKind`), et les rangées en dessous ne font que dire l'état obtenu. Poser
 * les rôles un par un laisserait exister, entre deux gestes, une paire que
 * `lineKind` ne sait pas nommer.
 *
 * Le bloc ne s'ouvre que sur la ligne **sélectionnée**, et c'est délibéré : six
 * lignes dépliées feraient six sélecteurs et douze rangées dans une colonne de
 * 24 rem, où on ne retrouverait plus la ligne qu'on cherchait.
 */
function LineRules({
  line,
  classes,
  onSetLineKind,
  onSwapDirections,
  onSetLineClasses,
}: {
  line: CountingLine;
  classes: readonly DetectableClass[];
  onSetLineKind: (id: string, kind: LineKind) => void;
  onSwapDirections: (id: string) => void;
  onSetLineClasses: (id: string, classIds: number[] | null) => void;
}) {
  const kind = lineKind(line);
  const selected = LINE_KINDS.find((option) => option.kind === kind) ?? null;
  // Une ligne dont les deux sens portent le **même** rôle n'a rien à inverser :
  // l'échange rendrait la paire identique, et un bouton qui ne fait rien se lit
  // comme un bouton cassé. Sur une ligne héritée « à préciser », il garde son rôle
  // d'ADR 0021 : poser la paire par défaut au premier clic.
  const swappable = kind !== "closed" && kind !== "transit";
  const reserved = line.allowedClassIds ?? null;

  return (
    <div className="mt-1 ms-5 space-y-2 border-s border-line ps-2">
      <fieldset>
        <legend className="label-micro mb-1">Type de ligne</legend>
        <div className="flex flex-wrap gap-1">
          {LINE_KINDS.map((option) => (
            <button
              key={option.kind}
              type="button"
              onClick={() => onSetLineKind(line.id, option.kind)}
              aria-pressed={option.kind === kind}
              title={option.hint}
              className={[
                "rounded-pill px-2 py-0.5 text-micro transition-colors",
                option.kind === kind
                  ? "bg-ink text-base font-bold"
                  : "bg-surface-2 text-ink-muted hover:bg-elevated hover:text-ink",
              ].join(" ")}
            >
              {option.label}
            </button>
          ))}
        </div>
        {/* L'aide décrit **une conséquence**, jamais une définition : « tout passage
            en face est signalé » dit ce que le choix fait aux chiffres, là où « ligne
            à sens unique » ne ferait que redire son nom. */}
        <p className="mt-1 text-micro text-ink-dim">
          {selected?.hint ??
            "Sens hérités d'un tracé antérieur : choisissez un type pour les préciser."}
        </p>
      </fieldset>

      {/* **« Comptage seul » n'a pas de sens à régler.** Les deux rangées y
          disaient « Passage » deux fois, sous un bouton d'inversion déjà grisé :
          trois éléments d'interface pour zéro information, dans une colonne où
          chaque rangée coûte de la place à la ligne suivante. Le type dit déjà
          tout ce qu'il y a à savoir — ce qui franchit compte, quel que soit le
          côté d'où il vient.

          Le canevas, lui, garde ses deux flèches : elles disent de quel côté est
          chaque sens, ce qui reste vrai et sert à relier une rangée à un trait.
          C'est le *réglage* des sens qui disparaît, pas leur géométrie. */}
      {kind === "transit" ? (
        <p className="rounded-input bg-base p-2 text-micro text-ink-dim">
          Les deux sens sont comptés ensemble : tout véhicule qui franchit la ligne
          compte, quel que soit le côté d'où il vient.
        </p>
      ) : (
        <div className="flex items-stretch gap-1.5">
          <ul className="min-w-0 flex-1 space-y-1">
            {(["positive", "negative"] as const).map((sign) => (
              <DirectionRoleRow key={sign} line={line} sign={sign} />
            ))}
          </ul>
          <button
            type="button"
            onClick={() => onSwapDirections(line.id)}
            disabled={!swappable}
            title={
              swappable
                ? "Échanger les deux sens de la ligne"
                : "Les deux sens portent le même rôle : il n'y a rien à échanger"
            }
            aria-label={`Échanger les deux sens de ${line.name}`}
            className="grid shrink-0 place-items-center rounded-input bg-surface-2 px-2 text-ink-muted transition-colors hover:bg-elevated hover:text-ink active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ArrowUpDown aria-hidden="true" className="size-4" />
          </button>
        </div>
      )}

      {classes.length > 0 && (
        <ReservedLane
          line={line}
          classes={classes}
          reserved={reserved}
          onSetLineClasses={onSetLineClasses}
        />
      )}
    </div>
  );
}

/**
 * La voie réservée : quelles classes ont le droit de franchir cette ligne.
 *
 * **Un interrupteur puis des cases, et pas seulement des cases.** Sans
 * l'interrupteur, « aucune case cochée » et « pas de restriction » seraient le même
 * écran pour deux règles opposées — la première interdit tout le monde, la seconde
 * n'interdit personne. L'état « restreint » est donc explicite, et décocher la
 * dernière classe éteint la règle plutôt que de fermer la voie.
 *
 * Les libellés viennent du **catalogue du serveur** et ne sont jamais recopiés :
 * une case cochable que le serveur refuserait à l'envoi est exactement le mode de
 * panne que la publication du catalogue existe pour empêcher.
 */
function ReservedLane({
  line,
  classes,
  reserved,
  onSetLineClasses,
}: {
  line: CountingLine;
  classes: readonly DetectableClass[];
  reserved: readonly number[] | null;
  onSetLineClasses: (id: string, classIds: number[] | null) => void;
}) {
  const active = reserved !== null;
  // Le **complément** de la liste autorisée, et non une seconde liste stockée : la
  // règle est écrite une fois (`allowedClassIds`), et ce qui est interdit s'en
  // déduit. Deux listes finiraient par se contredire — un type absent des deux, ou
  // présent dans les deux — et l'écran dirait alors autre chose que le juge
  // (`shared/lib/lineRules.ts`).
  const barred = active
    ? classes.filter((entry) => !(reserved ?? []).includes(entry.id))
    : [];

  const toggle = (id: number): void => {
    const current = reserved ?? [];
    const next = current.includes(id)
      ? current.filter((entry) => entry !== id)
      : [...current, id];
    // Une liste vidée éteint la règle : `null` et jamais `[]`, qui voudrait dire
    // « aucune classe n'a le droit de passer » — ce que le type « Infranchissable »
    // exprime déjà, en le disant.
    onSetLineClasses(line.id, next.length === 0 ? null : next);
  };

  return (
    <div>
      <label className="flex cursor-pointer items-center gap-1.5">
        <input
          type="checkbox"
          checked={active}
          onChange={(event) =>
            onSetLineClasses(
              line.id,
              // À l'activation, on part des classes cochées du catalogue plutôt que
              // d'une liste vide : une case activée qui n'autorise personne mettrait
              // tout le trafic en infraction le temps de cocher la première classe.
              event.target.checked ? classes.map((entry) => entry.id) : null,
            )
          }
          className="size-3.5 shrink-0 accent-[var(--color-accent)]"
        />
        <ShieldCheck aria-hidden="true" className="size-3.5 shrink-0 text-ink-dim" />
        <span className="text-micro text-ink">Voie réservée</span>
      </label>

      {active && (
        <>
          <div className="mt-1 flex flex-wrap gap-1">
            {classes.map((entry) => {
              const allowed = (reserved ?? []).includes(entry.id);
              return (
                <button
                  key={entry.id}
                  type="button"
                  onClick={() => toggle(entry.id)}
                  aria-pressed={allowed}
                  className={[
                    "rounded-pill px-2 py-0.5 text-micro transition-colors",
                    allowed
                      ? "bg-ink/15 text-ink"
                      : "bg-surface-2 text-ink-dim line-through hover:text-ink-muted",
                  ].join(" ")}
                >
                  {entry.label}
                </button>
              );
            })}
          </div>
          {/* **La phrase nomme les types barrés, elle ne décrit plus la règle en
              général.** « Les types barrés sont signalés » demandait de relire les
              pastilles pour savoir *lesquels*, et une pastille barrée se distingue
              d'une pastille autorisée par un trait et deux crans de gris — sur des
              libellés de six lettres. Écrire « Interdits : Camion, Bus » rend la
              règle vérifiable sans avoir lancé d'analyse, ce qui était la seule
              façon de la vérifier jusqu'ici.

              Le cas « rien de barré » est dit lui aussi : l'interrupteur est
              allumé, toutes les pastilles sont actives, et rien à l'écran ne
              distinguait cet état d'une restriction qui ne se déclencherait
              jamais. */}
          <p className="mt-1 text-micro text-ink-dim">
            {barred.length === 0 ? (
              "Tous les types sont autorisés : aucune infraction ne sera signalée. Barrez ceux qui n'ont pas le droit de passer."
            ) : (
              <>
                <strong className="text-negative">
                  Interdits : {barred.map((entry) => entry.label).join(", ")}
                </strong>{" "}
                — leur passage sur cette ligne sera signalé. Il reste compté : une
                infraction est un passage qualifié, pas un passage retiré.
              </>
            )}
          </p>
        </>
      )}
    </div>
  );
}

/**
 * Une rangée de sens, en **lecture seule** : la flèche réelle du tracé, son
 * libellé.
 *
 * Aucune interaction directe — le type de ligne et le bouton d'inversion portent
 * les deux seuls gestes possibles. Le libellé passe par `directionName` et n'est
 * plus écrit ici : c'est le même mot que sur le canvas, et deux tables de libellés
 * finiraient par dire « Interdit » d'un côté du trait et autre chose dans le
 * panneau qui le décrit.
 *
 * Un sens interdit se distingue par **le rouge et une icône**, pas par le mot seul :
 * c'est la seule rangée de ce panneau qui annonce une règle plutôt qu'un rôle, et
 * elle doit se repérer sans être lue.
 */
function DirectionRoleRow({ line, sign }: { line: CountingLine; sign: DirectionSign }) {
  // `directionHeadingDeg` **et pas** une négation du normal écrite ici : c'est la
  // fonction partagée qui décide de cet angle, et elle sert aussi à la chronologie
  // des franchissements et aux puces du registre. Trois écrans, une flèche — la
  // négation en double était exactement le signe qu'on inverse sans le remarquer,
  // mode de panne que `shared/lib/geometry.ts` documente.
  const headingDeg = directionHeadingDeg(line, sign);
  const role: DirectionRole = directionRole(line, sign);
  const forbidden = isForbiddenRole(role);

  return (
    <li
      className={[
        "flex items-center gap-1.5 rounded-input px-2 py-1",
        forbidden ? "bg-negative/10 ring-1 ring-negative/30" : "bg-surface-2",
      ].join(" ")}
    >
      {/* La flèche dit **quel** sens dans la convention du canvas — pivotée à
          l'angle **exact** du tracé, pas arrondie au huitième de tour le plus
          proche comme le ferait un glyphe unicode. Sans elle, l'utilisateur ne
          saurait pas laquelle des deux rangées correspond à quel côté.

          Un segment de longueur nulle — une ligne qu'on vient de commencer à
          tracer — n'a pas d'angle : aucune flèche plutôt qu'une flèche vers le
          haut, qui affirmerait une orientation que personne n'a mesurée. */}
      {headingDeg !== null && (
        <ArrowUp
          aria-hidden="true"
          className={`size-3.5 shrink-0 ${forbidden ? "text-negative" : ""}`}
          // La teinte de la ligne sur un sens ordinaire, le jeton `negative` sur un
          // sens interdit — d'où `undefined` ici, qui laisse la classe décider
          // plutôt que d'écraser la couleur avec un style en ligne.
          style={{
            color: forbidden ? undefined : line.color,
            transform: `rotate(${headingDeg}deg)`,
          }}
        />
      )}
      {forbidden && <Ban aria-hidden="true" className="size-3 shrink-0 text-negative" />}
      <span
        className={[
          "min-w-0 truncate text-micro",
          forbidden ? "font-bold text-negative" : "text-ink",
        ].join(" ")}
      >
        {role === "neutral" ? "À préciser" : directionName(line, sign)}
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
