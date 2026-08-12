/**
 * Le flash qui relie une ligne tracée au compteur qui monte.
 *
 * Ces tests portent sur la partie pure : l'extinction, et la façon dont une salve
 * de franchissements devient un ensemble de flashs. La boucle d'animation, elle,
 * n'a rien à décider.
 */

import { describe, expect, it } from "bun:test";

import type { CrossingEvent } from "@/shared/api/contracts";

import { FLASH_DURATION_MS, activeFlashes, flashIntensity, startFlashes } from "./lineFlashes";

function crossing(lineId: string, direction = 1, globalId = 1): CrossingEvent {
  return {
    lineId,
    globalId,
    trackId: globalId,
    label: "car",
    category: "vehicle" as const,
    direction,
    timestampMs: 1000,
    frameIndex: 25,
    // Le clignotement d'une ligne ne connaît pas les plaques ; le littéral doit
    // seulement rester complet.
    plateText: null,
    plateTextScore: null,
  };
}

describe("flashIntensity", () => {
  it("part de 1 et s'éteint à 0", () => {
    expect(flashIntensity(0)).toBe(1);
    expect(flashIntensity(FLASH_DURATION_MS)).toBe(0);
  });

  it("ne rend jamais de valeur hors de [0, 1]", () => {
    // Un onglet remis au premier plan peut produire un `elapsed` de plusieurs
    // secondes : une intensité négative multiplierait la largeur du halo par un
    // nombre négatif, et le canvas lèverait.
    expect(flashIntensity(-100)).toBe(1);
    expect(flashIntensity(FLASH_DURATION_MS * 10)).toBe(0);
  });

  it("décroît sans jamais remonter", () => {
    const samples = [0, 100, 300, 600, 899].map((elapsed) => flashIntensity(elapsed));
    const sorted = [...samples].sort((a, b) => b - a);

    expect(samples).toEqual(sorted);
  });

  it("s'éteint immédiatement si la durée est nulle", () => {
    expect(flashIntensity(0, 0)).toBe(0);
  });
});

describe("startFlashes", () => {
  it("allume une ligne par franchissement", () => {
    const starts = startFlashes([crossing("l1"), crossing("l2", -1, 2)], 1000);

    expect(starts.map((start) => start.lineId).sort()).toEqual(["l1", "l2"]);
  });

  it("n'allume qu'un flash par ligne dans une même salve", () => {
    // Trois voitures franchissant la même ligne dans la même image donneraient
    // trois halos superposés — c'est-à-dire un seul, mais calculé trois fois.
    const starts = startFlashes(
      [crossing("l1", 1, 1), crossing("l1", 1, 2), crossing("l1", 1, 3)],
      1000,
    );

    expect(starts).toHaveLength(1);
  });

  it("retient le sens, pour que le flash puisse le dire", () => {
    const [start] = startFlashes([crossing("l1", -1)], 1000);

    expect(start?.direction).toBe(-1);
  });
});

describe("activeFlashes", () => {
  it("ne garde que ce qui brûle encore", () => {
    const starts = [
      { lineId: "vieux", direction: 1, startedAt: 0 },
      { lineId: "recent", direction: 1, startedAt: 900 },
    ];

    const active = activeFlashes(starts, 1000);

    expect([...active.keys()]).toEqual(["recent"]);
  });

  it("rend une table vide quand tout est éteint", () => {
    // Vide et non `null` : le canvas dessine alors zéro flash, sans branche.
    expect(activeFlashes([{ lineId: "l1", direction: 1, startedAt: 0 }], 5000).size).toBe(0);
  });
});
