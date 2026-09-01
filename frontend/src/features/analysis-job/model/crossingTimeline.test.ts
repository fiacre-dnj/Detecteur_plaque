/**
 * La chronologie des franchissements.
 *
 * Ce que ces tests protègent, dans l'ordre de ce qui casserait le plus discrètement :
 *
 * - **l'ordre reste celui du journal** — le plus récent en tête, y compris après
 *   regroupement. Le calcul, lui, remonte le temps ; une inversion oubliée mettrait
 *   la chronologie à l'envers sans rien casser d'autre ;
 * - **un rôle n'est jamais inventé.** Une ligne retirée du tracé depuis l'analyse ne
 *   devient pas « entrée » par défaut : elle fabriquerait un temps de traversée faux ;
 * - **le lien entrée → sortie est la seule mesure de traversée de l'interface.** S'il
 *   se trompe de véhicule, il produit un chiffre plausible et faux ;
 * - **les tranches sont alignées sur des bornes rondes**, pour se retrouver sur la
 *   barre de lecture, et adaptées au journal — 10 s fixes donneraient un en-tête par
 *   événement sur un journal étalé.
 */

import { describe, expect, it } from "bun:test";

import type { CountingLine, CrossingEvent } from "@/shared/api/contracts";

import {
  BUCKET_LADDER,
  NO_CROSSING_FILTER,
  bucketiseCrossings,
  chooseBucketMs,
  crossingFacets,
  describeCrossings,
  filterCrossings,
  formatBucketRange,
  formatDuration,
  isFilterEmpty,
  passageNote,
} from "./crossingTimeline";

/** Une ligne dont le sens A→B est une entrée et B→A une sortie. */
function line(id: string, name: string, color = "#539df5"): CountingLine {
  return {
    id,
    name,
    color,
    zoneId: null,
    a: { x: 0, y: 0 },
    b: { x: 100, y: 0 },
    positiveName: "",
    negativeName: "",
    positiveRole: "entry",
    negativeRole: "exit",
  };
}

function crossing(
  globalId: number,
  timestampMs: number,
  lineId = "l1",
  direction = 1,
): CrossingEvent {
  return {
    lineId,
    globalId,
    trackId: globalId,
    label: "car",
    category: "vehicle" as const,
    direction,
    timestampMs,
    frameIndex: Math.round(timestampMs / 40),
    plateText: null,
    plateTextScore: null,
  };
}

/** Le journal tel que `appendCrossings` le tient : le plus récent en tête. */
function journal(...events: CrossingEvent[]): CrossingEvent[] {
  return [...events].reverse();
}

const LINES = [line("l1", "Voie nord"), line("l2", "Voie sud", "#ffa42b")];

describe("describeCrossings — ordre et rôles", () => {
  it("rend le plus récent en tête, comme le journal qu'il reçoit", () => {
    const entries = describeCrossings(journal(crossing(1, 1000), crossing(2, 2000)), LINES);

    expect(entries.map((entry) => entry.event.globalId)).toEqual([2, 1]);
  });

  it("lit le rôle et le nom du sens sur le tracé courant", () => {
    const entries = describeCrossings(
      journal(crossing(1, 1000, "l1", 1), crossing(2, 2000, "l1", -1)),
      LINES,
    );

    // Le sens négatif de `l1` est déclaré sortie : c'est le tracé qui le dit, pas le
    // serveur — il ne connaît pas les rôles et ne les lira jamais (ADR 0016).
    expect(entries[0]?.role).toBe("exit");
    expect(entries[0]?.directionName).toBe("Sortie");
    expect(entries[1]?.role).toBe("entry");
    expect(entries[1]?.directionName).toBe("Entrée");
  });

  it("n'invente aucun rôle pour une ligne retirée du tracé", () => {
    // Le franchissement a bien eu lieu : le masquer creuserait un écart inexpliqué
    // avec le total. Mais le ranger dans « entrée » fabriquerait un temps de
    // traversée que personne n'a mesuré.
    const entries = describeCrossings(journal(crossing(1, 1000, "effacee")), LINES);

    expect(entries[0]?.role).toBe("neutral");
    expect(entries[0]?.lineName).toBe("effacee");
    expect(entries[0]?.lineColor).toBeNull();
    expect(entries[0]?.directionName).toBe("sens ↑");
  });
});

/*
 * L'angle de la flèche lui-même est testé dans `shared/lib/directions.test.ts`, où
 * `directionHeadingDeg` vit désormais : la chronologie, le panneau de géométrie et les
 * puces du registre l'appellent tous les trois. Ne reste ici que ce qui est propre à la
 * chronologie — que chaque franchissement décrit **porte** cet angle, et qu'il soit
 * indéterminé quand la ligne a quitté le tracé.
 */
describe("describeCrossings — l'angle de la flèche", () => {
  it("porte l'angle sur chaque franchissement décrit", () => {
    // `LINES` trace ses lignes de (0,0) à (100,0) : sens positif vers le bas, donc à
    // un demi-tour d'une flèche vers le haut. `Math.abs` parce que `-180` et `180`
    // sont la même rotation — voir `directions.test.ts`.
    const entries = describeCrossings(
      journal(crossing(1, 1000, "l1", 1), crossing(2, 2000, "l1", -1)),
      LINES,
    );

    expect(Math.abs(entries[1]?.headingDeg ?? 0)).toBe(180);
    expect(entries[0]?.headingDeg).toBe(0);
  });

  it("laisse la flèche indéterminée quand la ligne a quitté le tracé", () => {
    // Poser `0` ferait pointer la flèche vers le haut, donc affirmerait un angle que
    // personne n'a mesuré. Le panneau n'en affiche alors aucune.
    const entries = describeCrossings(journal(crossing(1, 1000, "effacee")), LINES);

    expect(entries[0]?.headingDeg).toBeNull();
  });
});

describe("describeCrossings — le rythme du trafic", () => {
  it("mesure l'écart avec le franchissement précédent, toutes lignes confondues", () => {
    const entries = describeCrossings(
      journal(crossing(1, 1000, "l1"), crossing(2, 2500, "l2"), crossing(3, 2600, "l1")),
      LINES,
    );

    expect(entries[0]?.gapMs).toBe(100);
    expect(entries[1]?.gapMs).toBe(1500);
  });

  it("laisse le plus ancien sans écart plutôt que d'en inventer un", () => {
    // Le journal est borné : ce qui précède le plus ancien peut avoir été oublié.
    // Un « +0,0 s » se lirait comme deux franchissements simultanés.
    const entries = describeCrossings(journal(crossing(1, 4000), crossing(2, 5000)), LINES);

    expect(entries[1]?.gapMs).toBeNull();
  });

  it("rend un écart nul, jamais négatif, pour deux franchissements de la même image", () => {
    const entries = describeCrossings(
      journal(crossing(1, 3000, "l1"), crossing(2, 3000, "l2")),
      LINES,
    );

    expect(entries[0]?.gapMs).toBe(0);
  });
});

describe("describeCrossings — le temps de traversée du carrefour", () => {
  it("relie une sortie à l'entrée du même véhicule", () => {
    // **La mesure que rien d'autre ne produit.** Le registre donne l'heure des deux
    // franchissements ; l'écart entre eux se calculait de tête.
    const entries = describeCrossings(
      journal(crossing(7, 10_000, "l1", 1), crossing(7, 13_400, "l2", -1)),
      LINES,
    );

    expect(entries[0]?.previous).toEqual({
      role: "entry",
      lineName: "Voie nord",
      timestampMs: 10_000,
      deltaMs: 3400,
    });
    expect(passageNote(entries[0]!)).toBe(
      "Ressorti 3,4 s après son entrée par « Voie nord »",
    );
  });

  it("ne relie jamais deux véhicules différents", () => {
    // Le mode de panne le plus coûteux : un temps de traversée plausible et faux.
    const entries = describeCrossings(
      journal(crossing(7, 10_000, "l1", 1), crossing(8, 13_400, "l2", -1)),
      LINES,
    );

    expect(entries[0]?.previous).toBeNull();
    expect(entries[0]?.passageIndex).toBe(1);
    expect(passageNote(entries[0]!)).toBeNull();
  });

  it("nomme un retour quand une entrée suit une sortie", () => {
    const entries = describeCrossings(
      journal(crossing(7, 10_000, "l1", -1), crossing(7, 22_000, "l1", 1)),
      LINES,
    );

    expect(passageNote(entries[0]!)).toBe("Revenu 12 s après sa sortie par « Voie nord »");
  });

  it("compte les passages d'un aller-retour sans les fusionner", () => {
    // Invariant 6 : un aller-retour compte 2, et le journal doit le montrer comme
    // deux passages du même véhicule — pas comme un doublon d'affichage.
    const entries = describeCrossings(
      journal(
        crossing(7, 1000, "l1", 1),
        crossing(7, 4000, "l1", 1),
        crossing(7, 9000, "l1", 1),
      ),
      LINES,
    );

    expect(entries.map((entry) => entry.passageIndex)).toEqual([3, 2, 1]);
    expect(passageNote(entries[0]!)).toBe("3ᵉ passage — 5,0 s après « Voie nord »");
  });
});

describe("filterCrossings", () => {
  const entries = describeCrossings(
    journal(
      crossing(1, 1000, "l1", 1),
      crossing(2, 2000, "l1", -1),
      crossing(3, 3000, "l2", 1),
    ),
    LINES,
  );

  it("rend le journal inchangé sous un filtre neutre", () => {
    // Identité référentielle : le journal se rerend cinq fois par seconde pendant
    // une analyse, et copier pour n'écarter personne serait du gaspillage.
    expect(isFilterEmpty(NO_CROSSING_FILTER)).toBe(true);
    expect(filterCrossings(entries, NO_CROSSING_FILTER)).toBe(entries);
  });

  it("ne garde que les entrées, ou que les sorties", () => {
    expect(
      filterCrossings(entries, { role: "entry", lineId: null }).map((e) => e.event.globalId),
    ).toEqual([3, 1]);
    expect(
      filterCrossings(entries, { role: "exit", lineId: null }).map((e) => e.event.globalId),
    ).toEqual([2]);
  });

  it("combine le rôle et la ligne", () => {
    expect(
      filterCrossings(entries, { role: "entry", lineId: "l1" }).map((e) => e.event.globalId),
    ).toEqual([1]);
  });
});

describe("crossingFacets", () => {
  it("compte par rôle et par ligne", () => {
    const entries = describeCrossings(
      journal(crossing(1, 1000, "l1", 1), crossing(2, 2000, "l1", -1), crossing(3, 3000, "l2", 1)),
      LINES,
    );

    const facets = crossingFacets(entries, LINES);

    expect(facets.byRole).toEqual({ entry: 2, exit: 1, forbidden: 0, transit: 0, neutral: 0 });
    expect(facets.byLine.map((facet) => [facet.lineId, facet.count])).toEqual([
      ["l1", 2],
      ["l2", 1],
    ]);
  });

  it("garde une ligne du tracé qui n'a rien compté, dans l'ordre du tracé", () => {
    // Même règle que `directionRows` : une ligne absente se lirait « pas
    // d'information » alors qu'un zéro dit « posée là où rien ne passe ».
    const entries = describeCrossings(journal(crossing(1, 1000, "l2", 1)), LINES);

    const facets = crossingFacets(entries, LINES);

    expect(facets.byLine.map((facet) => [facet.lineId, facet.count])).toEqual([
      ["l1", 0],
      ["l2", 1],
    ]);
  });

  it("ajoute les lignes effacées après celles du tracé, sans couleur", () => {
    const entries = describeCrossings(journal(crossing(1, 1000, "effacee", 1)), LINES);

    const facets = crossingFacets(entries, LINES);

    expect(facets.byLine.at(-1)).toEqual({
      lineId: "effacee",
      lineName: "effacee",
      lineColor: null,
      count: 1,
    });
  });
});

describe("chooseBucketMs — la taille de tranche s'adapte au journal", () => {
  it("n'offre que des paliers ronds, de 5 s à 10 min", () => {
    // Des paliers et non une valeur calculée : « 00:17 → 00:31 » ne se relie à
    // rien sur la barre de lecture.
    expect([...BUCKET_LADDER]).toEqual([5_000, 10_000, 30_000, 60_000, 300_000, 600_000]);
  });

  it("prend le palier le plus fin sur un journal court", () => {
    expect(chooseBucketMs(8000, 12)).toBe(5_000);
  });

  it("s'élargit plutôt que de produire un en-tête par événement", () => {
    // 200 franchissements étalés sur trente minutes : à 10 s fixes, jusqu'à 180
    // en-têtes pour 200 événements — l'inverse d'un regroupement.
    expect(chooseBucketMs(1_800_000, 200)).toBe(60_000);
  });

  it("plafonne au dernier palier plutôt que d'inventer une borne", () => {
    expect(chooseBucketMs(7_200_000, 4)).toBe(600_000);
  });

  it("reste défini sur un journal d'un seul événement", () => {
    expect(chooseBucketMs(0, 1)).toBe(5_000);
  });
});

describe("bucketiseCrossings", () => {
  it("aligne les tranches sur des bornes rondes", () => {
    // Alignées et non ancrées sur le premier événement : « 00:10 → 00:20 » se
    // retrouve sur la barre de lecture, « 00:07 → 00:17 » non.
    const entries = describeCrossings(journal(crossing(1, 7000), crossing(2, 12_000)), LINES);

    const buckets = bucketiseCrossings(entries, 10_000);

    expect(buckets.map((bucket) => [bucket.startMs, bucket.endMs])).toEqual([
      [10_000, 20_000],
      [0, 10_000],
    ]);
  });

  it("garde le plus récent en tête, dans les tranches comme entre elles", () => {
    const entries = describeCrossings(
      journal(crossing(1, 1000), crossing(2, 2000), crossing(3, 15_000)),
      LINES,
    );

    const buckets = bucketiseCrossings(entries, 10_000);

    expect(buckets[0]?.entries.map((e) => e.event.globalId)).toEqual([3]);
    expect(buckets[1]?.entries.map((e) => e.event.globalId)).toEqual([2, 1]);
  });

  it("n'émet aucune tranche vide", () => {
    // Un silence de trois minutes ne mérite pas dix-huit en-têtes vides : l'écart
    // est déjà porté par le `gapMs` de l'événement qui le suit.
    const entries = describeCrossings(journal(crossing(1, 1000), crossing(2, 200_000)), LINES);

    expect(bucketiseCrossings(entries, 10_000)).toHaveLength(2);
  });

  it("rend une liste vide sur un journal vide", () => {
    expect(bucketiseCrossings([], 10_000)).toEqual([]);
  });
});

describe("formatDuration", () => {
  it("garde le dixième sous dix secondes", () => {
    expect(formatDuration(400)).toBe("0,4 s");
    expect(formatDuration(3400)).toBe("3,4 s");
  });

  it("abandonne le dixième au-delà, où il suggère une précision inexistante", () => {
    expect(formatDuration(14_300)).toBe("14 s");
  });

  it("passe en minutes au-delà d'une minute", () => {
    expect(formatDuration(125_000)).toBe("2 min 05 s");
  });

  it("ne produit jamais de durée négative", () => {
    expect(formatDuration(-500)).toBe("0,0 s");
  });

  it("écrit la virgule décimale française, là où un instant garde le point", () => {
    // Les deux se côtoient à l'écran : « 00:12.4 » est un repère de lecteur vidéo,
    // « 3,4 s » est une durée qui se lit comme de la prose.
    expect(formatDuration(3400)).toContain(",");
  });
});

describe("formatBucketRange", () => {
  it("écrit les bornes en mm:ss", () => {
    expect(formatBucketRange(70_000, 80_000)).toBe("01:10 → 01:20");
  });
});
