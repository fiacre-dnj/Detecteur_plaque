/**
 * Bouton — géométrie pilule, libellé en capitales espacées.
 *
 * La forme pilule et la voix « capitales + interlettrage » viennent de
 * `DESIGN.md` : elles constituent la signature du système. Un bouton carré ou en
 * casse normale n'appartient pas à cette interface.
 */

import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  /** Icône `lucide-react`, décorative — le libellé porte le sens. */
  icon?: ReactNode;
  children: ReactNode;
}

const VARIANTS: Record<Variant, string> = {
  // L'accent est fonctionnel : il ne sert qu'à l'action principale d'un écran.
  primary: "bg-accent text-accent-ink hover:brightness-110 active:brightness-95",
  secondary: "bg-surface-2 text-ink hover:bg-elevated",
  ghost: "bg-transparent text-ink-muted ring-1 ring-line-muted hover:text-ink hover:ring-ink-dim",
  danger: "bg-transparent text-negative ring-1 ring-negative/40 hover:bg-negative/10",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-4 text-[0.75rem]",
  md: "h-10 px-6",
};

export function Button({
  variant = "secondary",
  size = "md",
  icon,
  children,
  className = "",
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      className={[
        "label-caps inline-flex items-center justify-center gap-2 rounded-pill",
        "transition-[filter,background-color,box-shadow] duration-150",
        // Un bouton désactivé reste **lisible** : l'estomper jusqu'à
        // l'illisibilité empêche de comprendre ce qui est indisponible.
        "disabled:cursor-not-allowed disabled:opacity-45",
        SIZES[size],
        VARIANTS[variant],
        className,
      ].join(" ")}
      {...rest}
    >
      {icon ? <span aria-hidden="true" className="shrink-0">{icon}</span> : null}
      {children}
    </button>
  );
}
