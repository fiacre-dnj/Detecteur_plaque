/**
 * Réglages : persistance tolérante aux versions, et la sémantique de `null`.
 *
 * Les tests de lecture couvrent tous les moyens qu'un stockage a de mal tourner —
 * absent, illisible, d'une autre version, avec des types faux. Aucun ne doit lever :
 * un `localStorage` écrit par une version antérieure est le cas **normal** après une
 * mise à jour, et faire tomber l'écran de comptage pour un réglage mal formé serait
 * absurde.
 */

import { describe, expect, it } from "bun:test";

import {
  BOUNDS,
  DEFAULT_CONFIDENCE,
  DEFAULT_SETTINGS,
  SETTINGS_SCHEMA_VERSION,
  loadSettings,
  sanitiseClassIds,
  saveSettings,
  toRequest,
  type AnalysisSettings,
} from "./settings";

/** Faux stockage, pilotable et sans DOM. */
function fakeStorage(initial: string | null = null) {
  let value = initial;
  return {
    getItem: () => value,
    setItem: (_key: string, next: string) => {
      value = next;
    },
    read: () => value,
  };
}

/** Stockage qui lève, comme dans un iframe restreint. */
const throwingStorage = {
  getItem: (): string => {
    throw new Error("accès refusé");
  },
  setItem: (): void => {
    throw new Error("accès refusé");
  },
};

describe("loadSettings — jamais d'exception, toujours des valeurs utilisables", () => {
  it("rend les défauts sans stockage", () => {
    expect(loadSettings(null)).toEqual(DEFAULT_SETTINGS);
  });

  it("rend les défauts sur un stockage vide", () => {
    expect(loadSettings(fakeStorage())).toEqual(DEFAULT_SETTINGS);
  });

  it("rend les défauts sur un JSON illisible", () => {
    expect(loadSettings(fakeStorage("{ceci n'est pas du json"))).toEqual(DEFAULT_SETTINGS);
  });

  it("**rend les défauts sur un schéma d'une autre version**", () => {
    // Le cas normal après une mise à jour. On ne devine pas la forme ancienne :
    // une valeur relue sous un sens différent produirait une analyse dont les
    // réglages ne sont pas ceux que l'écran affiche.
    const stored = JSON.stringify({ version: 0, settings: { minHits: 9 } });

    expect(loadSettings(fakeStorage(stored)).minHits).toBe(DEFAULT_SETTINGS.minHits);
  });

  it("rend les défauts quand le stockage lève à la lecture", () => {
    // Accéder à `localStorage` **lève** dans un iframe restreint : ce n'est pas
    // seulement `null`, c'est une exception au premier accès.
    expect(loadSettings(throwingStorage)).toEqual(DEFAULT_SETTINGS);
  });

  it("rend les défauts sur un contenu qui n'est pas un objet", () => {
    expect(loadSettings(fakeStorage('"une chaîne"'))).toEqual(DEFAULT_SETTINGS);
    expect(loadSettings(fakeStorage("42"))).toEqual(DEFAULT_SETTINGS);
    expect(loadSettings(fakeStorage("null"))).toEqual(DEFAULT_SETTINGS);
  });

  it("relit les valeurs valides", () => {
    const stored = JSON.stringify({
      version: SETTINGS_SCHEMA_VERSION,
      settings: { modelId: "yolo11m", minHits: 4, detectPlates: true },
    });
    const loaded = loadSettings(fakeStorage(stored));

    expect(loaded.modelId).toBe("yolo11m");
    expect(loaded.minHits).toBe(4);
    expect(loaded.detectPlates).toBe(true);
  });

  it("ignore un champ du mauvais type au lieu de le propager", () => {
    // Un `Object.assign` global laisserait passer une chaîne là où un nombre est
    // attendu, et le serveur refuserait la requête en 422 sans que l'utilisateur
    // sache quel réglage est en cause.
    const stored = JSON.stringify({
      version: SETTINGS_SCHEMA_VERSION,
      settings: { minHits: "beaucoup", iouThreshold: null, modelId: 42 },
    });
    const loaded = loadSettings(fakeStorage(stored));

    expect(loaded.minHits).toBe(DEFAULT_SETTINGS.minHits);
    expect(loaded.iouThreshold).toBe(DEFAULT_SETTINGS.iouThreshold);
    expect(loaded.modelId).toBe(DEFAULT_SETTINGS.modelId);
  });

  it("borne une valeur hors intervalle au lieu de l'oublier", () => {
    // Une valeur légèrement hors bornes vient d'un changement de bornes entre
    // versions : la ramener respecte mieux l'intention que de l'ignorer.
    const stored = JSON.stringify({
      version: SETTINGS_SCHEMA_VERSION,
      settings: { minHits: 999, iouThreshold: -1 },
    });
    const loaded = loadSettings(fakeStorage(stored));

    expect(loaded.minHits).toBe(BOUNDS.minHits.max);
    expect(loaded.iouThreshold).toBe(BOUNDS.iouThreshold.min);
  });

  it("préserve un `null` explicite, distinct d'un champ absent", () => {
    // `null` veut dire « suivre le défaut » : c'est une valeur, pas une absence.
    const stored = JSON.stringify({
      version: SETTINGS_SCHEMA_VERSION,
      settings: { confidenceThreshold: null },
    });

    expect(loadSettings(fakeStorage(stored)).confidenceThreshold).toBeNull();
  });

  it("relit un plancher de lecture persisté, `0` compris", () => {
    // `0` est une valeur, pas une absence : « accepte toutes les lectures ». Un
    // relecteur qui le confondrait avec « non renseigné » remettrait silencieusement
    // le plancher du serveur sur un réglage que l'écran affiche à zéro.
    const stored = JSON.stringify({
      version: SETTINGS_SCHEMA_VERSION,
      settings: { plateTextConfidence: 0 },
    });

    expect(loadSettings(fakeStorage(stored)).plateTextConfidence).toBe(0);
  });

  it("reprend le défaut du plancher de lecture sur un stockage antérieur au champ", () => {
    // La fusion est champ par champ : un `localStorage` écrit avant ce réglage est le
    // cas **normal** après une mise à jour, pas une anomalie.
    const stored = JSON.stringify({
      version: SETTINGS_SCHEMA_VERSION,
      settings: { minHits: 4 },
    });

    expect(loadSettings(fakeStorage(stored)).plateTextConfidence).toBeNull();
  });
});

describe("saveSettings", () => {
  it("écrit la version avec les réglages", () => {
    const storage = fakeStorage();
    saveSettings({ ...DEFAULT_SETTINGS, minHits: 5 }, storage);
    const written = JSON.parse(storage.read() ?? "{}") as Record<string, unknown>;

    expect(written.version).toBe(SETTINGS_SCHEMA_VERSION);
  });

  it("fait un aller-retour fidèle", () => {
    const storage = fakeStorage();
    const settings: AnalysisSettings = {
      ...DEFAULT_SETTINGS,
      modelId: "yolo12l",
      confidenceThreshold: 0.6,
      detectPlates: true,
    };
    saveSettings(settings, storage);

    expect(loadSettings(storage)).toEqual(settings);
  });

  it("ne lève pas quand le stockage refuse l'écriture", () => {
    // Quota dépassé ou navigation privée : perdre une préférence n'est pas une
    // raison de faire échouer une analyse.
    expect(() => saveSettings(DEFAULT_SETTINGS, throwingStorage)).not.toThrow();
    expect(() => saveSettings(DEFAULT_SETTINGS, null)).not.toThrow();
  });
});

describe("toRequest — la traduction vers le serveur", () => {
  const LINES = [
    {
      id: "l1",
      name: "L",
      color: "#539df5",
      zoneId: null,
      positiveName: "",
      negativeName: "",
      positiveRole: "neutral" as const,
      negativeRole: "neutral" as const,
      a: { x: 0, y: 100 },
      b: { x: 200, y: 100 },
    },
  ];

  it("résout `null` en confiance par défaut, car le serveur refuse null", () => {
    // C'est le **seul** endroit où la résolution a lieu : plus tôt, on perdrait
    // l'information « je suis le défaut ».
    const request = toRequest(DEFAULT_SETTINGS, LINES, []);

    expect(request.confidenceThreshold).toBe(DEFAULT_CONFIDENCE);
  });

  it("respecte une confiance explicite", () => {
    const request = toRequest({ ...DEFAULT_SETTINGS, confidenceThreshold: 0.72 }, LINES, []);

    expect(request.confidenceThreshold).toBe(0.72);
  });


  it("n'envoie pas de confiance de plaque quand l'ANPR est désactivé", () => {
    // Un seuil de plaque sans lecture de plaque est un réglage sans effet : le
    // transmettre laisserait croire qu'il agit.
    const request = toRequest(
      { ...DEFAULT_SETTINGS, detectPlates: false, plateConfidence: 0.5 },
      LINES,
      [],
    );

    expect(request.plateConfidence).toBeNull();
  });

  it("transmet le plancher de lecture quand l'ANPR et l'OCR sont actifs", () => {
    const request = toRequest(
      { ...DEFAULT_SETTINGS, detectPlates: true, readPlateText: true, plateTextConfidence: 0.7 },
      LINES,
      [],
    );

    expect(request.plateTextConfidence).toBe(0.7);
  });

  it("n'envoie pas de plancher de lecture quand l'OCR est désactivée", () => {
    // Un plancher sur ce que l'OCR rend, sans OCR, est un réglage sans effet — même
    // règle que `plateConfidence` sans ANPR. Le laisser passer demanderait au serveur
    // d'arbitrer une incohérence que le client pouvait éviter.
    const request = toRequest(
      { ...DEFAULT_SETTINGS, detectPlates: true, readPlateText: false, plateTextConfidence: 0.7 },
      LINES,
      [],
    );

    expect(request.plateTextConfidence).toBeNull();
  });

  it("laisse `null` signifier « suivre le défaut du serveur »", () => {
    // `null` n'est pas `0` : l'un garde le plancher du déploiement (0,50), l'autre
    // accepte **toutes** les lectures. Les confondre publierait des plaques que le
    // serveur refusait jusque-là.
    const request = toRequest(
      { ...DEFAULT_SETTINGS, detectPlates: true, readPlateText: true },
      LINES,
      [],
    );

    expect(request.plateTextConfidence).toBeNull();
  });

  it("transmet un plancher de lecture nul, qui n'est pas une absence de réglage", () => {
    const request = toRequest(
      { ...DEFAULT_SETTINGS, detectPlates: true, readPlateText: true, plateTextConfidence: 0 },
      LINES,
      [],
    );

    expect(request.plateTextConfidence).toBe(0);
  });

  it("**désactive le masque quand aucune zone n'existe**", () => {
    // « Ignorer hors zone » sans zone masquerait toute l'image, et l'analyse
    // rendrait zéro véhicule sans que rien n'explique pourquoi.
    const request = toRequest({ ...DEFAULT_SETTINGS, maskOutsideZones: true }, LINES, []);

    expect(request.maskOutsideZones).toBe(false);
  });

  it("garde le masque quand une zone existe", () => {
    const zones = [
      {
        id: "z1",
        name: "Z",
        color: "#ffa42b",
        points: [
          { x: 0, y: 0 },
          { x: 10, y: 0 },
          { x: 10, y: 10 },
        ],
      },
    ];
    const request = toRequest({ ...DEFAULT_SETTINGS, maskOutsideZones: true }, LINES, zones);

    expect(request.maskOutsideZones).toBe(true);
  });

  it("transmet la géométrie telle quelle", () => {
    const request = toRequest(DEFAULT_SETTINGS, LINES, []);

    expect(request.lines).toEqual(LINES);
    expect(request.zones).toEqual([]);
  });

  it("analyse toute la vidéo quand aucun intervalle n'est demandé", () => {
    // Le défaut du quatrième argument **est** le comportement d'avant : qui ne
    // touche pas à l'intervalle retrouve exactement les chiffres qu'il avait.
    const request = toRequest(DEFAULT_SETTINGS, LINES, []);

    expect(request.startMs).toBe(0);
    expect(request.endMs).toBeNull();
  });

  it("transmet les deux bornes d'un intervalle", () => {
    const request = toRequest(DEFAULT_SETTINGS, LINES, [], {
      startMs: 34_000,
      endMs: 300_000,
    });

    expect(request.startMs).toBe(34_000);
    expect(request.endMs).toBe(300_000);
  });

  it("écarte un intervalle que le serveur refuserait en 422", () => {
    // Dernier filet avant l'envoi, comme pour les cadences : le serveur refuse un
    // début négatif et une fin qui précède le début, et un 422 sur un écran dont
    // toutes les valeurs paraissent valides n'aide personne. `clampRange` les a
    // normalement déjà rattrapés — ce garde couvre le chemin qui l'aurait évité.
    const invalide = toRequest(DEFAULT_SETTINGS, LINES, [], { startMs: -10, endMs: -1 });
    expect(invalide.startMs).toBe(0);
    expect(invalide.endMs).toBeNull();

    const inverse = toRequest(DEFAULT_SETTINGS, LINES, [], { startMs: 5_000, endMs: 2_000 });
    expect(inverse.endMs).toBeNull();
  });
});

describe("défauts alignés sur le serveur", () => {
  it("reprend les valeurs par défaut du backend", () => {
    // Un écart ici ferait que l'affichage du canvas (pointillés sous `minHits`) ne
    // correspondrait pas à ce que l'analyse fait réellement.
    expect(DEFAULT_SETTINGS.iouThreshold).toBe(0.45);
    expect(DEFAULT_SETTINGS.minHits).toBe(2);
    expect(DEFAULT_SETTINGS.maxLostMs).toBe(2_500);
    expect(DEFAULT_SETTINGS.frameStride).toBe(1);
    expect(DEFAULT_CONFIDENCE).toBe(0.35);
  });
});

describe("sanitiseClassIds — la sélection recalée sur le catalogue du serveur", () => {
  const CATALOGUE = [
    { id: 2, defaultSelected: true },
    { id: 3, defaultSelected: true },
    { id: 5, defaultSelected: true },
    { id: 7, defaultSelected: true },
    { id: 1, defaultSelected: false },
    { id: 0, defaultSelected: false },
  ];

  it("garde l'ordre du catalogue, pas celui des clics", () => {
    // Deux configurations identiques doivent se relire identiques : une liste
    // ordonnée par l'ordre des clics rendrait la comparaison instable.
    expect(sanitiseClassIds([0, 2], CATALOGUE)).toEqual([2, 0]);
  });

  it("écarte un identifiant que le serveur ne propose plus", () => {
    // Le cas réel : un réglage persisté par une version antérieure. Sans ce
    // nettoyage, l'envoi partirait en 422 sur un écran dont les cases paraissent
    // toutes valides.
    expect(sanitiseClassIds([2, 99], CATALOGUE)).toEqual([2]);
  });

  it("écarte les doublons", () => {
    expect(sanitiseClassIds([2, 2, 3], CATALOGUE)).toEqual([2, 3]);
  });

  it("**retombe sur les cases par défaut quand tout est décoché**", () => {
    // Le serveur refuse une liste vide, et il a raison : elle ne restreindrait rien
    // et compterait les 80 classes de COCO. Retomber sur le défaut vaut mieux qu'un
    // message d'erreur là où l'utilisateur a simplement tout décoché.
    expect(sanitiseClassIds([], CATALOGUE)).toEqual([2, 3, 5, 7]);
    expect(sanitiseClassIds([99], CATALOGUE)).toEqual([2, 3, 5, 7]);
  });

  it("rend la sélection intacte tant que le catalogue n'a pas répondu", () => {
    // Nettoyer contre une liste vide effacerait la sélection de l'utilisateur le
    // temps d'un aller-retour réseau, et l'écran se réinitialiserait sous ses yeux.
    expect(sanitiseClassIds([2, 99], [])).toEqual([2, 99]);
  });
});

describe("classIds dans la requête", () => {
  // Une ligne quelconque : `toRequest` en exige une, mais aucun de ces tests ne
  // parle de géométrie.
  const LINES = [
    { id: "l1", name: "", color: "", zoneId: null, a: { x: 0, y: 0 }, positiveName: "", negativeName: "", positiveRole: "neutral" as const, negativeRole: "neutral" as const, b: { x: 10, y: 10 } },
  ];

  it("part avec les quatre véhicules par défaut", () => {
    expect(toRequest(DEFAULT_SETTINGS, LINES, []).classIds).toEqual([2, 3, 5, 7]);
  });

  it("ne part jamais vide", () => {
    // Le serveur refuserait la requête ; le repli garde l'écran utilisable.
    const request = toRequest({ ...DEFAULT_SETTINGS, classIds: [] }, LINES, []);

    expect(request.classIds).toEqual([2, 3, 5, 7]);
  });

  it("transmet une sélection contenant les personnes", () => {
    const request = toRequest({ ...DEFAULT_SETTINGS, classIds: [2, 0] }, LINES, []);

    expect(request.classIds).toEqual([2, 0]);
  });
});

describe("analysisSpeed — la cadence d'analyse", () => {
  const LINES = [
    { id: "l1", name: "", color: "", zoneId: null, a: { x: 0, y: 0 }, positiveName: "", negativeName: "", positiveRole: "neutral" as const, negativeRole: "neutral" as const, b: { x: 10, y: 10 } },
  ];

  it("part en temps réel par défaut", () => {
    // Depuis ADR 0019 : sans borne, la lecture locale calée sur l'aperçu paraît
    // accélérée ou ralentie selon la charge du serveur.
    expect(DEFAULT_SETTINGS.analysisSpeed).toBe(1);
    expect(toRequest(DEFAULT_SETTINGS, LINES, []).analysisSpeed).toBe(1);
  });

  it("transmet une cadence choisie", () => {
    const request = toRequest({ ...DEFAULT_SETTINGS, analysisSpeed: 1 }, LINES, []);

    expect(request.analysisSpeed).toBe(1);
  });

  it("**n'envoie jamais une cadence hors bornes**", () => {
    // Le serveur la refuserait en 422 sur un écran qui paraissait valide. Hors
    // bornes ⇒ aucune borne, qui est le défaut.
    expect(toRequest({ ...DEFAULT_SETTINGS, analysisSpeed: 99 }, LINES, []).analysisSpeed).toBeNull();
    expect(toRequest({ ...DEFAULT_SETTINGS, analysisSpeed: 0 }, LINES, []).analysisSpeed).toBeNull();
  });

  it("relit une cadence persistée", () => {
    const stored = JSON.stringify({
      version: SETTINGS_SCHEMA_VERSION,
      settings: { analysisSpeed: 2 },
    });

    expect(loadSettings(fakeStorage(stored)).analysisSpeed).toBe(2);
  });

  it("relit `null` comme « aucune borne », et non comme « absent »", () => {
    // `nullableNumber` distingue les deux : un `null` explicite est un choix.
    const stored = JSON.stringify({
      version: SETTINGS_SCHEMA_VERSION,
      settings: { analysisSpeed: null },
    });

    expect(loadSettings(fakeStorage(stored)).analysisSpeed).toBeNull();
  });

  it("**écarte une cadence persistée hors bornes au lieu de la borner**", () => {
    // Bornée à 8×, elle afficherait « Illimitée » tout en bridant : un réglage que
    // l'écran contredirait. C'est ce qui la distingue des curseurs, dont une valeur
    // hors bornes vient d'un intervalle qui a changé entre deux versions. Le repli
    // est le défaut du module (`1`, temps réel, depuis ADR 0019).
    const stored = JSON.stringify({
      version: SETTINGS_SCHEMA_VERSION,
      settings: { analysisSpeed: 42 },
    });

    expect(loadSettings(fakeStorage(stored)).analysisSpeed).toBe(1);
  });

  it("ignore une cadence d'un type faux", () => {
    const stored = JSON.stringify({
      version: SETTINGS_SCHEMA_VERSION,
      settings: { analysisSpeed: "temps réel" },
    });

    expect(loadSettings(fakeStorage(stored)).analysisSpeed).toBe(1);
  });
});

describe("maxAnalysisFps — le plafond absolu de cadence", () => {
  const LINES = [
    { id: "l1", name: "", color: "", zoneId: null, a: { x: 0, y: 0 }, positiveName: "", negativeName: "", positiveRole: "neutral" as const, negativeRole: "neutral" as const, b: { x: 10, y: 10 } },
  ];

  it("part à 30 img/s par défaut", () => {
    // Depuis ADR 0022 : la cadence vidéo la plus courante, qui ne borne rien en
    // pratique sur une source à cette cadence ou en dessous.
    expect(DEFAULT_SETTINGS.maxAnalysisFps).toBe(30);
    expect(toRequest(DEFAULT_SETTINGS, LINES, []).maxAnalysisFps).toBe(30);
  });

  it("transmet un plafond choisi", () => {
    const request = toRequest({ ...DEFAULT_SETTINGS, maxAnalysisFps: 30 }, LINES, []);

    expect(request.maxAnalysisFps).toBe(30);
  });

  it("**n'envoie jamais un plafond hors bornes**", () => {
    expect(
      toRequest({ ...DEFAULT_SETTINGS, maxAnalysisFps: 999 }, LINES, []).maxAnalysisFps,
    ).toBeNull();
    expect(
      toRequest({ ...DEFAULT_SETTINGS, maxAnalysisFps: 0 }, LINES, []).maxAnalysisFps,
    ).toBeNull();
  });

  it("relit un plafond persisté", () => {
    const stored = JSON.stringify({
      version: SETTINGS_SCHEMA_VERSION,
      settings: { maxAnalysisFps: 60 },
    });

    expect(loadSettings(fakeStorage(stored)).maxAnalysisFps).toBe(60);
  });

  it("relit `null` comme « aucun plafond », et non comme « absent »", () => {
    const stored = JSON.stringify({
      version: SETTINGS_SCHEMA_VERSION,
      settings: { maxAnalysisFps: null },
    });

    expect(loadSettings(fakeStorage(stored)).maxAnalysisFps).toBeNull();
  });

  it("**écarte un plafond persisté hors bornes au lieu de le borner**", () => {
    const stored = JSON.stringify({
      version: SETTINGS_SCHEMA_VERSION,
      settings: { maxAnalysisFps: 999 },
    });

    // Repli sur le défaut du module (30 img/s depuis ADR 0022), pas sur `null`.
    expect(loadSettings(fakeStorage(stored)).maxAnalysisFps).toBe(30);
  });

  it("ignore un plafond d'un type faux", () => {
    const stored = JSON.stringify({
      version: SETTINGS_SCHEMA_VERSION,
      settings: { maxAnalysisFps: "30 img/s" },
    });

    expect(loadSettings(fakeStorage(stored)).maxAnalysisFps).toBe(30);
  });
});
