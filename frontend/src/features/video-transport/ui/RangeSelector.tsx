/**
 * L'intervalle d'analyse, **dessiné sur le lecteur**.
 *
 * C'est le seul endroit où « de 00:34 à 05:00 » redevient une portion de vidéo
 * plutôt que deux nombres. La modale de lancement laisse saisir les bornes ; ici on
 * les *voit*, alignées sur la même largeur que la barre de position, donc à la même
 * échelle que la vidéo qu'on regarde. Deux champs `mm:ss` seuls obligeraient à
 * imaginer où ils tombent.
 *
 * **Ce composant ne connaît pas l'analyse.** Il rend un intervalle, en publie un
 * autre, et c'est tout : le studio décide de ce qu'il en fait. C'est ce qui lui
 * permet de vivre dans `video-transport` sans que cette feature ait à importer
 * quoi que ce soit de `analysis-job`.
 *
 * Trois décisions qui ne se devinent pas :
 *
 * - **les poignées sont deux `<input type="range">` superposés**, pas des `<div>`
 *   glissables. C'est ce qui donne le clavier et les annonces ARIA gratuitement ;
 *   la CSS qui leur rend les clics vit dans `index.css` (`.range-handle`), faute de
 *   pouvoir styler un pseudo-élément depuis une classe utilitaire ;
 * - **les bornes sont contraintes à l'écriture, jamais à l'affichage.** Une poignée
 *   qu'on empêche de dépasser en bornant son `max` se bloque *avant* d'arriver au
 *   contact, ce qui donne l'impression que le curseur colle. On la laisse aller
 *   partout et c'est `clampRange` qui décide — la valeur publiée peut donc pousser
 *   l'autre borne, comportement attendu d'un sélecteur d'intervalle ;
 * - **la tête de lecture est répétée ici**, en repère fin. Sans elle, on choisit ses
 *   bornes en regardant une barre et l'image en regardant l'autre.
 */

import { Scissors, X } from "lucide-react";

import {
  FULL_RANGE,
  clampRange,
  formatTimecode,
  isFullRange,
  rangeDurationMs,
  secondsToMs,
  type AnalysisRange,
} from "@/entities/analysis-range";

interface RangeSelectorProps {
  range: AnalysisRange;
  /** Durée de la vidéo, en secondes — telle que la balise la rapporte. */
  duration: number;
  /** Tête de lecture, en secondes : le repère qui relie les bornes à l'image. */
  currentTime: number;
  disabled: boolean;
  onChange: (range: AnalysisRange) => void;
}

export function RangeSelector({
  range,
  duration,
  currentTime,
  disabled,
  onChange,
}: RangeSelectorProps) {
  const durationMs = secondsToMs(duration);
  const endMs = range.endMs ?? durationMs;
  const full = isFullRange(range);

  /** Position en pourcentage de la largeur — l'unique conversion vers le dessin. */
  const percent = (ms: number): number =>
    durationMs > 0 ? Math.min(100, Math.max(0, (ms / durationMs) * 100)) : 0;

  const publish = (next: AnalysisRange): void => onChange(clampRange(next, durationMs));

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <Scissors aria-hidden="true" className="size-3.5 shrink-0 text-ink-dim" />
        <span className="label-micro shrink-0">Intervalle d'analyse</span>

        {/* Les chiffres **à côté** du rail et non dessous : ce sont eux qu'on
            relit après avoir lâché la poignée, et les chercher plus bas
            obligerait à quitter des yeux ce qu'on vient de régler. */}
        <span className="ms-auto text-caption text-ink-muted tabular">
          {full ? (
            "Toute la vidéo"
          ) : (
            <>
              {formatTimecode(range.startMs)} → {formatTimecode(endMs)}
              <span className="text-ink-dim">
                {" "}
                · {formatTimecode(rangeDurationMs(range, durationMs))}
              </span>
            </>
          )}
        </span>

        {/* Le retour en arrière, visible **seulement** quand il y a de quoi
            revenir : un bouton « effacer » permanent sur un intervalle vide se
            lit comme une action sans effet. */}
        {!full && (
          <button
            type="button"
            onClick={() => onChange(FULL_RANGE)}
            disabled={disabled}
            title="Analyser toute la vidéo"
            className="grid size-6 shrink-0 place-items-center rounded-input text-ink-dim transition-colors hover:bg-elevated hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
          >
            <X aria-hidden="true" className="size-3.5" />
            <span className="sr-only">Retirer l'intervalle et analyser toute la vidéo</span>
          </button>
        )}
      </div>

      <div className="relative h-5">
        {/* Le rail, en trois couches : le hors-intervalle éteint, la bande
            retenue en accent, la tête de lecture par-dessus. L'accent encode ici
            une donnée — ce qui sera analysé — donc il est à sa place (ADR 0004). */}
        <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-pill bg-line" />
        <div
          className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-pill bg-accent/60"
          style={{
            left: `${percent(range.startMs)}%`,
            width: `${Math.max(0, percent(endMs) - percent(range.startMs))}%`,
          }}
        />
        <div
          aria-hidden="true"
          className="absolute top-1/2 h-3.5 w-0.5 -translate-y-1/2 rounded-pill bg-ink"
          style={{ left: `${percent(secondsToMs(currentTime))}%` }}
        />

        <input
          type="range"
          className="range-handle"
          min={0}
          max={durationMs}
          step={100}
          value={range.startMs}
          disabled={disabled}
          aria-label="Début de l'intervalle analysé"
          aria-valuetext={formatTimecode(range.startMs)}
          onChange={(event) => publish({ ...range, startMs: Number(event.target.value) })}
        />
        <input
          type="range"
          className="range-handle"
          min={0}
          max={durationMs}
          step={100}
          value={endMs}
          disabled={disabled}
          aria-label="Fin de l'intervalle analysé"
          aria-valuetext={formatTimecode(endMs)}
          onChange={(event) => publish({ ...range, endMs: Number(event.target.value) })}
        />
      </div>
    </div>
  );
}
