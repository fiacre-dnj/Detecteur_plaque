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
 *
 * **Les deux rails ont exactement la même longueur**, et ce n'est pas une question
 * de goût : la barre de position et l'intervalle d'analyse décrivent la même vidéo,
 * donc une borne posée à mi-chemin de l'un doit tomber à mi-chemin de l'autre. Le
 * temps courant était écrit *à côté* du curseur de position, ce qui raccourcissait
 * ce rail-là de la largeur de « 03:26 / 03:26 » : les deux échelles divergeaient
 * d'une centaine de pixels, et l'intervalle se lisait donc décalé vers la fin. Les
 * deux chiffres sont désormais en **entête de leur rail**, ce qui rend les deux
 * pistes pleine largeur et fait de « position » et « intervalle » deux lignes du
 * même tableau.
 *
 * La rangée du bas porte, dans cet ordre : le transport, la vitesse de lecture,
 * puis — à l'extrémité (`actions`) — ce que l'écran hôte veut y poser. Le studio y
 * met « Lancer l'analyse » et « Fermer » : ces boutons vivaient dans la colonne des
 * résultats, à un écran de défilement du lecteur qu'on vient de régler.
 */

import {
  ChevronFirst,
  ChevronLast,
  Film,
  Pause,
  Play,
  RotateCcw,
  SkipBack,
  SkipForward,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import type { AnalysisRange } from "@/entities/analysis-range";

import { PLAYBACK_RATES, formatRate, formatTime, hasSeekableDuration } from "../model/formatTime";
import { useVideoTransport } from "../model/useVideoTransport";
import { RangeSelector } from "./RangeSelector";

interface TransportBarProps {
  /**
   * L'élément vidéo à piloter, `null` avant son montage.
   *
   * **La barre appelle `useVideoTransport` elle-même**, plutôt que de recevoir un
   * `transport` déjà construit. Le hook miroite `currentTime` à ~60 Hz pendant la
   * lecture ; tant que l'appel vivait dans `StudioPage`, ces 60 mises à jour par
   * seconde re-rendaient tout l'écran — `GeometryCanvas` compris — et l'édition de
   * géométrie devenait saccadée dès qu'on lisait la vidéo. L'en-tête du hook
   * affirmait déjà que « seul le composant de transport consomme » cet état ;
   * c'est désormais vrai.
   *
   * La **référence** et non l'élément : un `ref` ne provoque pas de rendu en se
   * remplissant, donc passer `ref.current` ferait dépendre l'abonnement d'un rendu
   * ultérieur qui n'est garanti par rien. Le `useEffect` ci-dessous relit la
   * référence au montage, quand la balise existe forcément.
   */
  videoRef: React.RefObject<HTMLVideoElement | null>;
  /** Faux pour un flux caméra : lecture et déplacement n'y ont pas de sens. */
  seekable?: boolean;
  disabled?: boolean;
  /** Fin de lecture — le studio y affiche son bandeau de relecture. */
  onEnded?: () => void;
  /**
   * L'intervalle qui sera analysé, dessiné sous la barre de position.
   *
   * `undefined` (avec `onRangeChange`) masque le sélecteur : le direct n'a pas
   * d'intervalle à choisir, et un rail inerte y annoncerait un réglage inexistant.
   */
  range?: AnalysisRange | undefined;
  onRangeChange?: ((range: AnalysisRange) => void) | undefined;
  /**
   * Grise le **sélecteur d'intervalle** seul, sans figer la lecture.
   *
   * Distinct de `disabled`, et la distinction a un sens précis : pendant une
   * analyse, se déplacer dans la vidéo reste utile — on regarde l'aperçu — mais
   * déplacer les bornes ne l'est plus, elles sont déjà parties au serveur. Les
   * confondre interdirait la lecture ou laisserait croire qu'on peut encore
   * changer la fenêtre en cours de route.
   */
  rangeDisabled?: boolean;
  /**
   * Contenu posé à l'**extrémité** de la rangée de commandes (`ms-auto`).
   *
   * C'est là que le studio met « Lancer l'analyse » et « Fermer » : l'action qui
   * suit le réglage du lecteur, à l'endroit où on vient de le régler. Un
   * emplacement plutôt qu'un import : `video-transport` ne connaît ni l'analyse ni
   * la source — même règle que le `leading` de la barre de réglages.
   *
   * Ces boutons portent **leur propre** état désactivé et ne suivent donc pas
   * `disabled` : « Lancer » dépend de la géométrie et du serveur, pas de la
   * lecture, et griser « Fermer » pendant une analyse est une décision de l'hôte.
   */
  actions?: ReactNode;
}

export function TransportBar({
  videoRef,
  seekable = true,
  disabled = false,
  onEnded,
  range,
  onRangeChange,
  rangeDisabled = false,
  actions,
}: TransportBarProps) {
  /**
   * L'élément, une fois monté.
   *
   * Un état et non `videoRef.current` lu au rendu : remplir un `ref` ne déclenche
   * aucun rendu, donc la barre resterait branchée sur `null` jusqu'à ce qu'autre
   * chose la re-rende. Un effet au montage lit la référence quand la balise
   * existe, et le rendu qui s'ensuit abonne le transport pour de bon.
   */
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  useEffect(() => setVideo(videoRef.current), [videoRef]);

  const transport = useVideoTransport(video, onEnded);
  const showTimeline = seekable && hasSeekableDuration(transport.duration);
  const inert = disabled;

  return (
    <div className="flex flex-col gap-2 rounded-card bg-surface-2 p-3">
      {showTimeline && (
        <div className="space-y-1.5">
          {/* L'entête du rail, calquée sur celle de l'intervalle juste dessous :
              repère à gauche, chiffre à droite. Le temps courant était écrit à
              côté du curseur, où il **raccourcissait le rail** — voir la
              docstring du fichier. */}
          <div className="flex items-center gap-2">
            <Film aria-hidden="true" className="size-3.5 shrink-0 text-ink-dim" />
            <span className="label-micro shrink-0">Lecture</span>
            {/* `<time>` porte `tabular-nums` via `index.css` : sans cela, la
                position saute latéralement à chaque changement de chiffre. */}
            <time className="ms-auto shrink-0 text-caption text-ink-muted">
              {formatTime(transport.currentTime)} / {formatTime(transport.duration)}
            </time>
          </div>

          {/* Pleine largeur, exactement comme le rail de l'intervalle : c'est
              cette égalité qui fait qu'une borne se lit comme un endroit de la
              vidéo et non comme un pourcentage abstrait. */}
          <input
            type="range"
            min={0}
            max={transport.duration}
            step={0.01}
            value={transport.currentTime}
            disabled={inert}
            aria-label="Position dans la vidéo"
            onChange={(event) => transport.seek(Number(event.target.value))}
            className="h-1.5 w-full cursor-pointer appearance-none rounded-pill bg-line accent-accent disabled:cursor-not-allowed"
          />
        </div>
      )}

      {/* Le sélecteur d'intervalle **sous** la barre de position, pas ailleurs :
          les deux partagent la même largeur donc la même échelle, et c'est cet
          alignement qui fait qu'une borne se lit comme un endroit de la vidéo
          plutôt que comme un nombre. Il suit `showTimeline` pour la même raison
          qu'elle existe : sans durée exploitable, une borne n'a aucune position. */}
      {showTimeline && range !== undefined && onRangeChange !== undefined && (
        <RangeSelector
          range={range}
          duration={transport.duration}
          currentTime={transport.currentTime}
          disabled={inert || rangeDisabled}
          onChange={onRangeChange}
        />
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

        {/* La vitesse **contre les boutons de transport**, plus à l'extrémité de la
            rangée : c'est un réglage de lecture, sa place est dans le groupe qui
            lit. L'extrémité revient à l'action qui suit — `actions`. */}
        {seekable && (
          <label className="ms-2 flex items-center gap-2 text-small text-ink-dim">
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

        {actions !== undefined && (
          <div className="ms-auto flex flex-wrap items-center gap-2">{actions}</div>
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
