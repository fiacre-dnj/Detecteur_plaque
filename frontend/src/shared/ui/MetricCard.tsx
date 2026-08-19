/**
 * Carte de synthèse — un chiffre, son libellé, sa précision.
 *
 * `aria-live="polite"` : ces chiffres changent pendant une analyse, et un
 * lecteur d'écran doit l'annoncer sans interrompre ce qu'il est en train de
 * lire.
 *
 * **Deux tailles, et l'écart est une hiérarchie, pas une économie de place.** La
 * Répartition par type de véhicule vit désormais dans la même grille que les
 * chiffres de tête du carrefour ; rendues à l'identique, neuf cartes de même poids
 * ne diraient plus laquelle répond à la question qu'on se pose en arrivant.
 */

import type { ReactNode } from "react";

interface MetricCardProps {
  label: string;
  value: string | number;
  /** Précision sous le chiffre : unité, décomposition, mise en garde. */
  hint?: string;
  icon?: ReactNode;
  /** Vrai pendant le chargement : affiche un squelette **à la forme finale**. */
  loading?: boolean;
  /**
   * `md` (défaut) pour un chiffre de tête, `sm` pour un chiffre de détail.
   *
   * `sm` ne change que la densité — même carte, même structure, même
   * `aria-live` : c'est le poids visuel qui distingue « ce que je viens lire »
   * de « comment il se décompose ».
   */
  size?: "md" | "sm";
}

export function MetricCard({
  label,
  value,
  hint,
  icon,
  loading = false,
  size = "md",
}: MetricCardProps) {
  const dense = size === "sm";

  return (
    <div className={`rounded-card bg-surface shadow-card ${dense ? "p-3" : "p-4"}`}>
      <div className="flex items-start justify-between gap-3">
        <span className="label-micro">{label}</span>
        {icon ? (
          <span aria-hidden="true" className="text-ink-dim">
            {icon}
          </span>
        ) : null}
      </div>

      {loading ? (
        // Un squelette à la forme du contenu final, jamais un spinner centré :
        // la page ne doit pas sauter quand la valeur arrive.
        <div
          className={[
            "mt-2 animate-pulse rounded-input bg-elevated",
            dense ? "h-6 w-14" : "h-8 w-20",
          ].join(" ")}
        />
      ) : (
        <output
          aria-live="polite"
          className={[
            "mt-1 block font-bold leading-tight text-ink",
            dense ? "text-heading" : "text-[1.75rem]",
          ].join(" ")}
        >
          {value}
        </output>
      )}

      {hint ? (
        <p className={`mt-1 text-ink-dim ${dense ? "text-micro" : "text-small"}`}>{hint}</p>
      ) : null}
    </div>
  );
}
