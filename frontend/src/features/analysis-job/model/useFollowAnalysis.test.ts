/**
 * La décision de caler la vidéo, et celle de dessiner les boîtes.
 *
 * Toute la logique du suivi tient dans quatre fonctions pures ; le reste du hook
 * n'est que de la plomberie d'événements DOM. Les tester seules, c'est tester ce
 * qui peut réellement se tromper — et c'est la discipline que ce fichier avait
 * déjà quand `shouldSeek` était le seul prédicat.
 */

import { describe, expect, it } from "bun:test";

import {
  IDLE_SYNC,
  SEEK_TOLERANCE_MS,
  onIncoming,
  onPresented,
  onStall,
  shouldSeek,
  type SyncState,
} from "./useFollowAnalysis";

describe("shouldSeek", () => {
  it("cale quand l'analyse a pris de l'avance sur l'image affichée", () => {
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

  it("cale toujours tant que rien n'a été présenté", () => {
    // `null` n'est pas « zéro » : c'est « on ne sait pas ce qui est à l'écran ».
    // Supposer que la bonne image y est déjà figerait l'overlay au démarrage.
    expect(shouldSeek(null, 40)).toBe(true);
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

describe("onIncoming", () => {
  it("émet un calage quand rien n'est en vol", () => {
    const step = onIncoming(IDLE_SYNC, 1000);
    expect(step.seekTo).toBe(1000);
    expect(step.state.inFlightMs).toBe(1000);
    expect(step.promote).toBeNull();
  });

  it("promeut sans caler quand l'image affichée est déjà la bonne", () => {
    // Sans cette branche, un aperçu tombant sur l'image courante ne serait jamais
    // dessiné : on attendrait un `seeked` qui n'a aucune raison de survenir.
    const step = onIncoming({ shownMs: 1000, inFlightMs: null, pendingMs: null }, 1010);
    expect(step.seekTo).toBeNull();
    expect(step.promote).toBe("incoming");
  });

  it("écrase l'attente au lieu d'empiler les cibles", () => {
    // Le cœur de la correction. Trois aperçus pendant un calage en vol ne doivent
    // produire qu'UN calage à la promotion, sur la cible la plus récente : une
    // file rejouerait un retard au lieu de le rattraper.
    let state: SyncState = { shownMs: 0, inFlightMs: 1000, pendingMs: null };
    for (const target of [1100, 1200, 1300]) {
      const step = onIncoming(state, target);
      expect(step.seekTo).toBeNull();
      state = step.state;
    }
    expect(state.pendingMs).toBe(1300);
    expect(state.inFlightMs).toBe(1000);
  });

  it("ignore une cible aberrante sans rien promouvoir", () => {
    const step = onIncoming(IDLE_SYNC, Number.NaN);
    expect(step.seekTo).toBeNull();
    expect(step.promote).toBeNull();
    expect(step.state).toEqual(IDLE_SYNC);
  });
});

describe("onPresented", () => {
  it("promeut l'aperçu en vol quand son image est là", () => {
    const step = onPresented({ shownMs: null, inFlightMs: 1000, pendingMs: null }, 1000);
    expect(step.promote).toBe("inFlight");
    expect(step.state.shownMs).toBe(1000);
    expect(step.state.inFlightMs).toBeNull();
  });

  it("ne promeut rien sur une image que personne n'a demandée", () => {
    // L'utilisateur a déplacé le curseur à la main : cette image n'est celle
    // d'aucun aperçu, et y dessiner des boîtes serait exactement le défaut qu'on
    // corrige. Le calage en vol est tout de même clos — l'opération a rendu la
    // main — donc le prochain aperçu recalera et le tampon se répare seul.
    const step = onPresented({ shownMs: null, inFlightMs: 1000, pendingMs: null }, 7000);
    expect(step.promote).toBeNull();
    expect(step.state.shownMs).toBe(7000);
    expect(step.state.inFlightMs).toBeNull();
  });

  it("enchaîne la cible en attente", () => {
    const step = onPresented({ shownMs: 0, inFlightMs: 1000, pendingMs: 1300 }, 1000);
    expect(step.promote).toBe("inFlight");
    expect(step.seekTo).toBe(1300);
    expect(step.state.inFlightMs).toBe(1300);
    expect(step.state.pendingMs).toBeNull();
  });
});

describe("onStall", () => {
  it("promeut la cible la plus récente et relance le calage", () => {
    // Le seul vrai risque de gel : un calage qui n'aboutit jamais. On rend alors
    // le comportement d'avant — des boîtes possiblement en avance — plutôt qu'un
    // écran figé.
    const step = onStall({ shownMs: 0, inFlightMs: 1000, pendingMs: 1300 });
    expect(step.promote).toBe("pending");
    expect(step.seekTo).toBe(1300);
    expect(step.state.shownMs).toBe(1300);
  });

  it("promeut le calage en vol quand rien n'attend", () => {
    const step = onStall({ shownMs: 0, inFlightMs: 1000, pendingMs: null });
    expect(step.promote).toBe("inFlight");
    expect(step.seekTo).toBe(1000);
  });

  it("ne fait rien quand aucun calage n'est en cours", () => {
    const step = onStall(IDLE_SYNC);
    expect(step.promote).toBeNull();
    expect(step.seekTo).toBeNull();
    expect(step.state).toEqual(IDLE_SYNC);
  });
});
