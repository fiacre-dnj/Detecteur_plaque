/**
 * La convention de sens, fixée sur **les mêmes cas que le test Python**.
 *
 * `backend/tests/unit/counting/test_geometry.py::TestSideOfLine` utilise la même
 * ligne `A(0,100) → B(200,100)` et les mêmes points. C'est délibéré : ces deux
 * fichiers sont le seul endroit où la duplication de `sideOfLine` est vérifiée.
 *
 * Ce que ce test empêche : que `sideOfLine` rende ici le signe **opposé** à celui
 * du backend. Dans ce cas, les flèches « A→B » / « B→A » de l'interface seraient
 * inversées par rapport aux chiffres du serveur — rien ne planterait, aucun test
 * backend ne le verrait, et l'utilisateur lirait des sens faux sous des totaux
 * justes. C'est le pire mode de défaillance possible : silencieux et plausible.
 */

import { describe, expect, it } from "bun:test";

import type { Point } from "@/shared/api/contracts";
import {
  arrowRotationDeg,
  boxCentroid,
  clampToSource,
  distance,
  distanceToSegment,
  midpoint,
  pointInPolygon,
  positiveNormal,
  sideOfLine,
} from "./geometry";

// Ligne horizontale orientée vers la droite : A à gauche, B à droite.
// **Identiques aux constantes du test Python.**
const A: Point = { x: 0, y: 100 };
const B: Point = { x: 200, y: 100 };

describe("sideOfLine — le contrat de signe partagé avec le backend", () => {
  it("rend +1 pour un point sous la ligne, comme le backend", () => {
    // « Sous » à l'écran : y croît vers le bas en coordonnées image.
    expect(sideOfLine(A, B, { x: 100, y: 150 })).toBe(1);
  });

  it("rend -1 pour un point au-dessus de la ligne, comme le backend", () => {
    expect(sideOfLine(A, B, { x: 100, y: 50 })).toBe(-1);
  });

  it("rend 0 pour un point exactement sur la ligne", () => {
    // `0` veut dire « aucun côté », pas « côté positif ». Côté serveur, le
    // compteur attend la frame suivante ; ici, aucune flèche n'est pertinente.
    expect(sideOfLine(A, B, { x: 100, y: 100 })).toBe(0);
  });

  it("rend 0 sur le prolongement de la ligne — le côté suit la droite, pas le segment", () => {
    // C'est exactement pourquoi le backend a besoin d'une intersection de
    // segments en plus : un véhicule passant au-delà des extrémités change de
    // côté sans jamais couper le segment tracé (piège 7).
    expect(sideOfLine(A, B, { x: 500, y: 100 })).toBe(0);
  });

  it("inverse le signe quand on inverse l'orientation", () => {
    const point: Point = { x: 100, y: 150 };

    expect(sideOfLine(A, B, point)).toBe(-sideOfLine(B, A, point) as -1 | 0 | 1);
  });

  it("rend un signe opposé de part et d'autre d'une traversée", () => {
    // La propriété dont dépend tout le comptage : deux positions successives
    // d'un véhicule qui traverse ne sont pas du même côté.
    const before: Point = { x: 100, y: 50 };
    const after: Point = { x: 100, y: 150 };

    expect(sideOfLine(A, B, before)).not.toBe(sideOfLine(A, B, after));
  });
});

describe("positiveNormal — l'orientation de la flèche de sens", () => {
  it("pointe vers le côté que sideOfLine appelle positif", () => {
    // Le test qui compte vraiment : on part du milieu, on avance le long du
    // normal, et le point obtenu doit être du côté `+1`. Si le signe du normal
    // était inversé, la flèche montrerait le sens contraire du chiffre affiché.
    const centre = midpoint(A, B);
    const normal = positiveNormal(A, B);
    const shifted: Point = { x: centre.x + normal.x * 20, y: centre.y + normal.y * 20 };

    expect(sideOfLine(A, B, shifted)).toBe(1);
  });

  it("reste vrai pour une ligne verticale", () => {
    // Une seule orientation testée cacherait une erreur de rotation : la
    // propriété doit tenir quelle que soit la direction de la ligne.
    const top: Point = { x: 100, y: 0 };
    const bottom: Point = { x: 100, y: 200 };
    const centre = midpoint(top, bottom);
    const normal = positiveNormal(top, bottom);
    const shifted: Point = { x: centre.x + normal.x * 20, y: centre.y + normal.y * 20 };

    expect(sideOfLine(top, bottom, shifted)).toBe(1);
  });

  it("est unitaire", () => {
    const normal = positiveNormal(A, B);

    expect(Math.hypot(normal.x, normal.y)).toBeCloseTo(1, 10);
  });

  it("rend un vecteur nul pour un segment de longueur nulle plutôt que NaN", () => {
    // Cas réel : une ligne qu'on vient tout juste de commencer à tracer.
    expect(positiveNormal(A, A)).toEqual({ x: 0, y: 0 });
  });
});

describe("pointInPolygon", () => {
  const square: Point[] = [
    { x: 0, y: 0 },
    { x: 100, y: 0 },
    { x: 100, y: 100 },
    { x: 0, y: 100 },
  ];

  it("reconnaît un point intérieur", () => {
    expect(pointInPolygon({ x: 50, y: 50 }, square)).toBe(true);
  });

  it("rejette un point extérieur", () => {
    expect(pointInPolygon({ x: 150, y: 50 }, square)).toBe(false);
  });

  it("gère un polygone concave — le creux d'un U est dehors", () => {
    // Un test par boîte englobante dirait « dedans » ici, et une zone tracée à
    // la main est presque toujours concave.
    const u: Point[] = [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 100 },
      { x: 70, y: 100 },
      { x: 70, y: 30 },
      { x: 30, y: 30 },
      { x: 30, y: 100 },
      { x: 0, y: 100 },
    ];

    expect(pointInPolygon({ x: 50, y: 60 }, u)).toBe(false);
    expect(pointInPolygon({ x: 15, y: 60 }, u)).toBe(true);
  });

  it("refuse un polygone de moins de trois sommets", () => {
    // Une zone en cours de tracé n'est pas une surface : la rendre
    // sélectionnable ferait clignoter le masque à chaque clic.
    expect(pointInPolygon({ x: 50, y: 50 }, [{ x: 0, y: 0 }])).toBe(false);
    expect(
      pointInPolygon({ x: 50, y: 50 }, [
        { x: 0, y: 0 },
        { x: 100, y: 0 },
      ]),
    ).toBe(false);
  });
});

describe("distanceToSegment — la précision du clic", () => {
  it("mesure la perpendiculaire quand la projection tombe sur le segment", () => {
    expect(distanceToSegment({ x: 100, y: 140 }, A, B)).toBeCloseTo(40, 10);
  });

  it("mesure jusqu'à l'extrémité au-delà du segment, pas jusqu'à la droite", () => {
    // La distinction rend la sélection compréhensible : sans elle, cliquer très
    // loin dans le prolongement d'une ligne la sélectionnerait.
    expect(distanceToSegment({ x: 400, y: 100 }, A, B)).toBeCloseTo(200, 10);
  });

  it("gère un segment de longueur nulle sans diviser par zéro", () => {
    expect(distanceToSegment({ x: 0, y: 140 }, A, A)).toBeCloseTo(40, 10);
  });
});

describe("utilitaires de dessin", () => {
  it("distance rend la distance euclidienne", () => {
    expect(distance({ x: 0, y: 0 }, { x: 3, y: 4 })).toBe(5);
  });

  it("midpoint rend le milieu, où se pose l'étiquette", () => {
    expect(midpoint(A, B)).toEqual({ x: 100, y: 100 });
  });

  it("boxCentroid rend le point que le comptage suit côté serveur", () => {
    expect(boxCentroid({ x: 10, y: 20, width: 40, height: 60 })).toEqual({ x: 30, y: 50 });
  });

  it("clampToSource borne à l'image et n'invente jamais de coordonnée hors cadre", () => {
    expect(clampToSource({ x: -50, y: 5000 }, 1920, 1080)).toEqual({ x: 0, y: 1080 });
    expect(clampToSource({ x: 960, y: 540 }, 1920, 1080)).toEqual({ x: 960, y: 540 });
  });
});

describe("arrowRotationDeg — la flèche pivote à l'angle exact, pas au 45° le plus proche", () => {
  it("ne tourne pas une icône déjà orientée vers le haut", () => {
    expect(arrowRotationDeg({ x: 0, y: -1 })).toBeCloseTo(0);
  });

  it("tourne les trois autres cardinaux de 90° en 90°, dans le sens horaire", () => {
    // `y` croît vers le bas dans le repère du canvas et de la vidéo — comme
    // `transform: rotate()` en CSS, une rotation positive est horaire.
    expect(arrowRotationDeg({ x: 1, y: 0 })).toBeCloseTo(90);
    expect(arrowRotationDeg({ x: 0, y: 1 })).toBeCloseTo(180);
    expect(arrowRotationDeg({ x: -1, y: 0 })).toBeCloseTo(-90);
  });

  it("**rend l'angle exact, pas arrondi à 45°**", () => {
    // Le défaut corrigé : un vecteur à 40° tombait sur le glyphe de 45°, une
    // flèche presque perpendiculaire au trait, jamais exactement. Une icône
    // pivote à l'angle réel.
    expect(arrowRotationDeg({ x: Math.sin((40 * Math.PI) / 180), y: -Math.cos((40 * Math.PI) / 180) })).toBeCloseTo(40);
  });

  it("ignore la longueur du vecteur, seul l'angle compte", () => {
    expect(arrowRotationDeg({ x: 500, y: 0 })).toBeCloseTo(arrowRotationDeg({ x: 1, y: 0 }));
  });

  it("ne tourne pas un vecteur nul", () => {
    // Un segment de longueur nulle n'a pas de direction — pas de flèche fausse.
    expect(arrowRotationDeg({ x: 0, y: 0 })).toBe(0);
  });
});
