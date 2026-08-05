/**
 * Client HTTP — la garde `content-type` en particulier.
 *
 * `test_du_html_pris_pour_un_json_casse` protège du piège 35 de `prompt/13`, qui
 * est probablement le plus coûteux du projet en heures perdues : le repli SPA de
 * Vite répond `index.html` en **HTTP 200** pour une route inconnue, donc un
 * mauvais chemin d'API ne produit jamais de 404. Sans la garde, on débogue un
 * « JSON invalide » pendant une heure au lieu de lire « le backend est absent ».
 */

import { afterEach, describe, expect, it } from "bun:test";

import { ApiError, fetchOrNull, request } from "./httpClient";

const originalFetch = globalThis.fetch;

/**
 * Remplace `fetch` par une réponse fabriquée.
 *
 * Le double `as unknown as` est nécessaire : le `fetch` de Bun porte des membres
 * supplémentaires (`preconnect`) qu'une doublure n'a aucune raison d'imiter, et
 * la seule alternative serait de les stuber sans les utiliser.
 */
function respondWith(body: string, init: ResponseInit): void {
  globalThis.fetch = (() => Promise.resolve(new Response(body, init))) as unknown as typeof fetch;
}

function rejectWith(error: Error): void {
  globalThis.fetch = (() => Promise.reject(error)) as unknown as typeof fetch;
}

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe("request", () => {
  it("rend le corps JSON typé sur une réponse 2xx", async () => {
    respondWith('{"status":"ok"}', {
      status: 200,
      headers: { "content-type": "application/json" },
    });

    expect(await request<{ status: string }>("/api/v1/health/live")).toEqual({ status: "ok" });
  });

  it("dit que le backend est absent quand la réponse est du HTML", async () => {
    // Exactement ce que renvoie le repli SPA de Vite : du HTML, en 200.
    respondWith("<!doctype html><html></html>", {
      status: 200,
      headers: { "content-type": "text/html; charset=utf-8" },
    });

    const failure = await request("/api/v1/route-mal-orthographiee").catch(
      (error: unknown) => error,
    );

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).code).toBe("api_not_found");
    expect((failure as ApiError).message).toContain("backend");
  });

  it("traduit un Problem Details en message français avec son code", async () => {
    respondWith(
      JSON.stringify({
        title: "Requête non traitable",
        status: 422,
        detail: "Le modèle « yolo42x » n'existe pas au catalogue.",
        code: "validation_error",
        requestId: "corr-7",
      }),
      { status: 422, headers: { "content-type": "application/problem+json" } },
    );

    const failure = (await request("/api/v1/jobs").catch((error: unknown) => error)) as ApiError;

    expect(failure.message).toContain("yolo42x");
    expect(failure.code).toBe("validation_error");
    // L'identifiant de corrélation vient du corps : c'est ce que l'utilisateur
    // cite quand il signale un incident.
    expect(failure.requestId).toBe("corr-7");
  });

  it("retombe sur le statut quand le corps d'erreur n'est pas exploitable", async () => {
    respondWith("erreur de passerelle", {
      status: 502,
      headers: { "content-type": "text/plain" },
    });

    const failure = (await request("/api/v1/health").catch((error: unknown) => error)) as ApiError;

    expect(failure.message).toContain("502");
    expect(failure.code).toBe("http_error");
  });

  it("dit que le serveur ne répond pas quand le réseau échoue", async () => {
    rejectWith(new TypeError("Failed to fetch"));

    const failure = (await request("/api/v1/health").catch((error: unknown) => error)) as ApiError;

    expect(failure.code).toBe("network_error");
    // Aucun détail technique : « Failed to fetch » n'aide pas l'utilisateur.
    expect(failure.message).not.toContain("fetch");
  });
});

describe("fetchOrNull", () => {
  it("rend null au lieu de lever quand le backend est injoignable", async () => {
    // Un backend absent est un **état**, pas une erreur : le badge l'affiche et
    // désactive l'analyse, sans écran rouge sur chaque page.
    rejectWith(new TypeError("Failed to fetch"));

    expect(await fetchOrNull("/api/v1/health")).toBeNull();
  });

  it("rend la valeur quand le backend répond", async () => {
    respondWith('{"status":"ok"}', {
      status: 200,
      headers: { "content-type": "application/json" },
    });

    expect(await fetchOrNull<{ status: string }>("/api/v1/health")).toEqual({ status: "ok" });
  });
});
