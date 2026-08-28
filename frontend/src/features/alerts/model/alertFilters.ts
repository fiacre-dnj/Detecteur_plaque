/**
 * Lire un journal d'alertes sur trois axes : **quoi**, **qui**, **où**.
 *
 * Le panneau n'offrait qu'une facette — « Tout / Infractions / Plaques » — qui
 * répond à la seule question qu'on ne se pose pas : sur un carrefour chargé, on
 * cherche « les camions qui remontent la voie de bus », pas « les infractions ».
 * Trois axes qui se composent donnent cette phrase en trois clics.
 *
 * **Ce module filtre, il ne compte pas.** Les totaux affichés dans le résumé
 * viennent de `shared/lib/violationTally.ts`, dérivés de `stats` et sans plafond ;
 * les comptes rendus ici décrivent le **journal**, borné à `ALERT_LIMIT`. Les deux
 * répondent à deux questions différentes — « combien y en a-t-il eu » et « combien
 * cette liste en montre » — et les confondre ferait plafonner un total en silence
 * (invariant 3, un défaut que ce dépôt a déjà payé).
 *
 * **Les options sont dérivées du journal, jamais énumérées d'avance.** Une facette
 * « Camion » proposée sur une analyse sans camion serait un bouton qui ne fait
 * rien ; et une liste écrite en dur ici divergerait du catalogue du serveur, ce que
 * le dépôt refuse partout ailleurs (`ClassPicker`, `lineRules`).
 */

import type { Alert, AlertKind } from "./alerts";

/**
 * Ce que l'utilisateur a choisi de voir.
 *
 * `null` sur chaque axe veut dire « tout », **jamais** « rien » : c'est la même
 * distinction que le `null` d'`allowedClassIds`, et se tromper de repli viderait la
 * liste au lieu de la laisser entière.
 */
export interface AlertFilter {
  /** Natures retenues, ou `null` — toutes. */
  kind: AlertKind | null;
  /** Classe COCO **votée** du véhicule, ou `null` — tous les types. */
  label: string | null;
  /** Ligne concernée, ou `null` — toutes. Une alerte de plaque n'a pas de ligne. */
  lineId: string | null;
}

/** Rien de filtré — l'état d'ouverture du panneau. */
export const NO_FILTER: AlertFilter = Object.freeze({
  kind: null,
  label: null,
  lineId: null,
});

/** Un axe est-il actif ? Décide de l'affichage du bouton « Tout effacer ». */
export function isFiltering(filter: AlertFilter): boolean {
  return filter.kind !== null || filter.label !== null || filter.lineId !== null;
}

/**
 * Les alertes retenues, **dans l'ordre d'entrée**.
 *
 * L'ordre du journal est déjà le bon (`mergeAlerts` insère trié, `sortAlerts` trie)
 * et le reclasser ici masquerait à l'appelant la propriété d'ADR 0038 : l'ordre
 * d'émission d'un franchissement n'est pas celui de sa date.
 *
 * **Rendu par référence quand rien n'est filtré** : le panneau se rerend à chaque
 * aperçu SSE, et un tableau neuf à chaque fois casserait les mémos en aval pour
 * une liste identique. Même discipline que `filterByPlate` au registre.
 */
export function filterAlerts(
  alerts: readonly Alert[],
  filter: AlertFilter,
): readonly Alert[] {
  if (!isFiltering(filter)) return alerts;
  return alerts.filter(
    (alert) =>
      (filter.kind === null || alert.kind === filter.kind) &&
      (filter.label === null || alert.label === filter.label) &&
      // Une alerte de plaque n'a **pas** de ligne : filtrer par ligne l'écarte,
      // ce qui est juste — la question posée est « que s'est-il passé sur cette
      // ligne », et une plaque reconnue ne s'est passée sur aucune.
      (filter.lineId === null || alert.line?.id === filter.lineId),
  );
}

/** Une option de facette : sa valeur, son compte dans le journal. */
export interface AlertFacet<T> {
  value: T;
  count: number;
}

/**
 * Les trois listes d'options, avec leurs comptes.
 *
 * Calculées en **un seul parcours** : le journal est republié à chaque aperçu, et
 * trois parcours par rafraîchissement sur deux cents entrées seraient trois fois
 * le travail pour la même réponse.
 *
 * Les comptes portent sur le journal **entier**, jamais sur la liste déjà filtrée.
 * Des comptes qui rétrécissent à mesure qu'on filtre empêchent de savoir ce qu'on
 * trouverait en changeant d'axe — et c'est précisément ce qu'on veut savoir avant
 * de cliquer.
 */
export interface AlertFacets {
  kinds: readonly AlertFacet<AlertKind>[];
  labels: readonly AlertFacet<string>[];
  lines: readonly AlertFacet<{ id: string; name: string; color: string }>[];
}

export function alertFacets(alerts: readonly Alert[]): AlertFacets {
  const kinds = new Map<AlertKind, number>();
  const labels = new Map<string, number>();
  const lines = new Map<string, { name: string; color: string; count: number }>();

  for (const alert of alerts) {
    kinds.set(alert.kind, (kinds.get(alert.kind) ?? 0) + 1);
    labels.set(alert.label, (labels.get(alert.label) ?? 0) + 1);
    if (alert.line === null) continue;
    const known = lines.get(alert.line.id);
    if (known === undefined) {
      lines.set(alert.line.id, { name: alert.line.name, color: alert.line.color, count: 1 });
    } else {
      known.count += 1;
    }
  }

  return {
    // L'ordre est celui de la **première apparition**, donc celui du journal :
    // stable d'un rafraîchissement à l'autre. Trier par compte ferait permuter les
    // puces sous le curseur à chaque aperçu, sur une barre qu'on est en train de
    // cliquer.
    kinds: [...kinds].map(([value, count]) => ({ value, count })),
    labels: [...labels].map(([value, count]) => ({ value, count })),
    lines: [...lines].map(([id, entry]) => ({
      value: { id, name: entry.name, color: entry.color },
      count: entry.count,
    })),
  };
}
