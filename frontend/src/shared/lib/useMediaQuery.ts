/**
 * S'abonner à une requête média depuis React.
 *
 * Il existe parce que certains replis ne peuvent **pas** se faire en CSS : masquer un
 * élément par `display: none` le laisse monté, ses effets tournent et ses requêtes
 * partent. Quand le repli consiste à *déplacer* un contenu d'un endroit à un autre —
 * les chiffres techniques qui quittent la barre du studio pour un tiroir — il faut
 * choisir un seul montage, donc décider en JavaScript.
 *
 * **À n'utiliser que dans ce cas.** Une simple apparition ou disparition se fait en
 * CSS, qui n'a ni rendu supplémentaire ni état à désynchroniser.
 *
 * Trois précautions, chacune pour un piège réel :
 *
 * - **l'état initial est lu dans le même `useState`**, et non dans un effet : le
 *   lire après la peinture ferait rendre une frame avec le mauvais montage, donc
 *   monter puis démonter aussitôt le contenu déplacé ;
 * - **`matchMedia` est interrogé derrière un garde**, parce qu'un environnement de
 *   test (`bun test`, sans DOM) n'en a pas. Le repli est `false` — la mise en page
 *   large, qui est celle du poste de travail visé ;
 * - **l'abonnement est refait quand la requête change** et la valeur relue dans le
 *   même effet : sans cette relecture, changer de requête laisserait l'ancienne
 *   réponse à l'écran jusqu'au prochain redimensionnement.
 */

import { useEffect, useState } from "react";

/** Lit la requête maintenant, sans s'abonner. `false` là où `matchMedia` n'existe pas. */
export function matchesNow(query: string): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(query).matches
    : false;
}

/**
 * `true` tant que la requête est satisfaite.
 *
 * @param query une requête média CSS, p. ex. `"(width >= 80rem)"`.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => matchesNow(query));

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;

    const list = window.matchMedia(query);
    // Relu ici aussi : entre le premier rendu et cet effet, la fenêtre a pu changer
    // de taille — et si `query` change, l'état porte encore la réponse de l'ancienne.
    setMatches(list.matches);

    const update = (event: MediaQueryListEvent): void => setMatches(event.matches);
    list.addEventListener("change", update);
    return () => list.removeEventListener("change", update);
  }, [query]);

  return matches;
}
