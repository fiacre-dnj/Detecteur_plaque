/**
 * `visibleClasses` — la Répartition suit « Objets à compter ».
 *
 * Deux règles s'y croisent et se contredisent en apparence : la sélection
 * commande l'affichage, mais un chiffre déjà compté ne disparaît jamais. Les
 * tests ci-dessous fixent les deux, et surtout leur intersection — décocher une
 * classe **après** l'analyse, qui est le geste où l'une des deux doit céder.
 */

import { describe, expect, it } from "bun:test";

import { visibleClasses } from "./visibleClasses";

describe("visibleClasses", () => {
  it("n'affiche que les classes cochées quand rien n'a été compté", () => {
    expect(visibleClasses(["car", "bus"], {})).toEqual(["car", "bus"]);
  });

  it("retire le KPI d'une classe décochée sans entrée", () => {
    // Le cas de la demande : « moto » décochée ne doit pas afficher un zéro qui
    // se lirait comme « aucune moto n'est passée ».
    expect(visibleClasses(["car", "bus", "truck"], { car: 12 })).not.toContain("motorcycle");
  });

  it("garde une classe décochée qui porte des entrées dans le résultat relu", () => {
    // Sinon décocher une case après coup effacerait une colonne du résultat
    // qu'on est en train de lire.
    expect(visibleClasses(["car"], { car: 12, person: 3 })).toContain("person");
  });

  it("ignore une classe décochée dont le compte est nul", () => {
    expect(visibleClasses(["car"], { car: 12, person: 0 })).toEqual(["car"]);
  });

  it("range les véhicules dans l'ordre d'affichage, pas dans celui des clics", () => {
    expect(visibleClasses(["truck", "car", "motorcycle"], {})).toEqual([
      "car",
      "motorcycle",
      "truck",
    ]);
  });

  it("place les classes hors véhicules après, sans doublon", () => {
    expect(visibleClasses(["person", "car", "bicycle"], { person: 4 })).toEqual([
      "car",
      "person",
      "bicycle",
    ]);
  });
});
