/**
 * Les couleurs que le **canvas** encode — le seul endroit du projet, avec
 * `index.css`, où un hexadécimal est autorisé.
 *
 * Ici, une couleur n'est pas une décoration : c'est une **donnée**. La teinte
 * d'une boîte dit la classe du véhicule, celle d'une ligne dit de quelle ligne il
 * s'agit. C'est pourquoi ces valeurs ne peuvent pas être des classes Tailwind :
 * `ctx.strokeStyle` veut une chaîne de couleur, et il n'existe aucun moyen de lire
 * un jeton CSS depuis le contexte 2D sans le résoudre à la main.
 *
 * **La règle non négociable (ADR 0004) : l'accent vert `#1ed760` n'apparaît
 * jamais ici.** Il est réservé aux états fonctionnels de l'interface — action
 * primaire, navigation active, « serveur prêt », et le badge ✓ « compté ». Si le
 * vert servait aussi de couleur de classe, « vert = compté » et « vert = camion »
 * se contrediraient sur la même image, et l'utilisateur ne saurait plus lequel des
 * deux il regarde.
 *
 * Corollaire, appliqué partout dans le canvas : **les états positifs s'expriment
 * par la forme**, pas par la couleur — trait plein contre pointillés, présence du
 * badge ✓. Un test vérifie qu'aucune couleur de ce fichier n'est l'accent.
 */

/**
 * Couleurs de classe, indexées par le **libellé COCO** que le backend renvoie.
 *
 * Les quatre classes de `VEHICLE_CLASS_IDS` côté serveur (2, 3, 5, 7). Choisies
 * distinguables entre elles **et** sur un fond sombre, en évitant le vert.
 */
export const CLASS_COLORS: Readonly<Record<string, string>> = {
  car: "#539df5", // bleu — la classe la plus fréquente, la plus lisible
  truck: "#ffa42b", // ambre — masse et gabarit
  bus: "#c47dff", // violet — distinct de l'ambre du camion
  motorcycle: "#f3727f", // rose — le plus petit gabarit, le plus visible
};

/**
 * Couleur d'une classe inconnue.
 *
 * Elle existe parce que le catalogue COCO peut renvoyer un libellé hors de nos
 * quatre classes si les seuils changent : afficher un gris neutre est honnête,
 * réutiliser la couleur d'une autre classe serait un mensonge visuel.
 */
export const UNKNOWN_CLASS_COLOR = "#b3b3b3";

/**
 * Couleur d'une classe donnée.
 *
 * Prend le libellé **voté** (`identityLabel || label`) : une lecture qui vacille
 * d'une image à l'autre ne doit pas faire clignoter la couleur de la boîte.
 */
export function classColor(label: string): string {
  return CLASS_COLORS[label] ?? UNKNOWN_CLASS_COLOR;
}

/**
 * Palette d'attribution des lignes et des zones, dans l'ordre.
 *
 * Parcourue cycliquement à la création : deux lignes consécutives ont donc des
 * couleurs différentes, ce qui est le seul but. Le vert en est absent, comme
 * partout ici.
 */
export const GEOMETRY_COLORS: readonly string[] = [
  "#539df5", // bleu
  "#ffa42b", // ambre
  "#c47dff", // violet
  "#f3727f", // rose
  "#4dd0e1", // cyan
  "#ffd54f", // jaune
];

/**
 * Couleur suivante à attribuer, à partir du nombre de formes existantes.
 *
 * Déterministe : recharger un preset redonne les mêmes couleurs dans le même
 * ordre, ce qui évite qu'une géométrie sauvegardée revienne en habits neufs.
 */
export function nextGeometryColor(existingCount: number): string {
  // `?? ` inatteignable en pratique — la palette n'est jamais vide — mais
  // `noUncheckedIndexedAccess` l'exige, et un repli valide vaut mieux qu'un `!`.
  return GEOMETRY_COLORS[existingCount % GEOMETRY_COLORS.length] ?? UNKNOWN_CLASS_COLOR;
}

/**
 * Couleurs du canvas qui ne dépendent d'aucune donnée.
 *
 * Regroupées pour que la revue de design ait un seul endroit à lire, et
 * exprimées en `rgba()` là où la transparence fait partie de la valeur.
 */
export const CANVAS = {
  /**
   * Voile des zones masquées, appliqué en règle **even-odd**.
   *
   * Assez opaque pour que « le détecteur ne voit pas ça » soit évident, assez
   * transparent pour qu'on reconnaisse encore la scène dessous.
   */
  maskFill: "rgba(2, 6, 23, 0.62)",
  /** Trait des formes non sélectionnées. */
  handle: "#ffffff",
  handleStroke: "rgba(0, 0, 0, 0.55)",
  /** Fond des étiquettes, pour rester lisible sur une scène claire. */
  labelBackground: "rgba(18, 18, 18, 0.82)",
  labelInk: "#ffffff",
  /** Centroïde d'une piste — blanc, donc jamais confondu avec une classe. */
  centroid: "#ffffff",
  /** Plaque détectée : un contour fin, sans remplissage. */
  plate: "#ffd54f",
  /**
   * Le libellé d'un sens **interdit**, et lui seul.
   *
   * La seule couleur du canvas qui n'encode pas *quelle* chose on regarde mais
   * *ce qu'elle vaut* — et l'exception est étroite exprès : le trait garde
   * `line.color`, qui dit quelle ligne c'est, et la boîte du véhicule garde sa
   * couleur de classe. Seul le mot « Interdit » vire au rouge.
   *
   * Sans elle, un sens interdit s'écrivait dans la teinte de sa ligne, à côté
   * d'« Entrée » écrit dans la même teinte : la seule différence était le mot, à
   * lire, sur une vidéo qui défile. Le rouge est ici la convention routière, pas
   * une décoration.
   *
   * Le même rouge que `--color-negative` du thème sombre, recopié parce que le
   * canvas est posé sur de la vidéo et ne suit pas le thème de la page (ADR 0004).
   */
  forbidden: "#f3727f",
} as const;

/** Opacité des trajectoires, imposée par `prompt/09` §2.4. */
export const TRAJECTORY_ALPHA = 0.53;
