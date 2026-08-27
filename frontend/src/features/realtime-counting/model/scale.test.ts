/**
 * Le test de la mise à l'échelle — celui qui protège d'un comptage 25 % à côté.
 *
 * Ce fichier existe parce que la panne qu'il empêche est invisible. Une géométrie
 * non mise à l'échelle ne lève rien, ne journalise rien et produit des chiffres
 * crédibles ; aucun test d'intégration, aucune relecture visuelle et aucun
 * utilisateur ne peut la détecter. Seule une assertion sur les nombres exacts le
 * peut, d'où la précision des valeurs attendues ci-dessous : elles sont calculées à
 * la main, pas relevées d'une exécution.
 */

import { describe, expect, test } from "bun:test";

import type { AnalysisRequest, CountingLine, Zone } from "@/shared/api/contracts";

import {
  DIMENSION_TOLERANCE_PX,
  TARGET_WIDTH,
  dimensionMismatchMessage,
  dimensionsAgree,
  scaleFactor,
  scaleLine,
  scaleRequestGeometry,
  scaleZone,
  scaledSize,
  unscaleBox,
} from "./scale";

/** Une ligne aux coordonnées choisies pour que ×0,75 tombe juste. */
const LINE: CountingLine = {
  id: "l1",
  name: "Entrée nord",
  color: "#38bdf8",
  zoneId: "z1",
  positiveName: "",
  negativeName: "",
  positiveRole: "neutral" as const,
  negativeRole: "neutral" as const,
  a: { x: 400, y: 200 },
  b: { x: 1200, y: 600 },
};

const ZONE: Zone = {
  id: "z1",
  name: "Carrefour",
  color: "#f59e0b",
  points: [
    { x: 0, y: 0 },
    { x: 800, y: 0 },
    { x: 800, y: 400 },
    { x: 0, y: 400 },
  ],
};

const REQUEST: AnalysisRequest = {
  modelId: "yolo11m",
  plateWatchlist: [],
  confidenceThreshold: 0.35,
  iouThreshold: 0.45,
  minHits: 3,
  maxLostMs: 2500,
  maskOutsideZones: true,
  frameStride: 1,
  classIds: [2, 3, 5, 7],
  detectPlates: false,
  plateConfidence: null,
  plateTextConfidence: null,
  readPlateText: false,
  // Sans dimension, donc rejouée telle quelle par la mise à l'échelle — et sans
  // effet en direct de toute façon : c'est le client qui cadence son envoi.
  analysisSpeed: null,
  maxAnalysisFps: null,
  // Sans effet en direct non plus, et pour une raison plus radicale : un flux
  // caméra n'a ni début ni fin à borner. Les deux champs voyagent quand même,
  // parce que le direct envoie **exactement** la requête du différé — c'est ce
  // partage qui garantit qu'un même tracé compte pareil dans les deux modes.
  startMs: 0,
  endMs: null,
  lines: [LINE],
  zones: [ZONE],
};

describe("scaleFactor", () => {
  test("rend 0,75 pour une source de 1280 px — le cas d'une webcam 720p", () => {
    expect(scaleFactor(1280)).toBe(0.75);
  });

  test("rend exactement 1 pour une source déjà à la largeur cible", () => {
    expect(scaleFactor(TARGET_WIDTH)).toBe(1);
  });

  test("ne grandit jamais une source plus petite que la cible", () => {
    // Agrandir dépenserait de la bande passante et du temps d'inférence pour de
    // l'information inventée par l'interpolation.
    expect(scaleFactor(640)).toBe(1);
    expect(scaleFactor(320)).toBe(1);
  });

  test("rend 1 sur une largeur absente plutôt que de lever", () => {
    // Le hook appelle cette fonction pendant le montage, avant que la vidéo ait
    // des dimensions. Lever ici serait une panne pour un état transitoire.
    expect(scaleFactor(0)).toBe(1);
    expect(scaleFactor(-1)).toBe(1);
    expect(scaleFactor(Number.NaN)).toBe(1);
  });
});

describe("scaledSize", () => {
  test("réduit une 1280×720 en 960×540", () => {
    expect(scaledSize(1280, 720, 0.75)).toEqual({ width: 960, height: 540 });
  });

  test("arrondit à l'entier — un canvas n'a pas de dimension fractionnaire", () => {
    // 1281 × 0,75 = 960,75 ; 721 × 0,75 = 540,75.
    expect(scaledSize(1281, 721, 0.75)).toEqual({ width: 961, height: 541 });
  });

  test("ne rend jamais une dimension nulle", () => {
    // Un canvas de hauteur 0 fait rendre `null` à `toBlob`, et la session
    // s'arrêterait sans raison lisible.
    expect(scaledSize(4, 1, 0.1)).toEqual({ width: 1, height: 1 });
  });
});

describe("scaleRequestGeometry — facteur 1", () => {
  test("est l'identité sur la géométrie", () => {
    // Le cas le plus fréquent : une webcam déjà en dessous de 960 px. La fonction
    // ne doit alors rien perturber, sinon le mode direct serait cassé par la
    // protection elle-même.
    const scaled = scaleRequestGeometry(REQUEST, 1);
    expect(scaled.lines[0]?.a).toEqual({ x: 400, y: 200 });
    expect(scaled.lines[0]?.b).toEqual({ x: 1200, y: 600 });
    expect(scaled.zones[0]?.points).toEqual(ZONE.points);
  });

  test("laisse la requête entière intacte", () => {
    expect(scaleRequestGeometry(REQUEST, 1)).toEqual(REQUEST);
  });
});

describe("scaleRequestGeometry — facteur 0,75", () => {
  const scaled = scaleRequestGeometry(REQUEST, 0.75);

  test("met les extrémités de ligne à l'échelle, exactement", () => {
    // 400 × 0,75 = 300 ; 200 × 0,75 = 150 ; 1200 × 0,75 = 900 ; 600 × 0,75 = 450.
    expect(scaled.lines[0]?.a).toEqual({ x: 300, y: 150 });
    expect(scaled.lines[0]?.b).toEqual({ x: 900, y: 450 });
  });

  test("met tous les sommets de zone à l'échelle", () => {
    expect(scaled.zones[0]?.points).toEqual([
      { x: 0, y: 0 },
      { x: 600, y: 0 },
      { x: 600, y: 300 },
      { x: 0, y: 300 },
    ]);
  });

  test("préserve l'ordre des sommets — il porte l'orientation de la zone", () => {
    expect(scaled.zones[0]?.points.length).toBe(ZONE.points.length);
    // Le deuxième sommet reste celui qui vient du premier : un tri, une inversion
    // ou un `Set` intermédiaire retournerait le polygone.
    expect(scaled.zones[0]?.points[1]?.x).toBeGreaterThan(0);
    expect(scaled.zones[0]?.points[1]?.y).toBe(0);
  });

  test("ne touche à aucun seuil : ils sont sans dimension", () => {
    expect(scaled.confidenceThreshold).toBe(REQUEST.confidenceThreshold);
    expect(scaled.iouThreshold).toBe(REQUEST.iouThreshold);
  });

  test("ne touche pas aux compteurs d'images ni aux durées", () => {
    // `minHits` compte des images, `maxLostMs` des millisecondes : ni l'un ni
    // l'autre n'est une longueur.
    expect(scaled.minHits).toBe(3);
    expect(scaled.maxLostMs).toBe(2500);
    expect(scaled.frameStride).toBe(1);
  });

  test("préserve identifiants, noms, couleurs et rattachement de zone", () => {
    // La configuration doit rester rejouable à l'identique, et le rattachement
    // `zoneId` porte une règle de comptage : une ligne détachée compterait sur
    // toute l'image au lieu de sa zone.
    expect(scaled.lines[0]?.id).toBe("l1");
    expect(scaled.lines[0]?.name).toBe("Entrée nord");
    expect(scaled.lines[0]?.color).toBe("#38bdf8");
    expect(scaled.lines[0]?.zoneId).toBe("z1");
    expect(scaled.zones[0]?.id).toBe("z1");
  });

  test("ne mute pas la requête d'origine", () => {
    // Le studio garde la géométrie source pour le dessin : la muter ferait sauter
    // les lignes à l'écran au démarrage du direct.
    expect(REQUEST.lines[0]?.a).toEqual({ x: 400, y: 200 });
  });
});

describe("aller-retour", () => {
  test("unscaleBox annule scaleFactor", () => {
    const factor = scaleFactor(1280);
    const box = { x: 300, y: 150, width: 90, height: 60 };
    expect(unscaleBox(box, factor)).toEqual({ x: 400, y: 200, width: 120, height: 80 });
  });

  test("une ligne mise à l'échelle puis remise rend ses coordonnées d'origine", () => {
    const factor = scaleFactor(1280);
    const there = scaleLine(LINE, factor);
    const back = scaleLine(there, 1 / factor);
    expect(back.a).toEqual(LINE.a);
    expect(back.b).toEqual(LINE.b);
  });

  test("une zone survit au même aller-retour", () => {
    const factor = scaleFactor(1600); // 0,6
    const back = scaleZone(scaleZone(ZONE, factor), 1 / factor);
    expect(back.points).toEqual(ZONE.points);
  });

  test("unscaleBox rend la boîte inchangée sur un facteur absurde", () => {
    // Diviser par 0 donnerait des `Infinity`, et le dessin disparaîtrait sans
    // qu'aucun message n'explique pourquoi.
    const box = { x: 10, y: 20, width: 30, height: 40 };
    expect(unscaleBox(box, 0)).toEqual(box);
    expect(unscaleBox(box, Number.NaN)).toEqual(box);
  });
});

describe("dimensionsAgree — le contrôle croisé contre `ready`", () => {
  test("accepte des dimensions identiques", () => {
    expect(dimensionsAgree({ width: 960, height: 540 }, { width: 960, height: 540 })).toBe(true);
  });

  test("accepte un écart d'un pixel — alignement de bloc JPEG", () => {
    expect(dimensionsAgree({ width: 960, height: 540 }, { width: 961, height: 539 })).toBe(true);
    expect(DIMENSION_TOLERANCE_PX).toBe(1);
  });

  test("refuse l'écart qui compterait 25 % à côté", () => {
    // Le scénario exact : le client croit envoyer du 960, le serveur reçoit du
    // 1280 parce que la réduction n'a pas eu lieu.
    expect(dimensionsAgree({ width: 960, height: 540 }, { width: 1280, height: 720 })).toBe(false);
  });

  test("refuse un désaccord sur la seule hauteur", () => {
    // Une largeur juste et une hauteur fausse suffisent : c'est le symptôme d'un
    // rapport d'aspect changé, qui décale la géométrie verticalement.
    expect(dimensionsAgree({ width: 960, height: 540 }, { width: 960, height: 720 })).toBe(false);
  });

  test("accepte `null` : le serveur n'a pas encore décodé de frame", () => {
    // `ready` précède forcément la première frame. Traiter cette absence comme un
    // désaccord bloquerait toutes les sessions, sans exception.
    expect(dimensionsAgree({ width: 960, height: 540 }, { width: null, height: null })).toBe(true);
  });
});

describe("dimensionMismatchMessage", () => {
  test("donne les deux couples de dimensions, pas un verdict", () => {
    // Un « erreur de dimensions » sans chiffres ne permet pas de diagnostiquer.
    // Voir 1280×720 face à 960×540 désigne immédiatement la réduction manquante.
    const message = dimensionMismatchMessage(
      { width: 960, height: 540 },
      { width: 1280, height: 720 },
    );
    expect(message).toContain("1280×720");
    expect(message).toContain("960×540");
    expect(message).toContain("arrêté");
  });
});
