/**
 * Les **agrégations** par sens de ligne : totaux, bilan entrées/sorties, mouvements.
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
 *   c'est un passage qui change de colonne selon l'écran qui le montre.
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
  VehicleRecord,
} from "@/shared/api/contracts";
import {
  DIRECTION_SIGNS,
  EMPTY_DIRECTION_TALLY,
  directionName,
  directionRole,
  signOf,
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
  /** Passages sur des sens sans rôle déclaré — du transit, ou un rôle oublié. */
  neutral: number;
  /** Un rôle a-t-il été déclaré quelque part ? Sinon, l'écran affiche « — ». */
  declared: boolean;
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
  let neutral = 0;
  let declared = false;

  for (const row of directionRows(stats, lines)) {
    if (row.role !== "neutral") declared = true;
    if (row.role === "entry") entries += row.tally.total;
    else if (row.role === "exit") exits += row.tally.total;
    else neutral += row.tally.total;
  }

  return { entries, exits, net: entries - exits, neutral, declared };
}

/** Un mouvement observé : entré par un sens, ressorti par un autre. */
export interface Movement {
  from: { lineId: string; sign: DirectionSign; name: string; lineName: string };
  to: { lineId: string; sign: DirectionSign; name: string; lineName: string };
  count: number;
  /** Part de ce mouvement dans tous les mouvements observés. */
  share: number;
}

/**
 * La matrice origine-destination — **la réponse directe au carrefour**.
 *
 * « Combien de véhicules entrés par la rue Nord sont ressortis par la rue Est ». Un
 * total par ligne ne peut pas y répondre : il faut savoir ce qu'un *même* véhicule a
 * franchi, et dans quel ordre.
 *
 * Dérivée de `vehicles[].crossedLines`, qui est déjà chronologique : chaque paire de
 * franchissements **consécutifs** est un mouvement. Rien de nouveau n'est transporté
 * sur le fil, et rien n'est accumulé côté serveur.
 *
 * Deux limites à énoncer plutôt qu'à masquer :
 *
 * - un véhicule qui franchit trois lignes produit **deux** mouvements, pas un. C'est
 *   le bon comportement pour un carrefour instrumenté ligne par ligne, mais cela
 *   veut dire que la somme des mouvements n'est pas un nombre de véhicules ;
 * - un véhicule qui n'a franchi qu'une ligne ne produit aucun mouvement. Il compte
 *   bien dans les totaux, il n'a simplement pas de trajet observable.
 *
 * Le registre n'existe que sur un résultat **complet** : l'aperçu SSE et le direct ne
 * le transportent pas. L'onglet le dit au lieu d'afficher une matrice vide.
 */
export function movements(
  vehicles: readonly VehicleRecord[],
  lines: readonly CountingLine[],
): Movement[] {
  const byId = new Map(lines.map((line) => [line.id, line]));
  const counts = new Map<string, Movement>();
  let total = 0;

  for (const vehicle of vehicles) {
    const crossings = vehicle.crossedLines;
    for (let index = 1; index < crossings.length; index += 1) {
      const previous = crossings[index - 1];
      const current = crossings[index];
      if (previous === undefined || current === undefined) continue;

      const fromLine = byId.get(previous.lineId);
      const toLine = byId.get(current.lineId);
      // Une ligne disparue du tracé : on ne peut plus nommer le mouvement, et lui
      // donner son identifiant brut mélangerait deux vocabulaires dans le tableau.
      if (fromLine === undefined || toLine === undefined) continue;

      const fromSign = signOf(previous.direction);
      const toSign = signOf(current.direction);
      const key = `${previous.lineId}:${fromSign}>${current.lineId}:${toSign}`;
      const existing = counts.get(key);
      if (existing === undefined) {
        counts.set(key, {
          from: {
            lineId: fromLine.id,
            sign: fromSign,
            name: directionName(fromLine, fromSign),
            lineName: fromLine.name,
          },
          to: {
            lineId: toLine.id,
            sign: toSign,
            name: directionName(toLine, toSign),
            lineName: toLine.name,
          },
          count: 1,
          share: 0,
        });
      } else {
        existing.count += 1;
      }
      total += 1;
    }
  }

  // La part est calculée à la fin, une fois le total connu : l'incrémenter au fil de
  // l'eau donnerait des parts qui ne somment pas à 1.
  const rows = [...counts.values()];
  for (const row of rows) row.share = total === 0 ? 0 : row.count / total;
  // Le mouvement dominant en tête : c'est celui qu'on cherche en ouvrant l'onglet.
  return rows.sort((left, right) => right.count - left.count);
}
