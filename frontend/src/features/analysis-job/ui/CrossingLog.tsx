/**
 * Le journal des franchissements, au fil de l'analyse.
 *
 * Un total se croit ; une liste se vérifie. C'est la raison d'être de ce panneau :
 * pouvoir dire « à 00:12.4, cette voiture-là a franchi cette ligne-là dans ce
 * sens-là » et le confronter à l'image qu'on a sous les yeux. Sans lui, valider un
 * comptage revient à faire confiance à un nombre.
 *
 * Le plus récent en tête, et la liste **ne défile pas toute seule** : un
 * défilement automatique arracherait la ligne qu'on est en train de lire.
 */

import type { CrossingEvent } from "@/shared/api/contracts";
import { classColor } from "@/shared/config/palettes";
import { plateCell, plateTitle } from "@/shared/lib/plate";

import { directionLabel, formatSceneTime, lineLabel } from "../model/previewLog";

interface CrossingLogProps {
  events: readonly CrossingEvent[];
  /** Identifiant de ligne → nom affiché, tel que la géométrie courante le donne. */
  lineNames: ReadonlyMap<string, string>;
  /** Titre du panneau : « pendant l'analyse » n'est pas « après ». */
  title?: string;
}

export function CrossingLog({ events, lineNames, title = "Franchissements" }: CrossingLogProps) {
  return (
    <section aria-label={title} className="rounded-card bg-surface-2 p-3">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="label-micro">{title}</h3>
        <output className="text-small text-ink-muted tabular">{events.length}</output>
      </div>

      {events.length === 0 ? (
        <p className="mt-2 text-small text-ink-dim">
          Aucun franchissement pour l'instant. Les événements s'affichent ici au
          moment où le serveur les compte.
        </p>
      ) : (
        <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto">
          {events.map((event) => (
            <li
              key={`${event.lineId}-${event.globalId}-${event.frameIndex}-${event.direction}`}
              className="flex items-baseline gap-2 text-small"
            >
              <span className="shrink-0 tabular text-ink-dim">
                {formatSceneTime(event.timestampMs)}
              </span>
              <span
                aria-hidden="true"
                className="size-2 shrink-0 rounded-pill"
                style={{ backgroundColor: classColor(event.label) }}
              />
              <span className="shrink-0 text-ink">
                {event.label} #{event.globalId}
              </span>
              {/* La plaque **seulement quand elle est lue**. La plupart des
                  franchissements n'en ont pas — le serveur les émet avant la passe OCR
                  de la même image — et un « — » par ligne créerait une colonne de
                  tirets qui ferait passer l'exception pour la règle. La confiance va
                  dans l'infobulle : dans la ligne, elle doublerait la longueur du texte
                  utile pour une information qu'on ne consulte qu'en cas de doute. */}
              {event.plateText !== null && (
                <span
                  className="shrink-0 rounded-badge bg-elevated px-1.5 text-micro tabular tracking-wide text-ink"
                  title={plateTitle(event.plateText, event.plateTextScore, null)}
                >
                  {plateCell(event.plateText, null)}
                </span>
              )}
              {/* Le seul texte de longueur arbitraire de la ligne — l'utilisateur nomme
                  ses lignes — donc c'est lui qui cède quand la place manque. Sans cette
                  répartition, un quatrième élément fait déborder la ligne et le
                  `ms-auto` pousse le sens hors du conteneur. */}
              <span className="truncate text-ink-muted">{lineLabel(event.lineId, lineNames)}</span>
              <span className="ms-auto shrink-0 tabular text-ink-muted">
                {directionLabel(event.direction)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
