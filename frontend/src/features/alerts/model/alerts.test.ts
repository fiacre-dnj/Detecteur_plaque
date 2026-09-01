/**
 * Le journal d'alertes : sa clé de dédoublonnage, son ordre, sa borne.
 *
 * Trois propriétés qui ont chacune un mode de panne visible à l'écran : une clé
 * trop large fait disparaître un aller-retour interdit, une clé trop étroite remplit
 * la pile du même véhicule cinq fois par seconde, et un tri absent fait remonter en
 * tête une alerte sans qu'il se soit rien passé.
 */

import { describe, expect, it } from "bun:test";

import type { CrossingEvent } from "@/shared/api/contracts";
import type { LineRule } from "@/shared/lib/lineRules";
import type { Violation } from "@/shared/lib/lineViolations";

import {
  alertFromPlateHit,
  alertScore,
  alertFromVehicleMatch,
  alertFromViolation,
  crossingsBefore,
  mergeAlerts,
  sortAlerts,
} from "./alerts";
import type { PlateHit } from "./plateWatch";

const RULE: LineRule = {
  lineId: "l1",
  lineName: "Voie nord",
  color: "#539df5",
  kind: "oneway",
  forbiddenSigns: ["negative"],
  allowedClasses: null,
  restricted: true,
};

function crossing(overrides: Partial<CrossingEvent> = {}): CrossingEvent {
  return {
    lineId: "l1",
    globalId: 7,
    trackId: 3,
    label: "car",
    category: "vehicle",
    direction: -1,
    timestampMs: 12_000,
    frameIndex: 300,
    plateText: null,
    plateTextScore: null,
    ...overrides,
  };
}

function violation(overrides: Partial<CrossingEvent> = {}): Violation {
  return { kind: "wrong-way", crossing: crossing(overrides), rule: RULE };
}

const HIT: PlateHit = {
  globalId: 7,
  label: "car",
  plateText: "AB-123-CD",
  plateTextScore: 0.9,
  watched: "ab123cd",
  match: "exact",
};

describe("clés de dédoublonnage", () => {
  it("un aller-retour interdit produit deux alertes", () => {
    // Invariant 6 : deux passages sont deux faits. Une clé qui les fondrait ferait
    // disparaître la moitié de ce qu'on demande de signaler.
    const merged = mergeAlerts(
      [],
      [violation({ timestampMs: 12_000 }), violation({ timestampMs: 18_000 })].map(
        alertFromViolation,
      ),
    );

    expect(merged).toHaveLength(2);
  });

  it("le même franchissement republié n'en ajoute pas un second", () => {
    const first = mergeAlerts([], [alertFromViolation(violation())]);
    const again = mergeAlerts(first, [alertFromViolation(violation())]);

    expect(again).toHaveLength(1);
    // Rendu **par référence** : un aperçu qui n'apporte rien ne doit pas faire
    // rerendre la pile cinq fois par seconde.
    expect(again).toBe(first);
  });

  it("une plaque republiée à chaque image garde sa date d'origine", () => {
    // Sans cela, l'alerte remonterait en tête de liste à chaque aperçu, sans qu'il
    // se soit rien passé.
    const first = mergeAlerts([], [alertFromPlateHit(HIT, 4_000)]);
    const again = mergeAlerts(first, [alertFromPlateHit(HIT, 9_000)]);

    expect(again).toHaveLength(1);
    expect(again[0]?.timestampMs).toBe(4_000);
  });

  it("la même plaque sur deux véhicules produit deux alertes", () => {
    const merged = mergeAlerts(
      [],
      [alertFromPlateHit(HIT, 4_000), alertFromPlateHit({ ...HIT, globalId: 9 }, 5_000)],
    );

    expect(merged).toHaveLength(2);
  });
});

describe("ordre et borne", () => {
  it("insère à sa date, plus récent en tête, même arrivé en désordre", () => {
    // Depuis ADR 0038 un franchissement porte la date de son intersection avec le
    // trait : deux passages peuvent arriver dans deux trames SSE différentes en
    // ordre inverse de leurs dates.
    const merged = mergeAlerts(
      [alertFromViolation(violation({ timestampMs: 20_000 }))],
      [alertFromViolation(violation({ timestampMs: 5_000, globalId: 8 }))],
    );

    expect(merged.map((alert) => alert.timestampMs)).toEqual([20_000, 5_000]);
  });

  it("garde les plus récentes quand la borne est atteinte", () => {
    const many = Array.from({ length: 5 }, (_, index) =>
      alertFromViolation(violation({ timestampMs: index * 1_000, globalId: index })),
    );

    expect(mergeAlerts([], many, 2).map((alert) => alert.timestampMs)).toEqual([4_000, 3_000]);
    expect(sortAlerts(many, 2).map((alert) => alert.timestampMs)).toEqual([4_000, 3_000]);
  });
});

describe("gravité", () => {
  it("une correspondance probable avertit, une exacte alerte", () => {
    expect(alertFromPlateHit(HIT, 0).severity).toBe("critical");
    expect(alertFromPlateHit({ ...HIT, match: "partial" }, 0).severity).toBe("warning");
  });
});

describe("crossingsBefore", () => {
  it("s'arrête à la tête de lecture, borne incluse", () => {
    const all = [crossing({ timestampMs: 1_000 }), crossing({ timestampMs: 3_000 })];

    expect(crossingsBefore(all, 1_000)).toHaveLength(1);
    expect(crossingsBefore(all, 3_000)).toHaveLength(2);
  });
});

describe("alertFromVehicleMatch", () => {
  const vehicle = {
    globalId: 12,
    label: "car",
    firstSeenMs: 4200,
    matchScore: 0.83,
    plateText: null,
    plateTextScore: null,
  };

  it("ne met ni instant ni score dans sa clé", () => {
    // **Le test qui empêche le tiroir de se remplir du même véhicule.** Un véhicule
    // ressemblant est un *état*, republié à chaque aperçu SSE — soit une fois par
    // seconde — et son score s'améliore quand une meilleure vue est encodée. Une clé
    // qui porterait l'un ou l'autre produirait une carte par republication.
    const first = alertFromVehicleMatch(vehicle, "exact");
    const later = alertFromVehicleMatch(
      { ...vehicle, firstSeenMs: 9000, matchScore: 0.91 },
      "exact",
    );
    expect(first.key).toBe(later.key);
  });

  it("distingue deux véhicules", () => {
    expect(alertFromVehicleMatch(vehicle, "exact").key).not.toBe(
      alertFromVehicleMatch({ ...vehicle, globalId: 13 }, "exact").key,
    );
  });

  it("date de la première apparition et non de la meilleure vue", () => {
    // C'est là qu'il faut amener la tête de lecture pour vérifier, et c'est stable :
    // l'instant de la meilleure vue se déplace quand l'encodeur en retient une autre.
    expect(alertFromVehicleMatch(vehicle, "exact").timestampMs).toBe(4200);
  });

  it("porte la gravité de sa force, pas de son score", () => {
    expect(alertFromVehicleMatch(vehicle, "exact").severity).toBe("critical");
    expect(alertFromVehicleMatch(vehicle, "partial").severity).toBe("warning");
  });

  it("ne met aucune ligne en cause", () => {
    // Une ressemblance n'a rien à voir avec la géométrie : lui attribuer une ligne
    // ferait apparaître le véhicule dans le filtre « Ligne » du tiroir d'alertes.
    const alert = alertFromVehicleMatch(vehicle, "exact");
    expect(alert.line).toBeNull();
    expect(alert.direction).toBeNull();
    expect(alert.watched).toBeNull();
  });
});

describe("alertScore", () => {
  const vehicle = {
    globalId: 12,
    label: "car",
    firstSeenMs: 4200,
    matchScore: 0.83,
    plateText: null,
    plateTextScore: null,
  };

  it("chiffre la ressemblance depuis la source vivante, jamais depuis l'alerte", () => {
    // **Le test qui empêche un score figé.** `mergeAlerts` garde la première
    // occurrence d'une clé ; si la carte lisait l'alerte, elle afficherait encore
    // 0,83 pendant que le registre affiche 0,91 pour le même véhicule.
    const alert = alertFromVehicleMatch(vehicle, "exact");

    expect(alertScore(alert, { matchScore: 0.91 })).toEqual({ kind: "match", value: 0.91 });
    expect(alertScore(alert)).toBeNull();
  });

  it("chiffre la lecture d'une plaque recherchée, et retombe sur l'alerte", () => {
    // Le repli n'est pas décoratif : pendant l'analyse le registre de l'aperçu est
    // restreint aux franchisseurs (ADR 0026), et une plaque recherchée peut
    // appartenir à un véhicule à l'arrêt, donc absent de la carte des scores.
    const alert = alertFromPlateHit(HIT, 1_000);

    expect(alertScore(alert, { plateTextScore: 0.96 })).toEqual({ kind: "read", value: 0.96 });
    expect(alertScore(alert)).toEqual({ kind: "read", value: 0.9 });
  });

  it("ne chiffre pas une infraction", () => {
    // Un franchissement est un fait observé, pas une hypothèse : un pourcentage y
    // répondrait à une question que personne ne pose, et ferait douter d'un fait
    // certain. La plaque qu'il porte n'est qu'un renseignement de contexte.
    const alert = alertFromViolation(violation({ plateTextScore: 0.88 }));

    expect(alertScore(alert, { plateTextScore: 0.88, matchScore: 0.7 })).toBeNull();
  });

  it("distingue une lecture nulle d'une lecture absente", () => {
    // `0 %` est une mesure — la lecture a eu lieu et ne vaut rien — là où l'absence
    // dit « rien à chiffrer ». Les fondre effacerait le seul chiffre qui explique
    // pourquoi une correspondance est annoncée « probable ».
    const alert = alertFromPlateHit({ ...HIT, plateTextScore: 0 }, 1_000);

    expect(alertScore(alert)).toEqual({ kind: "read", value: 0 });
    expect(alertScore(alertFromPlateHit({ ...HIT, plateTextScore: null }, 1_000))).toBeNull();
  });
});
