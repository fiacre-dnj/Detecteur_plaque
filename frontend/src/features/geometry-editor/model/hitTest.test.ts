/**
 * Les règles de priorité du test de sélection.
 *
 * Chacune correspond à une frustration précise si elle est fausse : une poignée
 * qu'on n'arrive pas à saisir, une zone qui vole le clic destiné à la ligne
 * dessinée par-dessus, ou un polygone qui se ferme sur une arête de longueur nulle.
 */

import { describe, expect, it } from "bun:test";

import type { CountingLine, Zone } from "@/shared/api/contracts";

import {
  HANDLE_RADIUS_SCREEN,
  closesPolygon,
  hitTest,
  repeatsLastVertex,
  selectionOf,
} from "./hitTest";

/** Échelle 1 : un pixel écran = un pixel source. Le cas le plus lisible. */
const SCALE = 1;

const line: CountingLine = {
  id: "l1",
  name: "L1",
  color: "#539df5",
  zoneId: null,
  a: { x: 100, y: 500 },
  b: { x: 900, y: 500 },
};

const zone: Zone = {
  id: "z1",
  name: "Z1",
  color: "#ffa42b",
  points: [
    { x: 200, y: 300 },
    { x: 800, y: 300 },
    { x: 800, y: 700 },
    { x: 200, y: 700 },
  ],
};

describe("priorité des poignées", () => {
  it("attrape la poignée A quand le curseur est dessus", () => {
    expect(hitTest({ x: 100, y: 500 }, [line], [], SCALE)).toEqual({
      kind: "lineHandle",
      id: "l1",
      end: "a",
    });
  });

  it("attrape la poignée B, distincte de A", () => {
    expect(hitTest({ x: 900, y: 500 }, [line], [], SCALE)).toEqual({
      kind: "lineHandle",
      id: "l1",
      end: "b",
    });
  });

  it("préfère la poignée au corps de la même ligne", () => {
    // La poignée est dessinée par-dessus le trait. Si le corps gagnait, on ne
    // pourrait jamais redimensionner une ligne — seulement la déplacer.
    const nearHandle = { x: 103, y: 502 };

    expect(hitTest(nearHandle, [line], [], SCALE).kind).toBe("lineHandle");
  });

  it("préfère un sommet de zone au corps d'une ligne qui passe dessus", () => {
    // Les poignées de **tous** types passent avant **tous** les corps : sinon un
    // sommet recouvert par une ligne devient insaisissable.
    const lineOverVertex: CountingLine = { ...line, a: { x: 0, y: 300 }, b: { x: 1900, y: 300 } };

    expect(hitTest({ x: 200, y: 300 }, [lineOverVertex], [zone], SCALE)).toEqual({
      kind: "zoneVertex",
      id: "z1",
      index: 0,
    });
  });

  it("attrape le bon index de sommet", () => {
    expect(hitTest({ x: 800, y: 700 }, [], [zone], SCALE)).toEqual({
      kind: "zoneVertex",
      id: "z1",
      index: 2,
    });
  });
});

describe("les lignes gagnent sur les zones", () => {
  it("sélectionne la ligne quand elle traverse une zone", () => {
    // Les lignes sont dessinées **au-dessus** des zones : c'est ce que
    // l'utilisateur voit, donc ce qu'il croit viser.
    expect(hitTest({ x: 500, y: 500 }, [line], [zone], SCALE)).toEqual({
      kind: "lineBody",
      id: "l1",
    });
  });

  it("sélectionne la zone quand aucune ligne n'est sous le curseur", () => {
    expect(hitTest({ x: 500, y: 350 }, [line], [zone], SCALE)).toEqual({
      kind: "zoneBody",
      id: "z1",
    });
  });

  it("ne sélectionne rien hors de toute forme", () => {
    expect(hitTest({ x: 1800, y: 100 }, [line], [zone], SCALE)).toEqual({ kind: "none" });
  });
});

describe("à égalité, la forme la plus récente gagne", () => {
  it("préfère la dernière ligne ajoutée", () => {
    // Elle est dessinée en dernier, donc au-dessus. Préférer la première rendrait
    // une ligne fraîchement tracée insaisissable là où elle en recouvre une autre.
    const older: CountingLine = { ...line, id: "old" };
    const newer: CountingLine = { ...line, id: "new" };

    expect(hitTest({ x: 500, y: 500 }, [older, newer], [], SCALE)).toEqual({
      kind: "lineBody",
      id: "new",
    });
  });

  it("préfère la dernière zone ajoutée", () => {
    const older: Zone = { ...zone, id: "old" };
    const newer: Zone = { ...zone, id: "new" };

    expect(hitTest({ x: 500, y: 350 }, [], [older, newer], SCALE)).toEqual({
      kind: "zoneBody",
      id: "new",
    });
  });
});

describe("le rayon suit l'échelle d'affichage", () => {
  it("agrandit la zone de préhension quand la vidéo est affichée petite", () => {
    // **Le point de la conversion.** Une vidéo 4K affichée dans un petit cadre a
    // une échelle élevée : un même geste de la souris couvre plus de pixels
    // source. Sans conversion, la sélection deviendrait impossible.
    const farInSource = { x: 100 + HANDLE_RADIUS_SCREEN * 3, y: 500 };

    expect(hitTest(farInSource, [line], [], 1).kind).toBe("lineBody");
    expect(hitTest(farInSource, [line], [], 4).kind).toBe("lineHandle");
  });

  it("resserre la préhension quand la vidéo est affichée grande", () => {
    // Échelle < 1 : la précision au pixel source est meilleure que le geste, donc
    // le rayon doit se resserrer pour rester à la mesure du geste.
    const nearHandle = { x: 100 + HANDLE_RADIUS_SCREEN * 0.8, y: 500 };

    expect(hitTest(nearHandle, [line], [], 1).kind).toBe("lineHandle");
    expect(hitTest(nearHandle, [line], [], 0.25).kind).toBe("lineBody");
  });
});

describe("selectionOf", () => {
  it("traduit chaque type de prise en sélection de panneau", () => {
    expect(selectionOf({ kind: "lineHandle", id: "l1", end: "a" })).toEqual({
      kind: "line",
      id: "l1",
    });
    expect(selectionOf({ kind: "lineBody", id: "l1" })).toEqual({ kind: "line", id: "l1" });
    expect(selectionOf({ kind: "zoneVertex", id: "z1", index: 0 })).toEqual({
      kind: "zone",
      id: "z1",
    });
    expect(selectionOf({ kind: "zoneBody", id: "z1" })).toEqual({ kind: "zone", id: "z1" });
    expect(selectionOf({ kind: "none" })).toBeNull();
  });
});

describe("fermeture d'un polygone en cours de tracé", () => {
  const draft = [
    { x: 100, y: 100 },
    { x: 300, y: 100 },
    { x: 300, y: 300 },
  ];

  it("se ferme par un clic sur le premier sommet", () => {
    // L'un des deux gestes de fermeture. L'autre est le double-clic : les deux
    // existent parce que les gens attendent l'un ou l'autre.
    expect(closesPolygon({ x: 102, y: 101 }, draft, SCALE)).toBe(true);
  });

  it("ne se ferme pas sur un clic ailleurs", () => {
    expect(closesPolygon({ x: 500, y: 500 }, draft, SCALE)).toBe(false);
  });

  it("ne se ferme pas avec moins de trois sommets — il n'y a pas de surface", () => {
    expect(closesPolygon({ x: 100, y: 100 }, [{ x: 100, y: 100 }], SCALE)).toBe(false);
    expect(
      closesPolygon(
        { x: 100, y: 100 },
        [
          { x: 100, y: 100 },
          { x: 300, y: 100 },
        ],
        SCALE,
      ),
    ).toBe(false);
  });

  it("détecte un clic répété sur le dernier sommet", () => {
    // **Le cas du double-clic.** Deux `pointerdown` arrivent avant le `dblclick` :
    // sans cette détection, le second ajoute un sommet au même endroit et la zone
    // fermée porte une arête de longueur nulle — invisible, mais dégénérée.
    expect(repeatsLastVertex({ x: 301, y: 302 }, draft, SCALE)).toBe(true);
    expect(repeatsLastVertex({ x: 500, y: 500 }, draft, SCALE)).toBe(false);
  });

  it("ne signale pas de répétition sur un brouillon vide", () => {
    expect(repeatsLastVertex({ x: 0, y: 0 }, [], SCALE)).toBe(false);
  });
});
