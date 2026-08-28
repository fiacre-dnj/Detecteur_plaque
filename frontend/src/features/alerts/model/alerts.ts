/**
 * Une alerte : ce que l'analyse **signale**, par opposition à ce qu'elle compte.
 *
 * Deux familles, un seul type, parce qu'elles partagent tout ce qui compte à
 * l'écran — un véhicule, un instant, une gravité, un motif :
 *
 * - une **infraction** — sens interdit, ligne infranchissable, voie réservée ;
 * - une **plaque recherchée** — correspondance exacte ou probable.
 *
 * **La couleur encode la gravité, l'icône encode la nature.** Rouge pour une
 * infraction et pour une plaque trouvée à coup sûr, orange pour une correspondance
 * probable. Distinguer les deux familles par la teinte demanderait de retenir une
 * convention de plus, alors que le titre et l'icône le disent déjà.
 *
 * **Le journal est borné et sa borne est annoncée.** Les compteurs, eux, ne le sont
 * pas : ils sont dérivés de `stats` (`shared/lib/violationTally.ts`),
 * exacts et sans plafond. Confondre les deux ferait plafonner un total en silence —
 * exactement le défaut qu'avait l'ancienne chronologie avant qu'on l'annonce.
 */

import type { CrossingEvent } from "@/shared/api/contracts";
import type { Violation, ViolationKind } from "@/shared/lib/lineViolations";
import { normalisePlate } from "@/shared/lib/plate";

import type { PlateHit } from "./plateWatch";

/** Entrées conservées. Au-delà, les plus anciennes sont oubliées — et on le dit. */
export const ALERT_LIMIT = 200;

/** Ce que l'alerte signale. */
export type AlertKind = ViolationKind | "plate-exact" | "plate-partial";

/**
 * Ce que l'alerte vaut.
 *
 * `critical` — un fait établi : le véhicule est passé là où c'est interdit, ou sa
 * plaque est exactement celle qu'on cherche. `warning` — un fait probable, qui
 * demande vérification. Il n'y a pas de troisième niveau : une alerte qu'on peut
 * ignorer n'est pas une alerte.
 */
export type AlertSeverity = "critical" | "warning";

/** La ligne concernée, réduite à ce que l'alerte affiche. */
export interface AlertLine {
  id: string;
  name: string;
  color: string;
}

export interface Alert {
  /**
   * Identité de l'alerte, et **c'est elle qui empêche les doublons**.
   *
   * Pour une infraction, c'est l'identité du franchissement : même véhicule, même
   * ligne, même sens, même instant. Un aller-retour interdit produit donc bien deux
   * alertes (invariant 6), et un même aperçu republié n'en produit qu'une.
   *
   * Pour une plaque, c'est le couple véhicule + plaque **normalisée** : le vote est
   * republié à chaque image d'aperçu, et sans cette clé la pile se remplirait du
   * même véhicule cinq fois par seconde.
   */
  key: string;
  kind: AlertKind;
  severity: AlertSeverity;
  /** Temps de **scène** (invariant 1), celui sur lequel la vidéo se cale. */
  timestampMs: number;
  globalId: number;
  /** Classe **votée** sur la vie du véhicule, en nom COCO. */
  label: string;
  plateText: string | null;
  plateTextScore: number | null;
  /** `null` sur une alerte de plaque : aucune ligne n'est en cause. */
  line: AlertLine | null;
  /** Signe du franchissement, `null` sur une alerte de plaque. */
  direction: number | null;
  /** L'entrée surveillée qui correspond, `null` sur une infraction. */
  watched: string | null;
}

/** L'alerte que porte une infraction. */
export function alertFromViolation(violation: Violation): Alert {
  const { crossing, rule } = violation;
  return {
    key: `v:${crossing.lineId}:${crossing.globalId}:${crossing.direction}:${crossing.timestampMs}`,
    kind: violation.kind,
    severity: "critical",
    timestampMs: crossing.timestampMs,
    globalId: crossing.globalId,
    label: crossing.label,
    // La plaque d'un franchissement est celle que le serveur **connaissait au
    // moment de compter** : souvent nulle, parce qu'un franchissement est émis
    // avant la passe OCR de la même image. L'autorité reste le registre, d'où une
    // alerte qui n'affiche cette plaque que lorsqu'elle existe.
    plateText: crossing.plateText,
    plateTextScore: crossing.plateTextScore,
    line: { id: rule.lineId, name: rule.lineName, color: rule.color },
    direction: crossing.direction,
    watched: null,
  };
}

/**
 * L'alerte que porte une plaque trouvée.
 *
 * `timestampMs` est fourni par l'appelant, et **il ne veut pas dire la même chose
 * dans les deux modes**, faute de mieux et volontairement :
 *
 * - **pendant l'analyse**, c'est l'instant où la correspondance a été remarquée. Le
 *   vote de plaque n'a pas d'instant — il porte sur toute la vie du véhicule
 *   (invariant 4) — donc « quand on l'a su » est la seule date honnête ;
 * - **après**, c'est la première apparition du véhicule, que le registre connaît.
 *   C'est l'endroit où amener la vidéo pour le voir arriver.
 *
 * Les deux mènent au même véhicule à l'écran ; la seconde est la plus utile, et
 * c'est celle qui reste affichée une fois l'analyse terminée.
 */
export function alertFromPlateHit(hit: PlateHit, timestampMs: number): Alert {
  return {
    key: `p:${hit.globalId}:${normalisePlate(hit.plateText)}`,
    kind: hit.match === "exact" ? "plate-exact" : "plate-partial",
    severity: hit.match === "exact" ? "critical" : "warning",
    timestampMs,
    globalId: hit.globalId,
    label: hit.label,
    plateText: hit.plateText,
    plateTextScore: hit.plateTextScore,
    line: null,
    direction: null,
    watched: hit.watched,
  };
}

/**
 * Ajoute des alertes au journal, **la plus récente en tête**.
 *
 * Même discipline qu'`appendCrossings`, et pour les mêmes deux raisons :
 *
 * - **insertion triée** et non empilement — depuis ADR 0038 un franchissement porte
 *   la date de son intersection avec le trait, et deux passages peuvent arriver
 *   dans deux trames SSE différentes en ordre inverse de leurs dates ;
 * - **rendu par référence** quand rien n'est nouveau, pour qu'un aperçu qui
 *   n'apporte aucune alerte ne fasse pas rerendre la pile cinq fois par seconde.
 *
 * **La première occurrence d'une clé gagne**, et c'est ce qui rend l'horodatage
 * stable : une alerte de plaque republiée à chaque image garderait sinon la date du
 * dernier aperçu, et remonterait en tête de liste sans qu'il se soit rien passé.
 */
export function mergeAlerts(
  log: readonly Alert[],
  incoming: readonly Alert[],
  limit: number = ALERT_LIMIT,
): readonly Alert[] {
  if (incoming.length === 0) return log;

  const seen = new Set(log.map((alert) => alert.key));
  const fresh = incoming.filter((alert) => !seen.has(alert.key));
  if (fresh.length === 0) return log;

  const merged = [...log];
  for (const alert of fresh) {
    if (seen.has(alert.key)) continue;
    seen.add(alert.key);
    let at = merged.findIndex((known) => known.timestampMs <= alert.timestampMs);
    if (at < 0) at = merged.length;
    merged.splice(at, 0, alert);
  }
  return merged.slice(0, limit);
}

/**
 * Les alertes du plus récent au plus ancien, bornées.
 *
 * Pour une source **complète** — un résultat rejoué — là où `mergeAlerts` sert un
 * flux. Le tri est fait ici et la borne appliquée **après** : borner d'abord
 * garderait les premières alertes du fichier plutôt que les dernières vues.
 */
export function sortAlerts(alerts: readonly Alert[], limit: number = ALERT_LIMIT): Alert[] {
  return [...alerts].sort((a, b) => b.timestampMs - a.timestampMs).slice(0, limit);
}

/** Une infraction, par opposition à une plaque trouvée. */
export function isViolation(alert: Alert): boolean {
  return alert.line !== null;
}

/**
 * Les franchissements d'un résultat complet jusqu'à la tête de lecture.
 *
 * Écrit ici plutôt que réutilisé de `crossingsUpTo` (`timeline-replay`), qui borne
 * à 200 **franchissements** : sur un carrefour chargé, les infractions les plus
 * anciennes disparaîtraient de la liste avant même d'avoir été cherchées. On filtre
 * d'abord, on borne ensuite — l'ordre inverse est le bug.
 */
export function crossingsBefore(
  crossings: readonly CrossingEvent[],
  timeMs: number,
): CrossingEvent[] {
  return crossings.filter((crossing) => crossing.timestampMs <= timeMs);
}
