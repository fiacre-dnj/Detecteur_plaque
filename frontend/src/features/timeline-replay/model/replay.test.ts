/**
 * La relecture, sur la **fixture produite par le vrai backend**.
 *
 * Le test qui compte le plus : **reculer dans la vidéo doit faire baisser les
 * compteurs**. Sinon l'image et les nombres racontent deux histoires différentes,
 * et l'utilisateur ne sait pas lequel croire — ce qui ruine la confiance dans tout
 * le reste de l'écran.
 */

import { describe, expect, it } from "bun:test";

import fixture from "@/shared/api/__fixtures__/analysis-result.json";
import type { AnalysisResult, TimelineRow } from "@/shared/api/contracts";

import { chooseBucketMs, flowBuckets, formatBucketSpan } from "./flowBuckets";
import {
  crossingsUpTo,
  RATE_MIN_ELAPSED_MS,
  TRAIL_LENGTH,
  frameAt,
  frameIndexAt,
  hasRate,
  ratePerMinute,
  statsAt,
  trailsAt,
  tracksAt,
  vehiclesAt,
} from "./replay";

const result: AnalysisResult = fixture as AnalysisResult;

/** Timeline synthétique, pour les cas limites de la recherche binaire. */
const timeline: TimelineRow[] = [0, 40, 80, 120, 160].map((timestampMs, frameIndex) => ({
  frameIndex,
  timestampMs,
  tracks: [],
}));

describe("frameIndexAt — la recherche binaire", () => {
  it("trouve la frame exacte", () => {
    expect(frameIndexAt(timeline, 80)).toBe(2);
  });

  it("prend la frame précédente entre deux horodatages", () => {
    // La frame affichée est celle qui a **déjà** eu lieu : afficher la suivante
    // ferait apparaître des boîtes en avance sur l'image.
    expect(frameIndexAt(timeline, 99)).toBe(2);
  });

  it("rend -1 avant la première frame, et non 0", () => {
    // `0` afficherait les boîtes de la frame initiale sur une vidéo pas encore
    // commencée.
    expect(frameIndexAt(timeline, -1)).toBe(-1);
  });

  it("rend la dernière frame au-delà de la fin", () => {
    expect(frameIndexAt(timeline, 10_000)).toBe(4);
  });

  it("gère une timeline vide sans lever", () => {
    expect(frameIndexAt([], 100)).toBe(-1);
  });

  it("donne le même résultat qu'une recherche linéaire, sur toute la fixture", () => {
    // Le test qui protège l'optimisation : la binaire doit être **exactement**
    // équivalente à la linéaire, sinon on a gagné du temps en perdant la justesse.
    const linear = (timeMs: number): number => {
      let found = -1;
      result.timeline.forEach((row, index) => {
        if (row.timestampMs <= timeMs) found = index;
      });
      return found;
    };

    for (const timeMs of [-5, 0, 1, 39, 40, 41, 200, 439, 440, 441, 99_999]) {
      expect(frameIndexAt(result.timeline, timeMs), `t=${timeMs}`).toBe(linear(timeMs));
    }
  });
});

describe("frameAt", () => {
  it("rend la frame correspondante", () => {
    expect(frameAt(timeline, 80)?.frameIndex).toBe(2);
  });

  it("rend null avant le début", () => {
    expect(frameAt(timeline, -1)).toBeNull();
  });
});

describe("statsAt — les compteurs suivent la tête de lecture", () => {
  it("part de zéro avant tout événement", () => {
    const stats = statsAt(result, -1);

    expect(stats.crossings).toBe(0);
    expect(stats.uniqueVehicles).toBe(0);
  });

  it("atteint les totaux du serveur à la fin", () => {
    // La relecture doit converger vers ce que le serveur a calculé : un écart ici
    // signifierait que le client recompte différemment, et deux comptages
    // divergents sont pires qu'un seul.
    const stats = statsAt(result, result.video.durationMs + 1000);

    expect(stats.crossings).toBe(result.stats.crossings);
    expect(stats.uniqueVehicles).toBe(result.stats.uniqueVehicles);
  });

  it("**fait baisser les compteurs quand on recule**", () => {
    // Le test central de la relecture.
    const atEnd = statsAt(result, result.video.durationMs);
    const atStart = statsAt(result, 0);

    expect(atEnd.crossings).toBeGreaterThan(0);
    expect(atStart.crossings).toBeLessThan(atEnd.crossings);
  });

  it("croît de façon monotone au fil du temps", () => {
    // Un compteur qui redescendrait en **avançant** serait tout aussi faux que
    // l'inverse.
    let previous = -1;
    for (let timeMs = 0; timeMs <= result.video.durationMs; timeMs += 40) {
      const crossings = statsAt(result, timeMs).crossings;
      expect(crossings).toBeGreaterThanOrEqual(previous);
      previous = crossings;
    }
  });

  it("respecte l'invariant crossings === Σ byLine[*].total à tout instant", () => {
    // L'invariant 3 du projet ne vaut pas seulement pour le résultat final : un
    // compteur dérivé doit l'être **à chaque frame** de la relecture.
    for (let timeMs = 0; timeMs <= result.video.durationMs; timeMs += 80) {
      const stats = statsAt(result, timeMs);
      const perLine = Object.values(stats.byLine).reduce((sum, tally) => sum + tally.total, 0);
      expect(stats.crossings, `t=${timeMs}`).toBe(perLine);
    }
  });

  it("respecte total === positive + negative à tout instant", () => {
    for (let timeMs = 0; timeMs <= result.video.durationMs; timeMs += 80) {
      for (const tally of Object.values(statsAt(result, timeMs).byLine)) {
        expect(tally.byDirection.positive + tally.byDirection.negative).toBe(tally.total);
      }
    }
  });

  it("ne compte pas un véhicule avant sa première apparition", () => {
    // Compter tout le registre afficherait le total final dès la première seconde.
    const first = Math.min(...result.vehicles.map((vehicle) => vehicle.firstSeenMs));

    expect(statsAt(result, first - 1).uniqueVehicles).toBe(0);
    expect(statsAt(result, first).uniqueVehicles).toBeGreaterThan(0);
  });

  it("conserve les diagnostics, qui décrivent l'analyse entière", () => {
    // Les rejouer n'aurait pas de sens ; les mettre à zéro cacherait une
    // information utile au diagnostic d'un comptage douteux.
    expect(statsAt(result, 0).diagnostics).toEqual(result.stats.diagnostics);
  });
});

describe("trailsAt — trajectoires reconstituées côté client", () => {
  it("indexe par globalId et non par trackId", () => {
    // Une piste est détruite et recréée à chaque occlusion longue : la trajectoire
    // doit survivre à cette rupture, c'est tout l'intérêt de la ré-identification.
    const trails = trailsAt(result.timeline, result.timeline.length - 1);
    const identities = new Set(result.vehicles.map((vehicle) => vehicle.globalId));

    for (const key of trails.keys()) {
      expect(identities).toContain(key);
    }
  });

  it("accumule les positions des frames précédentes", () => {
    const trails = trailsAt(result.timeline, 5);
    const [firstTrail] = [...trails.values()];

    expect(firstTrail).toBeDefined();
    expect(firstTrail?.length).toBeGreaterThan(1);
  });

  it("borne la longueur de la trajectoire", () => {
    const trails = trailsAt(result.timeline, result.timeline.length - 1, 3);

    for (const points of trails.values()) {
      expect(points.length).toBeLessThanOrEqual(3);
    }
  });

  it("rend une carte vide avant la première frame", () => {
    expect(trailsAt(result.timeline, -1).size).toBe(0);
  });

  it("garde la longueur par défaut de la spécification", () => {
    expect(TRAIL_LENGTH).toBe(24);
  });
});

describe("débit par minute", () => {
  it("rend 0 sous le seuil de 3 secondes", () => {
    // Extrapoler depuis une demi-seconde donnerait « 120 par minute », et
    // l'utilisateur le prendrait au sérieux.
    expect(ratePerMinute(1, 500)).toBe(0);
    expect(hasRate(500)).toBe(false);
  });

  it("calcule le débit au-delà du seuil", () => {
    // 10 véhicules en 30 s → 20 par minute.
    expect(ratePerMinute(10, 30_000)).toBe(20);
    expect(hasRate(30_000)).toBe(true);
  });

  it("garde le seuil de la spécification", () => {
    expect(RATE_MIN_ELAPSED_MS).toBe(3_000);
  });
});

describe("vehiclesAt et tracksAt", () => {
  it("ne montre que les véhicules déjà apparus", () => {
    expect(vehiclesAt(result, -1)).toHaveLength(0);
    expect(vehiclesAt(result, result.video.durationMs)).toHaveLength(result.vehicles.length);
  });

  it("rend les pistes de la frame courante", () => {
    expect(tracksAt(result, -1)).toHaveLength(0);
    expect(tracksAt(result, 200).length).toBeGreaterThan(0);
  });
});

describe("crossingsUpTo", () => {
  it("ne montre que les franchissements déjà passés", () => {
    // Montrer un événement à venir ferait mentir la tête de lecture aussi sûrement
    // qu'un compteur en avance sur la vidéo.
    expect(crossingsUpTo(result, -1)).toHaveLength(0);
    expect(crossingsUpTo(result, result.video.durationMs)).toHaveLength(result.crossings.length);
  });

  it("place le plus récent en tête, comme le journal du direct", () => {
    const shown = crossingsUpTo(result, result.video.durationMs);
    const stamps = shown.map((event) => event.timestampMs);

    expect(stamps).toEqual([...stamps].sort((a, b) => b - a));
  });

  it("ne réordonne pas le tableau du résultat", () => {
    // `reverse` mute en place : l'appliquer sur `result.crossings` casserait
    // l'histogramme et les exports, qui partagent le même tableau.
    const before = result.crossings.map((event) => event.timestampMs);
    crossingsUpTo(result, result.video.durationMs);

    expect(result.crossings.map((event) => event.timestampMs)).toEqual(before);
  });

  it("borne le journal", () => {
    expect(crossingsUpTo(result, result.video.durationMs, 1)).toHaveLength(1);
  });

  it("inclut un franchissement situé exactement sur la tête de lecture", () => {
    const [first] = result.crossings;
    expect(first).toBeDefined();
    if (first === undefined) return;

    expect(crossingsUpTo(result, first.timestampMs).length).toBeGreaterThan(0);
  });
});

describe("tranches adaptatives de l'histogramme", () => {
  it("choisit la seconde pour un clip très court", () => {
    // Sans adaptation, un clip de 10 s tiendrait dans une seule barre d'une minute.
    expect(chooseBucketMs(10_000)).toBe(1_000);
  });

  it("choisit une tranche plus large quand la durée croît", () => {
    expect(chooseBucketMs(60_000)).toBe(5_000);
    expect(chooseBucketMs(600_000)).toBe(60_000);
    expect(chooseBucketMs(3_600_000)).toBe(300_000);
  });

  it("plafonne au plus grand palier plutôt que d'inventer une durée illisible", () => {
    // Une analyse de plusieurs heures : trente barres de dix minutes valent mieux
    // qu'un axe gradué en « 7,4 min ».
    expect(chooseBucketMs(100_000_000)).toBe(600_000);
  });

  it("vise une douzaine de barres", () => {
    for (const durationMs of [10_000, 60_000, 300_000, 1_800_000]) {
      const buckets = flowBuckets([], durationMs);
      expect(buckets.length, `durée=${durationMs}`).toBeLessThanOrEqual(12);
      expect(buckets.length).toBeGreaterThan(0);
    }
  });

  it("conserve les tranches vides — un creux est une information", () => {
    // Les retirer tasserait l'axe du temps et ferait paraître le trafic continu là
    // où il y a eu une interruption.
    const buckets = flowBuckets(
      [
        {
          lineId: "l1",
          globalId: 1,
          trackId: 1,
          label: "car",
          category: "vehicle" as const,
          direction: 1,
          timestampMs: 0,
          frameIndex: 0,
          plateText: null,
          plateTextScore: null,
        },
      ],
      12_000,
    );

    expect(buckets.length).toBeGreaterThan(1);
    expect(buckets.filter((bucket) => bucket.count === 0).length).toBeGreaterThan(0);
  });

  it("range chaque franchissement de la fixture dans une tranche", () => {
    const buckets = flowBuckets(result.crossings, result.video.durationMs);
    const total = buckets.reduce((sum, bucket) => sum + bucket.count, 0);

    expect(total).toBe(result.crossings.length);
  });

  it("range un événement situé exactement à la fin dans la dernière tranche", () => {
    // Sans le `Math.min`, il tomberait dans une tranche qui n'existe pas et
    // disparaîtrait du graphique.
    const buckets = flowBuckets(
      [
        {
          lineId: "l1",
          globalId: 1,
          trackId: 1,
          label: "car",
          category: "vehicle" as const,
          direction: 1,
          timestampMs: 10_000,
          frameIndex: 0,
          plateText: null,
          plateTextScore: null,
        },
      ],
      10_000,
    );
    const total = buckets.reduce((sum, bucket) => sum + bucket.count, 0);

    expect(total).toBe(1);
  });

  it("libelle les tranches en français lisible", () => {
    expect(formatBucketSpan(1_000)).toBe("1 s");
    expect(formatBucketSpan(30_000)).toBe("30 s");
    expect(formatBucketSpan(60_000)).toBe("1 min");
    expect(formatBucketSpan(600_000)).toBe("10 min");
  });
});
