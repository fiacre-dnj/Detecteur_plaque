/**
 * L'accès HTTP aux presets.
 *
 * **La lecture demande toujours la résolution courante.** C'est le seul appel du
 * projet dont les paramètres de requête changent le sens de la réponse : sans
 * `width`/`height`, le serveur rend la géométrie d'origine et l'appelant devrait
 * savoir qu'il doit la convertir. Avec, le serveur convertit et l'annonce par
 * `scaled`. La deuxième forme est la seule utilisable pour charger un preset, parce
 * qu'elle rend impossible d'oublier la conversion.
 */

import type { Page, Preset, PresetDraft } from "@/shared/api/contracts";
import { request } from "@/shared/api/httpClient";

const PRESETS_URL = "/api/v1/presets";

/**
 * La liste, pour choisir.
 *
 * Sans dimensions : elle sert à parcourir des noms, pas à charger une géométrie.
 * Demander une conversion ici la ferait calculer pour tous les presets affichés, et
 * pour la plupart elle serait jetée.
 */
export async function fetchPresets(): Promise<Page<Preset>> {
  return await request<Page<Preset>>(`${PRESETS_URL}?limit=200`);
}

/**
 * Un preset, mis à l'échelle de la vidéo courante.
 *
 * `width`/`height` sont **obligatoires** dans cette signature alors que l'API les
 * accepte optionnels : côté client, il n'existe aucun cas légitime de charger un
 * preset sans savoir sur quoi on le charge. Les rendre facultatifs ici rouvrirait la
 * porte à l'oubli que toute cette feature existe pour fermer.
 */
export async function fetchPreset(
  presetId: string,
  width: number,
  height: number,
): Promise<Preset> {
  const query = new URLSearchParams({ width: String(width), height: String(height) });
  return await request<Preset>(`${PRESETS_URL}/${encodeURIComponent(presetId)}?${query}`);
}

export async function createPreset(draft: PresetDraft): Promise<Preset> {
  return await request<Preset>(PRESETS_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draft),
  });
}

export async function deletePreset(presetId: string): Promise<void> {
  await request<void>(`${PRESETS_URL}/${encodeURIComponent(presetId)}`, { method: "DELETE" });
}
