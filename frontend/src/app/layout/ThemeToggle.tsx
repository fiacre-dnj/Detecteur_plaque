/**
 * La bascule sombre / clair, dans l'entête.
 *
 * Un seul bouton plutôt qu'un sélecteur à trois états (sombre / clair /
 * système) : le projet a un thème par défaut assumé — le sombre — et le clair
 * est une préférence explicite. Un troisième état « système » ferait basculer
 * l'interface au coucher du soleil sur les postes qui suivent l'heure, ce qui
 * surprend plus que ça ne rend service dans un outil de travail.
 *
 * L'icône montre **ce qu'on obtiendra**, pas l'état courant : c'est un bouton
 * d'action, et un soleil qui signifierait « vous êtes en clair » sur une
 * interface visiblement claire n'apprendrait rien.
 */

import { Moon, Sun } from "lucide-react";
import { useCallback, useState } from "react";

import {
  loadTheme,
  nextTheme,
  saveTheme,
  switchTheme,
  themeActionLabel,
  type Theme,
} from "@/shared/lib/theme";

export function ThemeToggle() {
  // Relu du stockage une seule fois : `useState(loadTheme)` et non
  // `useState(loadTheme())`, qui lirait le stockage à chaque rendu.
  const [theme, setTheme] = useState<Theme>(loadTheme);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const target = nextTheme(current);
      // Posé tout de suite, hors du cycle de rendu : le thème vit sur `<html>`,
      // que React ne gouverne pas. `switchTheme` et non `applyTheme` : il coupe
      // les transitions le temps de la bascule, sans quoi une partie de l'entête
      // reste peinte dans l'ancien thème.
      switchTheme(target);
      saveTheme(target);
      return target;
    });
  }, []);

  const label = themeActionLabel(theme);

  return (
    <button
      type="button"
      onClick={toggle}
      title={label}
      aria-label={label}
      className="grid size-9 place-items-center rounded-pill text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink"
    >
      {theme === "dark" ? (
        <Sun aria-hidden="true" className="size-4" />
      ) : (
        <Moon aria-hidden="true" className="size-4" />
      )}
    </button>
  );
}
