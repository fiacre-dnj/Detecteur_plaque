/**
 * Les phases d'une analyse, et surtout ce qui les sépare.
 *
 * Les deux cas qui comptent sont des régressions déjà payées ailleurs : une barre
 * unique qui retombe à zéro entre l'envoi et l'analyse (lu comme un échec, donc on
 * recommence), et un compteur « 0 / 0 images » pendant le chargement d'un modèle (lu
 * comme une analyse plantée).
 */

import { describe, expect, it } from "bun:test";

import type { Job, JobStatus } from "@/shared/api/contracts";

import { analysisProgress } from "./analysisProgress";

function job(status: JobStatus, overrides: Partial<Job> = {}): Job {
  return {
    jobId: "j1",
    status,
    progress: 0.39,
    processedFrames: 2420,
    totalFrames: 6181,
    processingFps: 24.5,
    error: null,
    errorCode: null,
    preparing: false,
    modelId: "yolo11n",
    ...overrides,
  } as Job;
}

describe("analysisProgress", () => {
  it("ne montre rien tant que rien n'a commencé", () => {
    const progress = analysisProgress(null, null);
    expect(progress.phase).toBe("idle");
    expect(progress.active).toBe(false);
  });

  it("montre l'envoi en octets, jamais en images", () => {
    const progress = analysisProgress({ loaded: 41_000_000, total: 340_000_000, ratio: 0.12 }, null);
    expect(progress.phase).toBe("upload");
    expect(progress.ratio).toBeCloseTo(0.12);
    expect(progress.detail).toContain("sur");
    expect(progress.detail).not.toContain("images");
  });

  it("passe à l'analyse dès que le job existe, même si l'envoi n'est pas acquitté", () => {
    // Le serveur peut rendre le job avant le dernier morceau : sans le garde
    // `job === null`, l'écran afficherait « Envoi 99 % » au-dessus d'une analyse
    // déjà commencée.
    const progress = analysisProgress(
      { loaded: 339_000_000, total: 340_000_000, ratio: 0.99 },
      job("running"),
    );
    expect(progress.phase).toBe("running");
  });

  it("ne compte pas d'images pendant la préparation", () => {
    const progress = analysisProgress(null, job("running", { preparing: true }), "YOLO11n");
    expect(progress.phase).toBe("preparing");
    expect(progress.detail).toBeNull();
    expect(progress.hint).toContain("YOLO11n");
  });

  it("ne donne que le compte d'images, jamais la cadence", () => {
    // La cadence est déjà dans la rangée de chiffres qui suit l'anneau, sous son
    // libellé « Cadence serveur ». La répéter ici coûtait la largeur d'une barre qui
    // doit tenir sur une ligne, pour un chiffre déjà lisible à trois centimètres.
    const progress = analysisProgress(null, job("running"));
    expect(progress.label).toBe("Analyse en cours");
    expect(progress.detail).toBe("2420 / 6181 images");
    expect(progress.detail).not.toContain("img/s");
  });

  it("dit où l'analyse est suspendue, et ce que la pause coûte", () => {
    const progress = analysisProgress(null, job("paused"));
    expect(progress.phase).toBe("paused");
    expect(progress.detail).toContain("2420 / 6181");
    expect(progress.hint).toContain("garde sa place");
  });

  it("fait de la file d'attente une phase à part, jamais une analyse en cours", () => {
    // Deux choses en dépendent, et aucune ne se voit : « Suspendre » ne doit pas être
    // proposé sur un job qui n'a pas encore de thread à arrêter, et le bloc
    // explicatif sous la vidéo doit s'afficher — ce que la phase `running` empêchait.
    const progress = analysisProgress(null, job("queued"));
    expect(progress.phase).toBe("queued");
    expect(progress.label).toBe("En file d'attente");
  });

  it("ne compte pas d'images tant que le serveur n'a pas sondé la vidéo", () => {
    // Vu à l'usage : un job reste en file derrière une analyse **suspendue**, qui
    // garde sa place. Il y affichait « 0 / 0 images · 0.0 img/s », ce qui se lit
    // comme une analyse plantée — le défaut même que `preparing` évitait déjà.
    const enFile = analysisProgress(
      null,
      job("queued", { totalFrames: 0, processedFrames: 0, processingFps: 0, progress: 0 }),
    );
    expect(enFile.detail).toBeNull();
    expect(enFile.hint).toContain("place sur le serveur");

    // Et juste après, quand le job a démarré mais que la vidéo n'est pas encore
    // sondée : toujours aucun compteur, mais ce n'est plus la file d'attente.
    const demarrage = analysisProgress(
      null,
      job("running", { totalFrames: 0, processedFrames: 0, processingFps: 0, progress: 0 }),
    );
    expect(demarrage.phase).toBe("running");
    expect(demarrage.detail).toBeNull();
  });

  it("ne rend plus de progression sur un statut terminal", () => {
    for (const status of ["done", "cancelled", "error"] as const) {
      const progress = analysisProgress(null, job(status, { progress: 1 }));
      expect(progress.phase).toBe("idle");
      expect(progress.active).toBe(false);
    }
  });
});
