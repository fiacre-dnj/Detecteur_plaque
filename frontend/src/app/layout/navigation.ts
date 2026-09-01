/**
 * Les entrées de la navigation principale, dérivées de la table des pages.
 *
 * Elles étaient un tableau de littéraux dans `AppShell` — `{ to: "/historique",
 * label: "Historique" }` — écrit à côté de `PAGE_PATHS` sans que rien ne les relie.
 * Le mode de panne est silencieux et complet : changer un chemin d'un seul côté
 * donne un lien qui compile, s'affiche, et mène à la page d'erreur. Rien ne le dit,
 * puisque `activePageId` ne reconnaît alors plus l'URL et que `RouteError` est
 * précisément ce qu'elle rend dans ce cas.
 *
 * Le chemin vient donc de `PAGE_PATHS` et l'ordre de `PAGE_IDS` — la seule chose
 * qui reste écrite ici est ce qu'aucune autre source ne porte : le mot affiché.
 *
 * `Record<PageId, string>` **exhaustif** et non un tableau : une quatrième page
 * ajoutée à `PAGE_PATHS` sans libellé fait échouer `tsc`, ce qu'aucun test ne peut
 * garantir puisqu'il faudrait connaître la page qui n'existe pas encore.
 */

import { PAGE_IDS, PAGE_PATHS, type PageId } from "./keepAlive";

/** Le mot affiché — en infobulle et en nom accessible, le rail n'ayant que des icônes. */
export const NAV_LABELS: Readonly<Record<PageId, string>> = {
  studio: "Studio",
  history: "Historique",
  benchmark: "Benchmark",
};

export interface NavItem {
  id: PageId;
  /** Le chemin, lu dans `PAGE_PATHS` : jamais recopié. */
  to: string;
  label: string;
}

/** Les trois entrées, dans l'ordre d'affichage figé par `PAGE_IDS`. */
export const NAV_ITEMS: readonly NavItem[] = PAGE_IDS.map((id) => ({
  id,
  to: PAGE_PATHS[id],
  label: NAV_LABELS[id],
}));
