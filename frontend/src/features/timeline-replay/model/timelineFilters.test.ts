/**
 * Le filtrage, le regroupement et la densité de la chronologie.
 *
 * Le test qui compte le plus est `un filtre vide ne filtre rien`. La convention est
 * l'inverse d'une intersection naïve, et s'y tromper produit le pire des symptômes :
 * au premier rendu aucune puce n'est active, une intersection vide afficherait donc une
 * chronologie **vide** sur une analyse qui a compté, et l'utilisateur conclurait à une
 * panne du comptage.
 */

import { describe, expect, it } from "bun:test";

import type { CountingLine, CrossingEvent } from "@/shared/api/contracts";

import {
  NO_FILTER,
  chooseGroupMs,
  densityBuckets,
  filterCrossings,
  groupByTime,
  presentLabels,
  presentLines,
  toggle,
} from "./timelineFilters";

function crossing(
  overrides: Partial<CrossingEvent> & Pick<CrossingEvent, "timestampMs">,
): CrossingEvent {
  return {
    lineId: "l1",
    globalId: 1,
    trackId: 1,
    label: "car",
    category: "vehicle",
    direction: 1,
    frameIndex: 0,
    plateText: null,
    plateTextScore: null,
    ...overrides,
  };
}

function line(id: string, name = `Ligne ${id}`): CountingLine {
  return {
    id,
    name,
    color: "#539df5",
    zoneId: null,
    a: { x: 0, y: 500 },
    b: { x: 1920, y: 500 },
    positiveName: "",
    negativeName: "",
    positiveRole: "neutral",
    negativeRole: "neutral",
  };
}

const EVENTS = [
  crossing({ timestampMs: 500, lineId: "l1", direction: 1, label: "car" }),
  crossing({ timestampMs: 1_500, lineId: "l1", direction: -1, label: "truck" }),
  crossing({ timestampMs: 12_000, lineId: "l2", direction: 1, label: "car" }),
  crossing({ timestampMs: 30_000, lineId: "l2", direction: -1, label: "bus" }),
];

describe("filterCrossings", () => {
  it("**un filtre vide ne filtre rien**", () => {
    expect(filterCrossings(EVENTS, NO_FILTER)).toHaveLength(EVENTS.length);
  });

  it("retient une ligne", () => {
    const kept = filterCrossings(EVENTS, { ...NO_FILTER, lineIds: ["l2"] });

    expect(kept.map((event) => event.timestampMs)).toEqual([12_000, 30_000]);
  });

  it("retient un sens", () => {
    const kept = filterCrossings(EVENTS, { ...NO_FILTER, signs: ["negative"] });

    expect(kept.map((event) => event.timestampMs)).toEqual([1_500, 30_000]);
  });

  it("retient un type", () => {
    const kept = filterCrossings(EVENTS, { ...NO_FILTER, labels: ["truck"] });

    expect(kept).toHaveLength(1);
  });

  it("combine les critères en ET", () => {
    // Chaque critère restreint ; deux critères ne s'additionnent pas. Un OU
    // afficherait plus d'entrées après un second clic, ce qui se lirait à l'envers.
    const kept = filterCrossings(EVENTS, {
      lineIds: ["l2"],
      signs: ["positive"],
      labels: [],
    });

    expect(kept.map((event) => event.timestampMs)).toEqual([12_000]);
  });

  it("conserve l'ordre chronologique", () => {
    const kept = filterCrossings(EVENTS, { ...NO_FILTER, lineIds: ["l1", "l2"] });
    const times = kept.map((event) => event.timestampMs);

    expect([...times].sort((left, right) => left - right)).toEqual(times);
  });

  it("peut rendre une liste vide sur un critère sans correspondance", () => {
    // Le seul cas où la chronologie doit être vide, et le composant le dit.
    expect(filterCrossings(EVENTS, { ...NO_FILTER, labels: ["train"] })).toEqual([]);
  });
});

describe("toggle", () => {
  it("ajoute puis retire", () => {
    expect(toggle([], "l1")).toEqual(["l1"]);
    expect(toggle(["l1"], "l1")).toEqual([]);
    expect(toggle(["l1"], "l2")).toEqual(["l1", "l2"]);
  });

  it("ne mute pas l'entrée", () => {
    // Un état React muté sur place ne redéclenche pas de rendu : la puce resterait
    // grise après le clic.
    const before = ["l1"];
    toggle(before, "l2");

    expect(before).toEqual(["l1"]);
  });
});

describe("presentLabels et presentLines", () => {
  it("ne propose que les types réellement présents", () => {
    // Sept puces dont quatre ne filtrent jamais rien seraient du bruit.
    expect(presentLabels(EVENTS)).toEqual(["bus", "car", "truck"]);
  });

  it("ne propose que les lignes réellement franchies", () => {
    const lines = [line("l1"), line("l2"), line("l3")];

    expect(presentLines(EVENTS, lines).map((candidate) => candidate.id)).toEqual(["l1", "l2"]);
  });

  it("garde l'ordre de la géométrie et non celui des franchissements", () => {
    // Les puces doivent rester à la même place d'un rafraîchissement à l'autre, sinon
    // celle qu'on visait bouge sous le curseur pendant la lecture.
    const lines = [line("l2"), line("l1")];

    expect(presentLines(EVENTS, lines).map((candidate) => candidate.id)).toEqual(["l2", "l1"]);
  });
});

describe("densityBuckets", () => {
  it("ventile par sens", () => {
    const buckets = densityBuckets(EVENTS, 40_000);
    const totals = buckets.reduce(
      (sum, bucket) => ({
        positive: sum.positive + bucket.positive,
        negative: sum.negative + bucket.negative,
      }),
      { positive: 0, negative: 0 },
    );

    expect(totals).toEqual({ positive: 2, negative: 2 });
  });

  it("conserve les tranches vides", () => {
    // Les retirer tasserait l'axe du temps et ferait paraître le trafic continu là où
    // il y a eu une interruption. Un creux est une information.
    const buckets = densityBuckets(EVENTS, 40_000);

    expect(buckets.some((bucket) => bucket.total === 0)).toBe(true);
  });

  it("couvre toute la durée sans trou ni chevauchement", () => {
    const buckets = densityBuckets(EVENTS, 40_000);

    expect(buckets[0]?.startMs).toBe(0);
    for (let index = 1; index < buckets.length; index += 1) {
      expect(buckets[index]?.startMs).toBe(buckets[index - 1]?.endMs);
    }
    expect(buckets[buckets.length - 1]?.endMs).toBeGreaterThanOrEqual(40_000);
  });

  it("place un franchissement à l'instant exact de la fin dans la dernière tranche", () => {
    // Sans le bornage, il tomberait dans une tranche qui n'existe pas et disparaîtrait
    // du rail alors qu'il est dans la liste.
    const buckets = densityBuckets([crossing({ timestampMs: 40_000 })], 40_000);
    const last = buckets[buckets.length - 1];

    expect(last?.total).toBe(1);
  });

  it("rend une liste vide sur une durée nulle", () => {
    // Une vidéo dont les métadonnées ne donnent pas de durée. Diviser par zéro
    // produirait `Infinity` tranches.
    expect(densityBuckets(EVENTS, 0)).toEqual([]);
  });

  it("somme au nombre de franchissements", () => {
    const buckets = densityBuckets(EVENTS, 40_000);

    expect(buckets.reduce((sum, bucket) => sum + bucket.total, 0)).toBe(EVENTS.length);
  });
});

describe("groupByTime", () => {
  const format = (ms: number) => String(ms);

  it("regroupe par tranche et garde l'ordre", () => {
    const groups = groupByTime(EVENTS, 40_000, format);
    const flattened = groups.flatMap((group) => group.events.map((event) => event.timestampMs));

    expect(flattened).toEqual([500, 1_500, 12_000, 30_000]);
    // Les deux premiers tombent dans la même tranche de 5 s.
    expect(groups[0]?.events).toHaveLength(2);
  });

  it("omet les tranches sans franchissement", () => {
    // À l'inverse du rail : la liste est un inventaire, où un en-tête vide serait une
    // ligne à faire défiler pour rien.
    const groups = groupByTime(EVENTS, 40_000, format);

    expect(groups.every((group) => group.events.length > 0)).toBe(true);
  });

  it("rend une liste vide sans franchissement", () => {
    expect(groupByTime([], 40_000, format)).toEqual([]);
  });

  it("adapte la tranche à la durée", () => {
    // Sur trente secondes, grouper à la minute ne produirait qu'un en-tête ; sur une
    // heure, grouper à la seconde en produirait plus que de franchissements.
    expect(chooseGroupMs(30_000)).toBeLessThan(chooseGroupMs(3_600_000));
  });

  it("ne perd aucun franchissement", () => {
    const groups = groupByTime(EVENTS, 40_000, format);

    expect(groups.reduce((sum, group) => sum + group.events.length, 0)).toBe(EVENTS.length);
  });
});
