/**
 * La paire d'une re-détection : ce qu'on met côte à côte, et ce qu'on refuse.
 *
 * Le test qui compte est le premier — l'antécédent se cherche dans **tous** les
 * véhicules. Chercher dans le jeu filtré donnerait une modale qui refuse de s'ouvrir
 * dès qu'on a filtré sur une ligne, c'est-à-dire au moment exact où l'on enquête.
 */

import { describe, expect, it } from "bun:test";

import type { VehicleRecord } from "@/shared/api/contracts";

import { hasRematch, isRematched, rematchPair } from "./rematchPair";

function vehicle(globalId: number, overrides: Partial<VehicleRecord> = {}): VehicleRecord {
  return {
    globalId,
    label: "car",
    firstSeenMs: globalId * 1_000,
    lastSeenMs: globalId * 1_000 + 500,
    crossedLines: [],
    zonesVisited: [],
    bestPlateScore: null,
    plateText: null,
    plateTextScore: null,
    plateUnreadReason: null,
    plateBestWidthPx: null,
    plateBestGuess: null,
    plateBestGuessScore: null,
    ...overrides,
  } as VehicleRecord;
}

describe("rematchPair", () => {
  it("rend les deux côtés dans l'ordre chronologique", () => {
    // `earlier` est le déposant, `later` celui qui vient de le reconnaître — et
    // jamais l'inverse selon la rangée cliquée, sinon la disposition changerait d'une
    // comparaison à l'autre alors que c'est la stabilité qui permet de comparer.
    const vehicles = [vehicle(12), vehicle(42, { rematchOf: 12, rematchScore: 0.87 })];

    const pair = rematchPair(vehicles, 42);

    expect(pair?.earlier.globalId).toBe(12);
    expect(pair?.later.globalId).toBe(42);
  });

  it("trouve un antécédent que le filtre courant masquerait", () => {
    // **Le test qui porte la règle.** L'appelant passe `vehicles` entier et non
    // `filtered` : le filtre décide de ce qu'on parcourt, pas de ce qu'on a le droit
    // de regarder de plus près. Ici #12 n'est pas dans la sous-liste qu'on affiche.
    const all = [vehicle(12), vehicle(42, { rematchOf: 12, rematchScore: 0.87 })];
    const filtered = all.filter((entry) => entry.globalId === 42);

    expect(rematchPair(all, 42)).not.toBeNull();
    expect(rematchPair(filtered, 42)).toBeNull();
  });

  it("ne rend rien pour un véhicule jamais re-détecté", () => {
    expect(rematchPair([vehicle(12), vehicle(42)], 42)).toBeNull();
  });

  it("ne rend rien quand l'antécédent est introuvable", () => {
    // Ne devrait pas arriver — le serveur ne désigne que des véhicules de la même
    // analyse — mais une comparaison avec un côté vide ne compare rien, et un
    // résultat rouvert n'a pas à faire confiance à cette invariance.
    const vehicles = [vehicle(42, { rematchOf: 99, rematchScore: 0.9 })];

    expect(rematchPair(vehicles, 42)).toBeNull();
  });

  it("ne rend rien pour un numéro absent de la liste", () => {
    expect(rematchPair([vehicle(12)], 404)).toBeNull();
  });
});

describe("isRematched / hasRematch — la porte du seuil", () => {
  const THRESHOLD = 0.75;

  it("refuse une identité affirmée sous le seuil", () => {
    // **Le test qui porte le correctif d'affichage.** Sur une vidéo doublée, les
    // sept véhicules de la première moitié n'ont par construction aucun jumeau
    // antérieur, et le serveur leur publie quand même leur meilleur voisin — à 2 %,
    // 27 %, 31 %. Les afficher en gris se lisait comme « le système se trompe
    // partout » : une identité à 2 % n'est pas une information nuancée.
    expect(isRematched(vehicle(42, { rematchOf: 12, rematchScore: 0.31 }), THRESHOLD)).toBe(
      false,
    );
    expect(isRematched(vehicle(42, { rematchOf: 12, rematchScore: 0.87 }), THRESHOLD)).toBe(true);
  });

  it("accepte le seuil lui-même", () => {
    // `matches` est inclusif à la borne : le curseur dit « à partir de », pas
    // « au-delà de ».
    expect(isRematched(vehicle(42, { rematchOf: 12, rematchScore: 0.75 }), THRESHOLD)).toBe(true);
  });

  it("refuse un antécédent sans score", () => {
    // `rematchOf` sans `rematchScore` ne devrait pas exister — le sérialiseur les
    // pose ensemble — mais un résultat rouvert n'a pas à faire confiance à cette
    // invariance pour afficher un numéro.
    expect(isRematched(vehicle(42, { rematchOf: 12 }), THRESHOLD)).toBe(false);
    expect(isRematched(vehicle(42), THRESHOLD)).toBe(false);
  });

  it("la colonne n'existe que si une rangée affirme quelque chose", () => {
    const noise = [
      vehicle(12),
      vehicle(42, { rematchOf: 12, rematchScore: 0.31 }),
    ];
    const real = [...noise, vehicle(43, { rematchOf: 12, rematchScore: 0.99 })];

    expect(hasRematch(noise, THRESHOLD)).toBe(false);
    expect(hasRematch(real, THRESHOLD)).toBe(true);
    expect(hasRematch([], THRESHOLD)).toBe(false);
  });
});
