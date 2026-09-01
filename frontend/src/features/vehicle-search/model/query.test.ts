/**
 * Ce que le cadrage garantit avant qu'un pixel ne soit découpé.
 *
 * `clampCrop` est la seule protection entre un geste de souris et un `drawImage` : un
 * rectangle hors bornes ou de côté nul rend un canvas vide, donc une vignette noire
 * envoyée au serveur — une recherche qui ne trouve rien **sans dire pourquoi**. C'est
 * le mode de panne que ces tests visent, pas l'arithmétique.
 */

import { describe, expect, it } from "bun:test";

import { clampCrop, FULL_CROP, isArmed, MIN_CROP_FRACTION, NO_QUERY } from "./query";

describe("clampCrop", () => {
  it("garantit un côté minimal à un clic sans glissement", () => {
    // Un `pointerdown` sans déplacement pose un rectangle de côté nul. Sans plancher,
    // `drawImage` recevrait une source de 0 px et rendrait un canvas vide.
    const crop = clampCrop({ x: 0.5, y: 0.5, width: 0, height: 0 });
    expect(crop.width).toBe(MIN_CROP_FRACTION);
    expect(crop.height).toBe(MIN_CROP_FRACTION);
  });

  it("ramène un rectangle qui dépasse à droite, sans le rétrécir", () => {
    // Glisser au-delà du bord droit est le geste le plus courant. Le rectangle est
    // **déplacé** et non réduit : réduire changerait le cadrage que l'utilisateur voit
    // sous son curseur.
    const crop = clampCrop({ x: 0.9, y: 0.9, width: 0.4, height: 0.4 });
    expect(crop.width).toBeCloseTo(0.4);
    expect(crop.x).toBeCloseTo(0.6);
    expect(crop.y).toBeCloseTo(0.6);
  });

  it("ramène un rectangle aux coordonnées négatives", () => {
    const crop = clampCrop({ x: -0.3, y: -0.1, width: 0.5, height: 0.5 });
    expect(crop.x).toBe(0);
    expect(crop.y).toBe(0);
  });

  it("borne un rectangle plus grand que l'image au plein cadre", () => {
    const crop = clampCrop({ x: -1, y: -1, width: 3, height: 3 });
    expect(crop).toEqual(FULL_CROP);
  });

  it("laisse le plein cadre intact", () => {
    // Le cas de départ : une image importée et pas encore cadrée ne doit pas se voir
    // rogner d'un sous-pixel.
    expect(clampCrop(FULL_CROP)).toEqual(FULL_CROP);
  });
});

describe("isArmed", () => {
  it("n'est pas armée sans fichier, même avec un seuil réglé", () => {
    // Le seuil survit à `resetForNewSource` — c'est une préférence de lecture — mais il
    // n'arme rien tout seul. Sans cette distinction, la cloche d'alertes s'allumerait
    // sur une vidéo neuve sans qu'aucune photo n'ait été fournie.
    expect(isArmed({ ...NO_QUERY, threshold: 0.9 })).toBe(false);
  });

  it("est armée dès qu'un fichier est là", () => {
    const file = new File([new Uint8Array([1, 2, 3])], "voiture.jpg", { type: "image/jpeg" });
    expect(isArmed({ ...NO_QUERY, file })).toBe(true);
  });
});
