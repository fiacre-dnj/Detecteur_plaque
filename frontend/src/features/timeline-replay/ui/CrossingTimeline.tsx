/**
 * La chronologie des franchissements — **et le moyen d'y aller**.
 *
 * `CrossingLog` reste le journal de l'analyse *en cours* : là, il n'y a nulle part
 * où se déplacer, et `useFollowAnalysis` ramènerait de force la tête de lecture sur
 * l'image analysée. Ce composant-ci sert l'autre moment, celui où l'analyse est
 * finie et où la question change : « le compteur dit 23 — montre-moi le douzième ».
 *
 * Trois différences avec le journal, et chacune répond à cette question :
 *
 * 1. **chronologique, pas anté-chronologique.** Une chronologie se lit du début vers
 *    la fin ; le journal, lui, montre ce qui vient d'arriver, donc le plus récent en
 *    tête. Les deux ordres sont justes pour leur usage ;
 * 2. **chaque entrée est un bouton** — donc atteignable au clavier et annoncée comme
 *    activable, ce qu'un `<li>` avec un `onClick` ne serait pas ;
 * 3. **l'entrée courante suit la lecture** et se met en évidence, ce qui fait de la
 *    liste un repère de position autant qu'un inventaire.
 */

import { useEffect, useRef } from "react";

import type { CrossingEvent } from "@/shared/api/contracts";
import { classColor } from "@/shared/config/palettes";
import { plateCell, plateTitle } from "@/shared/lib/plate";

import { activeCrossingIndex, formatTimecode } from "../model/timeline";

interface CrossingTimelineProps {
  /** Tous les franchissements, dans l'ordre **chronologique**. */
  events: readonly CrossingEvent[];
  /** Identifiant de ligne → nom affiché, tel que la géométrie courante le donne. */
  lineNames: ReadonlyMap<string, string>;
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
  lineNames,
  currentTimeMs,
  onSeek,
  inertReason,
}: CrossingTimelineProps) {
  const active = activeCrossingIndex(events, currentTimeMs);
  const activeRef = useRef<HTMLLIElement>(null);

  /**
   * Amène l'entrée courante dans la vue pendant la lecture.
   *
   * `block: "nearest"` et non `"center"` : recentrer à chaque franchissement ferait
   * sauter la liste sous les yeux de quelqu'un qui la parcourt. Ici, elle ne bouge
   * que lorsque l'entrée sortirait du cadre.
   *
   * Le défilement animé est **coupé** sous `prefers-reduced-motion`. La règle
   * globale d'`index.css` ne suffit pas : elle borne les transitions CSS, pas le
   * comportement d'un `scrollIntoView`, qui est une option JavaScript.
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
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="label-micro">Chronologie</h3>
        <output className="text-small text-ink-muted tabular">{events.length}</output>
      </div>

      {onSeek === undefined && inertReason !== undefined && (
        <p className="mt-1 text-micro text-ink-dim">{inertReason}</p>
      )}

      {events.length === 0 ? (
        <p className="mt-2 text-small text-ink-dim">
          Aucun franchissement sur cette analyse. Si vous en attendiez, vérifiez que
          la ligne traverse bien la voie.
        </p>
      ) : (
        <ol className="mt-2 max-h-64 space-y-0.5 overflow-y-auto pe-1">
          {events.map((event, index) => {
            const current = index === active;
            const key = `${event.lineId}-${event.globalId}-${event.frameIndex}-${event.direction}`;
            const label = `Aller à ${formatTimecode(event.timestampMs)} — ${event.label} ${event.globalId}`;
            return (
              <li key={key} ref={current ? activeRef : undefined}>
                <button
                  type="button"
                  disabled={onSeek === undefined}
                  aria-current={current ? "true" : undefined}
                  aria-label={label}
                  title={onSeek === undefined ? inertReason : label}
                  onClick={() => onSeek?.(event.timestampMs)}
                  className={[
                    "flex w-full items-center gap-2 rounded-input px-2 py-1 text-start text-small",
                    // L'accent marque la position — un état fonctionnel, le seul
                    // usage que le système de design lui autorise.
                    current ? "bg-elevated text-ink" : "text-ink-muted",
                    onSeek === undefined
                      ? "cursor-default"
                      : "cursor-pointer hover:bg-elevated hover:text-ink",
                  ].join(" ")}
                >
                  {/* Le rail : un filet continu que la pastille courante interrompt.
                      C'est ce qui fait lire la liste comme un axe du temps plutôt
                      que comme un tableau. */}
                  <span aria-hidden="true" className="relative flex w-3 shrink-0 justify-center">
                    <span className="absolute inset-y-[-4px] w-px bg-line" />
                    <span
                      className="relative size-2 self-center rounded-pill ring-2 ring-surface-2"
                      style={{ backgroundColor: classColor(event.label) }}
                    />
                  </span>

                  <time className="shrink-0 tabular text-ink-dim">
                    {formatTimecode(event.timestampMs)}
                  </time>

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

                  {/* Le seul texte de longueur arbitraire — l'utilisateur nomme ses
                      lignes — donc c'est lui qui cède quand la place manque. */}
                  <span className="truncate text-ink-dim">
                    {lineNames.get(event.lineId) ?? event.lineId}
                  </span>

                  {/* Le sens, en flèche plutôt qu'en mot : « sens + » n'apprend rien
                      à qui n'a pas la convention en tête, et la flèche tient dans la
                      largeur qu'un nom de ligne laisse. */}
                  <span
                    aria-hidden="true"
                    className="ms-auto shrink-0 tabular text-ink-dim"
                    title={event.direction > 0 ? "Sens A→B" : "Sens B→A"}
                  >
                    {event.direction > 0 ? "↑" : "↓"}
                  </span>
                  <span className="sr-only">
                    {event.direction > 0 ? "sens A vers B" : "sens B vers A"}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
