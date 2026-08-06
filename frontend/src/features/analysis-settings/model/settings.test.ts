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
      pixelsPerMeter: 12.5,
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

  it("traduit une échelle nulle en `null`, que le serveur exige", () => {
    // Le curseur utilise 0 pour « non définie », mais le serveur refuse 0
    // (`gt=0`) — et il a raison, une échelle nulle n'a pas de sens.
    expect(toRequest({ ...DEFAULT_SETTINGS, pixelsPerMeter: 0 }, LINES, []).pixelsPerMeter).toBeNull();
    expect(
      toRequest({ ...DEFAULT_SETTINGS, pixelsPerMeter: 12.5 }, LINES, []).pixelsPerMeter,
    ).toBe(12.5);
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
});

describe("défauts alignés sur le serveur", () => {
  it("reprend les valeurs par défaut du backend", () => {
    // Un écart ici ferait que l'affichage du canvas (pointillés sous `minHits`) ne
    // correspondrait pas à ce que l'analyse fait réellement.
    expect(DEFAULT_SETTINGS.iouThreshold).toBe(0.45);
    expect(DEFAULT_SETTINGS.minHits).toBe(2);
    expect(DEFAULT_SETTINGS.maxLostMs).toBe(2_500);
    expect(DEFAULT_SETTINGS.reidMinSimilarity).toBe(0.8);
    expect(DEFAULT_SETTINGS.frameStride).toBe(1);
    expect(DEFAULT_CONFIDENCE).toBe(0.35);
  });
});
