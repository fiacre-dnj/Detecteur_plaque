import { describe, expect, it } from "bun:test";

import { snapshotCaption } from "./snapshotCaption";

/** Un format d'instant réduit au strict nécessaire : le test vérifie la phrase. */
const at = (ms: number): string => `${ms} ms`;

describe("snapshotCaption", () => {
  it("annonce la cause en premier, même sans rien d'autre à dire", () => {
    expect(snapshotCaption({ snapshotKind: "appearance" }, at)).toBe(
      "retenue pour sa ressemblance",
    );
  });

  it("porte les deux pourcentages, qui ne mesurent pas la même chose", () => {
    expect(
      snapshotCaption(
        { snapshotKind: "plate_text", snapshotMs: 4200, snapshotScore: 0.87, matchScore: 0.732 },
        at,
      ),
    ).toBe(
      "plaque lue · capturée à 4200 ms · lecture 87 % · ressemblance à la photo cherchée 73 %",
    );
  });

  it("nomme à quoi la ressemblance se compare", () => {
    // **Il y a désormais DEUX ressemblances** : à la photo cherchée (ADR 0048) et à un
    // autre véhicule de la vidéo (ADR 0055). La modale de comparaison affiche les
    // deux — son entête pour le jumeau, cette légende pour la requête — et un seul
    // mot pour les deux serait une erreur d'unité invisible, les deux chiffres étant
    // plausibles.
    const caption = snapshotCaption({ snapshotKind: "appearance", matchScore: 0.61 }, at);

    expect(caption).toContain("à la photo cherchée");
  });

  it("dit la ressemblance d'une capture qui n'a rien lu", () => {
    // Le cas d'ADR 0051 : photo prise pour l'apparence, donc aucune confiance de
    // lecture à afficher — et c'est justement la ressemblance qu'on vient vérifier.
    expect(
      snapshotCaption({ snapshotKind: "appearance", snapshotMs: 900, matchScore: 0.61 }, at),
    ).toBe("retenue pour sa ressemblance · capturée à 900 ms · ressemblance à la photo cherchée 61 %");
  });

  it("ne confond pas un score nul avec un score absent", () => {
    // `0` est une mesure — « ne ressemble à rien » — là où `null` dit « rien à
    // classer ». Les fondre afficherait « — » sur un véhicule bel et bien encodé.
    expect(
      snapshotCaption({ snapshotKind: "plate_text", snapshotScore: 0, matchScore: 0 }, at),
    ).toBe("plaque lue · lecture 0 % · ressemblance à la photo cherchée 0 %");
  });
});
