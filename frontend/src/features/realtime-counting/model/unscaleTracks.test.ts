import { describe, expect, test } from "bun:test";

import type { TrackSnapshot } from "@/shared/api/contracts";

import { scaleFactor } from "./scale";
import { unscaleTrack, unscaleTracks } from "./unscaleTracks";

/** Une piste telle que le serveur la renvoie, en pixels de l'image **réduite**. */
const TRACK: TrackSnapshot = {
  trackId: 7,
  globalId: 3,
  classId: 2,
  label: "car",
  identityLabel: "car",
  score: 0.91,
  box: { x: 300, y: 150, width: 90, height: 60 },
  hits: 12,
  counted: true,
  plates: [
    {
      box: { x: 320, y: 190, width: 24, height: 9 },
      score: 0.77,
      text: "AB-123-CD",
      textScore: 0.9,
    },
  ],
  plateText: "AB-123-CD",
  plateTextScore: 0.9,
};

/** Facteur d'une webcam 720p : 960 / 1280. */
const FACTOR = scaleFactor(1280);

describe("unscaleTrack", () => {
  test("redilate la boîte principale en pixels source", () => {
    expect(unscaleTrack(TRACK, FACTOR).box).toEqual({
      x: 400,
      y: 200,
      width: 120,
      height: 80,
    });
  });

  test("redilate **aussi** les boîtes de plaques", () => {
    // L'oubli classique : les plaques sont un tableau imbriqué, et une copie
    // superficielle de la piste les laisserait à l'échelle d'envoi — dessinées trop
    // petites et décalées vers le coin supérieur gauche du véhicule.
    //
    // Comparé à 6 décimales et non à l'identique : 320 / 0,75 n'est pas
    // représentable exactement en binaire, et figer les derniers chiffres d'un
    // flottant ferait échouer le test sur une simple réécriture de la division.
    const plate = unscaleTrack(TRACK, FACTOR).plates[0];
    expect(plate?.box.x).toBeCloseTo(426.666667, 5);
    expect(plate?.box.y).toBeCloseTo(253.333333, 5);
    expect(plate?.box.width).toBe(32);
    expect(plate?.box.height).toBe(12);
  });

  test("laisse le texte de la plaque intact — ce n'est pas une longueur", () => {
    // Le `{ ...plate, box }` fait déjà survivre ces champs. Ce test **verrouille** ce
    // fait au lieu d'y faire confiance : le jour où quelqu'un reconstruira l'objet
    // champ par champ pour « être explicite », le texte disparaîtrait en silence — et
    // une plaque non redilatée se voit, une plaque muette ne se voit pas.
    const rescaled = unscaleTrack(TRACK, FACTOR);

    expect(rescaled.plates[0]?.text).toBe("AB-123-CD");
    expect(rescaled.plates[0]?.textScore).toBe(0.9);
    expect(rescaled.plateText).toBe("AB-123-CD");
    expect(rescaled.plateTextScore).toBe(0.9);
  });

  test("ne touche à rien de ce qui est sans dimension", () => {
    const back = unscaleTrack(TRACK, FACTOR);
    expect(back.score).toBe(0.91);
    expect(back.hits).toBe(12);
    expect(back.trackId).toBe(7);
    expect(back.globalId).toBe(3);
    expect(back.identityLabel).toBe("car");
    expect(back.counted).toBe(true);
    expect(back.plates[0]?.score).toBe(0.77);
  });

  test("rend l'objet **identique** au facteur 1", () => {
    // Pas seulement égal : le même objet. Recréer les pistes à 15 Hz pour rien
    // ferait voir à React un changement à chaque frame, et le canvas se
    // redessinerait même quand rien n'a bougé.
    expect(unscaleTrack(TRACK, 1)).toBe(TRACK);
  });

  test("rend l'objet identique sur un facteur absurde", () => {
    // Diviser par 0 donnerait des `Infinity` et les boîtes disparaîtraient du
    // dessin sans qu'aucun message n'explique pourquoi.
    expect(unscaleTrack(TRACK, 0)).toBe(TRACK);
    expect(unscaleTrack(TRACK, Number.NaN)).toBe(TRACK);
  });

  test("ne mute pas la piste reçue", () => {
    unscaleTrack(TRACK, FACTOR);
    expect(TRACK.box).toEqual({ x: 300, y: 150, width: 90, height: 60 });
    expect(TRACK.plates[0]?.box.x).toBe(320);
  });
});

describe("unscaleTracks", () => {
  test("traite toute la frame", () => {
    const back = unscaleTracks([TRACK, { ...TRACK, trackId: 8 }], FACTOR);
    expect(back.length).toBe(2);
    expect(back[0]?.box.x).toBe(400);
    expect(back[1]?.box.x).toBe(400);
  });

  test("rend le tableau identique au facteur 1", () => {
    const input = [TRACK];
    expect(unscaleTracks(input, 1)).toBe(input);
  });

  test("gère une frame sans piste", () => {
    expect(unscaleTracks([], FACTOR)).toEqual([]);
  });
});
