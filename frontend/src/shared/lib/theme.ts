/**
 * Le thème de l'interface — sombre par défaut, clair au choix.
 *
 * **Le sombre est le défaut, et pas parce que le système le dit.** Le système de
 * design du projet est né sombre (DESIGN.md) : c'est l'apparence pour laquelle
 * les couleurs de canvas ont été choisies, et celle où une scène vidéo occupe
 * l'écran sans être encadrée de blanc. Suivre `prefers-color-scheme` ferait
 * démarrer en clair la moitié des postes, sur une interface pensée en sombre.
 * Le clair est donc une préférence **explicite**, retenue une fois posée.
 *
 * Le thème vit sur `<html data-theme="…">` et nulle part ailleurs : les jetons
 * CSS s'y raccrochent, aucun composant n'a de branche « si clair ».
 */

export type Theme = "dark" | "light";

/** Le thème du projet. Voir plus haut pourquoi il ne dépend pas du système. */
export const DEFAULT_THEME: Theme = "dark";

export const THEME_STORAGE_KEY = "traffic-analysis.theme.v1";

/** L'attribut porté par `<html>`. Une seule constante, lue par le CSS et le JS. */
export const THEME_ATTRIBUTE = "data-theme";

/** Reconnaît un thème, ou rend le défaut. Ne lève jamais. */
export function normaliseTheme(raw: unknown): Theme {
  return raw === "light" || raw === "dark" ? raw : DEFAULT_THEME;
}

/** L'autre thème — ce que le bouton produira. */
export function nextTheme(current: Theme): Theme {
  return current === "dark" ? "light" : "dark";
}

/**
 * Relit la préférence enregistrée.
 *
 * **Ne lève jamais.** Accéder à `localStorage` lève dans un iframe restreint ou
 * en navigation privée verrouillée ; une interface ne doit pas rester blanche
 * pour une préférence de couleur.
 */
export function loadTheme(storage: Pick<Storage, "getItem"> | null = safeStorage()): Theme {
  if (storage === null) return DEFAULT_THEME;
  try {
    return normaliseTheme(storage.getItem(THEME_STORAGE_KEY));
  } catch {
    return DEFAULT_THEME;
  }
}

/** Enregistre la préférence. Silencieux en cas d'échec, pour la même raison. */
export function saveTheme(
  theme: Theme,
  storage: Pick<Storage, "setItem"> | null = safeStorage(),
): void {
  if (storage === null) return;
  try {
    storage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Préférence non retenue, interface parfaitement utilisable.
  }
}

/**
 * Applique le thème au document.
 *
 * `color-scheme` en plus de l'attribut : c'est lui qui fait suivre les éléments
 * que le CSS de la page ne peint pas — barres de défilement, sélecteurs natifs,
 * champs de formulaire. Sans lui, un thème clair garde des menus déroulants
 * noirs, et l'incohérence saute aux yeux au premier clic.
 */
export function applyTheme(theme: Theme, root: ThemeTarget = document.documentElement): void {
  root.setAttribute(THEME_ATTRIBUTE, theme);
  root.style.colorScheme = theme;
}

/**
 * Ce dont `applyTheme` a réellement besoin, et rien de plus.
 *
 * Structurel plutôt que `HTMLElement` : le lanceur de tests du projet est
 * `bun test`, **sans DOM**. Exiger un vrai élément obligerait à embarquer un
 * environnement de navigateur entier pour vérifier deux affectations.
 */
export interface ThemeTarget {
  setAttribute: (name: string, value: string) => void;
  style: { colorScheme: string };
}

/** Marque la bascule en cours, le temps que les nouvelles couleurs s'appliquent. */
export const THEME_SWITCHING_ATTRIBUTE = "data-theme-switching";

/**
 * Bascule le thème **sans laisser les transitions s'en mêler**.
 *
 * Le problème, observé et non supposé : les éléments portant `transition-colors`
 * — la navigation, les boutons, les cartes — restaient à leur ancienne couleur
 * après le changement. Le navigateur voit une transition de `color` déclenchée
 * par une variable personnalisée non enregistrée, et le résultat n'est pas
 * l'animation attendue : la valeur d'arrivée n'est jamais atteinte. Un élément
 * neuf, lui, prenait bien la bonne couleur — d'où une entête à moitié dans
 * l'ancien thème, ce qui se lit comme un bug de palette.
 *
 * On coupe donc les transitions le temps de la bascule. C'est de toute façon ce
 * qu'on veut visuellement : un thème change d'un coup, il ne se fond pas.
 */
export function switchTheme(
  theme: Theme,
  root: SwitchTarget = document.documentElement,
  /**
   * Quand rendre les transitions. **Deux frames** : la première laisse le
   * navigateur peindre avec les nouvelles couleurs, transitions coupées ; la
   * seconde les rend au reste de l'application. Une seule frame les rendrait
   * parfois avant la peinture, et le défaut reviendrait par intermittence — le
   * pire des cas.
   *
   * Injectable parce que `bun test` n'a pas de `requestAnimationFrame` : le
   * paramètre existe pour le test, la valeur par défaut est celle du navigateur.
   */
  afterPaint: (run: () => void) => void = doubleFrame,
): void {
  root.setAttribute(THEME_SWITCHING_ATTRIBUTE, "");
  applyTheme(theme, root);
  afterPaint(() => root.removeAttribute(THEME_SWITCHING_ATTRIBUTE));
}

/** `ThemeTarget`, plus de quoi retirer la marque de bascule. */
export interface SwitchTarget extends ThemeTarget {
  removeAttribute: (name: string) => void;
}

function doubleFrame(run: () => void): void {
  requestAnimationFrame(() => requestAnimationFrame(run));
}

/** Libellé de l'action, pas de l'état : le bouton dit ce qu'il fera. */
export function themeActionLabel(current: Theme): string {
  return current === "dark" ? "Passer en thème clair" : "Passer en thème sombre";
}

function safeStorage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}
