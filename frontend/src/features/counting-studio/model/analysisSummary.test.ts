/**
 * Le récapitulatif d'avant-analyse.
 *
 * Les cas qui comptent sont ceux où un réglage va décevoir sans rien casser :
 * aucune classe cochée, aucune ligne tracée, des zones seules. Chacun doit porter
 * sa **conséquence**, jamais un simple « manquant » — c'est la différence entre un
 * écran qui explique et un écran qui gronde.
 */

import { describe, expect, it } from "bun:test";

import { FULL_RANGE } from "@/entities/analysis-range";

import { analysisSummaryRows, type AnalysisSummaryInput } from "./analysisSummary";

const BASE: AnalysisSummaryInput = {
  modelLabel: "YOLOv8 nano",
  classLabels: ["Voiture", "Camion"],
  lineCount: 2,
  zoneCount: 0,
  ruledLineCount: 0,
  range: FULL_RANGE,
  detectPlates: false,
  readPlateText: false,
  watchedPlateCount: 0,
  analysisSpeed: 1,
  maxAnalysisFps: 30,
};

function row(input: Partial<AnalysisSummaryInput>, label: string) {
  const found = analysisSummaryRows({ ...BASE, ...input }).find((item) => item.label === label);
  if (found === undefined) throw new Error(`Aucune rangée « ${label} »`);
  return found;
}

describe("analysisSummaryRows", () => {
  it("rend les six rangées, dans l'ordre de lecture", () => {
    expect(analysisSummaryRows(BASE).map((item) => item.label)).toEqual([
      "Modèle",
      "Objets comptés",
      "Géométrie",
      "Portion analysée",
      "Plaques",
      "Cadence",
    ]);
  });

  it("n'avertit de rien quand tout est réglé", () => {
    expect(analysisSummaryRows(BASE).every((item) => item.warning === undefined)).toBe(true);
  });

  it("dit la conséquence d'une sélection de classes vide", () => {
    const found = row({ classLabels: [] }, "Objets comptés");
    expect(found.value).toBe("Aucun");
    expect(found.warning).toContain("rien ne sera compté");
  });

  it("distingue « rien de tracé » de « des zones sans ligne »", () => {
    // Les deux sont analysables — `hasGeometry` accepte une zone seule — mais
    // aucune des deux ne produit de franchissement, et c'est ce qu'il faut dire.
    const nothing = row({ lineCount: 0, zoneCount: 0 }, "Géométrie");
    expect(nothing.value).toBe("Rien de tracé");
    expect(nothing.warning).toContain("aucun franchissement");

    const zonesOnly = row({ lineCount: 0, zoneCount: 2 }, "Géométrie");
    expect(zonesOnly.value).toBe("2 zones");
    expect(zonesOnly.warning).toContain("zones seules");
  });

  it("accorde le singulier du tracé et cumule lignes et zones", () => {
    expect(row({ lineCount: 1, zoneCount: 1 }, "Géométrie")).toEqual({
      label: "Géométrie",
      value: "1 ligne · 1 zone",
      warning: undefined,
    });
  });

  it("décrit l'intervalle par ses bornes, y compris une fin ouverte", () => {
    expect(row({}, "Portion analysée").value).toBe("Toute la vidéo");
    expect(row({ range: { startMs: 34_000, endMs: null } }, "Portion analysée").value).toBe(
      "À partir de 00:34",
    );
    expect(row({ range: { startMs: 34_000, endMs: 95_000 } }, "Portion analysée").value).toBe(
      "De 00:34 à 01:35",
    );
  });

  it("sépare le repérage des plaques de la lecture de leur texte", () => {
    expect(row({}, "Plaques").value).toBe("Désactivées");
    expect(row({ detectPlates: true }, "Plaques").value).toBe("Repérage seul");
    expect(row({ detectPlates: true, readPlateText: true }, "Plaques").value).toBe(
      "Repérage et lecture du texte",
    );
  });

  it("compose les deux bridages, et chacun vaut même quand l'autre est nul", () => {
    expect(row({}, "Cadence").value).toBe("Temps réel · max 30 img/s");
    expect(row({ analysisSpeed: null }, "Cadence").value).toBe("Illimitée · max 30 img/s");
    expect(row({ analysisSpeed: 2, maxAnalysisFps: null }, "Cadence").value).toBe(
      "2× le temps réel",
    );
  });
});
