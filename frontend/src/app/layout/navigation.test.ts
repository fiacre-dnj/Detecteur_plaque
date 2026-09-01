/**
 * Les entrées du rail mènent bien aux pages qu'elles annoncent.
 *
 * L'assertion qui compte est l'**aller-retour** `activePageId(item.to) === item.id` :
 * elle relie les deux moitiés du commutateur — celle qui fabrique les liens et celle
 * qui décide quelle page est visible — et c'est la seule qui attrape un lien mort.
 * Un lien mort ne plante pas : il affiche la page d'erreur, exactement comme une
 * faute de frappe dans la barre d'adresse, donc rien ne dit que la faute est dans le
 * code.
 */

import { describe, expect, it } from "bun:test";

import { PAGE_IDS, PAGE_PATHS, activePageId } from "./keepAlive";
import { NAV_ITEMS, NAV_LABELS } from "./navigation";

describe("NAV_ITEMS", () => {
  it("mène à la page qu'il annonce", () => {
    for (const item of NAV_ITEMS) {
      expect(activePageId(item.to)).toBe(item.id);
    }
  });

  it("suit l'ordre d'affichage des pages", () => {
    expect(NAV_ITEMS.map((item) => item.id)).toEqual([...PAGE_IDS]);
  });

  it("ne recopie aucun chemin", () => {
    for (const item of NAV_ITEMS) {
      expect(item.to).toBe(PAGE_PATHS[item.id]);
    }
  });

  it("donne à chaque entrée un libellé non vide et distinct", () => {
    const labels = NAV_ITEMS.map((item) => item.label);
    expect(labels.every((label) => label.trim().length > 0)).toBe(true);
    // Distincts : le rail n'affiche que des icônes, le libellé est le seul nom
    // accessible de chaque lien. Deux fois le même rendrait le rail illisible au
    // lecteur d'écran sans que rien ne paraisse à l'œil.
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("couvre exactement les pages, sans entrée orpheline", () => {
    expect(Object.keys(NAV_LABELS).sort()).toEqual([...PAGE_IDS].sort());
  });
});
