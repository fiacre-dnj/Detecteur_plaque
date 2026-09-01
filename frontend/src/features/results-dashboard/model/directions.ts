/**
 * Les **agrégations** par sens de ligne : totaux, bilan entrées/sorties.
 *
 * Le vocabulaire lui-même — nommer un signe, lire un rôle — vit dans
 * `shared/lib/directions.ts`, parce que quatre features en ont besoin et qu'une
 * feature n'importe jamais une autre feature. Ici ne restent que les calculs dont ce
 * tableau de bord est le seul consommateur.
 *
 * **Ce module est le seul endroit qui sait ce que « entrée » veut dire.** Le serveur
 * accepte les noms et les rôles, les persiste et les rend, mais n'en fait rien : il
 * ne publie ni `entries` ni `exits`. Deux conséquences voulues :
 *
 * - corriger un libellé ou un rôle après coup est **instantané** et ne demande pas
 *   de relancer l'analyse. Un mot ne doit pas changer un chiffre du serveur ;
 * - la règle de classement n'existe pas en double. Le dépôt documente cette famille
 *   de bug plus que toute autre : deux copies d'une règle finissent par diverger, et
 *   c'est un passage qui change de colonne selon l'écran qui le montre. C'est
 *   exactement pourquoi `isEntryRow` ci-dessous est **exportée** plutôt que
 *   réécrite chez chacun de ses lecteurs : deux fichiers qui décident chacun ce
 *   qu'est un sens d'entrée finiraient par diverger.
 *
 * Tout ici est **dérivé** de `stats.byLine` et de la géométrie courante, jamais
 * accumulé en parallèle (invariant 3).
 */

import type {
  AnalysisStats,
  CountingLine,
  DirectionRole,
  DirectionSign,
  DirectionTally,
} from "@/shared/api/contracts";
import {
  DIRECTION_SIGNS,
  EMPTY_DIRECTION_TALLY,
  directionName,
  directionRole,
} from "@/shared/lib/directions";

/** Un sens de ligne, prêt à afficher : son identité, son rôle et ses compteurs. */
export interface DirectionRow {
  lineId: string;
  lineName: string;
  color: string;
  sign: DirectionSign;
  name: string;
  role: DirectionRole;
  tally: DirectionTally;
  /** Part de ce sens **dans sa ligne**, ou `null` si la ligne n'a rien compté. */
  shareOfLine: number | null;
  /** Part de ce sens dans **tous** les passages, ou `null` s'il n'y en a aucun. */
  shareOfTotal: number | null;
  /** Passages par minute sur la durée analysée. `null` sous le seuil publiable. */
  perMinute: number | null;
}

/** En dessous de trois secondes, un débit extrapolé n'est pas publiable. */
export const RATE_MIN_ELAPSED_MS = 3_000;

/**
 * Toutes les rangées de sens, une par ligne et par sens — donc deux par ligne.
 *
 * **Les deux sens sont toujours présents**, y compris à zéro. Une rangée absente se
 * lirait comme « pas d'information » alors qu'un sens jamais emprunté est une
 * information : la voie est à sens unique, ou la ligne est mal posée.
 */
export function directionRows(
  stats: AnalysisStats,
  lines: readonly CountingLine[],
): DirectionRow[] {
  const rows: DirectionRow[] = [];
  for (const line of lines) {
    const lineTally = stats.byLine[line.id];
    for (const sign of DIRECTION_SIGNS) {
      const tally = lineTally?.byDirection[sign] ?? EMPTY_DIRECTION_TALLY;
      rows.push({
        lineId: line.id,
        lineName: line.name,
        color: line.color,
        sign,
        name: directionName(line, sign),
        role: directionRole(line, sign),
        tally,
        shareOfLine:
          lineTally === undefined || lineTally.total === 0 ? null : tally.total / lineTally.total,
        shareOfTotal: stats.crossings === 0 ? null : tally.total / stats.crossings,
        perMinute:
          stats.analysedSceneMs < RATE_MIN_ELAPSED_MS
            ? null
            : Math.round((tally.total / (stats.analysedSceneMs / 60_000)) * 100) / 100,
      });
    }
  }
  return rows;
}

/** Le bilan entrées / sorties d'un carrefour, tel que les rôles le déclarent. */
export interface FlowBalance {
  entries: number;
  exits: number;
  /** `entries - exits`. Positif = la zone se remplit, négatif = elle se vide. */
  net: number;
  /** Passages sur des sens marqués « interdit ». Comptés, et signalés ailleurs. */
  forbidden: number;
  /** Passages sur des sens marqués « passage » — comptés, hors bilan, voulus. */
  transit: number;
  /** Passages sur des sens sans rôle déclaré — un rôle oublié, jamais un choix. */
  neutral: number;
  /**
   * Un sens **entrée ou sortie** a-t-il été déclaré quelque part ?
   *
   * Sinon, l'écran affiche « — ». La définition est restée exactement celle-là
   * malgré l'arrivée de `transit` et `forbidden`, et c'est délibéré : une géométrie
   * entièrement en « comptage seul » n'a pas de bilan de carrefour à montrer, et
   * afficher `0` y dirait « personne n'entre » au lieu de « ce n'est pas un
   * carrefour ». C'est la même honnêteté que le `null` de `LineFlow.entries`.
   */
  declared: boolean;
}

/**
 * Un sens marqué « entrée » — le seul prédicat qui décide ce qui compte comme une
 * entrée, réutilisé par `flowBalance` et par le bilan par ligne. L'exporter plutôt
 * que le laisser inline est ce qui empêche ces calculs de diverger silencieusement
 * si l'un d'eux change un jour de condition.
 *
 * **Il ne décide plus du chiffre de tête** : depuis ADR 0045 « Passages globaux »
 * compte des véhicules distincts et ne lit aucun rôle. Le bilan entrées / sorties
 * qu'il sert reste entier — cartes de ligne, Statistique, colonnes du registre.
 */
export function isEntryRow(row: DirectionRow): boolean {
  return row.role === "entry";
}

/**
 * Agrège les passages par rôle de sens.
 *
 * `declared` existe pour une raison d'honnêteté : sans rôle posé, `entries` et
 * `exits` valent tous deux zéro, et deux zéros se lisent comme « aucun véhicule
 * n'entre ni ne sort » alors que la vérité est « personne ne l'a encore dit ». Les
 * cartes affichent donc « — » et invitent à déclarer les rôles.
 */
export function flowBalance(stats: AnalysisStats, lines: readonly CountingLine[]): FlowBalance {
  let entries = 0;
  let exits = 0;
  let forbidden = 0;
  let transit = 0;
  let neutral = 0;
  let declared = false;

  for (const row of directionRows(stats, lines)) {
    if (isEntryRow(row)) {
      declared = true;
      entries += row.tally.total;
    } else if (row.role === "exit") {
      declared = true;
      exits += row.tally.total;
    } else if (row.role === "forbidden") {
      forbidden += row.tally.total;
    } else if (row.role === "transit") {
      transit += row.tally.total;
    } else {
      neutral += row.tally.total;
    }
  }

  return { entries, exits, net: entries - exits, forbidden, transit, neutral, declared };
}
