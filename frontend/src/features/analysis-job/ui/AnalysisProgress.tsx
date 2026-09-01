/**
 * L'anneau de progression de la barre — le %, puis le détail en petit.
 *
 * Il tient la place d'une barre horizontale qui aurait fait toute la largeur de la
 * rangée : sur une barre où chaque pixel est disputé, un anneau de 22 px dit la même
 * chose.
 *
 * **Il vit à gauche, juste après « Annuler »**, et non à l'autre bout avec les chiffres
 * — où il a été posé d'abord. Deux raisons : il répond au bouton qu'on vient de
 * cliquer, et les séparer obligeait à traverser toute la barre du regard pour vérifier
 * qu'un lancement avait pris ; et il ne dit pas la même chose que ses voisins de
 * droite — celui-ci dit **où en est l'analyse**, les autres **comment elle se passe**.
 *
 * Cinq points qui ne se devinent pas :
 *
 * - **`role="progressbar"` avec `aria-valuenow`, et aucun `aria-live`.** Un
 *   pourcentage qui change à chaque image ferait d'un lecteur d'écran un métronome —
 *   la raison qui prive déjà la rangée de chiffres et la chronologie d'annonce
 *   vivante. Le nom accessible porte la phase, donc « Analyse en cours » est annoncé
 *   quand on l'atteint ;
 * - **le détail ne porte que le compte d'images.** La cadence y a figuré, puis en est
 *   partie : la rangée de chiffres qui suit affiche déjà « Cadence serveur », et la
 *   répéter coûtait la largeur d'une barre qui doit tenir sur une ligne ;
 * - **le libellé de phase s'écrit à l'écran dès qu'il n'y a pas de compteur.** Il n'y
 *   figurait d'abord jamais, au motif qu'« Analyse en cours » à côté d'un anneau qui
 *   tourne et d'un compteur qui monte n'ajoute rien. C'est vrai — mais **seulement
 *   quand le compteur existe**. En file d'attente et pendant la préparation, il n'y a
 *   ni compteur ni mouvement : l'anneau montrait « 0 % » et rien d'autre, ce qui est
 *   exactement la lecture « analyse plantée » que `analysisProgress` existe pour
 *   éviter. Le défaut a été rapporté tel quel — « je n'arrive pas à lancer » sur une
 *   analyse qui tournait ;
 * - **suspendue, l'anneau se fige et passe en `warning`** — c'est le seul état où la
 *   teinte change, et le seul où le pourcentage cesse de bouger. Sans ce signal, une
 *   analyse suspendue est visuellement identique à une analyse très lente ;
 * - **la préparation n'a pas de compteur d'images** mais garde son anneau à zéro :
 *   c'est `analysisProgress` qui décide, pas ce composant.
 */

import type { AnalysisProgress as Progress } from "../model/analysisProgress";

/** Rayon et circonférence de l'anneau, calculés une fois. */
const RADIUS = 9;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

interface AnalysisProgressProps {
  progress: Progress;
}

export function AnalysisProgress({ progress }: AnalysisProgressProps) {
  if (!progress.active) return null;

  const percent = Math.round(progress.ratio * 100);
  const paused = progress.phase === "paused";
  const tone = paused ? "text-warning" : "text-accent";

  return (
    <div
      // `min-w-0` et **pas** `shrink-0` : quand la barre se resserre, c'est le détail
      // qui doit se tronquer, jamais la rangée qui doit passer sur deux lignes. Seul
      // l'anneau est incompressible — le pourcentage est ce qu'on vient lire.
      className="flex min-w-0 items-center gap-2"
      title={progress.hint ?? `${progress.label} — ${progress.detail ?? ""}`}
    >
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-label={progress.label}
        className="relative grid size-[22px] shrink-0 place-items-center"
      >
        <svg viewBox="0 0 24 24" className={`size-full -rotate-90 ${tone}`} aria-hidden="true">
          <circle cx="12" cy="12" r={RADIUS} fill="none" stroke="currentColor" strokeWidth="2.5" className="opacity-20" />
          <circle
            cx="12"
            cy="12"
            r={RADIUS}
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            // `strokeDashoffset` et non un arc calculé : un arc en `path` demanderait
            // de gérer le cas du cercle complet, où le point de départ et le point
            // d'arrivée se confondent et où le tracé disparaît.
            strokeDashoffset={CIRCUMFERENCE * (1 - Math.min(1, Math.max(0, progress.ratio)))}
            className="transition-[stroke-dashoffset] duration-300"
          />
        </svg>
      </div>

      {/* `text-center` : le pourcentage est court et la ligne du dessous longue, donc
          aligné à gauche il flottait au-dessus d'un vide. Centré, les deux se lisent
          comme un seul bloc — et c'est le pourcentage qu'on vient chercher, donc c'est
          lui qui doit tomber au milieu de ce qui le porte. */}
      <div className="min-w-0 text-center leading-tight">
        <p className={`text-small font-bold tabular ${paused ? "text-warning" : "text-ink"}`}>
          {percent} %
        </p>
        {/* Le compteur d'images s'il existe, sinon le nom de la phase — jamais rien.
            Une ligne vide sous un « 0 % » immobile ne dit pas qu'on attend son tour. */}
        <p className="truncate text-micro text-ink-dim tabular">
          {progress.detail ?? progress.label}
        </p>
      </div>
    </div>
  );
}
