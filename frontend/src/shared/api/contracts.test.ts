/**
 * Le garde-fou entre les deux moitiés du projet.
 *
 * La fixture `__fixtures__/analysis-result.json` est **produite par le vrai
 * backend** (`serialise_result` sur une analyse factice, deux véhicules, un
 * franchissement dans chaque sens). Elle est committée et parsée ici dans un
 * type explicite.
 *
 * Conséquence voulue : un champ renommé côté Python casse un test **côté
 * frontend**. C'est le seul mécanisme automatique qui relie les deux — il n'y a
 * pas de monorepo tool, et c'est un choix (voir CLAUDE.md).
 *
 * Ce que ces tests ne font **pas** : vérifier que le backend calcule juste. Le
 * comptage a ses 500 tests côté Python. Ici on vérifie la **forme du contrat**,
 * et les quelques invariants qu'un affichage ne doit jamais contredire.
 */

import { describe, expect, it } from "bun:test";

import fixture from "./__fixtures__/analysis-result.json";
import type { AnalysisResult, TrackSnapshot } from "./contracts";

/**
 * L'assignation **est** le test.
 *
 * Si le backend renomme `identityLabel`, `tsc -b` échoue ici — avant même que
 * les assertions ne tournent. C'est le mode de détection le plus rapide.
 */
const result: AnalysisResult = fixture as AnalysisResult;

describe("contrat du résultat d'analyse", () => {
  it("porte les blocs de premier niveau attendus", () => {
    expect(Object.keys(result).sort()).toEqual([
      "crossings",
      "jobId",
      "modelId",
      "processingFps",
      "stats",
      "timeline",
      "vehicles",
      "video",
      "zoneEvents",
    ]);
  });

  it("décrit la vidéo source, dont les dimensions ancrent toute la géométrie", () => {
    expect(result.video.width).toBeGreaterThan(0);
    expect(result.video.height).toBeGreaterThan(0);
    expect(result.video.fps).toBeGreaterThan(0);
  });

  it("horodate la timeline en temps de scène, croissant", () => {
    // `frameIndex / fps × 1000`, jamais l'horloge murale (invariant 1). Un
    // horodatage qui reculerait casserait la recherche binaire de la relecture.
    const stamps = result.timeline.map((row) => row.timestampMs);
    const sorted = [...stamps].sort((a, b) => a - b);

    expect(stamps).toEqual(sorted);
    expect(stamps[0]).toBe(0);
  });
});

describe("contrat d'une piste", () => {
  /**
   * La première piste porteuse de plaque.
   *
   * Extraite par une fonction qui **lève** si la fixture n'en contient pas,
   * plutôt que par un `!` : le jour où la fixture est régénérée sans ANPR, le
   * message doit dire ce qui manque au lieu de produire un `undefined` qui
   * échoue trois lignes plus loin.
   */
  function trackWithPlate(): TrackSnapshot {
    const found = result.timeline
      .flatMap((row) => row.tracks)
      .find((candidate) => candidate.plates.length > 0);
    if (found === undefined) {
      throw new Error("La fixture ne contient aucune piste avec plaque.");
    }
    return found;
  }

  const track = trackWithPlate();

  it("expose une piste complète, plaque comprise", () => {
    expect(Object.keys(track).sort()).toEqual([
      "box",
      "classId",
      "counted",
      "globalId",
      "hits",
      "identityLabel",
      "label",
      "plates",
      "reidCount",
      "score",
      "speedPxS",
      "trackId",
    ]);
  });

  it("porte `identityLabel` en plus de `label`", () => {
    // Les deux existent, et le canvas colore par le **voté** : une lecture qui
    // vacille d'une image à l'autre ne doit pas faire clignoter la couleur.
    expect(typeof track.identityLabel).toBe("string");
    expect(typeof track.label).toBe("string");
  });

  it("donne les boîtes en pixels de la vidéo source", () => {
    // Invariant 2 : jamais des pixels modèle, jamais des pixels CSS. Une boîte
    // qui dépasserait la source signalerait une conversion perdue en route.
    expect(track.box.x).toBeGreaterThanOrEqual(0);
    expect(track.box.x + track.box.width).toBeLessThanOrEqual(result.video.width);
    expect(track.box.y + track.box.height).toBeLessThanOrEqual(result.video.height);
  });

  it("exprime la plaque dans le repère de l'image complète, pas du recadrage", () => {
    const [plate] = track.plates;
    expect(plate).toBeDefined();
    if (plate === undefined) return;

    // Contenue dans la boîte du véhicule : c'est ce qui prouve que l'adaptateur
    // a réexprimé les coordonnées du crop en coordonnées absolues.
    expect(plate.box.x).toBeGreaterThanOrEqual(track.box.x);
    expect(plate.box.x + plate.box.width).toBeLessThanOrEqual(track.box.x + track.box.width);
  });
});

describe("invariants que l'affichage ne doit jamais contredire", () => {
  it("crossings === Σ byLine[*].total", () => {
    // Invariant 3 : un compteur affiché est **dérivé**, jamais accumulé en
    // double. Deux compteurs indépendants finissent toujours par se contredire,
    // et l'utilisateur ne sait alors plus lequel croire.
    const perLine = Object.values(result.stats.byLine).reduce(
      (sum, tally) => sum + tally.total,
      0,
    );

    expect(result.stats.crossings).toBe(perLine);
  });

  it("total === positive + negative pour chaque ligne", () => {
    for (const [lineId, tally] of Object.entries(result.stats.byLine)) {
      expect(tally.byDirection.positive + tally.byDirection.negative, lineId).toBe(tally.total);
    }
  });

  it("un aller-retour compte une fois dans chaque sens", () => {
    // La fixture décrit deux véhicules traversant en sens opposés : la
    // déduplication porte sur `(ligne, identité, sens)` et non sur
    // `(ligne, identité)`, sinon l'un des deux sens disparaîtrait.
    const tally = result.stats.byLine.l1;
    expect(tally).toBeDefined();
    if (tally === undefined) return;

    expect(tally.byDirection.positive).toBe(1);
    expect(tally.byDirection.negative).toBe(1);
  });

  it("un franchissement porte un sens qui vaut +1 ou -1", () => {
    for (const crossing of result.crossings) {
      expect([1, -1]).toContain(crossing.direction);
    }
  });

  it("chaque franchissement est rattaché à un véhicule du registre", () => {
    // On compte sous `globalId` (invariant 4) : un franchissement dont
    // l'identité n'existe pas au registre serait un chiffre impossible à
    // justifier dans l'interface.
    const known = new Set(result.vehicles.map((vehicle) => vehicle.globalId));

    for (const crossing of result.crossings) {
      expect(known).toContain(crossing.globalId);
    }
  });

  it("uniqueVehicles correspond à la taille du registre", () => {
    expect(result.stats.uniqueVehicles).toBe(result.vehicles.length);
  });
});

describe("contrat du diagnostic", () => {
  it("expose les sept compteurs qui rendent un comptage explicable", () => {
    // Ce bloc n'est pas décoratif : « le compte est faux » n'est diagnosticable
    // que si l'on voit si un véhicule manquant n'a jamais été détecté, l'a été
    // faiblement, n'était pas confirmé, ou a été masqué par une zone — et, dans
    // l'autre sens, si un véhicule compté en trop était un doublon inclus.
    expect(Object.keys(result.stats.diagnostics).sort()).toEqual([
      "confirmedTracks",
      "containedOut",
      "highDetections",
      "lowDetections",
      "maskedOut",
      "rescuedByLowScore",
      "tentativeTracks",
    ]);
  });
});

describe("contrat du registre des véhicules", () => {
  it("rend `null` et non 0 pour une vitesse inconnue", () => {
    // `0` voudrait dire « à l'arrêt ». La distinction compte : sans échelle
    // px/m, `avgSpeedKmh` doit être `null` plutôt qu'un chiffre inventé.
    for (const vehicle of result.vehicles) {
      if (vehicle.avgSpeedKmh !== null) {
        expect(vehicle.avgSpeedKmh).toBeGreaterThan(0);
      }
      expect(vehicle.avgSpeedPxS === null || vehicle.avgSpeedPxS > 0).toBe(true);
    }
  });

  it("liste les lignes franchies par chaque véhicule", () => {
    const vehicle = result.vehicles.find((candidate) => candidate.crossedLines.length > 0);
    expect(vehicle).toBeDefined();
    const crossed = vehicle?.crossedLines[0];
    expect(crossed).toBeDefined();
    if (crossed === undefined) return;

    expect(crossed.lineId).toBe("l1");
    expect([1, -1]).toContain(crossed.direction);
  });
});
