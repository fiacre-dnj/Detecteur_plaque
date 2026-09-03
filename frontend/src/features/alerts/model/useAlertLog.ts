/**
 * Le journal des alertes **pendant** que ça tourne.
 *
 * Il existe parce que le vivant n'est pas relisible : l'aperçu SSE ne porte que ce
 * qui vient de se passer, et la trame suivante l'a déjà remplacé. Une infraction
 * vue à 00:14 doit rester à l'écran jusqu'à ce qu'on l'ait lue — sinon la
 * fonctionnalité ne sert qu'à qui regardait au bon moment.
 *
 * **Une fois l'analyse terminée, ce journal n'est plus la source.** Le résultat
 * complet l'est, rejoué à la tête de lecture par `alertsFromResult`. Deux raisons :
 * le journal est borné alors que le résultat ne l'est pas, et un rôle de sens
 * corrigé après coup doit reclasser les alertes sans qu'on relance quoi que ce soit.
 *
 * **Il sert les deux modes.** Les infractions se dérivent des franchissements, que
 * le différé comme le direct publient ; les plaques, non — le direct n'a pas d'ANPR
 * du tout, donc `tracks` y arrive sans texte et aucune alerte de plaque n'en sort.
 */

import { useEffect, useRef, useState } from "react";

import type { CrossingEvent, TrackSnapshot, VehicleRecord } from "@/shared/api/contracts";
import type { LineRule } from "@/shared/lib/lineRules";
import { violations } from "@/shared/lib/lineViolations";
// La règle de ressemblance vit dans `shared/lib` parce que trois features la lisent —
// ce tiroir, le panneau de recherche et la colonne du registre. Une seule définition.
import { matches, matchStrength } from "@/shared/lib/vehicleMatch";

import {
  alertFromPlateHit,
  alertFromRematch,
  alertFromVehicleMatch,
  alertFromViolation,
  firstCrossingOf,
  mergeAlerts,
  type Alert,
} from "./alerts";
import { plateHits, type PlateBearer } from "./plateWatch";

/** Ce dont le journal a besoin à chaque trame d'aperçu. */
export interface AlertLogInput {
  /**
   * Les franchissements **de cette trame**, cumulés par le serveur depuis la
   * précédente — `preview.crossings` en différé, les derniers comptés en direct.
   */
  crossings: readonly CrossingEvent[];
  /**
   * Les pistes de l'aperçu **vivant**, jamais celles calées sur l'image affichée.
   *
   * Une alerte est un *événement* : elle suit le serveur. Une boîte est un *état* :
   * elle suit l'image. C'est la règle déjà écrite pour les compteurs, le journal et
   * les flashs de ligne, et l'appliquer ici évite qu'une plaque trouvée attende le
   * décodage d'une image pour être signalée.
   */
  tracks: readonly TrackSnapshot[];
  /** Temps de scène de la trame — la date des alertes de plaque de ce tour. */
  timestampMs: number;
  rules: ReadonlyMap<string, LineRule>;
  watchlist: readonly string[];
  /**
   * Les véhicules de l'aperçu **vivant**, ou `null` — l'aperçu n'en porte pas encore.
   *
   * C'est là que vit `matchScore` : les pistes d'une image ne le portent pas, la
   * ressemblance étant votée sur la meilleure vue de la vie du véhicule et non
   * mesurée à chaque image. `null` signifie « inchangé » côté serveur (ADR 0026), donc
   * l'appelant doit passer la dernière liste connue — ce que `carryVehicles` fait déjà.
   */
  vehicles: readonly VehicleRecord[] | null;
  /**
   * Seuil de ressemblance, ou `null` — aucune recherche par image en cours.
   *
   * `null` et non `0` : le second signalerait **tout** véhicule encodé, y compris ceux
   * dont le score est négatif, donc la totalité du trafic.
   */
  matchThreshold: number | null;
  /**
   * Seuil de **re-détection**, ou `null` — l'analyse ne la demande pas.
   *
   * Comme `matchThreshold`, il vit côté client sur un score brut : le baisser après
   * coup fait apparaître les candidats sans réanalyser.
   */
  rematchThreshold: number | null;
  /**
   * Ce qui identifie l'analyse en cours. Un changement **vide** le journal.
   *
   * `null` remet aussi à zéro : c'est l'état « aucune analyse ». Sans cela, relancer
   * une analyse sur une autre vidéo afficherait les alertes de la précédente
   * au-dessus des nouvelles, avec des horodatages qui ne désignent plus rien.
   */
  runId: string | null;
}

/**
 * Accumule les alertes de la course en cours, la plus récente en tête.
 *
 * L'accumulation vit dans un état React et non dans un `useMemo` : les trames
 * d'aperçu ne portent que du **nouveau**, donc il n'y a rien à recalculer, seulement
 * à retenir.
 */
export function useAlertLog(input: AlertLogInput): readonly Alert[] {
  const [log, setLog] = useState<readonly Alert[]>([]);
  const previousRun = useRef<string | null>(null);

  // Le vidage est fait au rendu et non dans un effet : un effet laisserait passer
  // une trame — celle du nouveau job — par-dessus les alertes de l'ancien, visible
  // à l'écran pendant une image.
  if (previousRun.current !== input.runId) {
    previousRun.current = input.runId;
    if (log.length > 0) setLog([]);
  }

  const { crossings, rules } = input;
  useEffect(() => {
    if (crossings.length === 0) return;
    const found = violations(crossings, rules).map(alertFromViolation);
    if (found.length === 0) return;
    setLog((previous) => mergeAlerts(previous, found));
  }, [crossings, rules]);

  const { tracks, watchlist, timestampMs } = input;
  useEffect(() => {
    if (watchlist.length === 0 || tracks.length === 0) return;
    const hits = plateHits(tracks.map(asPlateBearer), watchlist);
    if (hits.length === 0) return;
    // `timestampMs` volontairement **hors** des dépendances : il change à chaque
    // trame, et le relire ici ne servirait qu'à redater une alerte déjà connue —
    // que `mergeAlerts` refuse de toute façon. Le mettre en dépendance ferait
    // recalculer les correspondances à chaque image pour un résultat identique.
    setLog((previous) =>
      mergeAlerts(
        previous,
        hits.map((hit) => alertFromPlateHit(hit, timestampMs)),
      ),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tracks, watchlist]);

  const { vehicles, matchThreshold } = input;
  useEffect(() => {
    if (matchThreshold === null || vehicles === null || vehicles.length === 0) return;
    const found: Alert[] = [];
    for (const vehicle of vehicles) {
      if (!matches(vehicle.matchScore, matchThreshold)) continue;
      found.push(
        alertFromVehicleMatch(
          vehicle,
          matchStrength(vehicle.matchScore as number, matchThreshold),
        ),
      );
    }
    if (found.length === 0) return;
    // `mergeAlerts` dédoublonne sur `key`, qui ne porte ni instant ni score : le même
    // véhicule republié à chaque aperçu, ou dont la ressemblance s'améliore, ne
    // produit donc qu'une seule carte. Sans cela le tiroir se remplirait du même
    // véhicule une fois par seconde.
    setLog((previous) => mergeAlerts(previous, found));
  }, [vehicles, matchThreshold]);

  const { rematchThreshold } = input;
  useEffect(() => {
    if (rematchThreshold === null || vehicles === null || vehicles.length === 0) return;
    const found: Alert[] = [];
    for (const vehicle of vehicles) {
      if (vehicle.rematchOf == null) continue;
      if (!matches(vehicle.rematchScore, rematchThreshold)) continue;
      found.push(
        alertFromRematch(
          vehicle,
          firstCrossingOf(vehicle, rules),
          matchStrength(vehicle.rematchScore as number, rematchThreshold),
        ),
      );
    }
    if (found.length === 0) return;
    // Même dédoublonnage que la recherche par image : la clé ne porte ni instant ni
    // score, donc le même véhicule republié à chaque aperçu — ou dont la
    // ressemblance s'améliore quand une meilleure vue est encodée — ne produit
    // qu'une carte.
    setLog((previous) => mergeAlerts(previous, found));
  }, [vehicles, rematchThreshold, rules]);

  return log;
}

/**
 * Une piste vue comme porteuse de plaque.
 *
 * `identityLabel` et non `label` : c'est la classe **votée** sur la vie du véhicule
 * (invariant 4). La lecture de l'image courante vacille, et une alerte qui
 * changerait de type entre deux trames se lirait comme deux véhicules.
 */
function asPlateBearer(track: TrackSnapshot): PlateBearer {
  return {
    globalId: track.globalId,
    label: track.identityLabel,
    plateText: track.plateText,
    plateTextScore: track.plateTextScore,
  };
}
