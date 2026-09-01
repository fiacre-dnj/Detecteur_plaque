/**
 * Le journal des franchissements — l'objet qui rend un total vérifiable.
 *
 * Ce que ces tests protègent : l'ordre (le plus récent en tête, sinon il faut
 * défiler pour voir ce qu'on attendait), la borne (une analyse d'une heure ne doit
 * pas faire grossir la mémoire indéfiniment), et le fait qu'aucun événement ne
 * soit inventé ni perdu à l'intérieur d'un même aperçu.
 */

import { describe, expect, it } from "bun:test";

import type { CrossingEvent } from "@/shared/api/contracts";

import { LOG_LIMIT, appendCrossings, formatSceneTime } from "./previewLog";

function crossing(
  globalId: number,
  timestampMs: number,
  direction = 1,
  plateText: string | null = null,
): CrossingEvent {
  return {
    lineId: "l1",
    globalId,
    trackId: globalId,
    label: "car",
    category: "vehicle" as const,
    direction,
    timestampMs,
    frameIndex: Math.round(timestampMs / 40),
    plateText,
    // Un score **seulement** s'il y a un texte : une confiance dans le vide serait
    // affichée comme un fait.
    plateTextScore: plateText === null ? null : 0.88,
  };
}

describe("appendCrossings", () => {
  it("empile le plus récent en tête", () => {
    const log = appendCrossings([crossing(1, 1000)], [crossing(2, 2000)]);

    expect(log.map((event) => event.globalId)).toEqual([2, 1]);
  });

  it("garde l'ordre à l'intérieur d'un aperçu qui en porte plusieurs", () => {
    // Un aperçu cumule les événements depuis le précédent : il peut en porter
    // cinq d'un coup, et le dernier survenu doit rester le premier affiché.
    const log = appendCrossings([], [crossing(1, 1000), crossing(2, 2000), crossing(3, 3000)]);

    expect(log.map((event) => event.globalId)).toEqual([3, 2, 1]);
  });

  it("range un franchissement antidaté à sa place", () => {
    // **Le cas d'ADR 0038.** La bande morte est proportionnelle à la boîte : un
    // poids lourd la traverse bien plus lentement qu'une moto, donc son passage —
    // pourtant antérieur — arrive dans une trame SSE **postérieure**. L'empiler
    // tel quel donnerait un journal décroissant à un endroit et croissant à un
    // autre, et `describeCrossings` en tirerait un temps de traversée négatif.
    const log = appendCrossings([crossing(3, 3000), crossing(1, 1000)], [crossing(2, 2000)]);

    expect(log.map((event) => event.globalId)).toEqual([3, 2, 1]);
  });

  it("garde le journal décroissant sur une salve désordonnée", () => {
    const log = appendCrossings([], [crossing(1, 3000), crossing(2, 500), crossing(3, 1800)]);

    expect(log.map((event) => event.timestampMs)).toEqual([3000, 1800, 500]);
  });

  it("laisse l'entrant devant à date égale", () => {
    // Le serveur trie déjà à l'intérieur d'une trame, avec des clés secondaires
    // déterministes. À date strictement égale, on ne réordonne pas : on respecte
    // l'ordre qu'il a choisi.
    const log = appendCrossings([crossing(1, 2000)], [crossing(2, 2000)]);

    expect(log.map((event) => event.globalId)).toEqual([2, 1]);
  });

  it("rend le journal inchangé quand rien n'arrive", () => {
    // Identité référentielle : la grande majorité des aperçus ne portent aucun
    // franchissement, et recréer le tableau à chaque fois rerendrait la liste
    // cinq fois par seconde pour rien.
    const log = [crossing(1, 1000)];

    expect(appendCrossings(log, [])).toBe(log);
  });

  it("borne le journal en oubliant les plus anciens", () => {
    const many = Array.from({ length: 10 }, (_, index) => crossing(index, index * 100));

    const log = appendCrossings([], many, 4);

    expect(log).toHaveLength(4);
    // Les quatre derniers survenus, pas les quatre premiers.
    expect(log.map((event) => event.globalId)).toEqual([9, 8, 7, 6]);
  });

  it("borne à 200 entrées par défaut", () => {
    expect(LOG_LIMIT).toBe(200);
  });
});

describe("formatSceneTime", () => {
  it("écrit un temps de scène en mm:ss.d", () => {
    expect(formatSceneTime(0)).toBe("00:00.0");
    expect(formatSceneTime(12_400)).toBe("00:12.4");
    expect(formatSceneTime(65_000)).toBe("01:05.0");
  });

  it("ne produit jamais de temps négatif", () => {
    // Un horodatage négatif n'existe pas côté serveur, mais un affichage
    // « -00:01 » se lirait comme un bug de comptage plutôt que d'affichage.
    expect(formatSceneTime(-500)).toBe("00:00.0");
  });
});

/*
 * Les tests de `directionLabel` et `lineLabel` sont partis avec les fonctions.
 * Ce qui les remplace est couvert par `crossingTimeline.test.ts` : le rôle du sens
 * lu sur le tracé courant, et le repli d'une ligne retirée du tracé — qui reste
 * affichée sans que son rôle soit inventé.
 */
