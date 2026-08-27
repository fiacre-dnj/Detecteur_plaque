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
  LINE_KINDS,
  crossingDirectionName,
  crossingHeadingDeg,
  directionArrow,
  directionHeadingDeg,
  directionName,
  directionRole,
  isForbiddenRole,
  lineHasRule,
  lineKind,
  lineName,
  roleLabel,
  rolesForKind,
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

describe("directionName — le rôle d'abord, un repli pour les lignes héritées", () => {
  it("le rôle **est** le libellé, depuis ADR 0021", () => {
    const roled = line({ positiveRole: "entry", negativeRole: "exit" });

    expect(directionName(roled, "positive")).toBe("Entrée");
    expect(directionName(roled, "negative")).toBe("Sortie");
  });

  it("le rôle l'emporte même sur un nom saisi", () => {
    // Le panneau de géométrie n'écrit plus les deux à la fois, mais une ligne
    // héritée peut encore porter les deux — le rôle gagne toujours.
    const both = line({ positiveRole: "entry", positiveName: "Vieux libellé" });

    expect(directionName(both, "positive")).toBe("Entrée");
  });

  it("retombe sur le nom saisi quand le rôle est neutre (ligne héritée)", () => {
    const named = line({ positiveName: "Entrée rue Foch" });

    expect(directionName(named, "positive")).toBe("Entrée rue Foch");
  });

  it("retombe sur le défaut géométrique quand rôle et nom sont vides", () => {
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

/*
 * L'angle de la flèche de sens.
 *
 * Ces tests vivaient dans `analysis-job/model/crossingTimeline.test.ts`, où la
 * fonction était née. Elle a déménagé ici quand un deuxième — puis un troisième —
 * écran en a eu besoin : le panneau de géométrie, la chronologie des franchissements
 * et les puces « Lignes franchies » du registre. C'est le même angle pour les trois,
 * et c'est précisément ce que ce fichier verrouille.
 */
describe("directionHeadingDeg — la flèche prend l'angle du tracé", () => {
  function segment(a: { x: number; y: number }, b: { x: number; y: number }): CountingLine {
    return line({ a, b });
  }

  /**
   * L'angle ramené dans `]−180, 180]`.
   *
   * `rotate(-180deg)` et `rotate(180deg)` sont la **même** rotation, et c'est
   * l'arithmétique du zéro négatif qui décide laquelle sort : le normal d'une ligne
   * horizontale porte un `x` valant `-0`, ce qui fait basculer `atan2` de `π` à `−π`.
   * Assertionner la valeur brute figerait ce détail sans rapport avec ce qu'on veut
   * vérifier — et normaliser dans `directionHeadingDeg` ferait diverger son chiffre
   * de celui d'`arrowRotationDeg` pour une flèche identique à l'écran.
   */
  function rotation(deg: number | null): number {
    if (deg === null) return Number.NaN;
    const wrapped = ((deg % 360) + 360) % 360;
    return wrapped > 180 ? wrapped - 360 : wrapped;
  }

  it("pointe perpendiculairement au trait, du côté d'arrivée", () => {
    // Une ligne horizontale se franchit **verticalement** : c'est ce que montre le
    // canvas, et c'est la seule raison d'être de cette flèche.
    const horizontal = segment({ x: 0, y: 0 }, { x: 100, y: 0 });

    // Le côté positif d'une ligne tracée vers la droite est **en bas** (y descend
    // dans le repère de la vidéo) : la flèche est à 180° d'une flèche vers le haut.
    expect(rotation(directionHeadingDeg(horizontal, "positive"))).toBe(180);
    expect(rotation(directionHeadingDeg(horizontal, "negative"))).toBe(0);
  });

  it("suit la ligne quand on la fait pivoter", () => {
    // **Le comportement attendu** : l'angle n'est pas une constante par sens, c'est
    // celui du tracé. Pivoter la ligne de 45° pivote la flèche d'autant.
    const droit = segment({ x: 0, y: 0 }, { x: 100, y: 0 });
    const oblique = segment({ x: 0, y: 0 }, { x: 100, y: 100 });

    // 180° puis 225° — écrit −135°, la même rotation. La flèche a bien pivoté de 45°.
    expect(rotation(directionHeadingDeg(droit, "positive"))).toBe(180);
    expect(rotation(directionHeadingDeg(oblique, "positive"))).toBeCloseTo(-135, 6);
  });

  it("oppose exactement les deux sens d'une même ligne", () => {
    const oblique = segment({ x: 20, y: 90 }, { x: 130, y: 15 });

    const positive = directionHeadingDeg(oblique, "positive") ?? 0;
    const negative = directionHeadingDeg(oblique, "negative") ?? 0;

    expect(Math.abs(Math.abs(positive - negative) - 180)).toBeCloseTo(0, 6);
  });

  it("**mène bien du côté d'arrivée**, et pas du côté opposé", () => {
    // Le test qui compte, et le mode de panne qu'il attrape : un signe inversé ferait
    // pointer chaque flèche à l'envers sous des rôles et des totaux par ailleurs
    // justes — la panne silencieuse que `geometry.ts` documente, et le risque exact
    // que crée la négation du sens négatif.
    //
    // On reconstruit le vecteur depuis l'angle (l'inverse d'`arrowRotationDeg`), on
    // avance depuis le milieu du segment, et on demande à `sideOfLine` — la formule du
    // backend — de quel côté on est tombé.
    const oblique = segment({ x: 20, y: 90 }, { x: 130, y: 15 });
    const middle = { x: 75, y: 52.5 };

    for (const [sign, expected] of [
      ["positive", 1],
      ["negative", -1],
    ] as const) {
      const radians = ((directionHeadingDeg(oblique, sign) ?? 0) * Math.PI) / 180;
      const arrived = {
        x: middle.x + Math.sin(radians) * 30,
        y: middle.y - Math.cos(radians) * 30,
      };

      expect(sideOfLine(oblique.a, oblique.b, arrived)).toBe(expected);
    }
  });

  it("n'invente pas d'angle sur un segment de longueur nulle", () => {
    // `arrowRotationDeg` y rendrait `0`, soit une flèche vers le haut affirmée sans
    // mesure. Une ligne qu'on vient de commencer à tracer est dans ce cas.
    expect(directionHeadingDeg(segment({ x: 50, y: 50 }, { x: 50, y: 50 }), "positive")).toBeNull();
  });
});

describe("crossingHeadingDeg — l'angle depuis un franchissement", () => {
  const lines = [line({ id: "l1", a: { x: 0, y: 0 }, b: { x: 100, y: 0 } })];

  it("donne le même angle que directionHeadingDeg, par le signe du franchissement", () => {
    expect(crossingHeadingDeg(lines, "l1", 1)).toBe(directionHeadingDeg(lines[0]!, "positive"));
    expect(crossingHeadingDeg(lines, "l1", -1)).toBe(directionHeadingDeg(lines[0]!, "negative"));
  });

  it("rend null pour une ligne retirée du tracé", () => {
    // Même repli que `crossingDirectionName`, et pour la même raison : la géométrie ne
    // dit plus rien. L'appelant montre alors la flèche brute de la convention serveur,
    // qui ne prétend décrire aucun angle.
    expect(crossingHeadingDeg(lines, "disparue", 1)).toBeNull();
  });
});

describe("le type d'une ligne — dérivé, jamais stocké", () => {
  it("fait l'aller-retour sur les cinq types choisissables", () => {
    // C'est **la** propriété qui justifie de ne stocker aucun champ `lineKind` : le
    // type se relit exactement depuis la paire de rôles qu'il a posée. Sans elle,
    // une ligne pourrait s'afficher « sens unique » tout en comptant deux sens, sans
    // que rien ne plante.
    for (const option of LINE_KINDS) {
      const roles = rolesForKind(option.kind);
      const built = line({ positiveRole: roles.positive, negativeRole: roles.negative });

      expect(lineKind(built)).toBe(option.kind);
    }
  });

  it("range une paire héritée sous « à préciser »", () => {
    // Un sens resté `neutral` — preset ou `configJson` d'avant ADR 0021 — n'est
    // aucun des types proposés : le panneau demande alors un choix explicite plutôt
    // que de deviner un bilan que personne n'a demandé.
    expect(lineKind(line())).toBe("undeclared");
    expect(lineKind(line({ positiveRole: "entry", negativeRole: "entry" }))).toBe("undeclared");
  });

  it("distingue le côté interdit d'une ligne à sens unique", () => {
    expect(lineKind(line({ positiveRole: "entry", negativeRole: "forbidden" }))).toBe(
      "oneway-entry",
    );
    expect(lineKind(line({ positiveRole: "forbidden", negativeRole: "entry" }))).toBe(
      "oneway-entry",
    );
    expect(lineKind(line({ positiveRole: "exit", negativeRole: "forbidden" }))).toBe(
      "oneway-exit",
    );
  });

  it("ne propose jamais « à préciser » comme choix", () => {
    // On n'en choisit pas un état hérité : on en sort. `rolesForKind` lui donne donc
    // la paire par défaut, pour que le premier clic range la ligne au lieu de la
    // laisser dans l'état qu'on voulait quitter.
    expect(LINE_KINDS.some((option) => option.kind === "undeclared")).toBe(false);
    expect(rolesForKind("undeclared")).toEqual({ positive: "entry", negative: "exit" });
  });
});

describe("les libellés des nouveaux rôles", () => {
  it("nomme « Interdit » et « Passage »", () => {
    // Le rôle **est** le libellé depuis ADR 0021 : un rôle que ce module ne nomme
    // pas retomberait sur le nom géométrique — « Vers le haut » là où on attend
    // « Interdit » — sans que rien ne plante.
    const oneway = line({ positiveRole: "entry", negativeRole: "forbidden" });
    expect(directionName(oneway, "negative")).toBe("Interdit");

    const counting = line({ positiveRole: "transit", negativeRole: "transit" });
    expect(directionName(counting, "positive")).toBe("Passage");
  });

  it("rend le libellé court en minuscules", () => {
    expect(roleLabel("forbidden")).toBe("interdit");
    expect(roleLabel("transit")).toBe("passage");
  });

  it("garde une flèche sur un sens interdit", () => {
    // Un sens interdit **est** un sens : savoir de quel côté il l'est est toute
    // l'information. Seul `neutral` n'a rien à orienter.
    const oneway = line({ positiveRole: "entry", negativeRole: "forbidden" });
    expect(directionHeadingDeg(oneway, "negative")).not.toBeNull();
  });
});

describe("isForbiddenRole et lineHasRule", () => {
  it("ne reconnaît qu'`interdit` comme sens interdit", () => {
    expect(isForbiddenRole("forbidden")).toBe(true);
    expect(isForbiddenRole("transit")).toBe(false);
    expect(isForbiddenRole("neutral")).toBe(false);
  });

  it("repère une ligne qui déclare une règle, de l'une ou l'autre sorte", () => {
    expect(lineHasRule(line({ positiveRole: "entry", negativeRole: "exit" }))).toBe(false);
    expect(lineHasRule(line({ negativeRole: "forbidden" }))).toBe(true);
    expect(lineHasRule(line({ allowedClassIds: [5] }))).toBe(true);
  });
});
