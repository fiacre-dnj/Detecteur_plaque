/**
 * Ce qu'un camembert montre quand il y a trop de parts pour un camembert.
 *
 * Les deux graphiques de « Statistique » tracent une part par **ligne** et une
 * part par **type d'objet suivi** : deux quantités que l'utilisateur choisit, et
 * qui ne sont bornées par rien. À douze lignes tracées, le camembert devient une
 * roue de fines lamelles et sa légende une liste de douze rangées, deux fois plus
 * haute que le dessin qu'elle légende.
 *
 * Trois règles, et chacune répond à un défaut observable :
 *
 * - **on classe par valeur décroissante.** Dans l'ordre du tracé, la question
 *   « quelle est la part dominante » se résout en comparant des angles à l'œil,
 *   ce qu'un camembert est justement censé éviter. Les égalités gardent l'ordre
 *   d'entrée (tri stable par index), sinon deux lignes à égalité échangeraient de
 *   place d'une image d'aperçu à l'autre ;
 * - **au-delà de `maxSlices`, le reste devient UNE part**, « N autres », d'un gris
 *   de jeton et jamais d'une couleur de donnée — sinon la part agrégée se lirait
 *   comme une ligne de plus. Les cachées restent rendues : la légende les liste à
 *   la demande, personne ne perd un chiffre ;
 * - **une part agrégée nulle n'existe pas.** Dix lignes sans un seul passage
 *   totalisent zéro : un secteur d'angle nul est invisible mais présent dans la
 *   légende, où il afficherait « 0 — 0 % » sous un nom qui promet dix lignes.
 *   `otherValue` vaut alors `0` et l'appelant ne trace rien, tout en pouvant
 *   toujours dire combien de lignes se taisent.
 *
 * Aucun total n'est recalculé ici : les valeurs traversent telles quelles, et la
 * somme des parts montrées plus `otherValue` est **exactement** celle des parts
 * reçues (invariant 3 — un affichage dérive, il n'accumule pas).
 */

/** Une part de camembert, telle que la fournit le graphique appelant. */
export interface PieSlice {
  id: string;
  label: string;
  value: number;
  color: string;
}

/** L'identifiant de la part agrégée — réservé, aucune ligne ni classe ne le porte. */
export const OTHER_SLICE_ID = "__autres__";

/**
 * La couleur de la part agrégée : un jeton de bordure, pas une couleur de donnée.
 *
 * `var()` et non un hexadécimal, comme partout ailleurs — et c'est ce qui la fait
 * suivre la bascule de thème sans code.
 */
const OTHER_SLICE_COLOR = "var(--color-line-muted)";

export interface GroupedSlices {
  /**
   * Les parts à tracer, valeur décroissante, `maxSlices` au plus — la dernière
   * étant la part agrégée dès qu'il y a des cachées **porteuses de passages**.
   */
  shown: readonly PieSlice[];
  /** Les parts repliées, dans le même ordre décroissant. Vide si rien n'est replié. */
  hidden: readonly PieSlice[];
  /** La somme des cachées. `0` veut dire « rien à tracer pour elles ». */
  otherValue: number;
}

/**
 * Classe les parts et replie le surplus.
 *
 * `maxSlices` compte la part agrégée : à `6`, on montre les cinq premières plus
 * « N autres ». En dessous de 2 il n'y a plus de regroupement possible (une part
 * plus l'agrégat font déjà deux), donc la valeur est ramenée à 2.
 */
export function groupSlices(
  slices: readonly PieSlice[],
  maxSlices: number,
): GroupedSlices {
  const limit = Math.max(2, Math.trunc(maxSlices));

  // Tri **stable** : le comparateur retombe sur l'index d'origine, donc deux
  // lignes à égalité de passages gardent l'ordre du tracé au lieu de permuter à
  // chaque republication de l'aperçu.
  const sorted = slices
    .map((slice, index) => ({ slice, index }))
    .sort((a, b) => b.slice.value - a.slice.value || a.index - b.index)
    .map((entry) => entry.slice);

  if (sorted.length <= limit) {
    return { shown: sorted, hidden: [], otherValue: 0 };
  }

  const shown = sorted.slice(0, limit - 1);
  const hidden = sorted.slice(limit - 1);
  const otherValue = hidden.reduce((sum, slice) => sum + slice.value, 0);

  return {
    // La part agrégée n'est tracée que si elle pèse quelque chose : à zéro, elle
    // n'occuperait aucun angle et remplirait quand même une rangée de légende.
    shown:
      otherValue > 0
        ? [
            ...shown,
            {
              id: OTHER_SLICE_ID,
              label: `${hidden.length} autres`,
              value: otherValue,
              color: OTHER_SLICE_COLOR,
            },
          ]
        : shown,
    hidden,
    otherValue,
  };
}
