import { describe, expect, test } from "bun:test";

import type { CountingLine, Preset, Zone } from "@/shared/api/contracts";

import {
  aspectNotice,
  changesAspectRatio,
  draftProblem,
  matchesResolution,
  scalingNotice,
  toDraft,
} from "./notice";

const LINE: CountingLine = {
  id: "l1",
  name: "Entrée",
  color: "#38bdf8",
  zoneId: null,
  positiveName: "",
  negativeName: "",
  positiveRole: "neutral" as const,
  negativeRole: "neutral" as const,
  a: { x: 100, y: 400 },
  b: { x: 1180, y: 400 },
};

const ZONE: Zone = {
  id: "z1",
  name: "Carrefour",
  color: "#f59e0b",
  points: [
    { x: 0, y: 0 },
    { x: 640, y: 0 },
    { x: 640, y: 360 },
  ],
};

function preset(originalWidth = 1280, originalHeight = 720): Preset {
  return {
    id: "p1",
    name: "Carrefour nord",
    description: "",
    sourceWidth: originalWidth,
    sourceHeight: originalHeight,
    originalWidth,
    originalHeight,
    scaled: false,
    maskOutsideZones: false,
    lines: [LINE],
    zones: [ZONE],
    createdAt: null,
    updatedAt: null,
  };
}

describe("matchesResolution", () => {
  test("vrai quand les deux dimensions coïncident", () => {
    expect(matchesResolution(preset(), 1280, 720)).toBe(true);
  });

  test("faux dès qu'une seule diffère", () => {
    expect(matchesResolution(preset(), 1280, 1080)).toBe(false);
  });
});

describe("scalingNotice", () => {
  test("silencieux quand aucune adaptation n'est nécessaire", () => {
    // Afficher « aucune adaptation nécessaire » sur chaque ligne noierait le seul
    // cas qui mérite l'attention.
    expect(scalingNotice(preset(), 1280, 720)).toBeNull();
  });

  test("donne les **deux** résolutions", () => {
    // « Adapté à votre vidéo » sans chiffres oblige l'utilisateur à faire
    // confiance ; avec, il juge lui-même si l'écart est raisonnable.
    const notice = scalingNotice(preset(), 640, 360);

    expect(notice).toContain("1280×720");
    expect(notice).toContain("640×360");
  });

  test("invite explicitement à vérifier", () => {
    // La géométrie a bougé : c'est le seul moment où un contrôle visuel peut
    // rattraper une erreur, et il faut le demander.
    expect(scalingNotice(preset(), 640, 360)).toContain("vérifiez");
  });
});

describe("changesAspectRatio", () => {
  test("faux d'un 16/9 vers un autre 16/9", () => {
    // Une réduction homothétique conserve les angles : la ligne oblique suit
    // toujours la voie.
    expect(changesAspectRatio(preset(1280, 720), 640, 360)).toBe(false);
    expect(changesAspectRatio(preset(1280, 720), 1920, 1080)).toBe(false);
  });

  test("vrai d'un 16/9 vers un 4/3", () => {
    expect(changesAspectRatio(preset(1280, 720), 640, 480)).toBe(true);
  });

  test("tolère une résolution « presque » standard", () => {
    // 1366×768 n'est pas exactement du 16/9 (1,7786 contre 1,7778). Avertir pour
    // huit dix-millièmes apprendrait à ignorer l'avertissement.
    expect(changesAspectRatio(preset(1280, 720), 1366, 768)).toBe(false);
  });

  test("faux sur des dimensions absentes plutôt que de diviser par zéro", () => {
    expect(changesAspectRatio(preset(0, 0), 640, 360)).toBe(false);
    expect(changesAspectRatio(preset(1280, 720), 640, 0)).toBe(false);
  });
});

describe("aspectNotice", () => {
  test("silencieux quand le format ne change pas", () => {
    expect(aspectNotice(preset(), 640, 360)).toBeNull();
  });

  test("nomme la conséquence concrète : les obliques", () => {
    // Dire « le format change » n'apprend rien ; dire que les lignes obliques ne
    // suivront plus le même angle décrit ce que l'utilisateur va voir.
    const notice = aspectNotice(preset(1280, 720), 640, 480);

    expect(notice).toContain("obliques");
  });
});

describe("toDraft", () => {
  test("rogne le nom", () => {
    // Deux presets « Carrefour » et « Carrefour  » seraient indiscernables à
    // l'œil, et l'unicité du nom ne servirait plus à rien.
    expect(toDraft("  Carrefour  ", "", 1280, 720, false, [LINE], []).name).toBe("Carrefour");
  });

  test("rogne aussi la description", () => {
    expect(toDraft("A", "  note  ", 1280, 720, false, [LINE], []).description).toBe("note");
  });

  test("désactive le masque quand aucune zone n'existe", () => {
    // Comme `toRequest` : enregistrer un masque à vrai sans zone rechargerait un
    // réglage qui ment sur ce qu'il fait.
    expect(toDraft("A", "", 1280, 720, true, [LINE], []).maskOutsideZones).toBe(false);
  });

  test("conserve le masque quand une zone existe", () => {
    expect(toDraft("A", "", 1280, 720, true, [LINE], [ZONE]).maskOutsideZones).toBe(true);
  });

  test("copie les tableaux plutôt que de les partager", () => {
    // Le brouillon part en JSON, mais le partage exposerait la géométrie du studio
    // à une mutation par un futur appelant.
    const lines = [LINE];
    expect(toDraft("A", "", 1280, 720, false, lines, []).lines).not.toBe(lines);
  });

  test("porte les dimensions de la vidéo", () => {
    const draft = toDraft("A", "", 1280, 720, false, [LINE], []);

    expect([draft.sourceWidth, draft.sourceHeight]).toEqual([1280, 720]);
  });
});

describe("draftProblem", () => {
  test("accepte un brouillon complet", () => {
    expect(draftProblem("Carrefour", 1280, 720, [LINE], [])).toBeNull();
  });

  test("refuse un nom vide, et un nom d'espaces", () => {
    expect(draftProblem("", 1280, 720, [LINE], [])).toContain("nom");
    expect(draftProblem("   ", 1280, 720, [LINE], [])).toContain("nom");
  });

  test("refuse un nom trop long — la borne du serveur", () => {
    expect(draftProblem("x".repeat(121), 1280, 720, [LINE], [])).toContain("120");
  });

  test("refuse une géométrie vide", () => {
    // La même règle que le serveur : un preset vide est un piège, on le charge en
    // croyant récupérer une géométrie et on obtient un canvas nu.
    expect(draftProblem("A", 1280, 720, [], [])).toContain("au moins une ligne");
  });

  test("accepte une zone sans ligne", () => {
    expect(draftProblem("A", 1280, 720, [], [ZONE])).toBeNull();
  });

  test("refuse tant que les dimensions sont inconnues", () => {
    // Enregistrer avant que la vidéo ait ses métadonnées produirait un preset avec
    // `sourceWidth: 0`, donc impossible à mettre à l'échelle ensuite.
    expect(draftProblem("A", 0, 0, [LINE], [])).toContain("dimensions");
  });

  test("chaque message dit quoi faire", () => {
    // Un bouton grisé sans explication est le défaut d'interface le plus
    // frustrant : chaque cause a une action différente.
    const problems = [
      draftProblem("", 1280, 720, [LINE], []),
      draftProblem("A", 0, 0, [LINE], []),
      draftProblem("A", 1280, 720, [], []),
    ];

    for (const problem of problems) {
      expect(problem).not.toBeNull();
      expect(problem?.length).toBeGreaterThan(15);
    }
  });
});
