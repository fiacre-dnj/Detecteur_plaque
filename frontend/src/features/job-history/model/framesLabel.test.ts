import { describe, expect, test } from "bun:test";

import type { Job, JobStatus } from "@/shared/api/contracts";

import { framesLabel } from "./useJobHistory";

function job(status: JobStatus, processed: number, total: number): Job {
  return {
    jobId: "j1",
    status,
    progress: 1,
    processedFrames: processed,
    totalFrames: total,
    processingFps: 12,
    error: null,
    errorCode: null,
    preparing: false,
    modelId: "yolov8n",
    fileName: "clip.mp4",
    createdAt: "2026-09-03T06:00:00Z",
    finishedAt: null,
    trackedVehicles: 0,
    crossingsTotal: 0,
  };
}

describe("framesLabel", () => {
  test("une analyse terminée n'affiche que les images réellement analysées", () => {
    // `totalFrames` est l'estimation du conteneur : « 6590 / 6660 » se lit comme
    // soixante-dix images perdues sous un job à 100 %, alors que rien n'est perdu.
    expect(framesLabel(job("done", 6590, 6660))).toBe("6590");
    expect(framesLabel(job("done", 3280, 3281))).toBe("3280");
  });

  test("une analyse arrêtée garde sa fraction, qui dit jusqu'où elle est allée", () => {
    expect(framesLabel(job("cancelled", 1840, 6660))).toBe("1840 / 6660");
    expect(framesLabel(job("error", 400, 3219))).toBe("400 / 3219");
    expect(framesLabel(job("paused", 2420, 6181))).toBe("2420 / 6181");
    expect(framesLabel(job("running", 490, 750))).toBe("490 / 750");
  });

  test("un job sans total ne prétend pas en avoir un", () => {
    // `totalFrames` vaut zéro tant que le serveur n'a pas sondé la vidéo.
    expect(framesLabel(job("queued", 0, 0))).toBe("0 / 0");
  });
});
