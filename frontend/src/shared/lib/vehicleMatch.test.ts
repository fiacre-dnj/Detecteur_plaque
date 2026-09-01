/**
 * Ce que « ressembler » garantit — et ce qu'il refuse de garantir.
 *
 * Ces tests portent moins sur l'arithmétique que sur les **confusions** que ce module
 * existe pour empêcher : `null` pris pour zéro, un seuil haut figé qui ne suit pas le
 * curseur, et un score absent lu comme une non-ressemblance certaine.
 */

import { describe, expect, it } from "bun:test";

import { DEFAULT_MATCH_THRESHOLD, matches, matchStrength } from "./vehicleMatch";

describe("matches", () => {
  it("refuse tout quand aucune recherche n'est armée", () => {
    // `null` sur le seuil veut dire « on ne cherche rien », et **pas** « seuil zéro ».
    // Confondre les deux signalerait la totalité du trafic : tout véhicule encodé a un
    // score, y compris négatif.
    expect(matches(0.99, null)).toBe(false);
    expect(matches(-0.5, null)).toBe(false);
  });

  it("ne prend jamais un score absent pour une correspondance", () => {
    // Deux causes derrière l'absence — pas de requête, ou véhicule jamais encodé parce
    // que trop petit ou trop flou — et aucune n'est une ressemblance.
    expect(matches(null, 0.5)).toBe(false);
    expect(matches(undefined, 0.5)).toBe(false);
  });

  it("inclut le seuil lui-même", () => {
    // Bornes inclusives : un véhicule pile au seuil doit apparaître, sinon descendre le
    // curseur d'un cran ne fait rien la première fois.
    expect(matches(0.55, 0.55)).toBe(true);
    expect(matches(0.5499, 0.55)).toBe(false);
  });

  it("accepte un score négatif si le seuil descend jusque-là", () => {
    // La similarité cosinus vit dans [-1, 1], pas dans [0, 1] : borner à zéro ici
    // rendrait la moitié basse du curseur muette.
    expect(matches(-0.2, -0.5)).toBe(true);
  });
});

describe("matchStrength", () => {
  it("place la frontière à mi-chemin entre le seuil et 1", () => {
    // Le seuil haut **suit le curseur** au lieu d'être un second réglage caché. À 0,50
    // la frontière est 0,75.
    expect(matchStrength(0.76, 0.5)).toBe("exact");
    expect(matchStrength(0.74, 0.5)).toBe("partial");
  });

  it("suit le curseur quand il monte", () => {
    // À 0,80 la frontière monte à 0,90 : le même score de 0,85 change donc de gravité
    // selon le curseur, ce qui est exactement l'effet voulu. Un seuil haut fixe
    // classerait tout en « sûr » dès que le curseur passe au-dessus de lui.
    expect(matchStrength(0.85, 0.5)).toBe("exact");
    expect(matchStrength(0.85, 0.8)).toBe("partial");
  });

  it("ne classe jamais en « sûr » un score au seuil", () => {
    // Un véhicule qui vient d'entrer dans la liste est le moins sûr de la liste.
    expect(matchStrength(DEFAULT_MATCH_THRESHOLD, DEFAULT_MATCH_THRESHOLD)).toBe("partial");
  });
});
