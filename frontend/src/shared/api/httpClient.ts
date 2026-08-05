/**
 * Client HTTP — **un seul module**, une seule couche.
 *
 * Trois obligations, chacune évitant une heure de débogage :
 *
 * 1. **URL toujours relative.** Même origine en développement (proxy Vite) et en
 *    production (le backend sert le build) : aucune configuration d'URL nulle part.
 * 2. **Garde sur le `content-type`.** Le repli SPA de Vite répond `index.html`
 *    en **HTTP 200** pour une route inconnue : un mauvais chemin d'API ne produit
 *    donc jamais de 404, et sans cette garde on débogue un « JSON cassé » pendant
 *    une heure au lieu de lire « le backend n'est pas démarré ».
 * 3. **Timeout explicite.** Une requête sans borne laisse un écran en attente
 *    indéfiniment, ce que l'utilisateur lit comme un plantage.
 */

import type { ProblemDetails } from "./contracts";

/** 2,5 s : au-delà, le backend est considéré absent et l'interface le dit. */
export const HEALTH_TIMEOUT_MS = 2_500;
/** 30 s pour une requête ordinaire. */
export const DEFAULT_TIMEOUT_MS = 30_000;

const JSON_TYPES = ["application/json", "application/problem+json"];

/** Erreur d'API, porteuse de tout ce qu'un rapport d'incident exige. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;

  constructor(message: string, status: number, code: string, requestId: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

export interface RequestOptions extends RequestInit {
  /** `null` désactive le timeout — réservé aux envois de fichier. */
  timeoutMs?: number | null;
}

/**
 * Effectue une requête et rend le corps JSON typé.
 *
 * @throws {ApiError} Sur toute réponse non 2xx, sur une réponse HTML (backend
 * absent), et sur un dépassement de délai.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...init } = options;

  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { Accept: "application/json", ...init.headers },
      ...(timeoutMs === null ? {} : { signal: AbortSignal.timeout(timeoutMs) }),
    });
  } catch {
    // `TimeoutError` et `TypeError` (réseau injoignable) disent la même chose à
    // l'utilisateur : le serveur ne répond pas. Distinguer les deux dans le
    // message n'aiderait personne.
    throw new ApiError(
      "Le serveur ne répond pas. Vérifiez qu'il est démarré.",
      0,
      "network_error",
      null,
    );
  }

  const contentType = response.headers.get("content-type") ?? "";
  const requestId = response.headers.get("x-request-id");

  // La garde décisive : du HTML signifie qu'on a atteint le repli SPA, donc que
  // l'API n'est pas là — et non que le serveur a renvoyé un JSON invalide.
  if (contentType.includes("text/html")) {
    throw new ApiError(
      "API introuvable — le backend est-il démarré ?",
      response.status,
      "api_not_found",
      requestId,
    );
  }

  const isJson = JSON_TYPES.some((type) => contentType.includes(type));
  const body: unknown = isJson ? await response.json() : null;

  if (!response.ok) {
    throw toApiError(body, response.status, requestId);
  }
  return body as T;
}

/** Traduit un corps d'erreur en `ApiError` lisible. */
function toApiError(body: unknown, status: number, requestId: string | null): ApiError {
  const problem = body as ProblemDetails | null;
  if (problem && typeof problem.detail === "string") {
    return new ApiError(problem.detail, status, problem.code ?? "http_error", problem.requestId ?? requestId);
  }
  // Un corps non-JSON ou vide : on ne peut pas mieux dire que le statut.
  return new ApiError(`Le serveur a répondu ${status}.`, status, "http_error", requestId);
}

/**
 * Interroge la santé du backend et rend `null` s'il est injoignable.
 *
 * `null` plutôt qu'une exception : l'appelant affiche « serveur injoignable » et
 * désactive l'analyse. Une erreur rouge pour un badge d'état serait
 * disproportionnée — et elle apparaîtrait sur chaque écran.
 */
export async function fetchOrNull<T>(path: string, timeoutMs = HEALTH_TIMEOUT_MS): Promise<T | null> {
  try {
    return await request<T>(path, { timeoutMs });
  } catch {
    return null;
  }
}
