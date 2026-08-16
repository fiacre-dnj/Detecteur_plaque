/**
 * Le choix de la source : **un bouton d'import**, posé dans la barre du studio.
 *
 * C'étaient trois cartes en pleine largeur au-dessus de la vidéo. Deux d'entre elles
 * — le clip de démonstration et la caméra — étaient désactivées, et le sont depuis
 * assez longtemps pour que leur place ne se justifie plus : elles occupaient les deux
 * tiers d'un bandeau permanent pour annoncer « indisponible ». Elles sont retirées de
 * l'écran, **pas du code** : tout le chemin caméra — WebSocket, cadence, mise à
 * l'échelle d'envoi, garde de résolution — existe, est testé, et attend une porte
 * d'entrée. Les remettre est un composant à rebrancher, pas une fonctionnalité à
 * réécrire.
 *
 * Deux détails de glisser-déposer qui ne sont pas décoratifs, et qui survivent au
 * changement de forme :
 *
 * - `preventDefault()` sur **`dragover` autant que sur `drop`**. Sans le premier,
 *   le navigateur refuse le dépôt et **ouvre la vidéo dans l'onglet**, ce qui fait
 *   perdre l'application et tout son état. C'est l'oubli le plus courant.
 * - un compteur d'entrée/sortie plutôt qu'un booléen pour le surlignage :
 *   `dragleave` se déclenche en entrant dans un enfant, donc un booléen fait
 *   clignoter la bordure à chaque survol d'icône.
 *
 * La zone de dépôt, elle, **s'étend désormais à la scène** (`DropZone`) : viser un
 * bouton de barre avec un fichier serait plus difficile que viser la grande surface
 * noire juste en dessous.
 */

import { FileVideo, Upload } from "lucide-react";
import { useCallback, useId, useRef, useState, type ReactNode } from "react";

import { ACCEPT_ATTRIBUTE, hasAcceptedExtension } from "../model/useMediaSource";

interface SourcePickerProps {
  /** Nom de la source active, affiché à côté du bouton. `null` si aucune. */
  activeLabel: string | null;
  disabled: boolean;
  onFile: (file: File) => void;
}

export function SourcePicker({ activeLabel, disabled, onFile }: SourcePickerProps) {
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [rejected, setRejected] = useState<string | null>(null);

  const accept = useCallback(
    (file: File | undefined) => {
      if (file === undefined) return;
      if (!hasAcceptedExtension(file.name)) {
        // Le nom du fichier refusé est cité : « format non supporté » sans dire
        // lequel oblige l'utilisateur à deviner lequel de ses fichiers pose
        // problème.
        setRejected(`« ${file.name} » n'est pas une vidéo reconnue (${ACCEPT_ATTRIBUTE}).`);
        return;
      }
      setRejected(null);
      onFile(file);
    },
    [onFile],
  );

  return (
    <>
      <label
        htmlFor={inputId}
        className={[
          "label-caps inline-flex h-10 shrink-0 items-center gap-2 rounded-pill px-5",
          "bg-accent text-accent-ink transition-[filter] hover:brightness-110",
          disabled ? "pointer-events-none opacity-45" : "cursor-pointer",
        ].join(" ")}
      >
        <Upload aria-hidden="true" className="size-4" />
        {activeLabel === null ? "Importer une vidéo" : "Changer de vidéo"}
      </label>
      <input
        ref={input}
        id={inputId}
        type="file"
        accept={ACCEPT_ATTRIBUTE}
        disabled={disabled}
        className="sr-only"
        onChange={(event) => {
          accept(event.target.files?.[0]);
          // Réinitialisé pour que **rechoisir le même fichier** émette un nouveau
          // `change` : sans cela, recharger le fichier courant après un « Fermer »
          // ne fait rien.
          event.target.value = "";
        }}
      />

      {rejected !== null && (
        <p role="alert" className="w-full text-small text-negative">
          {rejected}
        </p>
      )}
    </>
  );
}

/**
 * Le nom du fichier actif, à part du bouton d'import.
 *
 * Posé **tout à droite** de la barre du studio (`SettingsPanels.trailing`) plutôt
 * qu'à côté du bouton : une fois la vidéo choisie, l'import redevient un geste
 * occasionnel — « Changer de vidéo » — alors que les trois tiroirs de réglages
 * sont ce qu'on ouvre le plus souvent juste après, et méritaient la place qui
 * suit immédiatement le bouton.
 */
export function SourceLabel({ label }: { label: string }) {
  return (
    <span
      className="inline-flex min-w-0 items-center gap-1.5 text-small text-ink-muted"
      title={label}
    >
      <FileVideo aria-hidden="true" className="size-4 shrink-0 text-ink-dim" />
      <span className="max-w-48 truncate">{label}</span>
    </span>
  );
}

interface DropZoneProps {
  disabled: boolean;
  onFile: (file: File) => void;
  children: ReactNode;
}

/**
 * Enveloppe la scène pour en faire la cible de dépôt.
 *
 * Séparée du bouton parce que les deux ont des tailles opposées : le bouton doit être
 * compact dans la barre, la cible de dépôt doit être la plus grande surface de
 * l'écran. Les fondre en un seul élément obligerait à choisir, et viser une pilule de
 * 40 px de haut avec un fichier est un geste qu'on rate.
 */
export function DropZone({ disabled, onFile, children }: DropZoneProps) {
  const [dragDepth, setDragDepth] = useState(0);
  const [rejected, setRejected] = useState<string | null>(null);

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      setDragDepth(0);
      if (disabled) return;
      const file = event.dataTransfer.files[0];
      if (file === undefined) return;
      if (!hasAcceptedExtension(file.name)) {
        setRejected(`« ${file.name} » n'est pas une vidéo reconnue (${ACCEPT_ATTRIBUTE}).`);
        return;
      }
      setRejected(null);
      onFile(file);
    },
    [disabled, onFile],
  );

  return (
    <div
      onDragEnter={(event) => {
        event.preventDefault();
        setDragDepth((depth) => depth + 1);
      }}
      onDragOver={(event) => {
        // **Indispensable** : sans lui le navigateur ouvre la vidéo dans l'onglet
        // et l'application disparaît avec son état.
        event.preventDefault();
      }}
      onDragLeave={() => setDragDepth((depth) => Math.max(0, depth - 1))}
      onDrop={handleDrop}
      className={[
        "relative rounded-section transition-shadow",
        dragDepth > 0 ? "ring-2 ring-accent" : "",
      ].join(" ")}
    >
      {children}

      {dragDepth > 0 && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center rounded-section bg-base/70">
          <p className="label-caps flex items-center gap-2 text-accent">
            <Upload aria-hidden="true" className="size-5" />
            Relâchez pour charger
          </p>
        </div>
      )}

      {rejected !== null && (
        <p role="alert" className="mt-2 text-small text-negative">
          {rejected}
        </p>
      )}
    </div>
  );
}
