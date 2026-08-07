/**
 * La fusion des mises à jour de progression.
 *
 * C'est la fonction qui rend le doublon SSE + sondage inoffensif. Elle doit être
 * **idempotente et monotone** : le SSE et le sondage arrivent dans un ordre non
 * garanti, et un sondage lancé avant une frame peut répondre après elle avec une
 * progression inférieure. Sans cette garde, la barre reculerait visiblement — ce
 * que l'utilisateur lit comme un bug, à raison.
 */

import { describe, expect, it } from "bun:test";

import type { Job, JobStatus } from "@/shared/api/contracts";

import { POLL_INTERVAL_MS, mergeProgress, statusLabel } from "./useJobProgress";

function job(status: JobStatus, progress: number, jobId = "j1"): Job {
  return {
    jobId,
    status,
    progress,
    processedFrames: Math.round(progress * 100),
    totalFrames: 100,
    processingFps: 12.5,
    error: null,
    errorCode: null,
    modelId: "yolov8n",
    fileName: "carrefour.mp4",
    createdAt: "2026-08-05T10:00:00+00:00",
    finishedAt: null,
  };
}

describe("mergeProgress — la barre ne recule jamais", () => {
  it("prend la première valeur reçue", () => {
    expect(mergeProgress(null, job("running", 0.2)).progress).toBe(0.2);
  });

  it("avance quand la nouvelle valeur est plus haute", () => {
    expect(mergeProgress(job("running", 0.2), job("running", 0.5)).progress).toBe(0.5);
  });

  it("ignore une valeur en retard", () => {
    // **Le cas réel** : un sondage lancé avant une frame SSE répond après elle.
    // Sans cette garde, la barre retomberait de 50 % à 20 %.
    expect(mergeProgress(job("running", 0.5), job("running", 0.2)).progress).toBe(0.5);
  });

  it("est idempotente : recevoir deux fois le même état ne change rien", () => {
    const current = job("running", 0.4);

    expect(mergeProgress(current, job("running", 0.4)).progress).toBe(0.4);
  });

  it("laisse toujours passer un statut terminal, même à progression plus basse", () => {
    // Un job annulé rapporte sa progression du moment de l'annulation, qui peut
    // être inférieure à la dernière frame reçue. Le statut compte plus.
    const merged = mergeProgress(job("running", 0.9), job("cancelled", 0.3));

    expect(merged.status).toBe("cancelled");
  });

  it("ne quitte jamais un statut terminal pour un état en cours", () => {
    // Une frame SSE en retard arrivant après la fin ne doit pas faire repartir
    // l'interface en « analyse en cours » sur un job déjà terminé.
    const merged = mergeProgress(job("done", 1), job("running", 0.8));

    expect(merged.status).toBe("done");
    expect(merged.progress).toBe(1);
  });

  it("préserve l'échec plutôt qu'une frame plus récente", () => {
    const merged = mergeProgress(job("error", 0.5), job("running", 0.7));

    expect(merged.status).toBe("error");
  });

  it("laisse passer une suspension annoncée avec une progression en retard", () => {
    // **Le cas réel.** Le serveur ne persiste la progression que toutes les deux
    // secondes : la réponse qui annonce « suspendue » porte donc souvent un
    // chiffre inférieur à la dernière frame SSE reçue. Sans exception pour le
    // changement de statut, l'interface afficherait « analyse en cours » sur une
    // analyse arrêtée, et jusqu'à la reprise.
    const merged = mergeProgress(job("running", 0.62), job("paused", 0.6));

    expect(merged.status).toBe("paused");
    // La barre, elle, ne recule toujours pas.
    expect(merged.progress).toBe(0.62);
  });

  it("laisse passer la reprise", () => {
    const merged = mergeProgress(job("paused", 0.62), job("running", 0.6));

    expect(merged.status).toBe("running");
    expect(merged.progress).toBe(0.62);
  });
});

describe("libellés de statut", () => {
  it("nomme les six statuts en français", () => {
    expect(statusLabel("queued")).toBe("En file d'attente");
    expect(statusLabel("running")).toBe("Analyse en cours");
    expect(statusLabel("paused")).toBe("Analyse suspendue");
    expect(statusLabel("done")).toBe("Analyse terminée");
    expect(statusLabel("error")).toBe("Analyse en échec");
    expect(statusLabel("cancelled")).toBe("Analyse annulée");
  });

  it("ne dit pas « échec » pour une annulation", () => {
    // L'utilisateur sait ce qu'il a fait : lui afficher « échec » serait faux, et
    // c'est déjà la règle côté serveur, qui distingue `cancelled` de `error`.
    expect(statusLabel("cancelled")).not.toContain("échec");
  });
});

describe("sondage de secours", () => {
  it("sonde toutes les 3 secondes, comme le backend le documente", () => {
    // Le SSE est un accélérateur, pas la vérité : il peut tomber sans prévenir, et
    // l'interface resterait alors figée sur une analyse peut-être terminée.
    expect(POLL_INTERVAL_MS).toBe(3_000);
  });
});
