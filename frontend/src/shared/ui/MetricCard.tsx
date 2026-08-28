/**
 * Carte de synthèse — un chiffre, son libellé, sa précision.
 *
 * `aria-live="polite"` : ces chiffres changent pendant une analyse, et un
 * lecteur d'écran doit l'annoncer sans interrompre ce qu'il est en train de
 * lire.
 *
 * **Trois tailles, et l'écart est une hiérarchie, pas une économie de place.** La
 * Répartition par type de véhicule et le bilan de chaque ligne vivent désormais
 * dans la même grille que le chiffre de tête ; rendues à l'identique, une dizaine
 * de cartes de même poids ne diraient plus laquelle répond à la question qu'on se
 * pose en arrivant.
 *
 * `lg` est arrivée avec cette grille : la colonne n'a plus qu'**une** tête de
 * lecture — « Passages globaux », désormais sur toute la largeur — et une carte
 * `md` au milieu de cartes `sm` ne se détachait plus assez pour l'être.
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
   * `lg` pour l'unique chiffre de tête d'un écran, `md` (défaut) pour un chiffre
   * important, `sm` pour un chiffre de détail.
   *
   * Elles ne changent que la densité — même carte, même structure, même
   * `aria-live`, et **le même alignement à gauche** : c'est le poids visuel qui
   * distingue « ce que je viens lire » de « comment il se décompose ». Le chiffre
   * de tête a été centré un moment ; à gauche, il s'aligne avec son libellé, sa
   * précision et tout ce que la colonne empile en dessous.
   */
  size?: "lg" | "md" | "sm";
}

/** Densités, par taille : marge de la carte, chiffre, précision, squelette. */
const SIZES: Readonly<
  Record<NonNullable<MetricCardProps["size"]>, { pad: string; value: string; hint: string; skeleton: string }>
> = {
  lg: { pad: "p-5", value: "text-[2.5rem]", hint: "text-small", skeleton: "h-10 w-24" },
  md: { pad: "p-4", value: "text-[1.75rem]", hint: "text-small", skeleton: "h-8 w-20" },
  sm: { pad: "p-3", value: "text-heading", hint: "text-micro", skeleton: "h-6 w-14" },
};

export function MetricCard({
  label,
  value,
  hint,
  icon,
  loading = false,
  size = "md",
}: MetricCardProps) {
  const density = SIZES[size];

  return (
    <div className={`rounded-card bg-surface shadow-card ${density.pad}`}>
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
          className={["mt-2 animate-pulse rounded-input bg-elevated", density.skeleton].join(" ")}
        />
      ) : (
        <output
          aria-live="polite"
          className={["mt-1 block font-bold leading-tight text-ink", density.value].join(" ")}
        >
          {value}
        </output>
      )}

      {hint ? <p className={`mt-1 text-ink-dim ${density.hint}`}>{hint}</p> : null}
    </div>
  );
}
