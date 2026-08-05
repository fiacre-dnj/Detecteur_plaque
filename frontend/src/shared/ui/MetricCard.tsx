/**
 * Carte de synthèse — un chiffre, son libellé, sa précision.
 *
 * `aria-live="polite"` : ces chiffres changent pendant une analyse, et un
 * lecteur d'écran doit l'annoncer sans interrompre ce qu'il est en train de
 * lire.
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
}

export function MetricCard({ label, value, hint, icon, loading = false }: MetricCardProps) {
  return (
    <div className="rounded-card bg-surface p-4 shadow-card">
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
        <div className="mt-2 h-8 w-20 animate-pulse rounded-input bg-elevated" />
      ) : (
        <output
          aria-live="polite"
          className="mt-1 block text-[1.75rem] font-bold leading-tight text-ink"
        >
          {value}
        </output>
      )}

      {hint ? <p className="mt-1 text-small text-ink-dim">{hint}</p> : null}
    </div>
  );
}
