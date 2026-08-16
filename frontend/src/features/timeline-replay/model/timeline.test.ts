/**
 * Ce que la chronologie garantit.
 *
 * Les deux règles testées ici décident de ce que l'utilisateur croit voir : quelle
 * entrée est « celle d'en ce moment », et à quel instant elle renvoie. Se tromper
 * sur l'une ou l'autre ne produit aucune erreur — juste une liste qui désigne le
 * mauvais passage, ce qui est exactement ce qu'on venait vérifier.
 */

import { describe, expect, it } from "bun:test";

import type { CrossingEvent } from "@/shared/api/contracts";

import { activeCrossingIndex, formatTimecode } from "./timeline";

function crossing(timestampMs: number): CrossingEvent {
  return {
    lineId: "l1",
    globalId: 1,
    trackId: 1,
    label: "car",
    category: "vehicle",
    direction: 1,
    timestampMs,
    frameIndex: Math.round(timestampMs / 40),
    plateText: null,
    plateTextScore: null,
  };
}

const EVENTS = [crossing(1000), crossing(2500), crossing(2540), crossing(9000)];

describe("activeCrossingIndex — l'entrée « en ce moment »", () => {
  it("rend -1 avant le premier franchissement", () => {
    // Mettre la première entrée en évidence dès l'instant zéro laisserait croire à
    // un franchissement au tout début de la vidéo.
    expect(activeCrossingIndex(EVENTS, 0)).toBe(-1);
    expect(activeCrossingIndex(EVENTS, 999)).toBe(-1);
  });

  it("désigne un franchissement **à** son horodatage, pas un instant après", () => {
    expect(activeCrossingIndex(EVENTS, 1000)).toBe(0);
  });

  it("n'annonce jamais un franchissement à venir", () => {
    // La règle est « le dernier déjà passé », pas « le plus proche ». À 2 400 ms, le
    // plus proche est celui de 2 500 — mais il n'a pas encore eu lieu, et le
    // surligner ferait douter des horodatages eux-mêmes.
    expect(activeCrossingIndex(EVENTS, 2400)).toBe(0);
    expect(activeCrossingIndex(EVENTS, 2499)).toBe(0);
  });

  it("distingue deux franchissements séparés de trois images", () => {
    // 2 500 et 2 540 ms : la même seconde. C'est le cas qui impose la décimale à
    // l'affichage, et il ne doit pas non plus confondre les deux entrées.
    expect(activeCrossingIndex(EVENTS, 2500)).toBe(1);
    expect(activeCrossingIndex(EVENTS, 2540)).toBe(2);
  });

  it("reste sur le dernier une fois la vidéo terminée", () => {
    expect(activeCrossingIndex(EVENTS, 60_000)).toBe(3);
  });

  it("rend -1 sur une liste vide plutôt que de lever", () => {
    expect(activeCrossingIndex([], 5000)).toBe(-1);
  });
});

describe("formatTimecode", () => {
  it("écrit mm:ss.d avec des champs de largeur fixe", () => {
    // Largeur fixe : sans elle, la colonne saute latéralement d'une entrée à
    // l'autre et la liste devient illisible pendant la lecture.
    expect(formatTimecode(0)).toBe("00:00.0");
    expect(formatTimecode(1000)).toBe("00:01.0");
    expect(formatTimecode(61_500)).toBe("01:01.5");
    expect(formatTimecode(600_000)).toBe("10:00.0");
  });

  it("garde le dixième, qui sépare deux franchissements de la même seconde", () => {
    expect(formatTimecode(2500)).toBe("00:02.5");
    expect(formatTimecode(2540)).toBe("00:02.5");
    expect(formatTimecode(2610)).toBe("00:02.6");
  });

  it("ramène un horodatage négatif à zéro", () => {
    // `-00:01.-2` serait illisible, et un instant antérieur au début de la scène
    // n'existe pas.
    expect(formatTimecode(-1)).toBe("00:00.0");
    expect(formatTimecode(-5000)).toBe("00:00.0");
  });
});
