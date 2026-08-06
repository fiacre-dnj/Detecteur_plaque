/**
 * Formatage des durées, et la décision de masquer la timeline.
 *
 * Les cas limites testés ici arrivent tous en vrai : `video.duration` vaut `NaN`
 * avant `loadedmetadata` et `Infinity` sur un flux caméra. Afficher `NaN:NaN` dans
 * une interface est le genre de détail qui fait douter de tout le reste.
 */

import { describe, expect, it } from "bun:test";

import {
  ASSUMED_FPS,
  FRAME_STEP_S,
  PLAYBACK_RATES,
  formatRate,
  formatTime,
  hasSeekableDuration,
} from "./formatTime";

describe("formatTime", () => {
  it("formate en mm:ss", () => {
    expect(formatTime(0)).toBe("00:00");
    expect(formatTime(9)).toBe("00:09");
    expect(formatTime(75)).toBe("01:15");
    expect(formatTime(599)).toBe("09:59");
  });

  it("passe en h:mm:ss au-delà d'une heure", () => {
    expect(formatTime(3600)).toBe("1:00:00");
    expect(formatTime(3725)).toBe("1:02:05");
  });

  it("tronque les fractions de seconde au lieu d'arrondir", () => {
    // Arrondir afficherait « 00:01 » à 0,6 s, donc une seconde avant qu'elle
    // s'écoule : la position semblerait en avance sur l'image.
    expect(formatTime(0.9)).toBe("00:00");
    expect(formatTime(1.9)).toBe("00:01");
  });

  it("rend --:-- pour NaN, qui est la valeur avant loadedmetadata", () => {
    expect(formatTime(Number.NaN)).toBe("--:--");
  });

  it("rend --:-- pour une durée infinie, qui est celle d'un flux caméra", () => {
    expect(formatTime(Number.POSITIVE_INFINITY)).toBe("--:--");
  });

  it("rend --:-- pour une valeur négative plutôt qu'un temps absurde", () => {
    expect(formatTime(-5)).toBe("--:--");
  });
});

describe("hasSeekableDuration — masquer la timeline plutôt que mentir", () => {
  it("accepte une durée finie et positive", () => {
    expect(hasSeekableDuration(42.5)).toBe(true);
  });

  it("refuse la durée infinie d'un flux live", () => {
    // Un curseur sur une durée infinie n'a aucune position significative.
    expect(hasSeekableDuration(Number.POSITIVE_INFINITY)).toBe(false);
  });

  it("refuse NaN, la valeur d'avant les métadonnées", () => {
    expect(hasSeekableDuration(Number.NaN)).toBe(false);
  });

  it("refuse zéro", () => {
    expect(hasSeekableDuration(0)).toBe(false);
  });
});

describe("pas-à-pas image", () => {
  it("suppose 30 images par seconde, faute d'API pour la connaître", () => {
    // Le navigateur n'expose aucune cadence par fichier. Être légèrement à côté
    // fait atterrir sur l'image voisine : acceptable pour une inspection visuelle.
    expect(ASSUMED_FPS).toBe(30);
    expect(FRAME_STEP_S).toBeCloseTo(1 / 30, 10);
  });
});

describe("vitesses de lecture", () => {
  it("propose les sept vitesses de la spécification, 1× incluse", () => {
    expect([...PLAYBACK_RATES]).toEqual([0.1, 0.25, 0.5, 0.75, 1, 1.5, 2]);
  });

  it("affiche les vitesses avec une virgule décimale, en français", () => {
    // Un « 0.25× » dans une interface française est une faute visible.
    expect(formatRate(0.25)).toBe("0,25×");
    expect(formatRate(1)).toBe("1×");
    expect(formatRate(1.5)).toBe("1,5×");
  });
});
