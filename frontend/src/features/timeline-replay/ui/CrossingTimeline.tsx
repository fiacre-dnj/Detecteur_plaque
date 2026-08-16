/**
 * La chronologie des franchissements — **et le moyen d'y aller**.
 *
 * `CrossingLog` reste le journal de l'analyse *en cours* : là, il n'y a nulle part où
 * se déplacer. Ce composant-ci sert l'autre moment, celui où l'analyse est finie et où
 * la question change : « le compteur dit 23 — montre-moi le douzième ».
 *
 * Quatre étages, du plus large au plus fin, et chacun répond à une question qu'aucun
 * autre ne sait poser :
 *
 * 1. le **rail de densité** — « à quel moment ça passe, et dans quel sens ». Trois
 *    cents entrées défilantes ne montrent ni la pointe ni l'interruption ; une
 *    silhouette de vingt barres le montre d'un coup d'œil, et cliquer dedans déplace
 *    la vidéo ;
 * 2. le **bandeau de synthèse** — « combien, dont combien d'entrées et de sorties »,
 *    recalculé selon les filtres actifs ;
 * 3. les **filtres** — ligne, sens, type. Un ensemble vide signifie « tout » : une
 *    intersection naïve afficherait une liste vide au premier rendu ;
 * 4. la **liste**, groupée par tranche de temps, chaque entrée cliquable et suivant la
 *    lecture.
 *
 * Trois propriétés de l'ancienne version sont conservées telles quelles, parce que
 * chacune a une raison : la liste est **chronologique** (un journal est
 * anté-chronologique, une chronologie se lit du début vers la fin), chaque entrée est
 * un `<button>` (donc atteignable au clavier et annoncée comme activable), et l'entrée
 * courante **suit la lecture**, ce qui fait de la liste un repère de position autant
 * qu'un inventaire.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import type { CountingLine, CrossingEvent, DirectionSign } from "@/shared/api/contracts";
import { classColor } from "@/shared/config/palettes";
import {
  crossingDirectionName,
  directionArrow,
  directionRole,
  lineName,
  roleLabel,
  signOf,
} from "@/shared/lib/directions";
import { plateCell, plateTitle } from "@/shared/lib/plate";

import { activeCrossingIndex, formatTimecode } from "../model/timeline";
import {
  NO_FILTER,
  type TimelineFilter,
  densityBuckets,
  filterCrossings,
  groupByTime,
  presentLabels,
  presentLines,
  toggle,
} from "../model/timelineFilters";

interface CrossingTimelineProps {
  /** Tous les franchissements, dans l'ordre **chronologique**. */
  events: readonly CrossingEvent[];
  /**
   * La géométrie courante — les lignes entières, pas une `Map` de noms.
   *
   * C'est ce qui permet d'afficher le **nom du sens** plutôt qu'une flèche : « ↑ »
   * n'apprend rien à qui n'a pas la convention A→B en tête, alors que « Vers le
   * centre » est ce que l'utilisateur a écrit lui-même.
   */
  lines: readonly CountingLine[];
  /** Durée de la scène, pour dimensionner le rail et les groupes. */
  durationMs: number;
  /** Position de lecture, pour mettre en évidence l'entrée atteinte. */
  currentTimeMs: number;
  /**
   * Déplace la lecture. **`undefined` rend la chronologie inerte**, et c'est un état
   * légitime : pendant l'analyse il n'y a rien où aller, et après un rechargement
   * d'historique sans vidéo il n'y a rien à déplacer. Un bouton qui ne fait rien
   * serait pire — d'où des entrées non cliquables plutôt que cliquables sans effet.
   */
  onSeek?: ((timestampMs: number) => void) | undefined;
  /** Pourquoi le déplacement est indisponible, affiché en aide. */
  inertReason?: string | undefined;
}

export function CrossingTimeline({
  events,
  lines,
  durationMs,
  currentTimeMs,
  onSeek,
  inertReason,
}: CrossingTimelineProps) {
  const [filter, setFilter] = useState<TimelineFilter>(NO_FILTER);

  const visible = useMemo(() => filterCrossings(events, filter), [events, filter]);
  const buckets = useMemo(() => densityBuckets(visible, durationMs), [visible, durationMs]);
  const groups = useMemo(
    () => groupByTime(visible, durationMs, formatTimecode),
    [visible, durationMs],
  );
  const lineChips = useMemo(() => presentLines(events, lines), [events, lines]);
  const labelChips = useMemo(() => presentLabels(events), [events]);

  // Le bilan porte sur ce qui est **affiché**, pas sur tout : un bandeau qui
  // annoncerait le total complet à côté d'une liste filtrée invite à croire que le
  // filtre n'a pas pris.
  const balance = useMemo(() => {
    let entries = 0;
    let exits = 0;
    for (const event of visible) {
      const line = lines.find((candidate) => candidate.id === event.lineId);
      if (line === undefined) continue;
      const role = directionRole(line, signOf(event.direction));
      if (role === "entry") entries += 1;
      else if (role === "exit") exits += 1;
    }
    return { entries, exits, declared: entries + exits > 0 };
  }, [visible, lines]);

  const active = activeCrossingIndex(visible, currentTimeMs);
  const activeEvent = active < 0 ? null : visible[active];
  const activeRef = useRef<HTMLLIElement>(null);
  const filtered = visible.length !== events.length;

  /**
   * Amène l'entrée courante dans la vue pendant la lecture.
   *
   * `block: "nearest"` et non `"center"` : recentrer à chaque franchissement ferait
   * sauter la liste sous les yeux de quelqu'un qui la parcourt. Ici, elle ne bouge
   * que lorsque l'entrée sortirait du cadre.
   *
   * Le défilement animé est **coupé** sous `prefers-reduced-motion`. La règle globale
   * d'`index.css` ne suffit pas : elle borne les transitions CSS, pas le comportement
   * d'un `scrollIntoView`, qui est une option JavaScript.
   */
  useEffect(() => {
    if (active < 0) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    activeRef.current?.scrollIntoView({
      block: "nearest",
      behavior: reduced ? "auto" : "smooth",
    });
  }, [active]);

  return (
    <section aria-label="Chronologie des franchissements" className="rounded-card bg-surface-2 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className="label-micro">Chronologie</h3>
        <output className="text-small text-ink-muted tabular">
          {visible.length}
          {filtered && <span className="text-ink-dim"> / {events.length}</span>}
          {balance.declared && (
            <span className="text-ink-dim">
              {" · "}
              {balance.entries} entrées · {balance.exits} sorties
            </span>
          )}
        </output>
      </div>

      {onSeek === undefined && inertReason !== undefined && (
        <p className="mt-1 text-micro text-ink-dim">{inertReason}</p>
      )}

      {events.length === 0 ? (
        <p className="mt-2 text-small text-ink-dim">
          Aucun franchissement sur cette analyse. Si vous en attendiez, vérifiez que la
          ligne traverse bien la voie.
        </p>
      ) : (
        <>
          <DensityRail
            buckets={buckets}
            durationMs={durationMs}
            currentTimeMs={currentTimeMs}
            onSeek={onSeek}
          />

          {(lineChips.length > 1 || labelChips.length > 1) && (
            <div className="mt-2 flex flex-wrap items-center gap-1">
              {lineChips.length > 1 &&
                lineChips.map((line) => (
                  <Chip
                    key={line.id}
                    active={filter.lineIds.includes(line.id)}
                    color={line.color}
                    label={line.name}
                    onToggle={() =>
                      setFilter((current) => ({
                        ...current,
                        lineIds: toggle(current.lineIds, line.id),
                      }))
                    }
                  />
                ))}
              {(["positive", "negative"] as const).map((sign) => (
                <Chip
                  key={sign}
                  active={filter.signs.includes(sign)}
                  label={`${sign === "positive" ? "↑" : "↓"} ${signChipLabel(lines, sign)}`}
                  onToggle={() =>
                    setFilter((current) => ({ ...current, signs: toggle(current.signs, sign) }))
                  }
                />
              ))}
              {labelChips.length > 1 &&
                labelChips.map((label) => (
                  <Chip
                    key={label}
                    active={filter.labels.includes(label)}
                    color={classColor(label)}
                    label={label}
                    onToggle={() =>
                      setFilter((current) => ({
                        ...current,
                        labels: toggle(current.labels, label),
                      }))
                    }
                  />
                ))}
              {filtered && (
                <button
                  type="button"
                  onClick={() => setFilter(NO_FILTER)}
                  className="ms-auto rounded-pill px-2 py-0.5 text-micro text-ink-dim transition-colors hover:bg-elevated hover:text-ink"
                >
                  Tout afficher
                </button>
              )}
            </div>
          )}

          {visible.length === 0 ? (
            <p className="mt-2 text-small text-ink-dim">
              Aucun franchissement ne correspond aux filtres actifs.
            </p>
          ) : (
            <ol className="mt-2 max-h-72 space-y-1 overflow-y-auto pe-1">
              {groups.map((group) => (
                <li key={group.startMs}>
                  {/* Le séparateur de tranche : il donne un repère fixe dans une liste
                      qui défile, et évite de lire trente horodatages pour situer un
                      passage. Purement visuel — chaque entrée porte déjà son heure. */}
                  <p
                    aria-hidden="true"
                    className="sticky top-0 z-10 bg-surface-2 py-0.5 text-micro text-ink-dim tabular"
                  >
                    {group.label}
                  </p>
                  <ol className="space-y-0.5">
                    {group.events.map((event) => (
                      <Entry
                        key={`${event.lineId}-${event.globalId}-${event.frameIndex}-${event.direction}`}
                        event={event}
                        lines={lines}
                        current={event === activeEvent}
                        rowRef={event === activeEvent ? activeRef : undefined}
                        onSeek={onSeek}
                        inertReason={inertReason}
                      />
                    ))}
                  </ol>
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </section>
  );
}

/**
 * Libellé de la puce d'un sens.
 *
 * Le nom de l'utilisateur quand **toutes** les lignes s'accordent, la convention
 * générique sinon. Prendre le nom de la première ligne serait pire que la convention :
 * un filtre étiqueté « Vers le centre » qui retient aussi « Vers la mer » ment.
 */
function signChipLabel(lines: readonly CountingLine[], sign: DirectionSign): string {
  const names = new Set(
    lines.map((line) => crossingDirectionName([line], line.id, sign === "positive" ? 1 : -1)),
  );
  const single = names.size === 1 ? [...names][0] : null;
  return single ?? (sign === "positive" ? "sens A→B" : "sens B→A");
}

/**
 * Le rail de densité — une barre par tranche, cliquable.
 *
 * Un `<button>` par tranche et non un `<canvas>` : chaque barre est une cible de
 * navigation, donc elle doit être atteignable au clavier et porter son propre libellé.
 * Un canvas cliquable serait invisible pour un lecteur d'écran.
 */
function DensityRail({
  buckets,
  durationMs,
  currentTimeMs,
  onSeek,
}: {
  buckets: ReturnType<typeof densityBuckets>;
  durationMs: number;
  currentTimeMs: number;
  onSeek?: ((timestampMs: number) => void) | undefined;
}) {
  if (buckets.length === 0) return null;
  const peak = Math.max(...buckets.map((bucket) => bucket.total), 1);
  const progress = durationMs <= 0 ? 0 : Math.min(1, Math.max(0, currentTimeMs / durationMs));

  return (
    <div className="relative mt-2">
      <ol className="flex h-10 items-end gap-px" aria-label="Densité des franchissements">
        {buckets.map((bucket) => {
          const label = `${bucket.total} à ${formatTimecode(bucket.startMs)}`;
          return (
            <li key={bucket.startMs} className="flex h-full flex-1 items-end">
              <button
                type="button"
                disabled={onSeek === undefined}
                aria-label={`Aller à ${formatTimecode(bucket.startMs)} — ${label}`}
                title={label}
                onClick={() => onSeek?.(bucket.startMs)}
                className={[
                  "flex h-full w-full flex-col justify-end rounded-[2px] transition-colors",
                  onSeek === undefined ? "cursor-default" : "cursor-pointer hover:bg-elevated",
                ].join(" ")}
              >
                {/* Deux segments empilés, le sens positif au-dessus. La hauteur totale
                    est proportionnelle à la pointe, pas absolue : sur un carrefour
                    calme, des barres de deux pixels ne montreraient rien. */}
                <span
                  aria-hidden="true"
                  className="block w-full rounded-t-[2px] bg-ink-muted"
                  style={{ height: `${(bucket.positive / peak) * 100}%` }}
                />
                <span
                  aria-hidden="true"
                  className="block w-full bg-ink-dim"
                  style={{ height: `${(bucket.negative / peak) * 100}%` }}
                />
              </button>
            </li>
          );
        })}
      </ol>
      {/* La tête de lecture, posée par-dessus le rail. `pointer-events-none` :
          elle indique, elle n'intercepte pas les clics destinés aux barres. */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0 w-px bg-accent"
        style={{ left: `${progress * 100}%` }}
      />
    </div>
  );
}

function Chip({
  active,
  label,
  color,
  onToggle,
}: {
  active: boolean;
  label: string;
  color?: string;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onToggle}
      className={[
        "flex items-center gap-1 rounded-pill px-2 py-0.5 text-micro transition-colors",
        active ? "bg-elevated-2 text-ink" : "text-ink-dim hover:bg-elevated hover:text-ink",
      ].join(" ")}
    >
      {color !== undefined && (
        <span
          aria-hidden="true"
          className="size-1.5 shrink-0 rounded-badge"
          style={{ backgroundColor: color }}
        />
      )}
      <span className="max-w-28 truncate">{label}</span>
    </button>
  );
}

function Entry({
  event,
  lines,
  current,
  rowRef,
  onSeek,
  inertReason,
}: {
  event: CrossingEvent;
  lines: readonly CountingLine[];
  current: boolean;
  rowRef?: React.Ref<HTMLLIElement> | undefined;
  onSeek?: ((timestampMs: number) => void) | undefined;
  inertReason?: string | undefined;
}) {
  const line = lines.find((candidate) => candidate.id === event.lineId);
  const sign = signOf(event.direction);
  const sensName = crossingDirectionName(lines, event.lineId, event.direction);
  const role = line === undefined ? "neutral" : directionRole(line, sign);
  const roleText = roleLabel(role);

  // Le libellé accessible dit **tout** ce que la rangée montre, dans l'ordre où on le
  // lirait à voix haute. Sans le sens nommé, un lecteur d'écran n'aurait que la flèche
  // — qui ne se prononce pas.
  const label = [
    `Aller à ${formatTimecode(event.timestampMs)}`,
    `${event.label} numéro ${event.globalId}`,
    sensName ?? `sens ${directionArrow(event.direction)}`,
    roleText,
    line === undefined ? null : `ligne ${line.name}`,
  ]
    .filter((part) => part !== null)
    .join(" — ");

  return (
    <li ref={rowRef}>
      <button
        type="button"
        disabled={onSeek === undefined}
        aria-current={current ? "true" : undefined}
        aria-label={label}
        title={onSeek === undefined ? inertReason : label}
        onClick={() => onSeek?.(event.timestampMs)}
        className={[
          "flex w-full items-center gap-2 rounded-input px-2 py-1 text-start text-small",
          // L'accent marque la position — un état fonctionnel, le seul usage que le
          // système de design lui autorise.
          current ? "bg-elevated text-ink" : "text-ink-muted",
          onSeek === undefined
            ? "cursor-default"
            : "cursor-pointer hover:bg-elevated hover:text-ink",
        ].join(" ")}
      >
        {/* Le rail : un filet continu que la pastille courante interrompt. C'est ce qui
            fait lire la liste comme un axe du temps plutôt que comme un tableau. */}
        <span aria-hidden="true" className="relative flex w-3 shrink-0 justify-center">
          <span className="absolute inset-y-[-4px] w-px bg-line" />
          <span
            className="relative size-2 self-center rounded-pill ring-2 ring-surface-2"
            style={{ backgroundColor: classColor(event.label) }}
          />
        </span>

        <time className="shrink-0 tabular text-ink-dim">{formatTimecode(event.timestampMs)}</time>

        <span className="shrink-0">
          {event.label} #{event.globalId}
        </span>

        {event.plateText !== null && (
          <span
            className="shrink-0 rounded-badge bg-elevated-2 px-1.5 text-micro tabular tracking-wide text-ink"
            title={plateTitle(event.plateText, event.plateTextScore, null)}
          >
            {plateCell(event.plateText, null)}
          </span>
        )}

        {/* **Le sens nommé, dans la couleur de sa ligne.** C'est le remplacement du
            « ↑ » de l'ancienne version : la flèche disait *quel* sens dans la
            convention du canvas, le nom dit ce que ce sens signifie. La couleur porte
            l'appartenance à la ligne, donc le nom de la ligne n'a plus à tenir dans la
            rangée — il reste dans l'infobulle. */}
        <span
          className="ms-auto flex min-w-0 shrink items-center gap-1"
          style={{ color: line?.color }}
        >
          <span aria-hidden="true" className="shrink-0 text-ink-dim">
            {directionArrow(event.direction)}
          </span>
          <span className="truncate text-micro">
            {sensName ?? lineName(lines, event.lineId)}
          </span>
        </span>

        {roleText !== null && (
          <span className="shrink-0 rounded-badge bg-elevated-2 px-1 text-micro text-ink-muted">
            {roleText}
          </span>
        )}
      </button>
    </li>
  );
}
