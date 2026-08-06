/**
 * Libellés et formatage des mesures.
 *
 * Le cas qui compte : **une vitesse sans échelle px/m ne doit jamais s'afficher en
 * km/h**. Un véhicule à « 360 km/h » sur une image mal calibrée discrédite tout le
 * tableau, et l'utilisateur ne saura pas si c'est la vitesse ou le comptage qui est
 * faux.
 */

import { describe, expect, it } from "bun:test";

import {
  VEHICLE_CLASSES,
  classLabel,
  directionArrow,
  directionLabel,
  formatSceneTime,
  formatScore,
  formatSpeed,
  plural,
} from "./labels";

describe("classes de véhicule", () => {
  it("ne liste que les quatre classes que le modèle peut émettre", () => {
    // Pas les 80 de COCO : 76 tuiles toujours vides transformeraient la
    // répartition par type en mur de zéros.
    expect([...VEHICLE_CLASSES]).toEqual(["car", "motorcycle", "bus", "truck"]);
  });

  it("traduit les libellés du backend en français", () => {
    expect(classLabel("car")).toBe("Voiture");
    expect(classLabel("truck")).toBe("Camion");
    expect(classLabel("motorcycle")).toBe("Moto");
    expect(classLabel("bus")).toBe("Bus");
  });

  it("laisse passer une classe inconnue au lieu de la masquer", () => {
    // Si le serveur commence à renvoyer `train`, il faut le **voir** pour décider
    // quoi en faire — un « Autre » fourre-tout cacherait le changement.
    expect(classLabel("train")).toBe("train");
  });
});

describe("formatSpeed — trois cas distincts, jamais confondus", () => {
  it("affiche des km/h quand l'échelle est fournie", () => {
    expect(formatSpeed(48.6, 1250)).toBe("49 km/h");
  });

  it("**retombe sur px/s sans échelle**, plutôt que d'inventer des km/h", () => {
    // Le cas central : afficher des km/h sans px/m produirait des chiffres
    // inventés que l'utilisateur prendrait au sérieux.
    expect(formatSpeed(null, 1250)).toBe("1250 px/s");
  });

  it("affiche un tiret quand la vitesse est inconnue", () => {
    // Un `0` voudrait dire « à l'arrêt », ce qui est une affirmation différente.
    expect(formatSpeed(null, null)).toBe("—");
  });
});

describe("formatSceneTime — millisecondes de scène", () => {
  it("formate en mm:ss", () => {
    expect(formatSceneTime(0)).toBe("00:00");
    expect(formatSceneTime(75_000)).toBe("01:15");
    expect(formatSceneTime(440)).toBe("00:00");
  });

  it("rend --:-- pour une valeur non exploitable", () => {
    expect(formatSceneTime(Number.NaN)).toBe("--:--");
    expect(formatSceneTime(-1)).toBe("--:--");
  });

  it("prend bien des millisecondes et non des secondes", () => {
    // La confusion d'un facteur 1000 est exactement le genre d'erreur invisible
    // que ce test rend impossible : 60 000 ms = une minute.
    expect(formatSceneTime(60_000)).toBe("01:00");
  });
});

describe("sens d'un franchissement", () => {
  it("nomme les sens par les poignées visibles sur le canvas", () => {
    // « + » et « − » sont le contrat machine ; « A→B » renvoie à ce que
    // l'utilisateur voit tracé à l'écran.
    expect(directionLabel(1)).toBe("A→B");
    expect(directionLabel(-1)).toBe("B→A");
  });

  it("donne une flèche pour les puces compactes", () => {
    expect(directionArrow(1)).toBe("↑");
    expect(directionArrow(-1)).toBe("↓");
  });
});

describe("formatScore", () => {
  it("affiche un pourcentage entier", () => {
    expect(formatScore(0.71)).toBe("71 %");
  });

  it("affiche un tiret pour une plaque absente", () => {
    expect(formatScore(null)).toBe("—");
  });
});

describe("plural", () => {
  it("accorde le nom au compte", () => {
    expect(plural(1, "véhicule", "véhicules")).toBe("1 véhicule");
    expect(plural(2, "véhicule", "véhicules")).toBe("2 véhicules");
    expect(plural(0, "véhicule", "véhicules")).toBe("0 véhicules");
  });
});
