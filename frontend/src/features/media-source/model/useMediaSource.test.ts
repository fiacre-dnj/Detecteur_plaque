/**
 * Validation d'extension et messages de refus de la caméra.
 *
 * Le piège `srcObject = null` n'est pas testé ici : il vit dans l'élément
 * `<video>`, et le vérifier demanderait un DOM complet avec un vrai média. Il est
 * documenté à l'endroit où il est appliqué (`useMediaSource.stop`) et dans
 * `VideoScene`, qui pose les deux attributs. Ce qui est testable sans média l'est.
 */

import { describe, expect, it } from "bun:test";

import {
  ACCEPTED_EXTENSIONS,
  ACCEPT_ATTRIBUTE,
  DEMO_MISSING_MESSAGE,
  cameraErrorMessage,
  hasAcceptedExtension,
} from "./useMediaSource";

describe("extensions acceptées", () => {
  it("accepte les six formats que le serveur accepte", () => {
    // La même liste que `ALLOWED_SUFFIXES` côté Python. Une divergence ferait
    // refuser côté client un fichier que le serveur aurait pris, ou l'inverse —
    // un 415 après l'envoi de 500 Mo.
    expect([...ACCEPTED_EXTENSIONS]).toEqual([
      ".mp4",
      ".mov",
      ".avi",
      ".mkv",
      ".webm",
      ".m4v",
    ]);
  });

  it("reconnaît une extension quelle que soit sa casse", () => {
    expect(hasAcceptedExtension("CLIP.MP4")).toBe(true);
    expect(hasAcceptedExtension("clip.Mov")).toBe(true);
  });

  it("refuse ce qui n'est pas une vidéo reconnue", () => {
    expect(hasAcceptedExtension("photo.jpg")).toBe(false);
    expect(hasAcceptedExtension("archive.zip")).toBe(false);
    expect(hasAcceptedExtension("sans-extension")).toBe(false);
  });

  it("ne se laisse pas tromper par une extension au milieu du nom", () => {
    // `.mp4` doit être à la **fin** : un fichier nommé « mp4-notes.txt » n'est
    // pas une vidéo.
    expect(hasAcceptedExtension("mp4-notes.txt")).toBe(false);
    expect(hasAcceptedExtension("vacances.mp4.exe")).toBe(false);
  });

  it("produit un attribut accept utilisable par l'input", () => {
    expect(ACCEPT_ATTRIBUTE).toBe(".mp4,.mov,.avi,.mkv,.webm,.m4v");
  });
});

describe("messages de refus de la caméra", () => {
  it("dit quoi faire quand l'autorisation est refusée", () => {
    // « NotAllowedError » est imprononçable pour un utilisateur : le message doit
    // nommer l'action, pas l'erreur.
    const message = cameraErrorMessage(named("NotAllowedError"));

    expect(message).toContain("refusé");
    expect(message).toContain("réglages du navigateur");
  });

  it("distingue l'absence de caméra d'un refus", () => {
    // Deux actions différentes : autoriser, ou brancher une caméra. Les
    // confondre envoie l'utilisateur au mauvais endroit.
    expect(cameraErrorMessage(named("NotFoundError"))).toContain("Aucune caméra");
  });

  it("dit qu'une autre application retient la caméra", () => {
    expect(cameraErrorMessage(named("NotReadableError"))).toContain("autre application");
  });

  it("reste compréhensible devant une erreur inconnue", () => {
    // Ni trace de pile ni nom d'erreur brut : un message générique mais français.
    const message = cameraErrorMessage(new Error("quelque chose d'inattendu"));

    expect(message).toContain("caméra");
    expect(message).not.toContain("Error");
  });

  it("ne casse pas si ce qui est levé n'est pas une Error", () => {
    // `getUserMedia` lève des `DOMException`, mais du code tiers peut lever
    // n'importe quoi. Un message vaut mieux qu'un plantage du composant.
    expect(cameraErrorMessage("oups")).toContain("caméra");
    expect(cameraErrorMessage(undefined)).toContain("caméra");
  });
});

describe("absence du clip de démonstration", () => {
  it("dit où déposer le fichier plutôt que de constater l'échec", () => {
    // Un « échec de chargement » laisse l'utilisateur sans recours ; le chemin
    // exact lui permet d'agir.
    expect(DEMO_MISSING_MESSAGE).toContain("public/demo/traffic.mp4");
    expect(DEMO_MISSING_MESSAGE).toContain("choisissez un fichier");
  });
});

/** Fabrique une erreur portant le `name` que le navigateur poserait. */
function named(name: string): Error {
  const error = new Error(name);
  error.name = name;
  return error;
}
