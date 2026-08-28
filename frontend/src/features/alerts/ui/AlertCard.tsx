/**
 * Une alerte, en détail.
 *
 * Elle répond aux quatre questions qu'on se pose en la lisant, dans cet ordre :
 * **quoi** (le titre et l'icône), **qui** (le numéro du véhicule, son type, sa
 * plaque), **où** (la ligne, avec sa pastille et la flèche à l'angle réel du tracé)
 * et **quand** (l'instant, au dixième de seconde).
 *
 * **Cliquable, et c'est une exception réfléchie.** L'ancienne chronologie
 * cliquable a été retirée pour double emploi avec la barre de lecture : on y
 * parcourait le temps. Ici on ne parcourt rien — on saute à un fait précis, dont
 * l'instant est justement l'information qu'on vient de lire. C'est le seul geste
 * qui permette de vérifier une alerte, et une alerte invérifiable ne vaut rien.
 */

import { ArrowUp } from "lucide-react";

import type { CountingLine } from "@/shared/api/contracts";
import { classColor } from "@/shared/config/palettes";
import { classLabel } from "@/shared/lib/classes";
import { crossingHeadingDeg, directionArrow } from "@/shared/lib/directions";
import { formatSceneTimePrecise } from "@/shared/lib/sceneTime";

import type { Alert } from "../model/alerts";
import { ALERT_LOOK, SEVERITY_INK, SEVERITY_RAIL, SEVERITY_SURFACE } from "./alertLook";

interface AlertCardProps {
  alert: Alert;
  /** Le tracé **courant**, pour l'angle de la flèche. */
  lines: readonly CountingLine[];
  /** Amène la tête de lecture à l'instant du fait. Absent = carte inerte. */
  onSeek?: ((timestampMs: number) => void) | undefined;
}

export function AlertCard({ alert, lines, onSeek }: AlertCardProps) {
  const look = ALERT_LOOK[alert.kind];
  const headingDeg =
    alert.line === null || alert.direction === null
      ? null
      : crossingHeadingDeg(lines, alert.line.id, alert.direction);

  const body = (
    <>
      <div className="flex items-center gap-1.5">
        <look.Icon aria-hidden="true" className={`size-3.5 shrink-0 ${SEVERITY_INK[alert.severity]}`} />
        <span className={`label-micro ${SEVERITY_INK[alert.severity]}`}>{look.title}</span>
        <time className="ms-auto shrink-0 text-micro text-ink-muted tabular">
          {formatSceneTimePrecise(alert.timestampMs)}
        </time>
      </div>

      <p className="mt-1 flex min-w-0 items-center gap-1.5 text-caption">
        <span
          aria-hidden="true"
          className="size-2 shrink-0 rounded-badge"
          style={{ backgroundColor: classColor(alert.label) }}
        />
        <span className="font-bold text-ink">
          {classLabel(alert.label)} #{alert.globalId}
        </span>
        {alert.plateText !== null && (
          <span className="min-w-0 truncate rounded-badge bg-elevated px-1 text-micro text-ink-muted tabular">
            {alert.plateText}
          </span>
        )}
      </p>

      {alert.line !== null && (
        <p className="mt-0.5 flex min-w-0 items-center gap-1.5 text-micro text-ink-muted">
          {/* La flèche est pivotée à l'angle **réel** du tracé, comme au panneau de
              géométrie et au registre : c'est ce qui relie la carte au trait qu'on
              voit sur la vidéo. Sans géométrie lisible — ligne retirée du tracé — on
              retombe sur le glyphe brut plutôt que sur une flèche non pivotée, qui
              affirmerait « vers le haut ». */}
          {headingDeg === null ? (
            <span aria-hidden="true" className="shrink-0">
              {alert.direction === null ? "" : directionArrow(alert.direction)}
            </span>
          ) : (
            <ArrowUp
              aria-hidden="true"
              className="size-3 shrink-0"
              style={{ color: alert.line.color, transform: `rotate(${headingDeg}deg)` }}
            />
          )}
          <span className="truncate">{alert.line.name}</span>
        </p>
      )}

      {/* Le motif, en clair. Il était masqué dans la pile flottante posée sur la
          vidéo, faute de place ; celle-ci a disparu avec son manque de place, et
          c'est cette phrase qui distingue « voie réservée » de « sens interdit »
          sans avoir à relire le tracé. */}
      <p className="mt-0.5 text-micro text-ink-dim">
        {look.describe({ lineName: alert.line?.name ?? null, watched: alert.watched })}
      </p>
    </>
  );

  // **Un filet de gravité à gauche**, en plus de l'écrin teinté. C'est ce qui fait
  // lire une pile de cartes comme une pile de notifications plutôt que comme une
  // liste de paragraphes : l'œil suit une colonne de traits colorés et repère les
  // rouges parmi les orange sans lire un mot. La teinte reste celle de la gravité —
  // jamais celle de la ligne, qui encode déjà une identité sur le canvas.
  const surface = [
    "w-full rounded-card border-s-2 p-2.5 text-start ring-1",
    SEVERITY_SURFACE[alert.severity],
    SEVERITY_RAIL[alert.severity],
  ].join(" ");

  if (onSeek === undefined) return <div className={surface}>{body}</div>;

  return (
    <button
      type="button"
      onClick={() => onSeek(alert.timestampMs)}
      title={`Aller à ${formatSceneTimePrecise(alert.timestampMs)} dans la vidéo`}
      className={`${surface} transition-colors hover:brightness-125`}
    >
      {body}
    </button>
  );
}
