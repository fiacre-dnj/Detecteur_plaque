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

  it("versionne l'adresse avec l'instant de la capture", () => {
    // Sans `?v=`, ces images servies `immutable` resteraient un an sur la première
    // capture d'un véhicule dont la vue s'améliore ensuite.
    expect(vehicleSnapshotUrl(JOB, 12, 12_400)).toBe(
      "/api/v1/jobs/0123456789abcdef/vehicles/12/snapshot.jpg?v=12400",
    );
  });

  it("compose la version et le réessai avec la bonne ponctuation", () => {
    // **Le piège que ce test ferme.** Deux appelants concaténaient `retry` eux-mêmes,
    // chacun en devinant la ponctuation de l'autre : le registre écrivait `&retry=`
    // en supposant `?v=` présent, la pile d'alertes `?retry=` en supposant l'inverse.
    // Aucun n'était faux, et les deux le devenaient au premier changement d'appelant.
    expect(vehicleSnapshotUrl(JOB, 12, 12_400, 1)).toBe(
      "/api/v1/jobs/0123456789abcdef/vehicles/12/snapshot.jpg?v=12400&retry=1",
    );
    expect(vehicleSnapshotUrl(JOB, 12, null, 1)).toBe(
      "/api/v1/jobs/0123456789abcdef/vehicles/12/snapshot.jpg?retry=1",
    );
    expect(platePhotoUrl(JOB, 12, 900, 2)).toBe(
      "/api/v1/jobs/0123456789abcdef/vehicles/12/plate.jpg?v=900&retry=2",
    );
  });

  it("n'ajoute rien pour la première tentative", () => {
    // `retry=0` priverait de cache toutes les vignettes visibles, pour rien.
    expect(vehicleSnapshotUrl(JOB, 12, 12_400, 0)).toBe(
      "/api/v1/jobs/0123456789abcdef/vehicles/12/snapshot.jpg?v=12400",
    );
    expect(vehicleSnapshotUrl(JOB, 12, null, 0)).toBe(
      "/api/v1/jobs/0123456789abcdef/vehicles/12/snapshot.jpg",
    );
  });

  it("toujours relatives — aucune URL de base nulle part", () => {
    for (const url of [inputVideoUrl(JOB), vehicleSnapshotUrl(JOB, 1), platePhotoUrl(JOB, 1)]) {
      expect(url.startsWith("/api/v1/")).toBe(true);
    }
  });
});
