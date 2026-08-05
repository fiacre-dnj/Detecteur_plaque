/**
 * Le dépôt d'une vidéo — **le seul `XMLHttpRequest` du projet**.
 *
 * `fetch` est utilisé partout ailleurs, et c'est le bon choix partout ailleurs.
 * Mais `fetch` **n'expose pas la progression d'envoi** : son `ReadableStream` de
 * requête n'est pas supporté de façon fiable, et il n'existe aucun événement
 * `upload.onprogress`. Sur une vidéo de 800 Mo, cela signifie une barre immobile
 * pendant plusieurs minutes — indistinguable d'un plantage pour l'utilisateur, qui
 * recharge la page et recommence.
 *
 * D'où cette exception unique et documentée. Elle est isolée dans ce module pour
 * que personne n'ait à se demander si `XMLHttpRequest` est la convention du projet :
 * il ne l'est pas.
 */

import { ApiError } from "@/shared/api/httpClient";
import type { AnalysisRequest, ProblemDetails } from "@/shared/api/contracts";

export interface UploadProgress {
  /** Octets transmis. */
  loaded: number;
  /** Taille totale, ou 0 si le navigateur ne la connaît pas encore. */
  total: number;
  /** Fraction transmise, bornée à 1. */
  ratio: number;
}

export interface UploadHandle {
  /** L'identifiant du job accepté. */
  jobId: Promise<string>;
  /** Interrompt l'envoi. Le job n'existe pas encore côté serveur. */
  abort: () => void;
}

/**
 * Envoie la vidéo et sa configuration, en rapportant la progression.
 *
 * Le corps est un `multipart/form-data` avec deux parties : `file` et `request`.
 * **Ne pas poser `Content-Type` à la main** — le navigateur doit générer la
 * frontière (`boundary`), et une valeur écrite manuellement produit un corps que
 * le serveur ne sait pas découper. C'est une erreur classique et son message
 * (« champ `file` manquant ») pointe très loin de la cause.
 */
export function uploadJob(
  file: File,
  request: AnalysisRequest,
  onProgress: (progress: UploadProgress) => void,
): UploadHandle {
  const xhr = new XMLHttpRequest();

  const jobId = new Promise<string>((resolve, reject) => {
    xhr.upload.addEventListener("progress", (event) => {
      onProgress({
        loaded: event.loaded,
        total: event.lengthComputable ? event.total : 0,
        ratio: event.lengthComputable && event.total > 0 ? event.loaded / event.total : 0,
      });
    });

    xhr.addEventListener("load", () => {
      // 202 attendu : le serveur accepte et analyse en tâche de fond.
      if (xhr.status === 202) {
        try {
          const body = JSON.parse(xhr.responseText) as { jobId?: string };
          if (typeof body.jobId === "string") {
            resolve(body.jobId);
            return;
          }
        } catch {
          // Corps illisible : traité comme une réponse inattendue ci-dessous.
        }
        reject(
          new ApiError(
            "Le serveur a accepté l'analyse mais n'a pas renvoyé son identifiant.",
            xhr.status,
            "malformed_response",
            requestIdOf(xhr),
          ),
        );
        return;
      }
      reject(problemFrom(xhr));
    });

    xhr.addEventListener("error", () => {
      reject(
        new ApiError(
          "L'envoi a échoué : le serveur ne répond pas. Vérifiez qu'il est démarré.",
          0,
          "network_error",
          null,
        ),
      );
    });

    xhr.addEventListener("abort", () => {
      reject(new ApiError("L'envoi a été annulé.", 0, "upload_aborted", null));
    });
  });

  const body = new FormData();
  body.append("file", file);
  // **La configuration part en chaîne brute, pas en `Blob`.** La route la déclare
  // `request: Annotated[str, Form(...)]` : un `Blob`, même typé
  // `application/json`, arrive côté FastAPI comme un *fichier* et non comme une
  // chaîne, et la requête est refusée en 422 avec « Input should be a valid
  // string ». Vérifié contre le serveur réel — c'est exactement l'erreur que
  // produisait la version précédente de cette ligne.
  body.append("request", JSON.stringify(request));

  xhr.open("POST", "/api/v1/jobs");
  // Aucun `setRequestHeader("Content-Type", …)` : le navigateur doit écrire la
  // frontière multipart lui-même.
  xhr.send(body);

  return { jobId, abort: () => xhr.abort() };
}

/** Traduit une réponse d'erreur en `ApiError`, en préservant le message français. */
function problemFrom(xhr: XMLHttpRequest): ApiError {
  const requestId = requestIdOf(xhr);
  try {
    const problem = JSON.parse(xhr.responseText) as ProblemDetails;
    if (typeof problem.detail === "string") {
      return new ApiError(
        problem.detail,
        xhr.status,
        problem.code ?? "http_error",
        problem.requestId ?? requestId,
      );
    }
  } catch {
    // Corps non-JSON : on ne peut pas mieux dire que le statut.
  }

  // 413 mérite un message particulier : c'est le refus le plus probable sur un
  // envoi de vidéo, et « erreur 413 » n'aide personne.
  if (xhr.status === 413) {
    return new ApiError(
      "Cette vidéo dépasse la taille maximale acceptée par le serveur.",
      413,
      "payload_too_large",
      requestId,
    );
  }
  return new ApiError(`Le serveur a répondu ${xhr.status}.`, xhr.status, "http_error", requestId);
}

function requestIdOf(xhr: XMLHttpRequest): string | null {
  return xhr.getResponseHeader("x-request-id");
}

/** Formate une taille en octets pour l'affichage. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} o`;
  const mb = bytes / (1024 * 1024);
  if (mb < 1) return `${Math.round(bytes / 1024)} Ko`;
  if (mb < 1024) return `${mb.toFixed(1)} Mo`;
  return `${(mb / 1024).toFixed(2)} Go`;
}
