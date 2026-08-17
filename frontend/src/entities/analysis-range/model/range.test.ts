import { describe, expect, test } from "bun:test";

import {
  FULL_RANGE,
  MIN_RANGE_MS,
  clampRange,
  describeRange,
  formatTimecode,
  isFullRange,
  parseTimecode,
  rangeDurationMs,
} from "./range";

describe("formatTimecode", () => {
  test("rend mm:ss sous l'heure, h:mm:ss au-delà", () => {
    expect(formatTimecode(0)).toBe("00:00");
    expect(formatTimecode(34_000)).toBe("00:34");
    expect(formatTimecode(300_000)).toBe("05:00");
    expect(formatTimecode(3_723_000)).toBe("1:02:03");
  });

  test("rend un tiret plutôt que NaN sur une durée inconnue", () => {
    // `duration` vaut `NaN` avant `loadedmetadata` et `Infinity` sur un flux :
    // les deux arrivent en vrai, et « NaN:NaN » fait douter de tout l'écran.
    expect(formatTimecode(Number.NaN)).toBe("--:--");
    expect(formatTimecode(Number.POSITIVE_INFINITY)).toBe("--:--");
    expect(formatTimecode(-1)).toBe("--:--");
  });
});

describe("parseTimecode", () => {
  test("accepte les quatre formes qu'on tape devant une vidéo", () => {
    expect(parseTimecode("90")).toBe(90_000);
    expect(parseTimecode("1:30")).toBe(90_000);
    expect(parseTimecode("01:30")).toBe(90_000);
    expect(parseTimecode("1:02:03")).toBe(3_723_000);
  });

  test("accepte la virgule décimale du clavier français", () => {
    expect(parseTimecode("1:30,5")).toBe(90_500);
    expect(parseTimecode("1:30.5")).toBe(90_500);
  });

  test("rend null plutôt que zéro sur une saisie qui ne veut rien dire", () => {
    // Le point qui compte : un `0` silencieux ramènerait la borne au début du
    // fichier sur une faute de frappe, et l'analyse partirait sur toute la vidéo
    // en affichant l'intervalle demandé.
    expect(parseTimecode("")).toBeNull();
    expect(parseTimecode("abc")).toBeNull();
    expect(parseTimecode("1:2:3:4")).toBeNull();
    expect(parseTimecode("-5")).toBeNull();
    // Une minute fractionnaire ne veut rien dire : seul le dernier champ le peut.
    expect(parseTimecode("1.5:30")).toBeNull();
  });
});

describe("clampRange", () => {
  const DUREE = 300_000;

  test("laisse passer un intervalle déjà valide", () => {
    expect(clampRange({ startMs: 34_000, endMs: 200_000 }, DUREE)).toEqual({
      startMs: 34_000,
      endMs: 200_000,
    });
  });

  test("ramène une fin au-delà de la vidéo à « jusqu'au bout »", () => {
    // Le cas de la vidéo remplacée par une plus courte : l'intervalle survit au
    // changement de fichier et pointerait au-delà de la fin, ce que le serveur
    // refuse en 422 sur un écran dont les deux champs paraissent valides.
    expect(clampRange({ startMs: 10_000, endMs: 900_000 }, DUREE).endMs).toBeNull();
  });

  test("une fin qui atteint la durée redevient « jusqu'au bout »", () => {
    // Sans cette normalisation, « toute la vidéo » se distinguerait de « de 0 à la
    // fin » sur un chiffre invisible, et l'écran afficherait un intervalle là où
    // l'utilisateur n'en a demandé aucun.
    const range = clampRange({ startMs: 0, endMs: DUREE }, DUREE);
    expect(range.endMs).toBeNull();
    expect(isFullRange(range)).toBe(true);
  });

  test("empêche les deux bornes de se croiser", () => {
    const range = clampRange({ startMs: 250_000, endMs: 100_000 }, DUREE);
    expect(range.startMs).toBe(100_000 - MIN_RANGE_MS);
    expect(range.endMs).toBe(100_000);
  });

  test("garde une seconde d'écart minimum", () => {
    const range = clampRange({ startMs: DUREE, endMs: null }, DUREE);
    expect(range.startMs).toBe(DUREE - MIN_RANGE_MS);
  });

  test("rend l'intervalle tel quel quand la durée n'est pas encore connue", () => {
    // Avant `loadedmetadata`, ramener à zéro effacerait un intervalle que
    // l'utilisateur vient de saisir — sur une durée qu'on ignore encore.
    const range = { startMs: 34_000, endMs: 200_000 };
    expect(clampRange(range, Number.NaN)).toEqual(range);
    expect(clampRange(range, Number.POSITIVE_INFINITY)).toEqual(range);
  });
});

describe("rangeDurationMs", () => {
  test("compte jusqu'à la fin de la vidéo quand la borne est absente", () => {
    expect(rangeDurationMs(FULL_RANGE, 300_000)).toBe(300_000);
    expect(rangeDurationMs({ startMs: 34_000, endMs: null }, 300_000)).toBe(266_000);
    expect(rangeDurationMs({ startMs: 34_000, endMs: 300_000 }, 300_000)).toBe(266_000);
  });
});

describe("describeRange", () => {
  test("dit les deux bornes **et** la durée", () => {
    // La durée répond à la vraie question — combien de temps l'analyse va
    // prendre — que « de 00:34 à 05:00 » oblige à calculer de tête.
    expect(describeRange({ startMs: 34_000, endMs: 300_000 }, 400_000)).toBe(
      "De 00:34 à 05:00 — 04:26 analysées",
    );
  });

  test("nomme la vidéo entière au lieu d'afficher 00:00 → fin", () => {
    expect(describeRange(FULL_RANGE, 300_000)).toBe("Toute la vidéo — 05:00");
  });
});
