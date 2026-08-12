/**
 * Ce que la session fait d'un job terminé.
 *
 * Le défaut que ces tests verrouillent : seul `done` était traité, donc un échec
 * serveur n'alimentait **aucun** des deux canaux d'affichage du Studio. Le message
 * du serveur — souvent le seul qui dise quoi faire — n'était rendu que par la barre
 * de progression, elle-même démontée au passage en statut terminal.
 */

import { describe, expect, it } from "bun:test";

import type { Job, JobStatus } from "@/shared/api/contracts";

import { terminalOutcome } from "./useAnalysisSession";

function job(status: JobStatus, overrides: Partial<Job> = {}): Job {
  return {
    jobId: "j1",
    status,
    progress: 1,
    processedFrames: 100,
    totalFrames: 100,
    processingFps: 12.5,
    error: null,
    errorCode: null,
    preparing: false,
    modelId: "yolov8n",
    fileName: "carrefour.mp4",
    uniqueVehicles: 12,
    crossingsTotal: 17,
    createdAt: "2026-08-05T10:00:00+00:00",
    finishedAt: "2026-08-05T10:01:00+00:00",
    ...overrides,
  };
}

describe("terminalOutcome", () => {
  it("charge le résultat sur « done »", () => {
    expect(terminalOutcome(job("done"))).toEqual({ kind: "fetchResult" });
  });

  it("fait traverser le message **et** le code d'un échec", () => {
    const outcome = terminalOutcome(
      job("error", {
        error: "Le modèle « yolo11x » n'a pas pu être chargé.",
        errorCode: "model_unavailable",
      }),
    );

    expect(outcome).toEqual({
      kind: "reportError",
      message: "Le modèle « yolo11x » n'a pas pu être chargé.",
      code: "model_unavailable",
    });
  });

  it("affiche un repli plutôt qu'une alerte vide sur un échec sans message", () => {
    const outcome = terminalOutcome(job("error"));

    expect(outcome).toEqual({
      kind: "reportError",
      message: "L'analyse a échoué.",
      code: null,
    });
  });

  /**
   * Une annulation n'est **pas** une erreur : l'utilisateur vient de cliquer sur
   * « annuler ». Lui afficher un message rouge pour son propre geste apprendrait à
   * ignorer les messages rouges.
   */
  it("ne dit rien sur « cancelled »", () => {
    expect(terminalOutcome(job("cancelled"))).toEqual({ kind: "silent" });
  });

  /**
   * `fetchResult` ne doit être tenté que sur `done` : un job annulé ou en échec n'a
   * pas de résultat, et le demander produit un 409 dont le message parle de « job
   * non terminé » — sans rapport avec ce que l'utilisateur vient de voir.
   */
  it("ne demande jamais le résultat d'un job non terminé avec succès", () => {
    for (const status of ["error", "cancelled"] as const) {
      expect(terminalOutcome(job(status)).kind).not.toBe("fetchResult");
    }
  });
});
