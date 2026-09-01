/**
 * Ce qu'une capture de véhicule est, et ce qu'elle porte.
 *
 * **Dans `shared/lib` et non dans une feature**, pour la raison exacte de
 * `vehicleMatch.ts` : trois surfaces montrent une vignette — le registre, le tiroir
 * d'alertes, la modale que le studio ouvre — et une feature n'importe jamais une
 * autre. Trois copies de « y a-t-il une photo » finiraient par diverger, et la panne
 * serait une colonne absente d'un écran et présente sur l'autre.
 *
 * **Des primitives et non un `VehicleRecord`** : ce module ne doit rien devoir à
 * `shared/api`, hormis le type de la cause. Les alertes n'ont pas de `VehicleRecord`
 * sous la main, et une signature qui l'exigerait les obligerait à en fabriquer un.
 */

import type { SnapshotKind } from "@/shared/api/contracts";

/**
 * Ce véhicule a-t-il une photo ?
 *
 * **C'est l'instant qui fait le drapeau, plus la confiance de lecture** (ADR 0051) :
 * deux des trois causes de capture n'ont rien lu, donc `snapshotScore` y vaut `null`
 * alors que la photo existe. Un lecteur resté sur l'ancien drapeau ne verrait ni les
 * plaques repérées non lues, ni les véhicules trouvés par ressemblance —
 * silencieusement, et ce sont précisément les deux populations qu'ADR 0051 ajoute.
 *
 * `undefined` couvre le résultat archivé qui ne portait pas encore le champ, et vaut
 * « pas de photo » : à l'époque le serveur posait score et instant ensemble.
 */
export function snapshotExists(snapshotMs: number | null | undefined): boolean {
  return (snapshotMs ?? null) !== null;
}

/**
 * Une vignette de plaque accompagne-t-elle cette photo ?
 *
 * `undefined` rend **`true`**, et ce n'est pas un défaut de prudence : sur un
 * résultat archivé, la lecture d'une plaque était la seule cause de capture possible,
 * donc le `plate.jpg` existe. Répondre `false` cacherait la vignette de tous les
 * anciens résultats — une régression invisible, la modale se contentant d'être plus
 * courte. Si le fichier a réellement été purgé, la modale a déjà son repère muet.
 */
export function snapshotHasPlateFace(kind: SnapshotKind | null | undefined): boolean {
  return kind !== "appearance";
}

/**
 * Pourquoi cette photo existe, en français et en trois mots.
 *
 * Sur la vignette du registre (infobulle) et sous la photo en grand. Sans elle,
 * « pourquoi ce véhicule a une photo et pas celui-là » n'a aucune réponse à l'écran —
 * et surtout, une photo sans plaque lue se lirait comme une lecture perdue.
 */
export function snapshotReasonLabel(kind: SnapshotKind | null | undefined): string {
  switch (kind) {
    case "plate_box":
      return "plaque repérée, non lue";
    case "appearance":
      return "retenue pour sa ressemblance";
    default:
      // `plate_text`, et le champ absent d'un résultat archivé — où c'était la seule
      // cause possible.
      return "plaque lue";
  }
}
