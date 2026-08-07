import { describe, expect, test } from "bun:test";

import type { VehicleModel } from "@/shared/api/contracts";

import { downloadNotice } from "./launchNotice";

function model(overrides: Partial<VehicleModel> = {}): VehicleModel {
  return {
    id: "yolov8n",
    label: "YOLOv8 nano",
    family: "yolov8",
    tier: "nano",
    tierLabel: "Nano",
    note: "",
    sizeMb: 6,
    sizeBytes: null,
    downloaded: false,
    loaded: false,
    isDefault: true,
    ...overrides,
  };
}

describe("downloadNotice", () => {
  test("annonce le téléchargement d'un modèle absent du serveur", () => {
    const notice = downloadNotice([model({ downloaded: false, sizeMb: 137 })], "yolov8n");

    expect(notice).not.toBeNull();
    // Les trois informations qui décident du clic : lequel, combien, combien de temps.
    expect(notice).toContain("YOLOv8 nano");
    expect(notice).toContain("137 Mo");
    expect(notice).toContain("une à deux minutes");
  });

  test("se tait quand le modèle est déjà sur le disque", () => {
    expect(downloadNotice([model({ downloaded: true })], "yolov8n")).toBeNull();
  });

  /**
   * Le cas du réglage persisté citant un modèle retiré du catalogue. `StudioPage`
   * recale la sélection sur le défaut du serveur ; annoncer un téléchargement pour un
   * modèle qui n'existe plus ajouterait un avertissement à une situation déjà résolue.
   */
  test("se tait pour un modèle inconnu du catalogue", () => {
    expect(downloadNotice([model()], "modele-retire")).toBeNull();
  });

  test("se tait sur un catalogue vide — le serveur est injoignable", () => {
    expect(downloadNotice([], "yolov8n")).toBeNull();
  });
});
