/**
 * La règle d'ADR 0004 rendue exécutable : **l'accent vert n'est pas une donnée**.
 *
 * Ce test existe parce que la violation est tentante et silencieuse. Le vert est
 * la plus jolie couleur de la palette du projet, et l'ajouter aux classes de
 * véhicule paraîtrait un progrès esthétique. Mais le badge ✓ « compté » est vert :
 * « vert = compté » et « vert = camion » se contrediraient alors sur la même
 * image, et rien à l'écran ne dirait lequel des deux on regarde.
 */

import { describe, expect, it } from "bun:test";

import {
  CANVAS,
  CLASS_COLORS,
  GEOMETRY_COLORS,
  TRAJECTORY_ALPHA,
  UNKNOWN_CLASS_COLOR,
  classColor,
  nextGeometryColor,
} from "./palettes";

/** L'accent fonctionnel et sa variante de bordure, tels que déclarés dans `index.css`. */
const ACCENT = ["#1ed760", "#1db954"];

/** Toutes les couleurs que ce module expose, à plat. */
const ALL_COLORS = [
  ...Object.values(CLASS_COLORS),
  UNKNOWN_CLASS_COLOR,
  ...GEOMETRY_COLORS,
  ...Object.values(CANVAS),
];

describe("l'accent vert est réservé à l'interface", () => {
  it("n'apparaît dans aucune couleur du canvas", () => {
    for (const color of ALL_COLORS) {
      for (const accent of ACCENT) {
        expect(color.toLowerCase()).not.toContain(accent);
      }
    }
  });

  it("n'est la couleur d'aucune classe de véhicule", () => {
    // La formulation explicite du corollaire d'ADR 0004, pour que l'échec dise
    // *pourquoi* et pas seulement *quoi*.
    for (const [label, color] of Object.entries(CLASS_COLORS)) {
      expect(ACCENT, `la classe « ${label} » ne doit pas être verte`).not.toContain(
        color.toLowerCase(),
      );
    }
  });
});

describe("couleurs de classe", () => {
  it("couvre les quatre classes de véhicule du backend", () => {
    // Les mêmes que `VEHICLE_CLASS_IDS` (2, 3, 5, 7) côté Python. Une classe
    // manquante ici s'afficherait en gris sans que personne ne le remarque.
    expect(Object.keys(CLASS_COLORS).sort()).toEqual(["bus", "car", "motorcycle", "truck"]);
  });

  it("donne une couleur distincte à chaque classe", () => {
    // Deux classes de même couleur rendraient le canvas illisible sans qu'aucun
    // test ne s'en plaigne autrement.
    const colors = Object.values(CLASS_COLORS);

    expect(new Set(colors).size).toBe(colors.length);
  });

  it("replie une classe inconnue sur un gris neutre, pas sur une autre classe", () => {
    // Réutiliser la couleur d'une classe existante serait un mensonge visuel :
    // l'utilisateur lirait « camion » là où le serveur n'a rien affirmé.
    expect(classColor("train")).toBe(UNKNOWN_CLASS_COLOR);
    expect(Object.values(CLASS_COLORS)).not.toContain(UNKNOWN_CLASS_COLOR);
  });

  it("respecte le libellé exact rendu par le backend", () => {
    // Comparé à la valeur littérale et non à `CLASS_COLORS.car` : sous
    // `noUncheckedIndexedAccess`, un accès indexé sur un `Record` est
    // `string | undefined`, et une comparaison entre deux `undefined` passerait
    // le test sans rien prouver.
    expect(classColor("car")).toBe("#539df5");
    expect(classColor("truck")).toBe("#ffa42b");
  });
});

describe("attribution des couleurs de géométrie", () => {
  it("donne des couleurs différentes à deux formes consécutives", () => {
    expect(nextGeometryColor(0)).not.toBe(nextGeometryColor(1));
  });

  it("est déterministe : un preset rechargé retrouve ses couleurs", () => {
    // Sans ce déterminisme, une géométrie sauvegardée reviendrait en habits
    // neufs, et l'utilisateur croirait avoir chargé autre chose.
    expect(nextGeometryColor(3)).toBe(nextGeometryColor(3));
  });

  it("boucle sur la palette au-delà de sa taille", () => {
    expect(nextGeometryColor(GEOMETRY_COLORS.length)).toBe(nextGeometryColor(0));
  });
});

describe("constantes de dessin", () => {
  it("garde le voile de masque translucide — la scène doit rester reconnaissable", () => {
    // Opaque, l'utilisateur ne verrait plus ce qu'il masque ; transparent, il ne
    // verrait pas *qu'il* masque. La valeur vient de `prompt/09` §2.4.
    expect(CANVAS.maskFill).toBe("rgba(2, 6, 23, 0.62)");
  });

  it("garde l'opacité des trajectoires imposée par la spécification", () => {
    expect(TRAJECTORY_ALPHA).toBeCloseTo(0.53, 10);
  });
});
