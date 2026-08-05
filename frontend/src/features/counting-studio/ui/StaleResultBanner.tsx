/**
 * Le bandeau « résultat obsolète ».
 *
 * **Le problème qu'il résout.** L'utilisateur lance une analyse, obtient des
 * chiffres, puis déplace une ligne pour essayer autre chose. Les chiffres affichés
 * ne correspondent plus à la géométrie visible à l'écran, et **rien ne le signale**.
 * C'est le genre d'écart qu'on ne remarque qu'après avoir tiré une conclusion
 * fausse — et à ce moment-là, on ne sait plus lequel des deux états était le bon.
 *
 * Ambre et non rouge : ce n'est pas une erreur. Le résultat est valide, il décrit
 * simplement une autre géométrie. Le rouge est réservé aux échecs, et l'utiliser ici
 * apprendrait à ignorer le rouge.
 */

import { TriangleAlert } from "lucide-react";

interface StaleResultBannerProps {
  onRelaunch: () => void;
  canRelaunch: boolean;
}

export function StaleResultBanner({ onRelaunch, canRelaunch }: StaleResultBannerProps) {
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-3 rounded-card bg-warning/10 p-3 ring-1 ring-warning/40"
    >
      <TriangleAlert aria-hidden="true" className="size-4 shrink-0 text-warning" />
      <p className="min-w-0 flex-1 text-small text-ink-muted">
        La géométrie a changé depuis cette analyse : les chiffres ci-dessous
        décrivent le tracé précédent.
      </p>
      <button
        type="button"
        onClick={onRelaunch}
        disabled={!canRelaunch}
        className="rounded-input px-3 py-1 text-small font-bold text-warning underline transition-colors hover:bg-warning/10 disabled:cursor-not-allowed disabled:opacity-50"
      >
        Relancer l'analyse
      </button>
    </div>
  );
}

/**
 * Le bandeau de fin de lecture.
 *
 * Il dit explicitement que **les statistiques sont figées** : sans cela, un
 * utilisateur qui relance la lecture s'attend à voir les compteurs repartir de zéro,
 * et leur stabilité lui paraît un bug. L'infobulle du bouton le précise encore.
 */
export function PlaybackEndedBanner({ onReplay }: { onReplay: () => void }) {
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-3 rounded-card bg-surface-2 p-3"
    >
      <p className="min-w-0 flex-1 text-small text-ink-muted">
        Analyse terminée — la vidéo a été lue en intégralité. Les statistiques
        ci-dessous sont figées.
      </p>
      <button
        type="button"
        onClick={onReplay}
        title="Les compteurs suivent la tête de lecture : ils ne repartent pas de zéro."
        className="rounded-input px-3 py-1 text-small font-bold text-ink-muted underline transition-colors hover:text-ink"
      >
        Revoir la vidéo
      </button>
    </div>
  );
}
