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

/** ~10 Hz : au-delà, l'œil ne distingue plus rien et le rendu coûte. */
export const PROGRESS_MIN_INTERVAL_MS = 100;
/** Un point de pourcentage : le plus petit pas que l'affichage sait montrer. */
export const PROGRESS_MIN_STEP = 0.01;

/**
 * Faut-il publier cette progression d'envoi ?
 *
 * `XMLHttpRequest` émet `progress` à chaque paquet : sur une vidéo de 800 Mo,
 * cela fait des centaines d'événements par seconde, dont **chacun** provoquait un
 * `setUpload` et donc un rendu complet du studio. L'interface devenait pâteuse
 * pendant tout l'envoi, ce qui se lit comme « l'application rame » alors que rien
 * n'est en train de calculer.
 *
 * Deux portes plutôt qu'une seule minuterie : le pas de 1 % laisse passer une
 * progression rapide sur un petit fichier, où attendre 100 ms perdrait la moitié
 * des étapes visibles.
 *
 * **Le dernier événement passe toujours** (`force`), et c'est indispensable : sans
 * lui, une barre étranglée s'arrête à 97 % sur un envoi terminé, et l'utilisateur
 * attend une fin qui a déjà eu lieu.
 *
 * Fonction pure — l'horloge est un paramètre — pour être testable sans minuteries.
 */
export function shouldPublishProgress(
  ratio: number,
  nowMs: number,
  last: { ratio: number; atMs: number } | null,
  force = false,
): boolean {
  if (force || last === null) return true;
  if (nowMs - last.atMs >= PROGRESS_MIN_INTERVAL_MS) return true;
  return Math.abs(ratio - last.ratio) >= PROGRESS_MIN_STEP;
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
  /**
   * La vignette du véhicule recherché, déjà recadrée. `null` = aucune recherche.
   *
   * Un `Blob` et non un champ de `request` : une image n'a pas sa place dans du JSON,
   * et surtout elle n'est **jamais persistée** côté serveur — elle ne traverse pas
   * `config_json`, donc rouvrir le job ne la rend pas. C'est la même doctrine que
   * `plateWatchlist` côté client, appliquée à une donnée plus sensible encore.
   */
  queryImage: Blob | null = null,
): UploadHandle {
  const xhr = new XMLHttpRequest();

  /** Dernière progression réellement publiée — l'état de l'étranglement. */
  let published: { ratio: number; atMs: number } | null = null;

  const publish = (event: ProgressEvent, force = false): void => {
    const total = event.lengthComputable ? event.total : 0;
    const ratio = event.lengthComputable && event.total > 0 ? event.loaded / event.total : 0;
    const now = performance.now();
    if (!shouldPublishProgress(ratio, now, published, force)) return;
    published = { ratio, atMs: now };
    onProgress({ loaded: event.loaded, total, ratio });
  };

  const jobId = new Promise<string>((resolve, reject) => {
    xhr.upload.addEventListener("progress", (event) => publish(event));
    // **Le dernier événement, forcé.** Sans lui, une barre étranglée resterait
    // figée à 97 % sur un envoi achevé, et l'utilisateur attendrait une fin déjà
    // survenue — exactement le défaut que l'étranglement doit éviter d'introduire.
    xhr.upload.addEventListener("load", (event) => publish(event, true));

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
  // **La vignette part en `Blob`, contrairement à la configuration juste au-dessus** :
  // la route la déclare `UploadFile | None`, donc FastAPI attend bien un fichier ici.
  // Le nom de partie doit être `query_image` — FastAPI nomme les parties d'après le
  // paramètre Python, jamais d'après son alias.
  if (queryImage !== null) body.append("query_image", queryImage, "query.jpg");

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
