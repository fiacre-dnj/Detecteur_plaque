/**
 * Le vocabulaire des classes de véhicule.
 *
 * Ce que ces tests protègent : la **liste fermée** (les quatre classes que le modèle
 * peut émettre, pas les 80 de COCO) et le fait qu'une classe inconnue traverse au
 * lieu d'être masquée. Le second est ce qui rend visible l'arrivée d'une classe que
 * l'interface ignore, au lieu de faire disparaître une ligne.
 */

import { describe, expect, it } from "bun:test";

import { VEHICLE_CLASSES, classLabel } from "./classes";

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

  it("couvre les sept classes que le serveur sait détecter", () => {
    // Les trois dernières sont arrivées avec ADR 0014 — l'utilisateur peut cocher
    // vélo, personne et train. Sans leur libellé, la répartition par type afficherait
    // « person » au milieu de « Voiture » et « Camion », ce qui se lit comme une
    // colonne mal branchée plutôt que comme une traduction manquante.
    expect(classLabel("bicycle")).toBe("Vélo");
    expect(classLabel("person")).toBe("Personne");
    expect(classLabel("train")).toBe("Train");
  });

  it("laisse passer une classe inconnue au lieu de la masquer", () => {
    // Si le serveur commence à renvoyer une classe que l'interface ignore, il faut
    // la **voir** pour décider quoi en faire — un « Autre » fourre-tout cacherait le
    // changement.
    expect(classLabel("boat")).toBe("boat");
  });
});
