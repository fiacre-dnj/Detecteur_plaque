/**
 * Les cinq raisons de non-lecture, et ce qu'elles disent à l'utilisateur.
 *
 * Le silence est ce que l'utilisateur lit comme une panne. Ces phrases sont la
 * seule chose qui distingue « le service ne marche pas » de « la plaque fait 48 px
 * et la chaîne refuse d'inventer » — d'où des tests sur la copie, et pas seulement
 * sur la logique.
 */

import { describe, expect, it } from "bun:test";

import type { PlateUnreadReason } from "@/shared/api/contracts";

import {
  READING_FLOOR_PX,
  plateBestGuessMessage,
  plateSilenceSummary,
  plateUnreadLabel,
  plateUnreadMessage,
} from "./plateUnread";

const REASONS: PlateUnreadReason[] = [
  "ocr_disabled",
  "not_detected",
  "too_small",
  "too_blurry",
  "no_consensus",
];

describe("plateUnreadLabel", () => {
  it("donne une étiquette courte et distincte pour chacune des cinq raisons", () => {
    const labels = REASONS.map((reason) => plateUnreadLabel(reason));

    expect(new Set(labels).size).toBe(REASONS.length);
    for (const label of labels) {
      expect(label).not.toBe("");
      // La cellule du tableau est étroite : une étiquette longue la ferait
      // déborder ou tronquer, et une raison tronquée n'explique plus rien.
      expect(label.length).toBeLessThanOrEqual(20);
    }
  });

  it("ne dit rien quand une plaque est publiée", () => {
    expect(plateUnreadLabel(null)).toBe("");
  });
});

describe("plateUnreadMessage", () => {
  it("rend une phrase pour chacune des cinq raisons", () => {
    for (const reason of REASONS) {
      expect(plateUnreadMessage(reason, 48).length).toBeGreaterThan(30);
    }
  });

  /**
   * **Le message le plus important**, parce que c'est la cause dominante sur les
   * vidéos disponibles : 27 à 88 px pour un plancher mesuré à ~64.
   */
  it("cite la largeur vue et le plancher sur « trop petite »", () => {
    const message = plateUnreadMessage("too_small", 48);

    expect(message).toContain("48 px");
    expect(message).toContain(String(READING_FLOOR_PX));
    // Et il dit **quoi faire**, pas seulement ce qui ne va pas.
    expect(message).toContain("plan plus serré");
  });

  it("survit à une largeur inconnue sans afficher « null px »", () => {
    expect(plateUnreadMessage("too_small", null)).not.toContain("null");
  });

  it("ne dit rien quand une plaque est publiée", () => {
    expect(plateUnreadMessage(null, 120)).toBe("");
  });
});

describe("plateBestGuessMessage", () => {
  it("cite le candidat et sa confiance", () => {
    const message = plateBestGuessMessage("AB-123-CD", 0.66);

    expect(message).toContain("AB-123-CD");
    expect(message).toContain("66 %");
  });

  it("dit explicitement que ce n'est pas une plaque confirmée", () => {
    // Le seul rempart contre la confusion avec `plateText` : le mot doit être là.
    expect(plateBestGuessMessage("AB-123-CD", 0.66)).toContain("pas une plaque confirmée");
  });

  it("survit à une confiance inconnue sans afficher « null »", () => {
    expect(plateBestGuessMessage("AB-123-CD", null)).not.toContain("null");
  });
});

describe("plateSilenceSummary", () => {
  it("se tait quand une minorité de plaques est muette", () => {
    // La raison par ligne suffit : une synthèse alarmiste ici apprendrait à
    // ignorer les synthèses.
    expect(plateSilenceSummary(2, 10)).toBeNull();
  });

  it("se tait quand aucune plaque n'est sous le plancher", () => {
    expect(plateSilenceSummary(0, 0)).toBeNull();
  });

  it("parle quand le silence est massif", () => {
    // 328 sous le plancher pour 0 publiée : le cas réel des vidéos disponibles.
    const summary = plateSilenceSummary(328, 0);

    expect(summary).not.toBeNull();
    expect(summary).toContain("trop petites");
    // **Et il dit que ce n'est pas une panne** — c'est tout l'objet du message.
    expect(summary).toContain("pas une panne");
  });
});
