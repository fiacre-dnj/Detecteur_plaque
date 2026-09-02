/**
 * La marge du cadrage de requête — la seule règle de cette étape.
 *
 * `cropToJpeg` touche un canvas et n'est donc pas testable ici ; `withMargin` porte
 * tout ce qui décide, et c'est ce qui fait **converger les deux côtés de la
 * comparaison** : la galerie encode la boîte du détecteur plus 6 %, la requête doit
 * lui ressembler. Sans elle, le même véhicule paraît 12 % plus gros dans la tuile de
 * requête que dans celle de la galerie, et la similarité baisse sans que rien ne le
 * signale.
 */

import { describe, expect, it } from "bun:test";

import { QUERY_MARGIN, withMargin } from "./crop";

describe("withMargin", () => {
  it("élargit de 6 % de chaque côté", () => {
    const framed = withMargin({ x: 0.4, y: 0.4, width: 0.2, height: 0.1 });

    expect(framed.x).toBeCloseTo(0.4 - 0.2 * QUERY_MARGIN, 10);
    expect(framed.y).toBeCloseTo(0.4 - 0.1 * QUERY_MARGIN, 10);
    expect(framed.width).toBeCloseTo(0.2 * (1 + 2 * QUERY_MARGIN), 10);
    expect(framed.height).toBeCloseTo(0.1 * (1 + 2 * QUERY_MARGIN), 10);
  });

  it("est proportionnelle à chaque côté, jamais un carré", () => {
    // Comme `pad_x = box.width * margin` / `pad_y = box.height * margin` côté
    // serveur : une marge absolue déformerait le rapport d'aspect, que le
    // prétraitement étire déjà au carré.
    const framed = withMargin({ x: 0.2, y: 0.2, width: 0.4, height: 0.1 });

    expect(framed.width - 0.4).toBeCloseTo(4 * (framed.height - 0.1), 10);
  });

  it("perd sa marge sur un bord, sans jamais sortir de l'image", () => {
    // **La même asymétrie que côté serveur**, où `crop` borne chaque arête
    // indépendamment. C'est tout ce qu'on demande : que les deux chaînes se trompent
    // de la même façon.
    const framed = withMargin({ x: 0, y: 0, width: 0.3, height: 0.3 });

    expect(framed.x).toBe(0);
    expect(framed.y).toBe(0);
    expect(framed.width).toBeCloseTo(0.3 * (1 + QUERY_MARGIN), 10);
  });

  it("laisse le plein cadre intact", () => {
    // Sans cadrage, toute la photo part — et il n'y a rien à élargir.
    expect(withMargin({ x: 0, y: 0, width: 1, height: 1 })).toEqual({
      x: 0,
      y: 0,
      width: 1,
      height: 1,
    });
  });

  it("borne un cadrage collé au coin opposé", () => {
    const framed = withMargin({ x: 0.8, y: 0.9, width: 0.2, height: 0.1 });

    expect(framed.x + framed.width).toBeCloseTo(1, 10);
    expect(framed.y + framed.height).toBeCloseTo(1, 10);
  });
});
