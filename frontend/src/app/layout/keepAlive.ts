/**
 * La table des pages, et le choix de celle qui est visible.
 *
 * Elle a remplacé les routes enfants du routeur : celles-ci démontaient la page
 * qu'on quittait, donc changer d'onglet coûtait la vidéo importée, le tracé et le
 * résultat en cours (voir `KeepAlivePages`). L'appariement URL → page se fait donc
 * ici, et il est **testé** — c'est le morceau que `react-router` faisait pour nous
 * et qu'il ne fait plus.
 *
 * Séparé du composant pour cette seule raison : il n'y a ni jsdom ni
 * testing-library dans ce projet, donc ce qui doit être vérifié doit être une
 * fonction pure.
 */

/** Les pages de l'application, dans leur ordre de navigation. */
export const PAGE_PATHS = {
  studio: "/",
  history: "/historique",
  benchmark: "/benchmark",
} as const;

export type PageId = keyof typeof PAGE_PATHS;

/** Les identifiants dans l'ordre d'affichage, figé — voir `KeepAlivePages`. */
export const PAGE_IDS = Object.keys(PAGE_PATHS) as readonly PageId[];

/**
 * La page que cette URL désigne, ou `null` si aucune — c'est alors la page
 * d'erreur qui s'affiche, comme le faisait la route `*`.
 *
 * Comparaison **exacte** et non par préfixe : `/` sinon désignerait tout, et le
 * studio resterait affiché sur `/benchmark`. La barre finale est la seule
 * tolérance, parce qu'un lien collé la porte souvent et qu'elle ne change pas de
 * page.
 */
export function activePageId(pathname: string): PageId | null {
  const wanted = normalisePath(pathname);
  return PAGE_IDS.find((id) => PAGE_PATHS[id] === wanted) ?? null;
}

/** Retire la barre finale : `/historique/` et `/historique` sont la même page. */
export function normalisePath(pathname: string): string {
  return pathname.length > 1 && pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
}
