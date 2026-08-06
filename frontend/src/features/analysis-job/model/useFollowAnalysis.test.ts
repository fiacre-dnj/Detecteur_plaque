/**
 * La décision de caler la vidéo sur l'image analysée.
 *
 * Toute la logique du suivi tient dans ce prédicat ; le reste du hook n'est que
 * de la plomberie d'événements DOM. Le tester seul, c'est tester ce qui peut
 * réellement se tromper.
 */

import { describe, expect, it } from "bun:test";

import { SEEK_TOLERANCE_MS, shouldSeek } from "./useFollowAnalysis";

describe("shouldSeek", () => {
  it("cale quand l'analyse a pris de l'avance", () => {
    expect(shouldSeek(1000, 4000)).toBe(true);
  });

  it("ne cale pas pour un écart inférieur à une image", () => {
    // À 25 images par seconde, la vidéo montre déjà la bonne image : écrire
    // `currentTime` ne ferait qu'un aller-retour du décodeur, donc un
    // scintillement, pour rien.
    expect(shouldSeek(1000, 1020)).toBe(false);
    expect(SEEK_TOLERANCE_MS).toBe(40);
  });

  it("cale aussi vers l'arrière", () => {
    // Le cas réel : l'utilisateur a avancé la vidéo à la main pendant l'analyse.
    // Le suivi doit la ramener sur l'image analysée, sinon l'overlay dessine des
    // boîtes sur une image qui n'est pas la leur.
    expect(shouldSeek(9000, 1000)).toBe(true);
  });

  it("ne cale sur rien sans aperçu", () => {
    expect(shouldSeek(1000, null)).toBe(false);
  });

  it("refuse une cible aberrante", () => {
    // Un `NaN` s'obtient d'un JSON tronqué ; l'écrire dans `currentTime` lève
    // une exception qui casserait le rendu au lieu de sauter une image.
    expect(shouldSeek(1000, Number.NaN)).toBe(false);
    expect(shouldSeek(1000, -1)).toBe(false);
  });
});
