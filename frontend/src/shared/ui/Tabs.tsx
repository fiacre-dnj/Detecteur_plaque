/**
 * Onglets — un seul panneau visible à la fois, navigables au clavier.
 *
 * **Le clavier n'est pas une option ici.** Le motif ARIA des onglets demande que les
 * flèches déplacent la sélection et que `Tab` sorte du groupe, parce qu'une barre de
 * dix onglets qui piège la tabulation oblige à dix pressions pour atteindre le
 * contenu. L'accordéon maison de `SettingsPanels` n'implémentait rien de tout cela —
 * ni `aria-controls`, ni `role`, ni flèches — et le refaire une troisième fois dans
 * le studio aurait figé l'oubli.
 *
 * Contrôlé de l'extérieur : le studio doit pouvoir ouvrir un onglet précis en
 * réponse à autre chose qu'un clic, et un état interne le lui interdirait.
 */

import { useId, useRef, type ReactNode } from "react";

export interface TabDefinition {
  id: string;
  label: string;
  /** Compteur discret à droite du libellé — « 23 » à côté de « Franchissements ». */
  badge?: string | number | undefined;
  content: ReactNode;
}

interface TabsProps {
  tabs: readonly TabDefinition[];
  activeId: string;
  onSelect: (id: string) => void;
  /** Nom du groupe pour les lecteurs d'écran. */
  label: string;
  className?: string | undefined;
}

export function Tabs({ tabs, activeId, onSelect, label, className = "" }: TabsProps) {
  const base = useId();
  const listRef = useRef<HTMLDivElement>(null);

  /**
   * Flèches, Home et Fin déplacent la sélection ; la boucle est **circulaire**.
   *
   * Le focus suit la sélection (« automatic activation ») : c'est le comportement
   * attendu quand changer d'onglet ne coûte rien, et il évite d'avoir à confirmer
   * par Entrée un déplacement déjà visible à l'écran.
   */
  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
    const index = tabs.findIndex((tab) => tab.id === activeId);
    if (index < 0) return;
    const last = tabs.length - 1;
    let next = index;
    if (event.key === "ArrowRight") next = index === last ? 0 : index + 1;
    else if (event.key === "ArrowLeft") next = index === 0 ? last : index - 1;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = last;
    else return;

    event.preventDefault();
    const target = tabs[next];
    if (target === undefined) return;
    onSelect(target.id);
    // Déplacer le focus avec la sélection : sans cela, les flèches suivantes
    // repartiraient de l'onglet d'origine.
    listRef.current?.querySelector<HTMLButtonElement>(`#${CSS.escape(`${base}-${target.id}`)}`)?.focus();
  };

  const active = tabs.find((tab) => tab.id === activeId) ?? tabs[0];

  return (
    <div className={className}>
      <div
        ref={listRef}
        role="tablist"
        aria-label={label}
        onKeyDown={onKeyDown}
        className="flex flex-wrap gap-1 rounded-pill bg-surface p-1 shadow-card"
      >
        {tabs.map((tab) => {
          const selected = tab.id === active?.id;
          return (
            <button
              key={tab.id}
              id={`${base}-${tab.id}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`${base}-${tab.id}-panel`}
              // Un seul onglet dans l'ordre de tabulation : `Tab` traverse le groupe
              // au lieu de s'arrêter sur chacun.
              tabIndex={selected ? 0 : -1}
              onClick={() => onSelect(tab.id)}
              className={[
                "label-caps rounded-pill px-4 py-1.5 transition-colors",
                selected
                  ? "bg-accent text-accent-ink"
                  : "text-ink-muted hover:bg-surface-2 hover:text-ink",
              ].join(" ")}
            >
              {tab.label}
              {tab.badge !== undefined && (
                <span
                  className={`ms-2 tabular ${selected ? "text-accent-ink/70" : "text-ink-dim"}`}
                >
                  {tab.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {active !== undefined && (
        <div
          id={`${base}-${active.id}-panel`}
          role="tabpanel"
          aria-labelledby={`${base}-${active.id}`}
          // `tabIndex={0}` : le panneau peut ne contenir aucun élément focalisable,
          // et il faut alors pouvoir l'atteindre pour le lire au clavier.
          tabIndex={0}
          className="mt-3 focus-visible:outline-none"
        >
          {active.content}
        </div>
      )}
    </div>
  );
}
