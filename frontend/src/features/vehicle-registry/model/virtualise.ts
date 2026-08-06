/**
 * Virtualisation **maison** du registre.
 *
 * Pourquoi maison : `@tanstack/react-virtual` pèse ~12 Ko compressés et gère des
 * cas dont ce tableau n'a pas besoin — hauteurs variables, colonnes virtuelles,
 * défilement horizontal. Ici les lignes ont une hauteur fixe et il n'y a qu'un axe.
 * Le calcul tient en une dizaine de lignes, et il est **testable sans DOM**, ce
 * qu'une dépendance ne serait pas.
 *
 * Au-delà de quel seuil : **200 lignes**. En dessous, virtualiser coûte plus qu'il
 * ne rapporte — on ajoute des conteneurs et un calcul pour économiser quelques
 * dizaines de nœuds que le navigateur gère très bien. Au-delà, un registre de 10 000
 * véhicules produirait 10 000 lignes de tableau et bloquerait l'onglet plusieurs
 * secondes à chaque rendu.
 */

/** Seuil au-delà duquel on virtualise. */
export const VIRTUALISE_THRESHOLD = 200;

/** Hauteur d'une ligne, en pixels. Doit correspondre au CSS du tableau. */
export const ROW_HEIGHT = 36;

/**
 * Lignes rendues en plus, de part et d'autre de la fenêtre visible.
 *
 * Sans cette marge, un défilement rapide laisse apparaître du vide le temps du
 * rendu suivant — le scintillement blanc caractéristique d'une virtualisation trop
 * juste.
 */
export const OVERSCAN = 6;

export interface Window {
  /** Premier index à rendre, marge comprise. */
  start: number;
  /** Dernier index à rendre, **exclu**. */
  end: number;
  /** Hauteur totale du contenu, pour dimensionner la barre de défilement. */
  totalHeight: number;
  /** Décalage du premier élément rendu, en pixels. */
  offsetTop: number;
}

/**
 * Fenêtre de rendu pour une position de défilement.
 *
 * Les bornes sont **toujours** dans `[0, count]` : une position de défilement
 * négative (rebond élastique sur macOS et iOS, qui rend un `scrollTop` négatif) ou
 * supérieure au contenu ne doit pas produire d'indices hors tableau.
 */
export function visibleWindow(
  count: number,
  scrollTop: number,
  viewportHeight: number,
  rowHeight = ROW_HEIGHT,
  overscan = OVERSCAN,
): Window {
  const totalHeight = count * rowHeight;

  if (count === 0 || viewportHeight <= 0) {
    return { start: 0, end: 0, totalHeight, offsetTop: 0 };
  }

  const safeScroll = Math.max(0, Math.min(scrollTop, Math.max(0, totalHeight - viewportHeight)));
  const firstVisible = Math.floor(safeScroll / rowHeight);
  const visibleCount = Math.ceil(viewportHeight / rowHeight);

  const start = Math.max(0, firstVisible - overscan);
  const end = Math.min(count, firstVisible + visibleCount + overscan);

  return { start, end, totalHeight, offsetTop: start * rowHeight };
}

/** Faut-il virtualiser ce nombre de lignes ? */
export function shouldVirtualise(count: number): boolean {
  return count > VIRTUALISE_THRESHOLD;
}

/**
 * Nombre de lignes affichées avant le bouton « Afficher les N restants ».
 *
 * Douze : assez pour voir une tendance, assez peu pour ne pas noyer les cartes de
 * synthèse qui sont au-dessus. La spécification le fixe.
 */
export const INITIAL_ROWS = 12;
