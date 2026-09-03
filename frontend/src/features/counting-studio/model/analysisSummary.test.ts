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
  // Aucune classe petite : `BASE` ne doit porter **aucun** avertissement, sinon les
  // tests qui en attendent un ne prouveraient plus rien.
  smallClassLabels: [],
  // `null` = le réglage du serveur, le défaut de l'écran.
  inferenceImgsz: null,
  lineCount: 2,
  zoneCount: 0,
  ruledLineCount: 0,
  range: FULL_RANGE,
  detectPlates: false,
  readPlateText: false,
  watchedPlateCount: 0,
  analysisSpeed: 1,
  // Le défaut depuis ADR 0049 : un plafond absolu ici ferait porter à `BASE` une
  // contradiction entre les deux bridages, et « tout est réglé » cesserait d'être vrai.
  maxAnalysisFps: null,
  // 1080p : la définition à partir de laquelle une vue de circulation cesse de
  // condamner l'ANPR. `BASE` ne doit porter aucun avertissement, donc pas moins.
  sourceHeight: 1080,
};

function row(input: Partial<AnalysisSummaryInput>, label: string) {
  const found = analysisSummaryRows({ ...BASE, ...input }).find((item) => item.label === label);
  if (found === undefined) throw new Error(`Aucune rangée « ${label} »`);
  return found;
}

describe("analysisSummaryRows", () => {
  it("rend les sept rangées, dans l'ordre de lecture", () => {
    // « Définition d'analyse » vient juste après les objets comptés : c'est le
    // réglage qui décide si les petits d'entre eux seront vus, et le lire ailleurs
    // qu'à côté d'eux n'aurait aucun sens.
    expect(analysisSummaryRows(BASE).map((item) => item.label)).toEqual([
      "Modèle",
      "Objets comptés",
      "Définition d'analyse",
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
    expect(row({ maxAnalysisFps: 30 }, "Cadence").value).toBe("Temps réel · max 30 img/s");
    expect(row({ analysisSpeed: null, maxAnalysisFps: 30 }, "Cadence").value).toBe(
      "Illimitée · max 30 img/s",
    );
    expect(row({ analysisSpeed: 2, maxAnalysisFps: null }, "Cadence").value).toBe(
      "2× le temps réel",
    );
  });

  it("**avertit quand le plafond absolu peut battre la cadence de scène**", () => {
    // Les deux bridages se contredisent en silence : `ScenePacer` retient la
    // période la plus longue, donc « Temps réel · max 30 img/s » rend la moitié du
    // temps réel sur une source 60 fps. C'est le défaut qu'ADR 0049 a retiré.
    expect(row({ maxAnalysisFps: 30 }, "Cadence").warning).toContain("30 images par seconde");
  });

  it("n'avertit pas quand un seul des deux bridages existe", () => {
    // Sans plafond, rien ne peut contredire la cadence de scène ; sans cadence de
    // scène, le plafond est le seul juge et ne contredit personne.
    expect(row({ maxAnalysisFps: null }, "Cadence").warning).toBeUndefined();
    expect(row({ analysisSpeed: null, maxAnalysisFps: 30 }, "Cadence").warning).toBeUndefined();
  });
});

describe("l'avertissement de définition sur les plaques", () => {
  const plateRow = (input: AnalysisSummaryInput) =>
    analysisSummaryRows(input).find((candidate) => candidate.label === "Plaques");

  it("prévient qu'une source peu définie ne publiera aucune plaque", () => {
    // Mesuré sur ce dépôt en 720p : 29 véhicules, zéro plaque publiée, toutes les
    // raisons en `too_small` ou `not_detected` — pendant que l'étage de détection
    // consommait la majorité du budget.
    const plaques = plateRow({ ...BASE, detectPlates: true, readPlateText: true, sourceHeight: 720 });

    expect(plaques?.warning).toContain("720p");
    expect(plaques?.warning).toContain("plancher de lecture");
    // Une conséquence et deux gestes, jamais un interdit : `canAnalyse` reste le
    // seul juge du lancement, et un plan resserré en 720p lit très bien.
    expect(plaques?.warning).toContain("Resserrer le plan");
    expect(plaques?.warning).not.toContain("impossible");
  });

  it("prévient aussi sans OCR : c'est le repérage qui coûte cher", () => {
    const plaques = plateRow({ ...BASE, detectPlates: true, readPlateText: false, sourceHeight: 720 });

    expect(plaques?.value).toBe("Repérage seul");
    expect(plaques?.warning).toBeDefined();
  });

  it("se tait dès 1080p, et quand les plaques sont désactivées", () => {
    expect(
      plateRow({ ...BASE, detectPlates: true, readPlateText: true, sourceHeight: 1080 })?.warning,
    ).toBeUndefined();
    expect(plateRow({ ...BASE, detectPlates: false, sourceHeight: 480 })?.warning).toBeUndefined();
  });

  it("se tait tant qu'aucune vidéo n'est chargée", () => {
    // `null` n'est pas « petite » : sans source, il n'y a rien à annoncer, et un
    // avertissement sur une page vide se lirait comme un défaut de l'application.
    expect(
      plateRow({ ...BASE, detectPlates: true, readPlateText: true, sourceHeight: null })?.warning,
    ).toBeUndefined();
  });
});

describe("les petits objets", () => {
  const counted = (input: Partial<AnalysisSummaryInput>) => row(input, "Objets comptés");

  it("prévient quand un type petit est coché, en nommant les gestes", () => {
    // Le jumeau de l'avertissement des plaques, pour la classe de problème que ce
    // dépôt a mis le plus longtemps à nommer : ce n'est pas la taille d'un objet
    // dans la vidéo qui décide qu'il est détecté, c'est sa taille dans le réseau.
    const objets = counted({
      classLabels: ["Voiture", "Moto"],
      smallClassLabels: ["Moto"],
    });

    expect(objets?.value).toBe("Voiture · Moto");
    expect(objets?.warning).toContain("Moto");
    expect(objets?.warning).toContain("Définition d'analyse");
  });

  it("accorde la phrase au nombre de types concernés", () => {
    const un = counted({ classLabels: ["Moto"], smallClassLabels: ["Moto"] });
    const deux = counted({
      classLabels: ["Moto", "Personne"],
      smallClassLabels: ["Moto", "Personne"],
    });

    expect(un?.warning).toContain("est le plus petit objet");
    expect(deux?.warning).toContain("sont les plus petits objets");
  });

  it("dit une conséquence et des gestes, jamais un interdit", () => {
    // La doctrine de tous les avertissements de cette page : `canAnalyse` reste le
    // seul juge, et une phrase qui dirait « impossible » contredirait un bouton
    // parfaitement actif.
    const objets = counted({ classLabels: ["Moto"], smallClassLabels: ["Moto"] });

    expect(objets?.warning).not.toContain("impossible");
    expect(objets?.warning).not.toContain("Cochez");
  });

  it("se tait quand aucun type petit n'est coché", () => {
    expect(counted({ classLabels: ["Voiture"], smallClassLabels: [] })?.warning).toBeUndefined();
  });

  it("ne recopie aucune dimension de tenseur, qui deviendrait fausse", () => {
    // `640×384` était tentant, et cesserait d'être vrai dès que la définition
    // d'analyse change. Même précaution que le seuil de plaques, qui n'affirme
    // qu'une hauteur de source.
    const objets = counted({ classLabels: ["Moto"], smallClassLabels: ["Moto"] });

    expect(objets?.warning).not.toContain("640");
    expect(objets?.warning).not.toContain("384");
  });
});

describe("la définition d'analyse", () => {
  const definition = (input: Partial<AnalysisSummaryInput>) => row(input, "Définition d'analyse");

  it("est toujours affichée : elle rend deux jobs incomparables sans qu'on la lise", () => {
    expect(definition({ inferenceImgsz: null })?.value).toBe("Réglage du serveur");
    expect(definition({ inferenceImgsz: 960 })?.value).toBe("960 px");
  });

  it("n'avertit de rien : ce n'est pas une conséquence, c'est un fait", () => {
    expect(definition({ inferenceImgsz: 1280 })?.warning).toBeUndefined();
  });
});
