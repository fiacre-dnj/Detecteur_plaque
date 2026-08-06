/**
 * La barre de transport — **maison, jamais `controls`**.
 *
 * La raison n'est pas esthétique : la barre native du navigateur se dessine en
 * **bas de l'élément vidéo**, c'est-à-dire exactement sur la zone où l'utilisateur
 * trace ses lignes de comptage. Elle capterait les clics destinés au canvas, et
 * aucun `z-index` n'y change quoi que ce soit — elle vit dans le shadow DOM du
 * navigateur.
 *
 * La timeline est **masquée quand la durée n'est pas exploitable** (caméra, clip
 * de `MediaRecorder`) : un curseur sur une durée infinie n'a aucune position
 * significative, et en afficher un serait mentir sur ce qu'on peut faire.
 */

import {
  ChevronFirst,
  ChevronLast,
  Pause,
  Play,
  RotateCcw,
  SkipBack,
  SkipForward,
} from "lucide-react";

import { PLAYBACK_RATES, formatRate, formatTime, hasSeekableDuration } from "../model/formatTime";
import type { VideoTransport } from "../model/useVideoTransport";

interface TransportBarProps {
  transport: VideoTransport;
  /** Faux pour un flux caméra : lecture et déplacement n'y ont pas de sens. */
  seekable?: boolean;
  disabled?: boolean;
}

export function TransportBar({ transport, seekable = true, disabled = false }: TransportBarProps) {
  const showTimeline = seekable && hasSeekableDuration(transport.duration);
  const inert = disabled;

  return (
    <div className="flex flex-col gap-2 rounded-card bg-surface-2 p-3">
      {showTimeline && (
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={0}
            max={transport.duration}
            step={0.01}
            value={transport.currentTime}
            disabled={inert}
            aria-label="Position dans la vidéo"
            onChange={(event) => transport.seek(Number(event.target.value))}
            className="h-1 w-full cursor-pointer appearance-none rounded-pill bg-line accent-accent disabled:cursor-not-allowed"
          />
          {/* `<time>` porte `tabular-nums` via `index.css` : sans cela, la
              position saute latéralement à chaque changement de chiffre. */}
          <time className="shrink-0 text-small text-ink-muted">
            {formatTime(transport.currentTime)} / {formatTime(transport.duration)}
          </time>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1">
        <IconButton
          label={transport.playing ? "Pause" : "Lecture"}
          onClick={transport.toggle}
          disabled={inert}
          primary
        >
          {transport.playing ? <Pause className="size-4" /> : <Play className="size-4" />}
        </IconButton>

        {seekable && (
          <>
            <IconButton
              label="Reculer de 10 secondes"
              onClick={() => transport.skip(-10)}
              disabled={inert}
            >
              <SkipBack className="size-4" />
            </IconButton>
            <IconButton
              label="Reculer d'une seconde"
              onClick={() => transport.skip(-1)}
              disabled={inert}
            >
              <ChevronFirst className="size-4" />
            </IconButton>
            <IconButton
              label="Image précédente"
              onClick={() => transport.stepFrame(-1)}
              disabled={inert}
            >
              <span aria-hidden="true" className="text-badge font-bold">
                −1i
              </span>
            </IconButton>
            <IconButton
              label="Image suivante"
              onClick={() => transport.stepFrame(1)}
              disabled={inert}
            >
              <span aria-hidden="true" className="text-badge font-bold">
                +1i
              </span>
            </IconButton>
            <IconButton
              label="Avancer d'une seconde"
              onClick={() => transport.skip(1)}
              disabled={inert}
            >
              <ChevronLast className="size-4" />
            </IconButton>
            <IconButton
              label="Avancer de 10 secondes"
              onClick={() => transport.skip(10)}
              disabled={inert}
            >
              <SkipForward className="size-4" />
            </IconButton>
            <IconButton
              label="Revoir depuis le début"
              onClick={transport.restart}
              disabled={inert}
            >
              <RotateCcw className="size-4" />
            </IconButton>
          </>
        )}

        {seekable && (
          <label className="ms-auto flex items-center gap-2 text-small text-ink-dim">
            Vitesse
            <select
              value={transport.rate}
              disabled={inert}
              onChange={(event) => transport.setRate(Number(event.target.value))}
              className="rounded-input bg-elevated px-2 py-1 text-small text-ink disabled:cursor-not-allowed"
            >
              {PLAYBACK_RATES.map((rate) => (
                <option key={rate} value={rate}>
                  {formatRate(rate)}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {transport.error !== null && (
        <p role="alert" className="text-small text-negative">
          {transport.error}
        </p>
      )}
    </div>
  );
}

interface IconButtonProps {
  label: string;
  onClick: () => void;
  disabled: boolean;
  primary?: boolean;
  children: React.ReactNode;
}

/**
 * Bouton icône avec un nom accessible.
 *
 * `aria-label` **et** `title` : le premier pour les lecteurs d'écran, le second
 * pour l'infobulle à la souris. Une icône seule sans nom accessible rend la barre
 * inutilisable au clavier comme au lecteur d'écran.
 */
function IconButton({ label, onClick, disabled, primary = false, children }: IconButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={[
        "grid size-8 place-items-center rounded-input transition-colors",
        primary
          ? "bg-accent text-accent-ink hover:brightness-110"
          : "text-ink-muted hover:bg-elevated hover:text-ink",
        "disabled:cursor-not-allowed disabled:opacity-50",
      ].join(" ")}
    >
      {children}
    </button>
  );
}
