/**
 * La forme des trois adresses.
 *
 * Un test de chaîne peut paraître futile ; il ne l'est pas ici. Ces URL ne passent
 * par aucun client typé — elles atterrissent directement dans un attribut `src`, où
 * une faute de frappe ne produit ni exception ni message, seulement une image qui ne
 * s'affiche pas. C'est la seule barrière automatique entre elles et les routes.
 */

import { describe, expect, it } from "bun:test";

import { inputVideoUrl, platePhotoUrl, vehicleSnapshotUrl } from "./jobUrls";

const JOB = "0123456789abcdef";

describe("les adresses des fichiers d'un job", () => {
  it("pointe la vidéo analysée", () => {
    expect(inputVideoUrl(JOB)).toBe("/api/v1/jobs/0123456789abcdef/input");
  });

  it("pointe la photo du véhicule, par son numéro", () => {
    expect(vehicleSnapshotUrl(JOB, 12)).toBe(
      "/api/v1/jobs/0123456789abcdef/vehicles/12/snapshot.jpg",
    );
  });

  it("pointe la vignette de plaque du même véhicule", () => {
    expect(platePhotoUrl(JOB, 12)).toBe("/api/v1/jobs/0123456789abcdef/vehicles/12/plate.jpg");
  });

  it("garde les deux faces d'une capture sur le même véhicule", () => {
    // Deux fichiers, un seul véhicule : le préfixe doit être identique, sinon la
    // modale montrerait la plaque d'une voiture et la photo d'une autre.
    const vehicle = vehicleSnapshotUrl(JOB, 7);
    const plate = platePhotoUrl(JOB, 7);
    const prefix = `/api/v1/jobs/${JOB}/vehicles/7/`;

    expect(vehicle.startsWith(prefix)).toBe(true);
    expect(plate.startsWith(prefix)).toBe(true);
  });

  it("toujours relatives — aucune URL de base nulle part", () => {
    for (const url of [inputVideoUrl(JOB), vehicleSnapshotUrl(JOB, 1), platePhotoUrl(JOB, 1)]) {
      expect(url.startsWith("/api/v1/")).toBe(true);
    }
  });
});
