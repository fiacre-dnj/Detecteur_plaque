/**
 * Les trois axes de lecture du journal d'alertes.
 *
 * Le mode de panne visé n'est pas « le filtre ne filtre pas » — il se voit tout de
 * suite. C'est le repli inversé : un axe à `null` qui viderait la liste au lieu de
 * la laisser entière, ou des comptes calculés sur la liste déjà filtrée, qui
 * empêcheraient de savoir ce qu'on trouverait en changeant d'axe.
 */

import { describe, expect, it } from "bun:test";

import type { Alert } from "./alerts";
import { NO_FILTER, alertFacets, filterAlerts, isFiltering } from "./alertFilters";

function violation(overrides: Partial<Alert> = {}): Alert {
  return {
    key: "v:1",
    kind: "wrong-way",
    severity: "critical",
    timestampMs: 1_000,
    globalId: 1,
    label: "car",
    plateText: null,
    plateTextScore: null,
    line: { id: "nord", name: "Voie nord", color: "#539df5" },
    direction: -1,
    watched: null,
    ...overrides,
  };
}

function plate(overrides: Partial<Alert> = {}): Alert {
  return violation({
    key: "p:9",
    kind: "plate-exact",
    line: null,
    direction: null,
    watched: "AB-123-CD",
    plateText: "AB123CD",
    ...overrides,
  });
}

describe("filterAlerts", () => {
  it("rend la liste PAR RÉFÉRENCE quand rien n'est filtré", () => {
    // Le panneau se rerend à chaque aperçu SSE. Un tableau neuf à chaque fois
    // casserait les mémos en aval pour une liste identique — même discipline que
    // `filterByPlate` au registre.
    const alerts = [violation(), plate()];

    expect(filterAlerts(alerts, NO_FILTER)).toBe(alerts);
  });

  it("filtre par nature", () => {
    const alerts = [violation(), plate()];

    expect(filterAlerts(alerts, { ...NO_FILTER, kind: "plate-exact" })).toHaveLength(1);
    expect(filterAlerts(alerts, { ...NO_FILTER, kind: "wrong-way" })[0]?.key).toBe("v:1");
  });

  it("filtre par type de véhicule — la classe votée", () => {
    // C'est la demande : « voir les types d'infraction selon les véhicules ».
    const alerts = [violation(), violation({ key: "v:2", label: "truck" })];

    expect(filterAlerts(alerts, { ...NO_FILTER, label: "truck" })).toHaveLength(1);
  });

  it("compose les trois axes", () => {
    const alerts = [
      violation({ key: "a", label: "truck" }),
      violation({ key: "b", label: "car" }),
      violation({
        key: "c",
        label: "truck",
        line: { id: "sud", name: "Voie sud", color: "#f5a623" },
      }),
    ];
    const found = filterAlerts(alerts, {
      kind: "wrong-way",
      label: "truck",
      lineId: "nord",
    });

    expect(found).toHaveLength(1);
    expect(found[0]?.key).toBe("a");
  });

  it("écarte les alertes de plaque dès qu'une ligne est choisie", () => {
    // Une plaque reconnue ne s'est passée sur aucune ligne : la question « que
    // s'est-il passé sur cette ligne » ne la concerne pas. La garder ferait
    // apparaître, sous un filtre de ligne, une carte sans ligne.
    const found = filterAlerts([violation(), plate()], { ...NO_FILTER, lineId: "nord" });

    expect(found).toHaveLength(1);
    expect(found[0]?.kind).toBe("wrong-way");
  });

  it("laisse tout passer sur un axe à null, jamais l'inverse", () => {
    // Le repli inversé viderait le panneau à l'ouverture. C'est la même
    // distinction que le `null` d'`allowedClassIds`, et elle se trompe de la même
    // façon.
    const alerts = [violation(), plate()];

    expect(filterAlerts(alerts, NO_FILTER)).toHaveLength(2);
    expect(isFiltering(NO_FILTER)).toBe(false);
    expect(isFiltering({ ...NO_FILTER, label: "car" })).toBe(true);
  });
});

describe("alertFacets", () => {
  it("compte chaque axe sur le journal entier", () => {
    const facets = alertFacets([
      violation({ key: "a", label: "car" }),
      violation({ key: "b", label: "truck", kind: "reserved-lane" }),
      violation({
        key: "c",
        label: "truck",
        line: { id: "sud", name: "Voie sud", color: "#f5a623" },
      }),
      plate({ key: "d", label: "bus" }),
    ]);

    expect(facets.kinds).toEqual([
      { value: "wrong-way", count: 2 },
      { value: "reserved-lane", count: 1 },
      { value: "plate-exact", count: 1 },
    ]);
    expect(facets.labels).toEqual([
      { value: "car", count: 1 },
      { value: "truck", count: 2 },
      { value: "bus", count: 1 },
    ]);
    expect(facets.lines).toHaveLength(2);
    expect(facets.lines[0]).toEqual({
      value: { id: "nord", name: "Voie nord", color: "#539df5" },
      count: 2,
    });
  });

  it("n'invente aucune ligne pour une alerte de plaque", () => {
    expect(alertFacets([plate()]).lines).toHaveLength(0);
  });

  it("garde l'ordre de première apparition, jamais celui des comptes", () => {
    // Trier par compte ferait permuter les puces sous le curseur à chaque aperçu,
    // sur une barre qu'on est justement en train de cliquer.
    const facets = alertFacets([
      violation({ key: "a", label: "bus" }),
      violation({ key: "b", label: "car" }),
      violation({ key: "c", label: "car" }),
    ]);

    expect(facets.labels.map((facet) => facet.value)).toEqual(["bus", "car"]);
  });
});
