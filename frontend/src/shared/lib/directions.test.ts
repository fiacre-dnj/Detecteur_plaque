/**
 * Le vocabulaire des sens : libellés par défaut, noms effectifs, rôles.
 *
 * Le test le plus important du fichier est
 * `le libellé positif tombe du côté où sideOfLine rend +1`. C'est un test de **signe**,
 * et un signe s'inverse sans qu'on le remarque : les totaux resteraient justes, mais
 * l'écran dirait « Vers la droite » pour des véhicules qui vont à gauche. Une panne
 * silencieuse, donc exactement celles que ce dépôt verrouille par un test.
 */

import { describe, expect, it } from "bun:test";

import type { CountingLine } from "@/shared/api/contracts";

import {
  crossingDirectionName,
  directionArrow,
  directionName,
  directionRole,
  lineName,
  roleLabel,
  signOf,
} from "./directions";
import { defaultDirectionNames, sideOfLine } from "./geometry";

function line(overrides: Partial<CountingLine> = {}): CountingLine {
  return {
    id: "l1",
    name: "Voie nord",
    color: "#539df5",
    zoneId: null,
    // Horizontale, de gauche à droite : elle se franchit verticalement.
    a: { x: 0, y: 500 },
    b: { x: 1920, y: 500 },
    positiveName: "",
    negativeName: "",
    positiveRole: "neutral",
    negativeRole: "neutral",
    ...overrides,
  };
}

describe("defaultDirectionNames — le libellé géométrique", () => {
  it("nomme haut/bas une ligne horizontale", () => {
    // Elle se franchit verticalement : la nommer gauche/droite décrirait un
    // déplacement *le long* de la ligne, qui ne la franchit jamais.
    const names = defaultDirectionNames({ x: 0, y: 500 }, { x: 1920, y: 500 });

    expect(names).toEqual({ positive: "Vers le bas", negative: "Vers le haut" });
  });

  it("nomme gauche/droite une ligne verticale", () => {
    const names = defaultDirectionNames({ x: 900, y: 0 }, { x: 900, y: 1080 });

    expect(names).toEqual({ positive: "Vers la gauche", negative: "Vers la droite" });
  });

  it("s'inverse quand on retourne le tracé", () => {
    // A et B échangés : le côté positif change de côté, donc les libellés aussi.
    // Sans cela, retourner une ligne afficherait des sens faux sous des totaux justes.
    const forward = defaultDirectionNames({ x: 0, y: 500 }, { x: 1920, y: 500 });
    const backward = defaultDirectionNames({ x: 1920, y: 500 }, { x: 0, y: 500 });

    expect(backward.positive).toBe(forward.negative);
    expect(backward.negative).toBe(forward.positive);
  });

  it("le libellé positif tombe du côté où sideOfLine rend +1", () => {
    // **LE test de signe.** On prend un point du côté que le libellé « Vers le bas »
    // décrit — plus bas que la ligne, donc `y` plus grand — et on vérifie que le
    // serveur appellerait bien ce côté `+1`.
    const a = { x: 0, y: 500 };
    const b = { x: 1920, y: 500 };
    const names = defaultDirectionNames(a, b);
    expect(names.positive).toBe("Vers le bas");

    const below = { x: 960, y: 700 };
    expect(sideOfLine(a, b, below)).toBe(1);
  });

  it("le libellé positif d'une verticale tombe aussi du bon côté", () => {
    // Deuxième orientation, parce que le calcul passe par une branche différente
    // (`|normal.x| >= |normal.y|`) et qu'une seule des deux pourrait être inversée.
    const a = { x: 900, y: 0 };
    const b = { x: 900, y: 1080 };
    expect(defaultDirectionNames(a, b).positive).toBe("Vers la gauche");

    const toTheLeft = { x: 700, y: 540 };
    expect(sideOfLine(a, b, toTheLeft)).toBe(1);
  });

  it("rend la convention brute sur un segment de longueur nulle", () => {
    // Aucune orientation n'a de sens ; choisir un axe au hasard serait pire que dire
    // « A→B ».
    expect(defaultDirectionNames({ x: 100, y: 100 }, { x: 100, y: 100 })).toEqual({
      positive: "Sens A→B",
      negative: "Sens B→A",
    });
  });
});

describe("directionName — le nom de l'utilisateur, ou le défaut", () => {
  it("préfère le nom saisi", () => {
    const named = line({ positiveName: "Entrée rue Foch" });

    expect(directionName(named, "positive")).toBe("Entrée rue Foch");
  });

  it("retombe sur le défaut géométrique quand le champ est vide", () => {
    expect(directionName(line(), "positive")).toBe("Vers le bas");
    expect(directionName(line(), "negative")).toBe("Vers le haut");
  });

  it("traite une chaîne d'espaces comme vide", () => {
    // Un champ « effacé » contient souvent un espace résiduel. Le laisser passer
    // afficherait une étiquette vide sur le canvas, sans qu'on comprenne pourquoi.
    expect(directionName(line({ positiveName: "   " }), "positive")).toBe("Vers le bas");
  });

  it("suit la ligne quand elle pivote", () => {
    // La propriété qui justifie de ne **pas** stocker le défaut : une ligne devenue
    // verticale doit dire gauche/droite, pas haut/bas.
    const pivoted = line({ a: { x: 900, y: 0 }, b: { x: 900, y: 1080 } });

    expect(directionName(pivoted, "positive")).toBe("Vers la gauche");
  });
});

describe("directionRole", () => {
  it("lit le rôle déclaré", () => {
    const roled = line({ positiveRole: "entry", negativeRole: "exit" });

    expect(directionRole(roled, "positive")).toBe("entry");
    expect(directionRole(roled, "negative")).toBe("exit");
  });

  it("retombe sur neutral quand le champ manque", () => {
    // Une ligne venue d'un preset enregistré avant les sens nommés. Sans ce repli, le
    // rôle vaudrait `undefined` et les agrégations compareraient contre rien — un
    // total qui reste à zéro sans qu'aucune erreur ne l'explique.
    const legacy = { ...line(), positiveRole: undefined } as unknown as CountingLine;

    expect(directionRole(legacy, "positive")).toBe("neutral");
  });
});

describe("signOf et directionArrow — la convention du serveur", () => {
  it("associe le positif à A→B", () => {
    expect(signOf(1)).toBe("positive");
    expect(signOf(-1)).toBe("negative");
    expect(directionArrow(1)).toBe("↑");
    expect(directionArrow(-1)).toBe("↓");
  });

  it("traite zéro comme négatif, comme le serveur", () => {
    // Le serveur n'émet jamais `0` — un centroïde pile sur la ligne attend la frame
    // suivante — mais si un résultat archivé en portait un, il faut que les deux côtés
    // du fil le classent pareil.
    expect(signOf(0)).toBe("negative");
  });
});

describe("crossingDirectionName et lineName", () => {
  const lines = [line({ id: "l1", positiveName: "Entrée" })];

  it("nomme le sens d'un franchissement", () => {
    expect(crossingDirectionName(lines, "l1", 1)).toBe("Entrée");
    expect(crossingDirectionName(lines, "l1", -1)).toBe("Vers le haut");
  });

  it("rend null pour une ligne retirée du tracé", () => {
    // On ne peut plus nommer le sens ; inventer un nom serait pire que la flèche
    // brute, et l'appelant sait quoi mettre à la place.
    expect(crossingDirectionName(lines, "disparue", 1)).toBeNull();
  });

  it("retombe sur l'identifiant pour une ligne inconnue", () => {
    expect(lineName(lines, "l1")).toBe("Voie nord");
    expect(lineName(lines, "l9")).toBe("l9");
  });
});

describe("roleLabel", () => {
  it("ne libelle pas le rôle neutre", () => {
    // `null` et non `""` : l'appelant décide de ne rien rendre du tout, plutôt que de
    // poser un badge vide qui prendrait de la place.
    expect(roleLabel("neutral")).toBeNull();
    expect(roleLabel("entry")).toBe("entrée");
    expect(roleLabel("exit")).toBe("sortie");
  });
});
