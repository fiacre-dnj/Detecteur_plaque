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
export type AlertKind =
  | ViolationKind
  | "plate-exact"
  | "plate-partial"
  | "vehicle-exact"
  | "vehicle-partial"
  | "vehicle-rematch-exact"
  | "vehicle-rematch-partial";

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

/**
 * L'alerte d'un véhicule qui ressemble à l'image de requête.
 *
 * **La clé n'a pas de composante temporelle**, contrairement à celle d'une infraction :
 * un véhicule ressemblant est un *état* du véhicule, pas un événement daté. Sans cela
 * le même véhicule produirait une alerte par aperçu SSE, soit une par seconde.
 *
 * Elle ne porte pas non plus le score : celui-ci s'améliore quand une meilleure vue est
 * encodée, et l'inclure ferait réapparaître le même véhicule à chaque amélioration.
 */
export function alertFromVehicleMatch(vehicle: {
  globalId: number;
  label: string;
  plateText?: string | null;
  plateTextScore?: number | null;
  firstSeenMs: number;
  matchScore?: number | null;
}, strength: "exact" | "partial"): Alert {
  return {
    key: `m:${vehicle.globalId}`,
    kind: strength === "exact" ? "vehicle-exact" : "vehicle-partial",
    severity: strength === "exact" ? "critical" : "warning",
    // L'instant de **première apparition** et non celui de la meilleure vue : c'est
    // là qu'il faut amener la tête de lecture pour vérifier, et c'est stable — la
    // meilleure vue se déplace quand l'encodeur en retient une autre.
    timestampMs: vehicle.firstSeenMs,
    globalId: vehicle.globalId,
    label: vehicle.label,
    plateText: vehicle.plateText ?? null,
    plateTextScore: vehicle.plateTextScore ?? null,
    line: null,
    direction: null,
    watched: null,
  };
}

/** Ce qu'il faut d'un véhicule pour situer sa re-détection dans le temps. */
export interface CrossingBearer {
  crossedLines: readonly { lineId: string; direction: number; timestampMs: number }[];
  firstSeenMs: number;
}

/**
 * Le **premier** franchissement d'un véhicule, résolu sur le tracé courant.
 *
 * Trois points :
 *
 * - **le premier et non le plus récent** : c'est le moment où l'on a reconnu le
 *   véhicule, donc celui qu'il faut aller voir. Les passages suivants sont le même
 *   véhicule qui continue sa route ;
 * - **résolu contre `rules`, qui contient TOUTES les lignes** et pas seulement
 *   celles qui portent une règle. La re-détection vaut pour tout type de ligne, y
 *   compris « Comptage seul » ;
 * - **une ligne retirée du tracé ne fait pas disparaître l'alerte** : l'instant
 *   survit, la ligne devient `null`. Taire l'alerte ferait dépendre ce qu'on
 *   remarque d'une géométrie qu'on a le droit de modifier après coup.
 */
export function firstCrossingOf(
  vehicle: CrossingBearer,
  rules: ReadonlyMap<string, { lineId: string; lineName: string; color: string }>,
): { line: AlertLine | null; direction: number | null; timestampMs: number } {
  let earliest: { lineId: string; direction: number; timestampMs: number } | null = null;
  for (const crossing of vehicle.crossedLines) {
    if (earliest === null || crossing.timestampMs < earliest.timestampMs) earliest = crossing;
  }
  if (earliest === null) {
    // Ne devrait pas arriver — le serveur ne re-détecte que des franchisseurs — mais
    // un résultat rouvert n'a pas à faire confiance à cette invariance pour afficher
    // une carte. La première apparition est le repli honnête.
    return { line: null, direction: null, timestampMs: vehicle.firstSeenMs };
  }
  const rule = rules.get(earliest.lineId);
  return {
    line: rule ? { id: rule.lineId, name: rule.lineName, color: rule.color } : null,
    direction: earliest.direction,
    timestampMs: earliest.timestampMs,
  };
}

/**
 * L'alerte d'un véhicule qui ressemble à un franchisseur **antérieur** (ADR 0055).
 *
 * Trois choix qui ne se devinent pas :
 *
 * - **une carte par véhicule**, clé `r:<globalId>`, sans instant ni score. Un même
 *   véhicule qui franchit trois lignes ne remplit pas le tiroir de trois cartes
 *   identiques, et l'amélioration du score n'en crée pas une quatrième. Même raison
 *   que `alertFromVehicleMatch` juste au-dessus ;
 * - **datée du franchissement**, pas de la première apparition : l'alerte parle du
 *   passage sur le trait, et c'est là qu'il faut amener la tête de lecture pour
 *   vérifier. C'est la différence avec la recherche par image, où le véhicule est
 *   intéressant du début à la fin ;
 * - **elle nomme l'antécédent** (`rematchOf`). « 87 % » tout seul ne se vérifie sur
 *   rien ; « comme #12 — 87 % » se vérifie sur deux captures.
 */
export function alertFromRematch(
  vehicle: {
    globalId: number;
    label: string;
    plateText?: string | null;
    plateTextScore?: number | null;
    rematchOf?: number | null;
  },
  crossing: { line: AlertLine | null; direction: number | null; timestampMs: number },
  strength: "exact" | "partial",
): Alert {
  return {
    key: `r:${vehicle.globalId}`,
    kind: strength === "exact" ? "vehicle-rematch-exact" : "vehicle-rematch-partial",
    severity: strength === "exact" ? "critical" : "warning",
    timestampMs: crossing.timestampMs,
    globalId: vehicle.globalId,
    label: vehicle.label,
    plateText: vehicle.plateText ?? null,
    plateTextScore: vehicle.plateTextScore ?? null,
    line: crossing.line,
    direction: crossing.direction,
    // `watched` porte « ce qu'on cherchait » : ici, le véhicule déjà vu. C'est le
    // seul champ de l'`Alert` qui puisse le nommer, et `ALERT_LOOK` le lit déjà pour
    // composer sa phrase — un huitième champ pour la même idée serait un de trop.
    watched: vehicle.rematchOf == null ? null : `#${vehicle.rematchOf}`,
  };
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

/**
 * Les scores **vivants** d'un véhicule, republiés à chaque aperçu.
 *
 * En paramètre et non dans l'`Alert`, pour la raison exacte de `capturedMs` :
 * `mergeAlerts` garde la **première** occurrence d'une clé, donc un score porté par
 * l'alerte serait gelé à sa première publication. Or les deux bougent, et vers le
 * haut — la ressemblance quand une meilleure vue est encodée (ADR 0050), la confiance
 * de lecture quand une nouvelle vignette gagne le vote (invariant 4). Une alerte
 * figée à « 57 % » sous un registre qui affiche « 84 % » pour le même véhicule se lit
 * comme un désaccord entre deux écrans.
 */
export interface VehicleScores {
  matchScore?: number | null;
  rematchScore?: number | null;
  plateTextScore?: number | null;
}

/**
 * Le pourcentage de confiance d'une alerte, et **ce qu'il mesure**.
 *
 * Deux natures, jamais fondues en un nombre : `read` est la confiance de **lecture**
 * de la plaque votée, `match` la **similarité** à l'image recherchée. Les afficher
 * sous le même mot serait une erreur d'unité invisible, les deux chiffres étant
 * plausibles — le même mode de panne que « passages » contre « véhicules »
 * (invariant 3).
 */
export interface AlertScore {
  kind: "read" | "match";
  value: number;
}

/**
 * Ce que vaut la confiance affichée sur une carte, ou `null` — rien à afficher.
 *
 * **Rien sur une infraction**, et c'est délibéré : le franchissement est un fait
 * observé, pas une hypothèse, et la plaque qu'il porte n'est qu'un renseignement de
 * contexte — souvent absente, le franchissement étant émis avant la passe OCR de la
 * même image. Un pourcentage y répondrait à une question que personne ne pose, et
 * ferait douter d'un fait certain.
 *
 * Le score **vivant** l'emporte sur celui que l'alerte a figé ; le second sert de
 * repli, indispensable pour une plaque recherchée pendant l'analyse — le registre de
 * l'aperçu est restreint aux franchisseurs (ADR 0026), et un véhicule à l'arrêt n'y
 * figure pas.
 */
export function alertScore(alert: Alert, live?: VehicleScores | undefined): AlertScore | null {
  switch (alert.kind) {
    case "plate-exact":
    case "plate-partial": {
      const value = live?.plateTextScore ?? alert.plateTextScore;
      return value == null ? null : { kind: "read", value };
    }
    case "vehicle-exact":
    case "vehicle-partial": {
      // Aucun repli possible : l'alerte ne porte pas le score de ressemblance, et
      // c'est voulu — l'inclure ferait réapparaître le même véhicule à chaque
      // amélioration de sa meilleure vue.
      const value = live?.matchScore ?? null;
      return value === null ? null : { kind: "match", value };
    }
    case "vehicle-rematch-exact":
    case "vehicle-rematch-partial": {
      // Même unité que ci-dessus — une similarité cosinus — donc le même mot.
      // Inventer une troisième nature pour le même nombre serait une distinction
      // sans différence, et l'écart entre les deux est déjà porté par le titre.
      const value = live?.rematchScore ?? null;
      return value === null ? null : { kind: "match", value };
    }
    default:
      return null;
  }
}

/**
 * Une infraction, par opposition à ce que l'analyse ne fait que **remarquer**.
 *
 * **Décidé sur la nature et non sur la présence d'une ligne**, depuis qu'une
 * re-détection en porte une (ADR 0055). `alert.line !== null` a longtemps été un
 * raccourci exact — seules les infractions nommaient une ligne — et il est devenu
 * faux en silence : une re-détection aurait été comptée comme une infraction, donc
 * teintée et filtrée comme telle, sans que rien ne lève.
 */
export function isViolation(alert: Alert): boolean {
  return VIOLATION_KINDS.has(alert.kind);
}

const VIOLATION_KINDS = new Set<AlertKind>(["wrong-way", "closed-line", "reserved-lane"]);

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
