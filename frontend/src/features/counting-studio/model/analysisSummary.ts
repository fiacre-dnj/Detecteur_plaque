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
  /**
   * Ceux d'entre eux qui sont **petits** — moto, vélo, personne.
   *
   * Traduits par l'appelant comme `classLabels`, et **sous-ensemble de celui-ci** :
   * ce module ne connaît pas le catalogue, et deviner « ce nom ressemble à une
   * moto » depuis une chaîne française serait le genre de coïncidence qui cesse
   * d'être vraie à la première traduction.
   */
  smallClassLabels: readonly string[];
  /** Définition d'analyse demandée, `null` = celle du serveur. */
  inferenceImgsz: number | null;
  lineCount: number;
  zoneCount: number;
  /** Lignes portant au moins un sens interdit ou une voie réservée. */
  ruledLineCount: number;
  range: AnalysisRange;
  detectPlates: boolean;
  readPlateText: boolean;
  /** Plaques recherchées — leur nombre suffit, le récapitulatif ne les liste pas. */
  watchedPlateCount: number;
  /** Multiples du temps réel, `null` = aucune borne relative. */
  analysisSpeed: number | null;
  /** Plafond absolu en images par seconde réelle, `null` = aucun. */
  maxAnalysisFps: number | null;
  /**
   * Hauteur de la source en pixels, `null` tant qu'aucune vidéo n'est chargée.
   *
   * Sert **uniquement** à prévenir sur le plancher de lecture des plaques. La
   * largeur ne dirait rien de plus : c'est la définition verticale qui décide de
   * la hauteur d'une plaque dans l'image, et un format large ne rapproche rien.
   */
  sourceHeight: number | null;
}

/**
 * En dessous, une vue de circulation ne rend quasiment jamais une plaque lisible.
 *
 * Ce n'est pas un seuil inventé : le plancher de **tentative** de l'OCR est de
 * 64 px de large (invariant 12), et ADR 0032 a mesuré des plaques de moins de 48 px
 * sur une vue de circulation en 1080p. Vérifié à nouveau sur ce dépôt en 720p —
 * 29 véhicules, **zéro plaque publiée**, toutes les raisons en `too_small` ou
 * `not_detected` — pendant que l'étage de détection consommait 73 % du budget.
 *
 * Le seuil porte sur la source et non sur la scène cadrée, parce que c'est le seul
 * chiffre connu avant de lancer.
 */
const PLATE_READABLE_MIN_SOURCE_HEIGHT = 1080;

export function analysisSummaryRows(input: AnalysisSummaryInput): AnalysisSummaryRow[] {
  return [
    { label: "Modèle", value: input.modelLabel },
    countedObjects(input.classLabels, input.smallClassLabels),
    definitionRow(input.inferenceImgsz),
    geometrySummary(input.lineCount, input.zoneCount),
    ...surveillance(input.ruledLineCount, input.watchedPlateCount, input.readPlateText),
    { label: "Portion analysée", value: rangeSummary(input.range) },
    plateRow(input.detectPlates, input.readPlateText, input.sourceHeight),
    paceRow(input.analysisSpeed, input.maxAnalysisFps),
  ];
}

/**
 * Ce que l'analyse va **signaler** — la ligne n'existe que s'il y a quelque chose.
 *
 * Une rangée « Surveillance : rien » sur une analyse ordinaire serait du bruit :
 * l'immense majorité des tracés ne déclare aucune règle et ne cherche aucune plaque.
 * D'où un tableau, vide ou à une entrée, plutôt qu'une rangée toujours présente.
 *
 * **L'avertissement est celui qui compte de toute cette page** : une liste de
 * plaques saisie puis laissée en place après avoir décoché l'OCR chercherait dans un
 * texte que personne ne lit. Rien ne planterait, aucune alerte ne sortirait, et
 * l'utilisateur conclurait que la plaque n'est jamais passée.
 */
function surveillance(
  ruledLineCount: number,
  watchedPlateCount: number,
  readPlateText: boolean,
): AnalysisSummaryRow[] {
  const parts: string[] = [];
  if (ruledLineCount > 0) {
    parts.push(
      `${ruledLineCount} ${ruledLineCount === 1 ? "ligne à règle" : "lignes à règles"}`,
    );
  }
  if (watchedPlateCount > 0) {
    parts.push(
      `${watchedPlateCount} ${watchedPlateCount === 1 ? "plaque recherchée" : "plaques recherchées"}`,
    );
  }
  if (parts.length === 0) return [];

  return [
    {
      label: "Surveillance",
      value: parts.join(" · "),
      warning:
        watchedPlateCount > 0 && !readPlateText
          ? "La lecture des plaques est désactivée : aucune plaque recherchée ne pourra être trouvée."
          : undefined,
    },
  ];
}

function countedObjects(
  labels: readonly string[],
  smallLabels: readonly string[],
): AnalysisSummaryRow {
  if (labels.length === 0) {
    return {
      label: "Objets comptés",
      value: "Aucun",
      warning: "Cochez au moins un type dans « Détection » : sans classe, rien ne sera compté.",
    };
  }
  const value = labels.join(" · ");
  if (smallLabels.length === 0) return { label: "Objets comptés", value };

  // Le jumeau de l'avertissement des plaques, pour la classe de problème que ce
  // dépôt a mis le plus longtemps à nommer. Il dit une **conséquence** et trois
  // gestes, jamais un interdit : `canAnalyse` reste le seul juge.
  //
  // **Il ne recopie aucun chiffre de tenseur.** Le dire en « 640×384 » était
  // tentant et deviendrait faux dès que la définition d'analyse change — c'est
  // exactement ce que `PLATE_READABLE_MIN_SOURCE_HEIGHT` évite en n'affirmant
  // qu'une hauteur de source.
  const names = smallLabels.join(" et ");
  const plural = smallLabels.length > 1;
  return {
    label: "Objets comptés",
    value,
    warning:
      `${names} ${plural ? "sont les plus petits objets" : "est le plus petit objet"} de ` +
      "COCO. Ce n'est pas leur taille dans la vidéo qui décide qu'ils sont détectés, " +
      "c'est leur taille dans l'entrée du réseau : monter « Définition d'analyse », " +
      "baisser « Confiance véhicules » ou resserrer le plan sont les trois gestes qui " +
      "en récupèrent.",
  };
}

/**
 * La définition d'analyse, **toujours affichée**.
 *
 * Contrairement aux autres rangées, celle-ci n'existe pas pour avertir : elle
 * existe parce que ce réglage rend deux jobs incomparables sans qu'on le lise. Il
 * était jusqu'ici une variable d'environnement du serveur, donc identique pour tout
 * le monde ; il ne l'est plus.
 */
function definitionRow(imgsz: number | null): AnalysisSummaryRow {
  return {
    label: "Définition d'analyse",
    value: imgsz === null ? "Réglage du serveur" : `${imgsz} px`,
  };
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
 * La ligne « Plaques », plus l'avertissement que la définition de la source impose.
 *
 * **Le seul avertissement de cette page qui parle de temps perdu**, et il le mérite :
 * sur une vue de circulation peu définie, l'ANPR dépense la majorité du budget
 * d'analyse pour ne rien publier du tout. L'information existait déjà — chaque
 * véhicule reçoit sa raison de non-lecture (`too_small`) — mais **après** l'analyse,
 * c'est-à-dire après l'avoir payée.
 *
 * Il dit une conséquence et jamais un interdit, comme les autres : un plan resserré
 * en 720p lit très bien, et `canAnalyse` reste le seul juge du lancement. Les deux
 * gestes nommés sont ceux d'ADR 0032, et ce sont les seuls qui marchent — aucun
 * réglage ne rattrape des pixels absents.
 *
 * L'avertissement suit `detectPlates` et non `readPlateText` : le repérage seul est
 * précisément l'étage qui coûte cher, et il ne rend rien d'utile non plus quand les
 * plaques font trente pixels.
 */
function plateRow(
  detectPlates: boolean,
  readPlateText: boolean,
  sourceHeight: number | null,
): AnalysisSummaryRow {
  const value = plateSummary(detectPlates, readPlateText);
  if (!detectPlates || sourceHeight === null || sourceHeight >= PLATE_READABLE_MIN_SOURCE_HEIGHT) {
    return { label: "Plaques", value };
  }
  return {
    label: "Plaques",
    value,
    warning:
      `Source en ${sourceHeight}p : sur une vue de circulation, les plaques passent ` +
      "sous le plancher de lecture et l'analyse durera plus longtemps sans en publier " +
      "aucune. Resserrer le plan ou filmer plus défini sont les deux seuls remèdes.",
  };
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

/**
 * La cadence, plus l'avertissement qui manquait — les deux bridages peuvent se
 * contredire, et c'est **silencieux**.
 *
 * `ScenePacer` retient la période la **plus longue** des deux, donc le plafond
 * absolu bat la cadence de scène dès que la source dépasse ce plafond. Un « Temps
 * réel · max 30 img/s » sur une source 60 fps ne rend pas le temps réel : il rend
 * la moitié, et rien ne le disait. C'est le défaut qu'ADR 0049 a retiré ; il reste
 * atteignable à la main, d'où l'avertissement plutôt qu'un interdit.
 *
 * Pas de nombre d'images par seconde ici, et c'est délibéré : la cadence de la
 * source n'est lisible que sur la balise `<video>` et ne vit dans aucun état
 * réactif — même raison qui prive `describeRange` de la durée. La phrase est donc
 * conditionnelle, ce qui la garde vraie sans connaître la source.
 */
function paceRow(analysisSpeed: number | null, maxAnalysisFps: number | null): AnalysisSummaryRow {
  const value = paceSummary(analysisSpeed, maxAnalysisFps);
  if (maxAnalysisFps === null || analysisSpeed === null) return { label: "Cadence", value };

  return {
    label: "Cadence",
    value,
    warning:
      `Au-dessus de ${maxAnalysisFps} images par seconde, la source est analysée plus ` +
      "lentement que le temps réel et l'aperçu défile au ralenti.",
  };
}
