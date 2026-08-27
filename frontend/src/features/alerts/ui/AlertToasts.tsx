/**
 * La pile d'alertes **pendant** que ça tourne, posée sur la scène.
 *
 * Elle existe parce qu'une analyse se regarde : au moment où un véhicule remonte
 * une ligne à sens unique, l'écran montre la vidéo, pas le bas de page. Une alerte
 * qui n'apparaît que dans une section qu'il faut aller chercher n'alerte personne.
 *
 * Quatre décisions qui ne se devinent pas :
 *
 * - **trois cartes au plus, et un compteur pour le reste.** Un carrefour chargé
 *   peut produire dix infractions en vingt secondes ; empiler dix cartes couvrirait
 *   la vidéo qu'elles servent à faire regarder ;
 * - **aucune disparition automatique.** Une alerte qui s'efface toute seule oblige
 *   à surveiller l'écran en continu — exactement ce qu'on cherchait à éviter. Elle
 *   se ferme d'un clic, ou reste ;
 * - **`aria-live="polite"` et jamais `assertive`.** Une alerte n'a pas à couper la
 *   parole à un lecteur d'écran ; sur un carrefour chargé, `assertive` ferait de la
 *   synthèse vocale un métronome. C'est la même raison qui garde la rangée de
 *   chiffres techniques hors des régions vivantes ;
 * - **hors du canvas, et marquée `KEEP_PANELS_OPEN_ATTR` par son conteneur.** La
 *   scène est une surface de tracé : y poser des boutons demanderait au canvas de
 *   partager ses événements de pointeur.
 */

import { X } from "lucide-react";
import { useMemo, useState } from "react";

import type { CountingLine } from "@/shared/api/contracts";

import type { Alert } from "../model/alerts";
import { AlertCard } from "./AlertCard";

/** Au-delà, les plus anciennes sont comptées plutôt qu'empilées. */
const VISIBLE = 3;

interface AlertToastsProps {
  alerts: readonly Alert[];
  lines: readonly CountingLine[];
  onSeek?: ((timestampMs: number) => void) | undefined;
}

export function AlertToasts({ alerts, lines, onSeek }: AlertToastsProps) {
  const [dismissed, setDismissed] = useState<readonly string[]>([]);

  const pending = useMemo(
    () => alerts.filter((alert) => !dismissed.includes(alert.key)),
    [alerts, dismissed],
  );

  if (pending.length === 0) return null;

  const shown = pending.slice(0, VISIBLE);
  const hidden = pending.length - shown.length;

  return (
    <div
      // `pointer-events-none` sur le conteneur et `auto` sur les cartes : la bande
      // vide entre deux alertes ne doit pas capter un clic destiné à la géométrie
      // qu'on est en train de tracer dessous.
      // **En bas à droite de la scène**, et pas en haut : le coin haut-gauche porte
      // le nom du fichier et le coin haut-droit les dimensions et la cadence. Trois
      // incrustations dans le même angle, dont une qui grandit, finiraient par se
      // recouvrir — et c'est l'alerte, la seule qui apparaisse par surprise, qui
      // passerait dessous.
      className="pointer-events-none absolute bottom-3 end-3 z-20 flex w-64 max-w-[calc(100%-1.5rem)] flex-col-reverse gap-2"
      aria-live="polite"
      aria-label="Alertes de l'analyse en cours"
    >
      {shown.map((alert) => (
        <div key={alert.key} className="pointer-events-auto relative shadow-dialog">
          <AlertCard alert={alert} lines={lines} onSeek={onSeek} compact />
          <button
            type="button"
            onClick={() => setDismissed((previous) => [...previous, alert.key])}
            aria-label="Masquer cette alerte"
            className="absolute end-1 top-1 grid size-5 place-items-center rounded-input text-ink-dim transition-colors hover:bg-base hover:text-ink"
          >
            <X aria-hidden="true" className="size-3" />
          </button>
        </div>
      ))}
      {hidden > 0 && (
        <p className="pointer-events-auto rounded-card bg-surface/90 px-2 py-1 text-center text-micro text-ink-muted shadow-card">
          + {hidden} autre{hidden > 1 ? "s" : ""} — voir la section Alertes
        </p>
      )}
    </div>
  );
}
