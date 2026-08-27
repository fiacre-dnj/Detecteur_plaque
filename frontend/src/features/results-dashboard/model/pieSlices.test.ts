/**
 * `groupSlices` — ce qui est tracé, ce qui est replié, ce qui ne se perd jamais.
 *
 * Le test qui compte est le dernier : la somme des parts tracées **plus** la part
 * agrégée doit égaler la somme reçue. C'est l'invariant 3 appliqué à un
 * graphique — un affichage dérive, il n'accumule pas — et c'est ce qu'un
 * regroupement écrit à la main casse en premier.
 */

import { describe, expect, it } from "bun:test";

import { groupSlices, OTHER_SLICE_ID, type PieSlice } from "./pieSlices";

const slice = (id: string, value: number): PieSlice => ({
  id,
  label: id,
  value,
  color: "#000",
});

describe("groupSlices", () => {
  it("classe par valeur décroissante", () => {
    const { shown } = groupSlices([slice("a", 1), slice("b", 9), slice("c", 5)], 6);
    expect(shown.map((s) => s.id)).toEqual(["b", "c", "a"]);
  });

  it("ne replie rien sous la limite, et ne fabrique aucune part agrégée", () => {
    const { shown, hidden, otherValue } = groupSlices([slice("a", 3), slice("b", 1)], 6);
    expect(shown).toHaveLength(2);
    expect(hidden).toEqual([]);
    expect(otherValue).toBe(0);
    expect(shown.map((s) => s.id)).not.toContain(OTHER_SLICE_ID);
  });

  it("replie le surplus dans une part agrégée qui porte leur somme", () => {
    const many = [10, 9, 8, 7, 6, 5, 4].map((value, index) => slice(`l${index}`, value));
    const { shown, hidden, otherValue } = groupSlices(many, 4);

    // Quatre parts au plus, agrégat compris : trois lignes nommées puis « 4 autres ».
    expect(shown).toHaveLength(4);
    expect(shown.at(-1)?.id).toBe(OTHER_SLICE_ID);
    expect(shown.at(-1)?.label).toBe("4 autres");
    expect(hidden.map((s) => s.id)).toEqual(["l3", "l4", "l5", "l6"]);
    expect(otherValue).toBe(7 + 6 + 5 + 4);
    expect(shown.at(-1)?.value).toBe(otherValue);
  });

  it("ne trace pas de part agrégée quand les repliées ne portent aucun passage", () => {
    // Le cas réel : huit lignes tracées, deux seulement traversées. Un secteur
    // d'angle nul est invisible sur le dessin et remplirait une rangée de légende
    // à « 0 — 0 % » sous un nom qui promet six lignes.
    const lines = [slice("a", 5), slice("b", 3), ...[0, 0, 0, 0, 0, 0].map((v, i) => slice(`z${i}`, v))];
    const { shown, hidden, otherValue } = groupSlices(lines, 5);

    expect(shown.map((s) => s.id)).not.toContain(OTHER_SLICE_ID);
    expect(shown).toHaveLength(4);
    expect(hidden).toHaveLength(4);
    expect(otherValue).toBe(0);
  });

  it("garde l'ordre d'entrée à égalité de valeur", () => {
    // Sans ce tri stable, deux lignes à égalité permuteraient d'une image
    // d'aperçu à la suivante : le camembert clignoterait pendant l'analyse.
    const { shown } = groupSlices([slice("a", 4), slice("b", 4), slice("c", 4)], 6);
    expect(shown.map((s) => s.id)).toEqual(["a", "b", "c"]);
  });

  it("ramène une limite absurde à deux parts", () => {
    const { shown, hidden } = groupSlices([slice("a", 3), slice("b", 2), slice("c", 1)], 1);
    expect(shown.map((s) => s.id)).toEqual(["a", OTHER_SLICE_ID]);
    expect(hidden.map((s) => s.id)).toEqual(["b", "c"]);
  });

  it("ne perd aucun passage : montré + agrégé = reçu", () => {
    const values = [12, 8, 6, 5, 4, 3, 2, 1];
    const input = values.map((value, index) => slice(`l${index}`, value));
    const { shown } = groupSlices(input, 5);

    const total = shown.reduce((sum, s) => sum + s.value, 0);
    expect(total).toBe(values.reduce((sum, v) => sum + v, 0));
  });
});
