/**
 * Entretient les flashs de ligne, et **seulement tant qu'il en reste un**.
 *
 * Une boucle `requestAnimationFrame` permanente pour une animation qui se
 * déclenche trois fois par minute réveillerait le processeur soixante fois par
 * seconde pour dessiner exactement la même image. Ici la boucle démarre à la
 * première salve et s'arrête d'elle-même à l'extinction du dernier flash.
 */

import { useEffect, useRef, useState } from "react";

import type { CrossingEvent } from "@/shared/api/contracts";

import {
  FLASH_DURATION_MS,
  activeFlashes,
  startFlashes,
  type FlashStart,
  type LineFlash,
} from "./lineFlashes";

const NONE: ReadonlyMap<string, LineFlash> = new Map();

/**
 * @param crossings Franchissements de la salve courante. Chaque **nouvelle**
 *   référence de tableau déclenche des flashs : le hook ne compare pas les
 *   contenus, parce qu'un même véhicule peut légitimement franchir la même ligne
 *   deux fois — un aller-retour est deux événements, pas un doublon.
 */
export function useLineFlashes(
  crossings: readonly CrossingEvent[],
): ReadonlyMap<string, LineFlash> {
  const [flashes, setFlashes] = useState<ReadonlyMap<string, LineFlash>>(NONE);
  const starts = useRef<FlashStart[]>([]);
  const frame = useRef<number | null>(null);

  useEffect(() => {
    if (crossings.length === 0) return;

    const now = performance.now();
    // Les flashs de la salve précédente encore vivants sont conservés : deux
    // lignes franchies coup sur coup doivent clignoter toutes les deux.
    const fresh = startFlashes(crossings, now);
    const freshIds = new Set(fresh.map((start) => start.lineId));
    starts.current = [
      ...starts.current.filter(
        (start) => !freshIds.has(start.lineId) && now - start.startedAt < FLASH_DURATION_MS,
      ),
      ...fresh,
    ];

    const tick = (): void => {
      const at = performance.now();
      const active = activeFlashes(starts.current, at);
      setFlashes(active.size === 0 ? NONE : active);
      if (active.size === 0) {
        starts.current = [];
        frame.current = null;
        return;
      }
      frame.current = requestAnimationFrame(tick);
    };

    // Une seule boucle, même si trois salves arrivent pendant qu'elle tourne.
    if (frame.current === null) frame.current = requestAnimationFrame(tick);
  }, [crossings]);

  // La boucle est coupée au démontage : un `requestAnimationFrame` orphelin
  // appellerait `setFlashes` sur un composant démonté.
  useEffect(
    () => () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      frame.current = null;
    },
    [],
  );

  return flashes;
}
