/**
 * Le reducer d'édition, et les deux comportements qui coûtent un bug.
 *
 * Le plus important est la **cohérence ligne↔zone à la suppression** : une ligne
 * qui référence une zone disparue fait échouer la requête en 422, après que
 * l'utilisateur a cliqué « Lancer l'analyse ». C'est le pire moment pour un refus,
 * et c'est la raison d'être du reducer.
 *
 * Le second est le **décalage de préhension** : un déplacement doit translater la
 * forme, jamais la recentrer sur le curseur ni la déformer.
 */

import { beforeEach, describe, expect, it } from "bun:test";

import type { CountingLine, Zone } from "@/shared/api/contracts";

import {
  geometryReducer,
  resetIdCounter,
  translateLine,
  translateZone,
  withDirectionDefaults,
} from "./reducer";
import { EMPTY_GEOMETRY, geometrySignature, scaleGeometry, type GeometryState } from "./types";

const WIDTH = 1920;
const HEIGHT = 1080;

beforeEach(() => {
  // Identifiants stables d'un test à l'autre : sans cela, l'ordre d'exécution
  // changerait les identifiants attendus.
  resetIdCounter();
});

/** Un état portant une zone et une ligne rattachée à cette zone. */
function withLinkedZone(): GeometryState {
  let state = geometryReducer(EMPTY_GEOMETRY, {
    type: "addZone",
    points: [
      { x: 100, y: 100 },
      { x: 800, y: 100 },
      { x: 800, y: 700 },
    ],
  });
  const zoneId = state.zones[0]?.id ?? "";
  state = geometryReducer(state, { type: "addLine", width: WIDTH, height: HEIGHT });
  const lineId = state.lines[0]?.id ?? "";
  return geometryReducer(state, { type: "setLineZone", id: lineId, zoneId });
}

describe("cohérence ligne ↔ zone", () => {
  it("détache les lignes d'une zone supprimée", () => {
    // **Le test qui justifie le reducer.** Sans ce détachement, la requête part
    // avec une `zoneId` inexistante et le serveur la refuse en 422 — après le
    // clic sur « Lancer », donc au pire moment.
    const state = withLinkedZone();
    const zoneId = state.zones[0]?.id ?? "";
    expect(state.lines[0]?.zoneId).toBe(zoneId);

    const after = geometryReducer(state, { type: "removeZone", id: zoneId });

    expect(after.zones).toHaveLength(0);
    expect(after.lines).toHaveLength(1);
    expect(after.lines[0]?.zoneId).toBeNull();
  });

  it("ne détache pas les lignes rattachées à une autre zone", () => {
    let state = withLinkedZone();
    state = geometryReducer(state, {
      type: "addZone",
      points: [
        { x: 900, y: 100 },
        { x: 1500, y: 100 },
        { x: 1500, y: 700 },
      ],
    });
    const firstZoneId = state.zones[0]?.id ?? "";
    const secondZoneId = state.zones[1]?.id ?? "";

    const after = geometryReducer(state, { type: "removeZone", id: secondZoneId });

    expect(after.lines[0]?.zoneId).toBe(firstZoneId);
  });

  it("efface la sélection quand la forme sélectionnée disparaît", () => {
    // Une sélection qui survit à sa cible fait dessiner des poignées sur du vide.
    const state = withLinkedZone();
    const zoneId = state.zones[0]?.id ?? "";
    const selected = geometryReducer(state, {
      type: "select",
      selection: { kind: "zone", id: zoneId },
    });

    const after = geometryReducer(selected, { type: "removeZone", id: zoneId });

    expect(after.selection).toEqual({ kind: "none" });
  });

  it("garde la sélection quand une autre forme est supprimée", () => {
    let state = geometryReducer(EMPTY_GEOMETRY, { type: "addLine", width: WIDTH, height: HEIGHT });
    state = geometryReducer(state, { type: "addLine", width: WIDTH, height: HEIGHT });
    const firstId = state.lines[0]?.id ?? "";
    const secondId = state.lines[1]?.id ?? "";
    state = geometryReducer(state, { type: "select", selection: { kind: "line", id: firstId } });

    const after = geometryReducer(state, { type: "removeLine", id: secondId });

    expect(after.selection).toEqual({ kind: "line", id: firstId });
  });
});

describe("création", () => {
  it("amorce une ligne dans le tiers inférieur, où le trafic est au premier plan", () => {
    // Un écran sans ligne ne compte rien, et l'utilisateur qui obtient zéro ne
    // devine pas que c'est parce qu'il n'a rien tracé.
    const state = geometryReducer(EMPTY_GEOMETRY, {
      type: "addLine",
      width: WIDTH,
      height: HEIGHT,
    });
    const line = state.lines[0];

    expect(line).toBeDefined();
    expect(line?.a.y).toBeCloseTo(HEIGHT * 0.66, 5);
    expect(line?.a.y).toBe(line?.b.y);
  });

  it("garde les poignées à l'écart des bords pour qu'elles restent saisissables", () => {
    const state = geometryReducer(EMPTY_GEOMETRY, {
      type: "addLine",
      width: WIDTH,
      height: HEIGHT,
    });
    const line = state.lines[0];

    expect(line?.a.x).toBeGreaterThan(0);
    expect(line?.b.x).toBeLessThan(WIDTH);
  });

  it("sélectionne la forme créée", () => {
    const state = geometryReducer(EMPTY_GEOMETRY, {
      type: "addLine",
      width: WIDTH,
      height: HEIGHT,
    });
    const created = state.lines[0];
    expect(created).toBeDefined();
    if (created === undefined) return;

    expect(state.selection).toEqual({ kind: "line", id: created.id });
  });

  it("refuse une zone de moins de trois sommets", () => {
    // Dernière barrière avant une requête que le serveur refusera.
    const state = geometryReducer(EMPTY_GEOMETRY, {
      type: "addZone",
      points: [
        { x: 0, y: 0 },
        { x: 10, y: 10 },
      ],
    });

    expect(state.zones).toHaveLength(0);
  });

  it("referme le mode tracé après avoir ajouté une zone", () => {
    const drawing = geometryReducer(EMPTY_GEOMETRY, { type: "setDrawingZone", drawing: true });
    const state = geometryReducer(drawing, {
      type: "addZone",
      points: [
        { x: 0, y: 0 },
        { x: 10, y: 0 },
        { x: 10, y: 10 },
      ],
    });

    expect(state.drawingZone).toBe(false);
  });

  it("désélectionne en entrant en mode tracé", () => {
    // Les poignées de la forme sélectionnée capteraient les clics destinés aux
    // sommets du nouveau polygone.
    let state = geometryReducer(EMPTY_GEOMETRY, { type: "addLine", width: WIDTH, height: HEIGHT });
    state = geometryReducer(state, { type: "setDrawingZone", drawing: true });

    expect(state.selection).toEqual({ kind: "none" });
  });
});

describe("nommage des sens", () => {
  function withLine(): GeometryState {
    return geometryReducer(EMPTY_GEOMETRY, { type: "addLine", width: WIDTH, height: HEIGHT });
  }

  it("crée une ligne avec des noms de sens **vides** et un rôle déjà tranché", () => {
    // La chaîne vide n'est pas un oubli : c'est le signal que l'interface pose son
    // défaut géométrique, recalculé quand la ligne pivote. Y écrire un libellé le
    // figerait à l'orientation de la création. Le rôle, lui, est déjà entrée/sortie
    // — obligatoire depuis que le panneau ne propose plus « ni l'un ni l'autre ».
    const line = withLine().lines[0];

    expect(line?.positiveName).toBe("");
    expect(line?.negativeName).toBe("");
    expect(line?.positiveRole).toBe("entry");
    expect(line?.negativeRole).toBe("exit");
  });

  it("renomme un sens sans toucher à l'autre", () => {
    const state = withLine();
    const id = state.lines[0]?.id ?? "";

    const renamed = geometryReducer(state, {
      type: "renameDirection",
      id,
      sign: "positive",
      name: "Entrée rue Foch",
    });

    expect(renamed.lines[0]?.positiveName).toBe("Entrée rue Foch");
    expect(renamed.lines[0]?.negativeName).toBe("");
  });

  it("pose un rôle sans changer inutilement l'autre sens déjà complémentaire", () => {
    const state = withLine();
    const id = state.lines[0]?.id ?? "";

    const roled = geometryReducer(state, {
      type: "setDirectionRole",
      id,
      sign: "negative",
      role: "exit",
    });

    expect(roled.lines[0]?.negativeRole).toBe("exit");
    expect(roled.lines[0]?.positiveRole).toBe("entry");
  });

  it("**bascule automatiquement l'autre sens à l'opposé**, depuis ADR 0021", () => {
    // Le cas qui justifie le changement : une ligne dont les deux sens disaient
    // « entrée » ne devrait jamais exister — poser l'un des deux tranche l'autre.
    const state = withLine();
    const id = state.lines[0]?.id ?? "";

    const bothEntry = geometryReducer(state, {
      type: "setDirectionRole",
      id,
      sign: "negative",
      role: "entry",
    });

    expect(bothEntry.lines[0]?.negativeRole).toBe("entry");
    expect(bothEntry.lines[0]?.positiveRole).toBe("exit");
  });

  it("ne bascule rien pour un rôle neutre", () => {
    // `neutral` n'est plus atteignable depuis le panneau, mais l'action reste
    // générale : elle ne doit pas prêter un opposé à un rôle qui n'en a pas.
    const state = withLine();
    const id = state.lines[0]?.id ?? "";

    const neutral = geometryReducer(state, {
      type: "setDirectionRole",
      id,
      sign: "negative",
      role: "neutral",
    });

    expect(neutral.lines[0]?.negativeRole).toBe("neutral");
    expect(neutral.lines[0]?.positiveRole).toBe("entry");
  });

  it("ne touche pas aux autres lignes", () => {
    let state = geometryReducer(EMPTY_GEOMETRY, {
      type: "addLine",
      width: WIDTH,
      height: HEIGHT,
    });
    state = geometryReducer(state, { type: "addLine", width: WIDTH, height: HEIGHT });
    const first = state.lines[0]?.id ?? "";

    const renamed = geometryReducer(state, {
      type: "renameDirection",
      id: first,
      sign: "positive",
      name: "Nord",
    });

    expect(renamed.lines[1]?.positiveName).toBe("");
  });

  it("ignore une ligne inconnue plutôt que de lever", () => {
    const state = withLine();

    const untouched = geometryReducer(state, {
      type: "renameDirection",
      id: "disparue",
      sign: "positive",
      name: "Nord",
    });

    expect(untouched.lines).toEqual(state.lines);
  });

  it("complète les champs de sens d'un preset enregistré avant qu'ils existent", () => {
    // **Le cas qui casserait en silence.** Sans ce complément, `positiveRole` vaudrait
    // `undefined` là où le type promet un rôle, et les agrégations d'entrées/sorties
    // compareraient contre rien — un total qui reste à zéro sans qu'une erreur
    // l'explique.
    const legacy = {
      id: "l1",
      name: "Voie nord",
      color: "#539df5",
      zoneId: null,
      a: { x: 0, y: 600 },
      b: { x: 1920, y: 600 },
    } as unknown as CountingLine;

    const state = geometryReducer(EMPTY_GEOMETRY, {
      type: "replace",
      lines: [legacy],
      zones: [],
    });

    expect(state.lines[0]).toMatchObject({
      positiveName: "",
      negativeName: "",
      positiveRole: "neutral",
      negativeRole: "neutral",
    });
  });

  it("laisse intacts les champs déjà présents", () => {
    // Garde-fou du test précédent : le complément ne doit pas écraser un libellé.
    const named: CountingLine = {
      id: "l1",
      name: "Voie nord",
      color: "#539df5",
      zoneId: null,
      a: { x: 0, y: 600 },
      b: { x: 1920, y: 600 },
      positiveName: "Entrée",
      negativeName: "Sortie",
      positiveRole: "entry",
      negativeRole: "exit",
    };

    expect(withDirectionDefaults(named)).toEqual(named);
  });
});

describe("déplacement — le décalage de préhension", () => {
  const line: CountingLine = {
    id: "l1",
    name: "L",
    color: "#539df5",
    zoneId: null,
    positiveName: "",
    negativeName: "",
    positiveRole: "neutral" as const,
    negativeRole: "neutral" as const,
    a: { x: 100, y: 500 },
    b: { x: 900, y: 500 },
  };

  it("translate la ligne sans la recentrer sur le curseur", () => {
    // Sans décalage conservé, saisir une ligne par son extrémité la
    // téléporterait sous la souris au premier pixel de mouvement.
    const moved = translateLine(line, { x: 50, y: -20 }, WIDTH, HEIGHT);

    expect(moved.a).toEqual({ x: 150, y: 480 });
    expect(moved.b).toEqual({ x: 950, y: 480 });
  });

  it("refuse en bloc un déplacement qui sortirait du cadre, au lieu de déformer", () => {
    // Borner point par point ferait pivoter la ligne : un bout s'arrête au bord,
    // l'autre continue. Refuser garde la forme intacte.
    const moved = translateLine(line, { x: 0, y: 5000 }, WIDTH, HEIGHT);

    expect(moved.a).toEqual(line.a);
    expect(moved.b).toEqual(line.b);
  });

  it("applique la même règle du tout ou rien à une zone", () => {
    const zone: Zone = {
      id: "z1",
      name: "Z",
      color: "#ffa42b",
      points: [
        { x: 100, y: 100 },
        { x: 300, y: 100 },
        { x: 300, y: 300 },
      ],
    };

    expect(translateZone(zone, { x: 10, y: 10 }, WIDTH, HEIGHT)[0]).toEqual({ x: 110, y: 110 });
    expect(translateZone(zone, { x: -5000, y: 0 }, WIDTH, HEIGHT)).toEqual(zone.points);
  });
});

describe("signature de géométrie — la détection d'un résultat obsolète", () => {
  const line: CountingLine = {
    id: "l1",
    name: "Voie nord",
    color: "#539df5",
    zoneId: null,
    positiveName: "",
    negativeName: "",
    positiveRole: "neutral" as const,
    negativeRole: "neutral" as const,
    a: { x: 0, y: 600 },
    b: { x: 1920, y: 600 },
  };

  it("change quand une ligne se déplace", () => {
    // Le cas central : les chiffres affichés ne correspondent plus à la
    // géométrie visible, et sans ce bandeau rien ne le dirait.
    const before = geometrySignature([line], []);
    const after = geometrySignature([{ ...line, a: { x: 0, y: 400 } }], []);

    expect(after).not.toBe(before);
  });

  it("**ne change pas** quand un sens est renommé ou re-rôlé", () => {
    // Un libellé ne change aucun chiffre : le serveur ne le lit pas, et le bilan
    // entrées/sorties est recalculé côté client à chaque rendu. Faire clignoter le
    // bandeau « résultat obsolète » sur une correction de vocabulaire pousserait à
    // relancer une analyse de trente minutes pour rien.
    const before = geometrySignature([line], []);
    const renamed = geometrySignature(
      [{ ...line, positiveName: "Entrée nord", positiveRole: "entry" as const }],
      [],
    );

    expect(renamed).toBe(before);
  });

  it("change quand la portée d'une ligne change", () => {
    // Restreindre une ligne à une zone change ce qui est compté autant qu'un
    // déplacement.
    const before = geometrySignature([line], []);
    const after = geometrySignature([{ ...line, zoneId: "z1" }], []);

    expect(after).not.toBe(before);
  });

  it("change quand un sommet de zone bouge", () => {
    const zone: Zone = {
      id: "z1",
      name: "Z",
      color: "#ffa42b",
      points: [
        { x: 0, y: 0 },
        { x: 100, y: 0 },
        { x: 100, y: 100 },
      ],
    };
    const before = geometrySignature([], [zone]);
    const after = geometrySignature(
      [],
      [{ ...zone, points: [{ x: 0, y: 0 }, { x: 120, y: 0 }, { x: 100, y: 100 }] }],
    );

    expect(after).not.toBe(before);
  });

  it("ne change PAS pour un renommage", () => {
    // Volontaire : renommer ne change aucun chiffre. Avertir pour un renommage
    // apprendrait à l'utilisateur à ignorer l'avertissement — et il l'ignorerait
    // aussi le jour où il compte.
    const before = geometrySignature([line], []);
    const after = geometrySignature([{ ...line, name: "Nord" }], []);

    expect(after).toBe(before);
  });

  it("ne change PAS pour un changement de couleur", () => {
    const before = geometrySignature([line], []);
    const after = geometrySignature([{ ...line, color: "#ffa42b" }], []);

    expect(after).toBe(before);
  });

  it("ne change PAS pour un déplacement sous le pixel", () => {
    // Un glisser produit des flottants dont les dernières décimales n'ont aucune
    // conséquence sur le comptage. Les comparer déclencherait le bandeau pour un
    // déplacement invisible à l'œil.
    const before = geometrySignature([line], []);
    const after = geometrySignature([{ ...line, a: { x: 0.4, y: 600.2 } }], []);

    expect(after).toBe(before);
  });

  it("change quand une ligne est ajoutée ou retirée", () => {
    const one = geometrySignature([line], []);
    const two = geometrySignature([line, { ...line, id: "l2" }], []);

    expect(two).not.toBe(one);
    expect(geometrySignature([], [])).not.toBe(one);
  });
});

describe("mise à l'échelle d'un preset", () => {
  it("applique les facteurs x et y séparément", () => {
    // Une homothétie unique sortirait du cadre en changeant de format d'image :
    // un preset 16:9 chargé sur du 4:3 doit rester dans l'image.
    const line: CountingLine = {
      id: "l1",
      name: "L",
      color: "#539df5",
      zoneId: null,
      positiveName: "",
      negativeName: "",
      positiveRole: "neutral" as const,
      negativeRole: "neutral" as const,
      a: { x: 100, y: 200 },
      b: { x: 300, y: 200 },
    };

    const scaled = scaleGeometry([line], [], 0.5, 2);

    expect(scaled.lines[0]?.a).toEqual({ x: 50, y: 400 });
    expect(scaled.lines[0]?.b).toEqual({ x: 150, y: 400 });
  });

  it("préserve l'identité, le nom et la couleur", () => {
    const zone: Zone = {
      id: "z1",
      name: "Carrefour",
      color: "#ffa42b",
      points: [
        { x: 10, y: 10 },
        { x: 20, y: 10 },
        { x: 20, y: 20 },
      ],
    };

    const scaled = scaleGeometry([], [zone], 2, 2);

    expect(scaled.zones[0]?.id).toBe("z1");
    expect(scaled.zones[0]?.name).toBe("Carrefour");
    expect(scaled.zones[0]?.points[1]).toEqual({ x: 40, y: 20 });
  });
});
