/**
 * L'étranglement de la progression d'envoi, et le format des tailles.
 *
 * `XMLHttpRequest` émet `progress` à chaque paquet : sur une vidéo de 800 Mo, des
 * centaines d'événements par seconde, dont chacun provoquait un rendu complet du
 * studio. L'interface devenait pâteuse pendant tout l'envoi — ce qui se lit comme
 * « l'application rame » alors que rien ne calcule.
 */

import { describe, expect, it } from "bun:test";

import {
  PROGRESS_MIN_INTERVAL_MS,
  formatBytes,
  shouldPublishProgress,
} from "./uploadJob";

describe("shouldPublishProgress", () => {
  it("publie toujours le premier événement", () => {
    // Sans lui, la barre resterait vide jusqu'au premier seuil franchi.
    expect(shouldPublishProgress(0.001, 0, null)).toBe(true);
  });

  it("étrangle deux événements rapprochés et quasi identiques", () => {
    const last = { ratio: 0.5, atMs: 1_000 };

    expect(shouldPublishProgress(0.5001, 1_010, last)).toBe(false);
  });

  it("laisse passer après l'intervalle, même sans progression visible", () => {
    // La barre doit rester vivante sur une liaison lente : un envoi qui n'avance
    // pas d'un pour cent en une seconde ne doit pas paraître arrêté.
    const last = { ratio: 0.5, atMs: 1_000 };

    expect(shouldPublishProgress(0.5001, 1_000 + PROGRESS_MIN_INTERVAL_MS, last)).toBe(true);
  });

  it("laisse passer un saut d'un point, même immédiat", () => {
    // Le cas du petit fichier : attendre 100 ms y perdrait la moitié des étapes.
    const last = { ratio: 0.5, atMs: 1_000 };

    expect(shouldPublishProgress(0.51, 1_001, last)).toBe(true);
  });

  /**
   * **La garde qui empêche l'étranglement d'introduire son propre défaut.** Sans
   * `force`, une barre étranglée s'arrête à 97 % sur un envoi terminé et
   * l'utilisateur attend une fin déjà survenue.
   */
  it("publie toujours l'événement forcé, quel que soit l'écart", () => {
    const last = { ratio: 0.97, atMs: 1_000 };

    expect(shouldPublishProgress(0.9701, 1_001, last, true)).toBe(true);
  });
});

describe("formatBytes", () => {
  it("passe des octets aux kilo-, méga- puis gigaoctets", () => {
    expect(formatBytes(512)).toBe("512 o");
    expect(formatBytes(2048)).toBe("2 Ko");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 Mo");
    expect(formatBytes(2 * 1024 * 1024 * 1024)).toBe("2.00 Go");
  });
});
