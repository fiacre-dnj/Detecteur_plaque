/**
 * Une pilule de la barre du studio : une icône, et son libellé qui se déplie.
 *
 * La barre porte trois familles de boutons — les tiroirs de réglages, les outils de
 * scène, et les commandes de l'analyse — qui doivent avoir **exactement** la même
 * forme et la même mécanique de survol. Deux d'entre elles vivent dans des features
 * différentes (`analysis-settings` et `analysis-job`), et une feature n'importe jamais
 * une autre : la forme commune ne peut vivre qu'ici.
 *
 * ## Pourquoi l'icône seule au repos
 *
 * La rangée doit tenir sur **une** ligne, et son budget ne dépend pas de la fenêtre :
 * il plafonne à ~1552 px, la rangée vivant dans le cadre `max-w-[1600px]` de la page
 * (ADR 0052). Six libellés en toutes lettres n'y tiennent pas dès que les alertes sont
 * armées et que les chiffres techniques sont montés. L'icône est donc l'état de repos,
 * et le mot revient au survol — là où l'on en a besoin, c'est-à-dire quand on hésite.
 *
 * ## Les cinq détails de l'animation
 *
 * - **c'est une `max-width` qu'on anime, et le passage par `grid-template-columns`
 *   `0fr → 1fr` a été essayé puis mesuré faux ici.** Ce motif est la façon courante
 *   d'animer une largeur `auto` — mais il suppose un conteneur qui distribue de
 *   l'espace libre, et ce bouton est un `inline-flex` **dimensionné par son contenu** :
 *   la piste se résout à son minimum et ne s'ouvre jamais. Mesuré en page, `1fr` forcé
 *   à la main : bouton 48 px avant, 48 px après. La `max-width`, elle, donne 40 px
 *   replié et 138 px déplié.
 *
 *   Sa contrepartie est réelle et assumée : la vitesse **apparente** dépend de la
 *   longueur du mot, puisque l'animation court jusqu'au plafond et non jusqu'au texte.
 *   Le plafond est donc serré (`max-w-40`, 10 rem) — juste au-dessus du plus long
 *   libellé, « Lancer l'analyse » — pour que l'écart reste imperceptible ;
 * - **il n'y a pas de `gap` sur le bouton**, l'espace est un `ps-2` porté par le texte
 *   lui-même, **à l'intérieur de la zone rognée**. Un `gap-2` sur le bouton
 *   s'appliquerait même replié : il resterait 8 px de vide à droite de chaque icône, et
 *   toute la rangée paraîtrait mal alignée sans qu'on voie pourquoi. C'est exactement
 *   ce qu'on a mesuré sur la version en grille, dont le padding survivait au repli ;
 * - **`overflow-hidden` va sur l'enveloppe qu'on anime**, et jamais sur le bouton :
 *   posé là, il rognerait l'anneau de focus, qui déborde de 4 px ;
 * - **`group-focus-visible` autant que `group-hover`**, sinon le libellé n'existe pas
 *   au clavier — et il n'existerait alors que pour ceux qui n'en ont pas besoin ;
 * - **`open` garde le libellé déplié.** La pilule dont le tiroir est ouvert est la
 *   seule qui doive se nommer sans qu'on la survole : c'est elle qui dit ce qu'on est
 *   en train de lire.
 *
 * L'expansion **pousse les voisins**, elle ne flotte pas au-dessus d'eux. C'est un
 * choix, et sa contrepartie est visible : survoler la première pilule décale toutes
 * les suivantes. Un calque flottant n'aurait rien décalé mais aurait recouvert la
 * pilule voisine, ce qui est pire sur une rangée qu'on parcourt. **Condition de
 * retour** : si la rangée en vient à passer sur deux lignes quand un libellé s'ouvre,
 * c'est ce choix qu'il faut défaire, pas la largeur des pilules.
 *
 * `aria-label` et `title` sont posés **inconditionnellement**, jamais dérivés de l'état
 * de survol : un nom accessible qui dépendrait d'un pointeur n'existerait pas.
 *
 * `prefers-reduced-motion` est déjà traité globalement dans `index.css` — la
 * transition y tombe à 0,01 ms et le libellé apparaît d'un coup, ce qui reste juste.
 */

import type { ButtonHTMLAttributes, ReactNode } from "react";

/**
 * La teinte de repos, qui **est** la hiérarchie de la rangée.
 *
 * Plus aucun libellé n'étant visible au repos, c'est la couleur — avec le filet de
 * groupe — qui porte seule la distinction entre ce qui règle le calcul et ce qui agit
 * sur la scène. Les quatre dernières sont des commandes : elles ne se distinguent pas
 * par leur place mais par ce qu'elles font, d'où une teinte propre à chacune.
 */
export type ToolbarTone =
  /** Les tiroirs de réglages de l'analyse. */
  | "settings"
  /** Les outils de scène — géométrie, recherche, alertes. */
  | "tools"
  /** L'action principale de l'écran : lancer, reprendre. */
  | "primary"
  /** Suspendre — réversible, mais elle arrête quelque chose. */
  | "warning"
  /** Annuler — destructif : les images déjà analysées sont perdues. */
  | "danger";

const TONES: Record<ToolbarTone, string> = {
  settings: "bg-surface text-ink-muted hover:enabled:bg-surface-2 hover:enabled:text-ink",
  tools: "bg-surface-2 text-ink-muted hover:enabled:bg-elevated hover:enabled:text-ink",
  // **Bleu et non vert**, alors que c'est bien l'action principale. Le vert est déjà
  // pris par le bouton d'import, juste à sa gauche : deux pastilles vertes côte à côte
  // se lisaient comme un seul groupe, et « Lancer » passait pour une variante de
  // « Changer de vidéo ». La distinction porte donc sur la teinte — la **source** est
  // verte, le **job** est bleu — et c'est ce qui rend la paire lisible sans libellé.
  //
  // `text-accent-ink` avec un fond bleu n'est pas une erreur : ce jeton vaut noir en
  // thème sombre et blanc en clair, ce qui est exactement ce que demandent `#539df5`
  // et `#1a5fbf`. Une couleur d'encre écrite en dur serait illisible dans l'un des deux.
  primary: "bg-info text-accent-ink hover:enabled:brightness-110",
  warning: "bg-warning/12 text-warning hover:enabled:bg-warning/20",
  danger: "bg-negative/12 text-negative hover:enabled:bg-negative/20",
};

interface ToolbarButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  /** Le mot déplié au survol, et le nom accessible **dans tous les cas**. */
  label: string;
  /** Icône `lucide-react`, décorative : passez-la en `aria-hidden`. */
  icon: ReactNode;
  tone?: ToolbarTone;
  /** Le libellé reste déplié — pour la pilule dont le tiroir est ouvert. */
  open?: boolean;
  /**
   * Le libellé se déplie-t-il au survol ? `true` par défaut.
   *
   * `false` pour les **commandes du job**, et c'est un choix d'usage : elles sont en
   * tête de rangée, donc leur expansion pousse *toute* la barre — y compris les
   * chiffres et la progression, qu'on est justement en train de lire quand on hésite à
   * suspendre. Elles changent en plus de nature en cours de route (« Lancer » devient
   * « Suspendre » puis « Reprendre »), si bien qu'une pilule qui s'ouvre sous le
   * curseur au moment où elle change de rôle se lit comme un déplacement.
   *
   * Le nom accessible ne bouge pas pour autant : `aria-label` et `title` restent posés
   * dans tous les cas. Ce qui disparaît est l'affichage, jamais le sens.
   */
  expandOnHover?: boolean;
  /** Rendu après le libellé : une pastille, un compte. */
  badge?: ReactNode;
}

export function ToolbarButton({
  label,
  icon,
  tone = "settings",
  open = false,
  expandOnHover = true,
  badge,
  className = "",
  disabled,
  ...rest
}: ToolbarButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-label={label}
      title={label}
      className={[
        "group label-caps inline-flex h-10 shrink-0 items-center rounded-pill px-3",
        "transition-colors disabled:cursor-not-allowed disabled:opacity-45",
        TONES[tone],
        className,
      ].join(" ")}
      {...rest}
    >
      <span aria-hidden="true" className="grid shrink-0 place-items-center">
        {icon}
      </span>

      {/* C'est l'enveloppe qui s'anime ; le texte, lui, ne bouge pas — il est
          simplement rogné. Animer une largeur sur le texte lui-même le comprimerait,
          donc changerait son rendu typographique pendant la transition.

          Rien du tout quand la pilule ne se déplie jamais : une enveloppe à largeur
          nulle laisserait un nœud vide dans l'arbre, et surtout la tentation d'y
          remettre un jour un `gap` qui rouvrirait le padding fantôme. */}
      {(expandOnHover || open) && (
        <span
          aria-hidden="true"
          className={[
            "block overflow-hidden transition-[max-width] duration-150 ease-out",
            // Décidé ici et non par un variant `group-disabled:` : `:hover` continue de
            // matcher sur un bouton désactivé, et l'ordre entre variants Tailwind n'est
            // pas celui de la source — une pilule grisée se déplierait au survol sans
            // qu'on puisse la cliquer.
            open
              ? "max-w-40"
              : disabled === true
                ? "max-w-0"
                : "max-w-0 group-hover:max-w-40 group-focus-visible:max-w-40",
          ].join(" ")}
        >
          <span className="inline-block whitespace-nowrap ps-2">{label}</span>
        </span>
      )}

      {badge}
    </button>
  );
}
