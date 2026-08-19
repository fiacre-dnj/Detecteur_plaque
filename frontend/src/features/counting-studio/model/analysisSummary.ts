/**
 * Ce qu'une analyse va faire, en une poignée de lignes — le récapitulatif de la
 * colonne de droite tant qu'aucun chiffre n'existe encore.
 *
 * Il répond à la question qu'on se pose juste avant de cliquer sur « Lancer » :
 * *avec quel modèle, sur quels objets, sur quel tracé, sur quelle portion*. Chacune
 * de ces réponses vit dans un tiroir différent de la barre, et vérifier les quatre
 * demandait d'ouvrir les quatre — alors que la colonne d'à côté était vide.
 *
 * **Il n'invente aucun réglage et n'en corrige aucun.** Il ne fait que relire l'état
 * courant : si une valeur y paraît fausse, c'est le réglage qui l'est, pas cet
 * écran. Les avertissements suivent la même règle — ils décrivent une conséquence
 * (« aucun franchissement ne sera compté »), jamais un interdit : lancer reste
 * possible, `canAnalyse` en est le seul juge.
 *
 * En **modèle** et pas dans le composant : c'est du texte à vérifier, et un test le
 * vérifie sans monter de DOM.
 */

import { formatTimecode, isFullRange, type AnalysisRange } from "@/entities/analysis-range";

/** Une ligne du récapitulatif : ce qui est réglé, et ce que ça implique. */
export interface AnalysisSummaryRow {
  label: string;
  value: string;
  /**
   * La conséquence d'un réglage qui va décevoir — aucune classe cochée, aucune
   * ligne tracée. Rendue sous la valeur, en avertissement.
   *
   * `undefined` est le cas normal : une ligne sans conséquence à annoncer n'a pas
   * de phrase, plutôt qu'une phrase rassurante que personne ne lira deux fois.
   */
  warning?: string | undefined;
}

export interface AnalysisSummaryInput {
  /** Le nom lisible du modèle, pas son identifiant. */
  modelLabel: string;
  /** Les types cochés, déjà traduits en français par l'appelant. */
  classLabels: readonly string[];
  lineCount: number;
  zoneCount: number;
  range: AnalysisRange;
  detectPlates: boolean;
  readPlateText: boolean;
  /** Multiples du temps réel, `null` = aucune borne relative. */
  analysisSpeed: number | null;
  /** Plafond absolu en images par seconde réelle, `null` = aucun. */
  maxAnalysisFps: number | null;
}

export function analysisSummaryRows(input: AnalysisSummaryInput): AnalysisSummaryRow[] {
  return [
    { label: "Modèle", value: input.modelLabel },
    countedObjects(input.classLabels),
    geometrySummary(input.lineCount, input.zoneCount),
    { label: "Portion analysée", value: rangeSummary(input.range) },
    { label: "Plaques", value: plateSummary(input.detectPlates, input.readPlateText) },
    { label: "Cadence", value: paceSummary(input.analysisSpeed, input.maxAnalysisFps) },
  ];
}

function countedObjects(labels: readonly string[]): AnalysisSummaryRow {
  if (labels.length === 0) {
    return {
      label: "Objets comptés",
      value: "Aucun",
      warning: "Cochez au moins un type dans « Détection » : sans classe, rien ne sera compté.",
    };
  }
  return { label: "Objets comptés", value: labels.join(" · ") };
}

/**
 * Le tracé, et ce qu'il permet de compter.
 *
 * Une géométrie sans **ligne** est analysable — les zones comptent des entrées et
 * une occupation — mais elle ne produit aucun franchissement, donc aucun des
 * chiffres de tête de la colonne. C'est exactement le genre d'écart qui se lit
 * comme un comptage en panne, d'où la phrase.
 */
function geometrySummary(lineCount: number, zoneCount: number): AnalysisSummaryRow {
  const parts: string[] = [];
  if (lineCount > 0) parts.push(`${lineCount} ${lineCount === 1 ? "ligne" : "lignes"}`);
  if (zoneCount > 0) parts.push(`${zoneCount} ${zoneCount === 1 ? "zone" : "zones"}`);

  if (parts.length === 0) {
    return {
      label: "Géométrie",
      value: "Rien de tracé",
      warning: "Tracez une ligne dans « Géométrie » : sans trait, aucun franchissement n'existe.",
    };
  }
  return {
    label: "Géométrie",
    value: parts.join(" · "),
    warning:
      lineCount === 0
        ? "Aucune ligne : les zones seules ne produisent pas de franchissement."
        : undefined,
  };
}

/**
 * L'intervalle, **sans la durée de la vidéo**.
 *
 * `describeRange` la demande pour annoncer « — 02:14 analysées », mais elle n'est
 * lisible que sur la balise `<video>`, hors de tout état réactif : ce récapitulatif
 * se contenterait d'un chiffre figé au premier rendu. Les deux bornes suffisent à
 * dire ce qui sera analysé.
 */
function rangeSummary(range: AnalysisRange): string {
  if (isFullRange(range)) return "Toute la vidéo";
  if (range.endMs === null) return `À partir de ${formatTimecode(range.startMs)}`;
  return `De ${formatTimecode(range.startMs)} à ${formatTimecode(range.endMs)}`;
}

/**
 * Les deux étages de l'ANPR, distingués parce qu'ils ne coûtent pas la même chose
 * et ne rendent pas la même information : repérer une plaque encadre un rectangle,
 * en lire le texte demande l'OCR — et le texte n'est publié qu'au-dessus du
 * plancher de lisibilité.
 */
function plateSummary(detectPlates: boolean, readPlateText: boolean): string {
  if (!detectPlates) return "Désactivées";
  return readPlateText ? "Repérage et lecture du texte" : "Repérage seul";
}

/**
 * Les deux bridages, sur une seule ligne — le plus restrictif des deux s'applique.
 *
 * `analysisSpeed` borne une vitesse **relative** au temps de la scène,
 * `maxAnalysisFps` un débit **absolu** : ils se composent, et chacun agit même quand
 * l'autre vaut `null` (ADR 0017 et 0020).
 */
function paceSummary(analysisSpeed: number | null, maxAnalysisFps: number | null): string {
  const relative =
    analysisSpeed === null
      ? "Illimitée"
      : analysisSpeed === 1
        ? "Temps réel"
        : `${analysisSpeed}× le temps réel`;
  return maxAnalysisFps === null ? relative : `${relative} · max ${maxAnalysisFps} img/s`;
}
