/**
 * Une capture, ou le repère muet qui la remplace.
 *
 * **Extrait de `SnapshotDialog` parce que deux modales l'affichent** — celle d'une
 * capture et celle qui compare deux véhicules — et que le repli « purgée » ne doit
 * exister qu'à un endroit. Deux copies finiraient par diverger sur la phrase, et
 * l'écart serait de la pire espèce : un état normal présenté comme une panne dans
 * une modale et pas dans l'autre.
 *
 * `onError` plutôt qu'une vérification préalable : la seule façon de savoir qu'une
 * capture a été purgée est de la demander. Un 409 est le cas **normal** après le TTL
 * de la vidéo — les captures partent avec elle, ce sont des plaques et des visages —
 * et une icône barrée le dit mieux que l'image cassée du navigateur.
 */

import { ImageOff } from "lucide-react";
import { useState } from "react";

/** Hauteur du cadre. `tall` pour un véhicule, le défaut pour une plaque. */
export interface SnapshotFrameProps {
  src: string;
  alt: string;
  tall?: boolean;
}

export function SnapshotFrame({ src, alt, tall = false }: SnapshotFrameProps) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <p
        className={`grid place-items-center gap-1 rounded-card bg-surface-2 p-3 text-center text-micro text-ink-dim ${
          tall ? "h-56" : "h-20"
        }`}
      >
        <ImageOff aria-hidden="true" className="size-5" />
        Capture purgée — elle est effacée en même temps que la vidéo.
      </p>
    );
  }

  return (
    <img
      src={src}
      alt={alt}
      // `contain` et non `cover` : une capture est une preuve, la rogner pour
      // remplir un cadre en retirerait justement ce qu'on vient regarder.
      className={`w-full rounded-card bg-base object-contain ${tall ? "max-h-72" : "max-h-24"}`}
      onError={() => setFailed(true)}
    />
  );
}
