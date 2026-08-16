/**
 * Deux calculs de placement, tous deux extraits de `draw.ts` pour la même raison :
 * `drawLabelAt` a besoin d'un contexte 2D, eux non — et il n'y a ni jsdom ni
 * testing-library dans ce projet.
 *
 * Le second, `directionLabelAnchors`, protège un **signe** contre `sideOfLine`. Un
 * signe s'inverse sans qu'on le remarque : les totaux resteraient justes et l'écran
 * dirait « Vers la droite » pour des véhicules qui vont à gauche. C'est la même
 * discipline que le test de `positiveNormal`, et la même panne silencieuse.
 *
 * Ce que le premier protège : **l'étiquette de plaque qui sort du canvas**.
 *
 * Une plaque lisible est une plaque proche, donc basse dans l'image. Sans bascule vers
 * le haut, l'étiquette disparaîtrait précisément quand elle porte l'information la plus
 * sûre — et le seul symptôme serait « ça ne s'affiche pas », sans rien à déboguer.
 *
 * `plateLabelBaseline` est extraite pour cette raison : `drawLabelAt` a besoin d'un
 * contexte 2D, ce calcul non — et il n'y a ni jsdom ni testing-library dans ce projet.
 */

import { describe, expect, it } from "bun:test";

import type { Box, Point } from "@/shared/api/contracts";
import { sideOfLine } from "@/shared/lib/geometry";

import {
  DIRECTION_LABEL_CLEARANCE,
  type LabelPlacement,
  directionLabelAnchors,
  lineNameAnchor,
  plateLabelBaseline,
  resolveLabelCollisions,
} from "./draw";

/** Hauteur d'étiquette + écart, tels que `drawLabelAt` les peint. */
const LABEL_SPACE = 18;

function plateBox(y: number, height = 9): Box {
  return { x: 100, y, width: 32, height };
}

describe("plateLabelBaseline", () => {
  it("pose l'étiquette sous le rectangle quand la place existe", () => {
    const box = plateBox(200);
    expect(plateLabelBaseline(box, 1080)).toBe(200 + 9 + LABEL_SPACE);
  });

  it("bascule au-dessus quand le bas du canvas est atteint", () => {
    // Le cas réel : un véhicule proche, en bas de l'image, dont la plaque est la
    // mieux lue de toute la scène.
    const box = plateBox(1060);
    expect(plateLabelBaseline(box, 1080)).toBe(1060 - 2);
  });

  it("reste en dessous quand il ne manque pas un pixel", () => {
    // La frontière, et non le cas facile : `below === canvasHeight` doit encore
    // passer, sinon la dernière ligne utile de l'image serait perdue.
    const box = plateBox(1080 - 9 - LABEL_SPACE);
    expect(plateLabelBaseline(box, 1080)).toBe(1080);
  });

  it("bascule dès qu'il manque un seul pixel", () => {
    const y = 1080 - 9 - LABEL_SPACE + 1;
    expect(plateLabelBaseline(plateBox(y), 1080)).toBe(y - 2);
  });

  it("tient compte de la hauteur du rectangle, pas seulement de son sommet", () => {
    // Une plaque vue de près est plus haute : son étiquette descend d'autant.
    const petite = plateLabelBaseline(plateBox(500, 9), 1080);
    const grande = plateLabelBaseline(plateBox(500, 40), 1080);
    expect(grande - petite).toBe(31);
  });
});

describe("directionLabelAnchors — placement des deux libellés de sens", () => {
  /** Le cas courant : une ligne horizontale, franchie verticalement. */
  const a: Point = { x: 0, y: 500 };
  const b: Point = { x: 1920, y: 500 };
  /** Une étiquette réaliste : « → Entree centre-vil… » mesure environ 130 px. */
  const SIZE = { width: 130, height: 16 };
  const SIZES = { positive: SIZE, negative: SIZE };

  /** La boîte peinte autour d'une ancre — `drawCentredLabel` centre sur les deux axes. */
  function box(anchor: Point, size = SIZE) {
    return {
      left: anchor.x - size.width / 2,
      right: anchor.x + size.width / 2,
      top: anchor.y - size.height / 2,
      bottom: anchor.y + size.height / 2,
    };
  }

  function overlap(first: ReturnType<typeof box>, second: ReturnType<typeof box>): boolean {
    return (
      first.left < second.right &&
      second.left < first.right &&
      first.top < second.bottom &&
      second.top < first.bottom
    );
  }

  it("**pose le libellé positif du côté où sideOfLine rend +1**", () => {
    // LE test de signe. Si les deux s'inversaient, l'écran nommerait chaque sens à
    // l'envers sous des totaux parfaitement justes.
    const anchors = directionLabelAnchors(a, b, SIZES);
    expect(anchors).not.toBeNull();
    if (anchors === null) return;

    expect(sideOfLine(a, b, anchors.positive)).toBe(1);
    expect(sideOfLine(a, b, anchors.negative)).toBe(-1);
  });

  it("tient aussi pour une ligne verticale", () => {
    // Seconde orientation : `positiveNormal` fait une rotation, et une seule des deux
    // orientations pourrait être fausse.
    const top: Point = { x: 900, y: 0 };
    const bottom: Point = { x: 900, y: 1080 };
    const anchors = directionLabelAnchors(top, bottom, SIZES);
    expect(anchors).not.toBeNull();
    if (anchors === null) return;

    expect(sideOfLine(top, bottom, anchors.positive)).toBe(1);
    expect(sideOfLine(top, bottom, anchors.negative)).toBe(-1);
  });

  it("**ne fait jamais se chevaucher les deux étiquettes, quel que soit l'angle**", () => {
    // Le défaut corrigé : avec un décalage fixe de 30 px, une ligne verticale mettait
    // deux boîtes de 130 px de large à 60 px l'une de l'autre. Elles se recouvraient
    // sur 70 px, et les deux sens devenaient illisibles.
    //
    // Toutes les orientations, tous les 5° : c'est le balayage qui prouve que la
    // correction ne marche pas seulement sur les deux angles qu'on teste d'habitude.
    for (let degrees = 0; degrees < 360; degrees += 5) {
      const radians = (degrees * Math.PI) / 180;
      const end: Point = {
        x: 500 + Math.cos(radians) * 400,
        y: 500 + Math.sin(radians) * 400,
      };
      const anchors = directionLabelAnchors({ x: 500, y: 500 }, end, SIZES);
      expect(anchors, `${degrees}°`).not.toBeNull();
      if (anchors === null) continue;

      expect(overlap(box(anchors.positive), box(anchors.negative)), `${degrees}°`).toBe(false);
    }
  });

  it("laisse le même espace libre quel que soit l'angle", () => {
    // La propriété qui rend le placement prévisible : l'écart entre les bords des deux
    // boîtes ne dépend pas de l'orientation, donc l'œil retrouve toujours la même
    // silhouette. Un décalage fixe donnait un espace qui fondait avec l'angle.
    const gaps = [0, 30, 45, 60, 90].map((degrees) => {
      const radians = (degrees * Math.PI) / 180;
      const anchors = directionLabelAnchors(
        { x: 500, y: 500 },
        { x: 500 + Math.cos(radians) * 400, y: 500 + Math.sin(radians) * 400 },
        SIZES,
      );
      if (anchors === null) return 0;
      // Distance entre les deux ancres, moins ce que chaque boîte occupe le long du
      // normal qui les sépare.
      const dx = anchors.positive.x - anchors.negative.x;
      const dy = anchors.positive.y - anchors.negative.y;
      const distance = Math.hypot(dx, dy);
      const unit = { x: dx / distance, y: dy / distance };
      const extent =
        Math.abs(unit.x) * (SIZE.width / 2) + Math.abs(unit.y) * (SIZE.height / 2);
      return Math.round(distance - 2 * extent);
    });

    expect(gaps).toEqual(gaps.map(() => 2 * DIRECTION_LABEL_CLEARANCE));
  });

  it("écarte davantage une étiquette plus large sur une ligne verticale", () => {
    // Le décalage suit la taille du texte : sinon un libellé long dépasserait de la
    // zone réservée et mordrait sur l'autre.
    const top: Point = { x: 900, y: 0 };
    const bottom: Point = { x: 900, y: 1080 };
    const court = directionLabelAnchors(top, bottom, {
      positive: { width: 60, height: 16 },
      negative: { width: 60, height: 16 },
    });
    const long = directionLabelAnchors(top, bottom, SIZES);
    if (court === null || long === null) return;

    expect(Math.abs(long.positive.x - 900)).toBeGreaterThan(Math.abs(court.positive.x - 900));
  });

  it("suit le retournement du tracé", () => {
    // A et B échangés : les deux ancres échangent leur place, sinon retourner une
    // ligne afficherait des sens faux.
    const forward = directionLabelAnchors(a, b, SIZES);
    const backward = directionLabelAnchors(b, a, SIZES);
    if (forward === null || backward === null) return;

    expect(backward.positive).toEqual(forward.negative);
    expect(backward.negative).toEqual(forward.positive);
  });

  it("rend null sur un segment de longueur nulle", () => {
    // Aucun côté n'existe ; poser deux étiquettes au même point les rendrait
    // illisibles.
    expect(directionLabelAnchors({ x: 100, y: 100 }, { x: 100, y: 100 }, SIZES)).toBeNull();
  });
});

describe("lineNameAnchor — le nom ne dispute plus le milieu aux sens", () => {
  it("se pose près de la poignée A, pas au milieu", () => {
    // Le défaut corrigé : au milieu, le nom chevauchait le libellé du sens négatif dès
    // que la ligne penchait — les deux se disputaient le même axe perpendiculaire.
    const a: Point = { x: 100, y: 500 };
    const b: Point = { x: 900, y: 500 };
    const anchor = lineNameAnchor(a, b);

    expect(anchor.x).toBeLessThan((a.x + b.x) / 2);
    expect(anchor.x).toBeGreaterThan(a.x);
  });

  it("se décale du trait pour ne pas le recouvrir", () => {
    const anchor = lineNameAnchor({ x: 100, y: 500 }, { x: 900, y: 500 });

    expect(Math.abs(anchor.y - 500)).toBeGreaterThan(8);
  });

  it("ne dépasse jamais le milieu, même sur un segment très court", () => {
    // Sinon le nom atterrirait du mauvais côté du centre, là où vivent les sens.
    const a: Point = { x: 500, y: 500 };
    const b: Point = { x: 520, y: 500 };
    const anchor = lineNameAnchor(a, b);

    expect(anchor.x).toBeLessThanOrEqual((a.x + b.x) / 2);
  });

  it("ne lève pas sur un segment de longueur nulle", () => {
    const anchor = lineNameAnchor({ x: 100, y: 100 }, { x: 100, y: 100 });

    expect(Number.isFinite(anchor.x)).toBe(true);
    expect(Number.isFinite(anchor.y)).toBe(true);
  });
});

describe("resolveLabelCollisions — deux lignes proches ne s'écrasent plus", () => {
  const VIEW = { width: 800, height: 450 };
  const SIZE = { width: 120, height: 16 };

  function label(
    key: string,
    centre: Point,
    escape: Point | null = { x: 0, y: 1 },
  ): LabelPlacement {
    return { key, text: key, color: "#539df5", centre, escape, size: SIZE, emphasis: 0 };
  }

  function overlaps(placed: readonly ReturnType<typeof resolveLabelCollisions>[number][]): string[] {
    const clashes: string[] = [];
    for (let i = 0; i < placed.length; i += 1) {
      for (let j = i + 1; j < placed.length; j += 1) {
        const p = placed[i];
        const q = placed[j];
        if (p === undefined || q === undefined) continue;
        if (
          p.x < q.x + q.size.width &&
          q.x < p.x + p.size.width &&
          p.y < q.y + q.size.height &&
          q.y < p.y + p.size.height
        ) {
          clashes.push(`${p.key}/${q.key}`);
        }
      }
    }
    return clashes;
  }

  it("laisse une étiquette isolée exactement où elle veut être", () => {
    const [placed] = resolveLabelCollisions([label("seule", { x: 400, y: 200 })], VIEW);

    expect(placed?.x).toBe(400 - SIZE.width / 2);
    expect(placed?.y).toBe(200 - SIZE.height / 2);
  });

  it("**écarte deux étiquettes qui se superposeraient**", () => {
    // Le défaut de la capture : deux lignes parallèles distantes de quelques dizaines
    // de pixels posaient le libellé « dessous » de l'une sur le « dessus » de l'autre.
    const placed = resolveLabelCollisions(
      [label("basse", { x: 400, y: 200 }), label("haute", { x: 405, y: 205 })],
      VIEW,
    );

    expect(overlaps(placed)).toEqual([]);
  });

  it("écarte le long de l'échappée, donc **sans changer de côté**", () => {
    // La contrainte qui rend l'écartement acceptable : une étiquette qui passerait de
    // l'autre côté du trait nommerait le mauvais sens. Elle s'éloigne, elle ne
    // traverse pas.
    const placed = resolveLabelCollisions(
      [
        label("fixe", { x: 400, y: 200 }, null),
        label("mobile", { x: 400, y: 200 }, { x: 0, y: 1 }),
      ],
      VIEW,
    );

    const mobile = placed.find((entry) => entry.key === "mobile");
    expect(mobile?.y).toBeGreaterThan(200);
    expect(placed.find((entry) => entry.key === "fixe")?.y).toBe(200 - SIZE.height / 2);
  });

  it("ne déplace jamais une étiquette fixe", () => {
    // Les noms de ligne passent en premier et sont fixes : un nom qui errerait loin de
    // son trait serait pire qu'un chevauchement.
    const placed = resolveLabelCollisions(
      [label("nom-a", { x: 400, y: 200 }, null), label("nom-b", { x: 402, y: 202 }, null)],
      VIEW,
    );

    expect(placed[0]?.y).toBe(200 - SIZE.height / 2);
    expect(placed[1]?.y).toBe(202 - SIZE.height / 2);
    // Deux fixes qui se croisent restent croisées : c'est assumé, et cela ne se
    // produit qu'entre deux noms de lignes quasi confondues.
    expect(overlaps(placed)).toHaveLength(1);
  });

  it("résout une pile de six étiquettes au même point", () => {
    // Le cas dégénéré : six lignes tracées l'une sur l'autre. Aucune ne doit disparaître.
    const placed = resolveLabelCollisions(
      Array.from({ length: 6 }, (_, index) => label(`l${index}`, { x: 400, y: 100 })),
      VIEW,
    );

    expect(placed).toHaveLength(6);
    expect(overlaps(placed)).toEqual([]);
  });

  it("**borne chaque étiquette au canvas**", () => {
    // Une ligne tracée près d'un bord — le cas courant, puisqu'on trace en travers de
    // la chaussée — poussait son libellé hors cadre, où il était simplement invisible.
    const placed = resolveLabelCollisions(
      [
        label("hors-gauche", { x: -200, y: 20 }),
        label("hors-droite", { x: 1200, y: 20 }),
        label("hors-bas", { x: 400, y: 900 }),
      ],
      VIEW,
    );

    for (const entry of placed) {
      expect(entry.x).toBeGreaterThanOrEqual(0);
      expect(entry.y).toBeGreaterThanOrEqual(0);
      expect(entry.x + entry.size.width).toBeLessThanOrEqual(VIEW.width);
      expect(entry.y + entry.size.height).toBeLessThanOrEqual(VIEW.height);
    }
  });

  it("pose quand même une étiquette qui ne trouve pas de place", () => {
    // Renoncer à l'afficher serait pire : un libellé absent se lit comme un sens non
    // configuré, alors qu'il l'est. Ici l'échappée est bloquée par le bord.
    const placed = resolveLabelCollisions(
      [
        label("premier", { x: 400, y: 440 }),
        label("second", { x: 400, y: 440 }),
        label("troisieme", { x: 400, y: 440 }),
      ],
      VIEW,
    );

    expect(placed).toHaveLength(3);
    expect(placed.every((entry) => Number.isFinite(entry.x) && Number.isFinite(entry.y))).toBe(
      true,
    );
  });

  it("rend une liste vide sans entrée", () => {
    expect(resolveLabelCollisions([], VIEW)).toEqual([]);
  });
});
