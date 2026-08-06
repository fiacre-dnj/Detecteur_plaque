/**
 * Le sélecteur de source : trois cartes, dont une zone de dépôt.
 *
 * Deux détails de glisser-déposer qui ne sont pas décoratifs :
 *
 * - `preventDefault()` sur **`dragover` autant que sur `drop`**. Sans le premier,
 *   le navigateur refuse le dépôt et **ouvre la vidéo dans l'onglet**, ce qui fait
 *   perdre l'application et tout son état. C'est l'oubli le plus courant.
 * - un compteur d'entrée/sortie plutôt qu'un booléen pour le surlignage :
 *   `dragleave` se déclenche en entrant dans un enfant, donc un booléen fait
 *   clignoter la bordure à chaque survol d'icône.
 */

import { Camera, FileVideo, MonitorPlay, Upload } from "lucide-react";
import { useCallback, useId, useRef, useState } from "react";

import {
  ACCEPT_ATTRIBUTE,
  hasAcceptedExtension,
  type SourceKind,
} from "../model/useMediaSource";

/**
 * Sources désactivées pour l'instant : le clip de démonstration et la caméra.
 *
 * Un drapeau explicite plutôt qu'une suppression des cartes. Les retirer
 * laisserait croire que l'application ne sait pas faire, alors qu'elle sait :
 * tout le chemin caméra — WebSocket, cadence, mise à l'échelle d'envoi, garde de
 * résolution — existe et est testé. Grisées **avec leur raison**, elles disent la
 * vérité : « pas maintenant », et non « pas possible ».
 *
 * Remettre l'une des deux en service est un `false` à passer à `true`.
 */
const DEMO_ENABLED = false;
const CAMERA_ENABLED = false;

/** Ce qu'on affiche à la place de l'aide, quand la source est mise de côté. */
const UNAVAILABLE_HINT = "Indisponible pour l'instant";

interface SourcePickerProps {
  /** Source active, pour marquer la carte correspondante. */
  activeKind: SourceKind | null;
  disabled: boolean;
  requestingCamera: boolean;
  onFile: (file: File) => void;
  onDemo: () => void;
  onCamera: () => void;
}

export function SourcePicker({
  activeKind,
  disabled,
  requestingCamera,
  onFile,
  onDemo,
  onCamera,
}: SourcePickerProps) {
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [dragDepth, setDragDepth] = useState(0);
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

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      setDragDepth(0);
      if (disabled) return;
      accept(event.dataTransfer.files[0]);
    },
    [accept, disabled],
  );

  return (
    <section aria-labelledby="source-title">
      <h2 id="source-title" className="label-micro mb-3">
        Source à analyser
      </h2>

      <div className="grid gap-3 sm:grid-cols-3">
        {/* ── Fichier : la carte est aussi la zone de dépôt ─────────────── */}
        <div
          onDragEnter={(event) => {
            event.preventDefault();
            setDragDepth((depth) => depth + 1);
          }}
          onDragOver={(event) => {
            // **Indispensable** : sans lui le navigateur ouvre la vidéo dans
            // l'onglet et l'application disparaît avec son état.
            event.preventDefault();
          }}
          onDragLeave={() => setDragDepth((depth) => Math.max(0, depth - 1))}
          onDrop={handleDrop}
          className={[
            "rounded-card transition-colors",
            dragDepth > 0 ? "ring-2 ring-accent" : "",
          ].join(" ")}
        >
          <label
            htmlFor={inputId}
            aria-current={activeKind === "file" ? "true" : undefined}
            className={[
              "flex h-full cursor-pointer flex-col rounded-card p-4 text-start transition-colors",
              activeKind === "file" ? "bg-elevated shadow-inset" : "bg-surface hover:bg-elevated",
              disabled ? "cursor-not-allowed opacity-60" : "",
            ].join(" ")}
          >
            {dragDepth > 0 ? (
              <Upload aria-hidden="true" className="size-5 text-accent" />
            ) : (
              <FileVideo aria-hidden="true" className="size-5 text-ink-dim" />
            )}
            <p className="mt-3 text-caption font-bold text-ink">Fichier vidéo</p>
            <p className="mt-0.5 text-small text-ink-dim">
              {dragDepth > 0 ? "Relâchez pour charger" : "Glissez un clip ou cliquez"}
            </p>
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
              // Réinitialisé pour que **rechoisir le même fichier** émette un
              // nouveau `change` : sans cela, recharger le fichier courant après
              // un « Fermer » ne fait rien.
              event.target.value = "";
            }}
          />
        </div>

        {/* ── Démonstration ─────────────────────────────────────────────── */}
        <SourceCard
          icon={MonitorPlay}
          label="Vidéo de démonstration"
          hint={DEMO_ENABLED ? "Un clip fourni pour essayer" : UNAVAILABLE_HINT}
          active={activeKind === "demo"}
          disabled={disabled || !DEMO_ENABLED}
          onClick={onDemo}
        />

        {/* ── Caméra ────────────────────────────────────────────────────── */}
        <SourceCard
          icon={Camera}
          label="Caméra"
          hint={
            !CAMERA_ENABLED
              ? UNAVAILABLE_HINT
              : requestingCamera
                ? "Autorisation en attente…"
                : "Comptage en direct"
          }
          active={activeKind === "camera"}
          disabled={disabled || requestingCamera || !CAMERA_ENABLED}
          onClick={onCamera}
        />
      </div>

      {rejected !== null && (
        <p role="alert" className="mt-3 text-small text-negative">
          {rejected}
        </p>
      )}

      {/* La conséquence d'ADR 0003, énoncée là où l'utilisateur choisit sa
          source — pas enfouie dans une page « à propos ». */}
      <p className="mt-3 text-small text-ink-dim">
        Les images sont envoyées au serveur, qui réalise l'analyse.
      </p>
    </section>
  );
}

interface SourceCardProps {
  icon: typeof Camera;
  label: string;
  hint: string;
  active: boolean;
  disabled: boolean;
  onClick: () => void;
}

function SourceCard({ icon: Icon, label, hint, active, disabled, onClick }: SourceCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-current={active ? "true" : undefined}
      className={[
        "rounded-card p-4 text-start transition-colors",
        active ? "bg-elevated shadow-inset" : "bg-surface hover:bg-elevated",
        "disabled:cursor-not-allowed disabled:opacity-60",
      ].join(" ")}
    >
      <Icon aria-hidden="true" className={active ? "size-5 text-accent" : "size-5 text-ink-dim"} />
      <p className="mt-3 text-caption font-bold text-ink">{label}</p>
      <p className="mt-0.5 text-small text-ink-dim">{hint}</p>
    </button>
  );
}
