/**
 * La fenêtre d'une page — la liste des lignes de « Statistique » quand il y en a
 * beaucoup.
 *
 * Un calcul de pagination tient en trois lignes et se trompe de un dans les deux
 * sens ; celui-ci est ici pour être **testé**, et parce qu'il doit rester juste
 * dans le cas qui casse toujours les paginations d'écran vivant : le jeu de
 * données **rétrécit** sous la page courante. Retirer trois lignes du tracé
 * pendant qu'on lit la page 3 laisse un index qui ne désigne plus rien, et une
 * liste vide sous une pagination qui annonce « 19–24 sur 6 » se lit comme une
 * panne d'affichage.
 *
 * La page demandée est donc **ramenée** dans les bornes plutôt que respectée : la
 * fonction rend toujours une fenêtre non vide dès qu'il y a un élément, et son
 * `page` est celui qu'il faut afficher, jamais celui qui a été demandé.
 */

export interface PageWindow {
  /** La page réellement affichée, 0-indexée et bornée. */
  page: number;
  /** Nombre de pages, au moins 1 — une liste vide a une page vide, pas zéro page. */
  pageCount: number;
  /** Index de début, inclus. */
  start: number;
  /** Index de fin, **exclu** — prêt pour `slice`. */
  end: number;
  /** Faut-il afficher les commandes ? Faux tant que tout tient sur une page. */
  paginated: boolean;
}

export function pageWindow(total: number, pageSize: number, page: number): PageWindow {
  const size = Math.max(1, Math.trunc(pageSize));
  const count = Math.max(1, Math.ceil(Math.max(0, total) / size));
  // `page` vient d'un état React qui a pu survivre à un rétrécissement de la
  // liste : on le borne dans les deux sens, sans jamais faire confiance à
  // l'appelant.
  const current = Math.min(Math.max(0, Math.trunc(page)), count - 1);
  const start = current * size;

  return {
    page: current,
    pageCount: count,
    start,
    end: Math.min(start + size, Math.max(0, total)),
    paginated: total > size,
  };
}
