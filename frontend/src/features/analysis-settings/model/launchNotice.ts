/**
 * Ce qu'il faut savoir **avant** de cliquer sur « Lancer l'analyse serveur ».
 *
 * Deux attentes cachées font lire « l'analyse ne fonctionne pas » là où elle
 * fonctionne parfaitement, et les deux se règlent par une phrase et non par du code
 * de calcul :
 *
 * 1. **Le modèle n'est pas sur le serveur.** Le catalogue en annonce vingt, le disque
 *    en porte trois : dix-sept choix sur vingt déclenchent un téléchargement de
 *    plusieurs dizaines de mégaoctets au lancement. Ce téléchargement n'a lieu qu'à la
 *    première image analysée, donc **après** le passage en « en cours » : la
 *    progression reste à 0 % pendant une à deux minutes, sans le moindre indice.
 * 2. **La détection de plaques coûte une inférence de plus par véhicule et par
 *    image.** Sur processeur, elle domine largement le temps total, et rien à l'écran
 *    ne le disait.
 *
 * Des fonctions **pures**, testées, qui rendent des phrases : le calcul d'une durée
 * probable n'a pas à connaître React, et une phrase testée est une phrase qu'on peut
 * corriger sans rouvrir l'écran.
 *
 * Tout est au **conditionnel**. Ces phrases sont de l'information, pas des promesses :
 * la cadence dépend de la machine, du modèle et de la scène, et annoncer « 4 minutes »
 * pour en prendre 11 est pire que de ne rien annoncer.
 */

import type { VehicleModel } from "@/shared/api/contracts";

/**
 * Avertit qu'un modèle absent du serveur sera téléchargé au lancement.
 *
 * Rend `null` quand il n'y a rien à dire — modèle inconnu du catalogue (le recalage
 * de `StudioPage` s'en charge) ou déjà présent sur le disque. Rendre une chaîne vide
 * obligerait chaque appelant à la distinguer de l'absence d'avertissement.
 */
export function downloadNotice(
  models: readonly VehicleModel[],
  modelId: string,
): string | null {
  const model = models.find((entry) => entry.id === modelId);
  if (model === undefined || model.downloaded) return null;

  return (
    `Premier usage de « ${model.label} » : environ ${model.sizeMb} Mo seront ` +
    `téléchargés au lancement. Comptez une à deux minutes avant que la progression ` +
    `démarre.`
  );
}
