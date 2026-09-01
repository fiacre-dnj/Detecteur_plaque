/**
 * Le juge des captures — trois questions, et deux réponses non évidentes.
 *
 * La première est le changement de drapeau d'ADR 0051 : c'est l'instant, et non la
 * confiance de lecture, qui dit qu'une photo existe. La seconde est le repli du
 * résultat archivé, où l'absence de cause veut dire « plaque lue » et non « rien ».
 */

import { describe, expect, it } from "bun:test";

import { snapshotExists, snapshotHasPlateFace, snapshotReasonLabel } from "./snapshotKind";

describe("snapshotExists", () => {
  it("lit l'instant, qui est le drapeau", () => {
    expect(snapshotExists(12_400)).toBe(true);
    expect(snapshotExists(0)).toBe(true);
    expect(snapshotExists(null)).toBe(false);
  });

  it("traite un résultat archivé sans le champ comme sans capture", () => {
    // Avant cette fonctionnalité, le serveur posait score et instant ensemble : pas
    // de champ, pas de photo.
    expect(snapshotExists(undefined)).toBe(false);
  });

  it("accepte l'instant zéro, qui est une capture comme une autre", () => {
    // Un véhicule capturé sur la première image analysée porte `0`. Une garde écrite
    // en vérité JavaScript (`if (snapshotMs)`) le priverait de sa vignette — et ce
    // cas arrive à chaque analyse dont la première image porte déjà une lecture.
    expect(snapshotExists(0)).toBe(true);
  });
});

describe("snapshotHasPlateFace", () => {
  it("refuse la vignette de plaque à une capture de ressemblance", () => {
    // Il n'y avait pas de plaque à recadrer : la demander rendrait 409, et la modale
    // afficherait « Capture purgée » sur un état parfaitement normal.
    expect(snapshotHasPlateFace("appearance")).toBe(false);
  });

  it("l'accorde aux deux causes de plaque", () => {
    expect(snapshotHasPlateFace("plate_text")).toBe(true);
    expect(snapshotHasPlateFace("plate_box")).toBe(true);
  });

  it("l'accorde aussi quand la cause est absente", () => {
    // **Le repli conservateur, et il compte.** Sur un résultat archivé, la lecture
    // d'une plaque était la seule cause de capture possible, donc le `plate.jpg`
    // existe. Répondre `false` cacherait la vignette de tous les anciens résultats —
    // une régression invisible, la modale se contentant d'être plus courte.
    expect(snapshotHasPlateFace(undefined)).toBe(true);
    expect(snapshotHasPlateFace(null)).toBe(true);
  });
});

describe("snapshotReasonLabel", () => {
  it("nomme les trois causes en français", () => {
    expect(snapshotReasonLabel("plate_text")).toBe("plaque lue");
    expect(snapshotReasonLabel("plate_box")).toBe("plaque repérée, non lue");
    expect(snapshotReasonLabel("appearance")).toBe("retenue pour sa ressemblance");
  });

  it("retombe sur la lecture quand la cause est absente", () => {
    expect(snapshotReasonLabel(undefined)).toBe("plaque lue");
  });
});
