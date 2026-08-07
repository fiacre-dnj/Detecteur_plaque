/**
 * Précharge un modèle sur le serveur — téléchargement **et** préchauffage.
 *
 * Dans `entities/` et non dans une feature, pour la raison qui a déjà mis
 * `useModels` ici : le sélecteur de modèles, le studio et le benchmark en ont tous
 * besoin, et une feature n'importe jamais une autre (règle FSD du projet).
 *
 * Ce que cet appel déplace, il ne le supprime pas : le premier usage d'un modèle
 * coûte son téléchargement (plusieurs dizaines de mégaoctets) puis la fusion de ses
 * couches. Précharger fait payer cette attente **au moment choisi** — la sélection,
 * ou le clic sur « réessayer » après un échec — au lieu de la faire subir à une
 * analyse qui affiche 0 % sans rien dire.
 *
 * **Long, et c'est normal.** Le timeout est nettement au-dessus du défaut : un
 * `xlarge` sur une liaison ordinaire dépasse largement les trente secondes, et
 * abandonner à mi-téléchargement laisserait le serveur finir un travail dont le
 * client a cessé d'attendre le résultat.
 */

import { request } from "@/shared/api/httpClient";

/** Cinq minutes : un modèle `xlarge` sur une liaison lente y tient. */
export const PRELOAD_TIMEOUT_MS = 300_000;

export interface PreloadResponse {
  modelId: string;
  status: string;
}

/**
 * Demande au serveur de charger un modèle.
 *
 * @throws {ApiError} 404 si le modèle est inconnu du catalogue, 503 si le
 * chargement échoue — avec, dans les deux cas, le message français du registre.
 */
export function preloadModel(modelId: string): Promise<PreloadResponse> {
  return request<PreloadResponse>(
    `/api/v1/models/${encodeURIComponent(modelId)}/preload`,
    { method: "POST", timeoutMs: PRELOAD_TIMEOUT_MS },
  );
}
