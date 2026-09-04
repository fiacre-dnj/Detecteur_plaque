/**
 * Ce que la modale de capture dit sous le titre — **un seul juge**.
 *
 * Quatre faits, quatre questions différentes, dans cet ordre : **pourquoi** cette
 * photo existe, **quand** elle a été prise, à quel point la plaque y était **lue**
 * sûrement, et à quel point le véhicule **ressemble** à l'image recherchée.
 *
 * La cause passe en premier depuis ADR 0051 : sans elle, une photo sans confiance de
 * lecture se lirait comme une lecture ratée, alors qu'il n'y avait rien à lire.
 *
 * **Dans `shared/lib` et non dans le registre**, pour la raison exacte de
 * `snapshotKind.ts` : deux features ouvrent cette modale — le registre depuis sa
 * colonne, le studio depuis une alerte — et une feature n'importe jamais une autre.
 * Elle était écrite dans le registre seul, et la légende du studio, recopiée à la
 * main, avait déjà perdu la confiance de lecture en route.
 *
 * **Les deux pourcentages ne mesurent pas la même chose et ne se remplacent jamais** :
 * `snapshotScore` dit « le texte lu sur *cette image* est fiable » — non-nul implique
 * `plate_text` (ADR 0051) — là où `matchScore` dit « ce véhicule ressemble à celui
 * qu'on cherche », une similarité cosinus dont le seuil vit côté client
 * (`shared/lib/vehicleMatch.ts`). Une capture retenue pour la ressemblance porte donc
 * le second sans le premier, ce qui est exactement l'information à lire.
 *
 * **Des primitives et non un `VehicleRecord`**, même règle que `snapshotKind.ts` : les
 * champs suffisent, et les exiger tous obligerait un appelant à fabriquer un
 * enregistrement complet pour afficher une phrase.
 */

import type { SnapshotKind } from "@/shared/api/contracts";

import { formatScore } from "./score";
import { snapshotReasonLabel } from "./snapshotKind";

/** Ce dont la légende a besoin, et rien de plus. */
export interface CaptionedSnapshot {
  snapshotKind?: SnapshotKind | null;
  snapshotMs?: number | null;
  snapshotScore?: number | null;
  matchScore?: number | null;
}

/**
 * La légende d'une capture, en une phrase.
 *
 * `formatTime` est passé en paramètre plutôt qu'importé : le format d'instant du
 * projet vit dans `sceneTime.ts`, mais le dixième de seconde est un choix de l'écran
 * — et cette fonction n'a pas à trancher pour ses deux appelants.
 */
export function snapshotCaption(
  vehicle: CaptionedSnapshot,
  formatTime: (ms: number) => string,
): string {
  const parts: string[] = [snapshotReasonLabel(vehicle.snapshotKind)];
  if (vehicle.snapshotMs != null) parts.push(`capturée à ${formatTime(vehicle.snapshotMs)}`);
  if (vehicle.snapshotScore != null) parts.push(`lecture ${formatScore(vehicle.snapshotScore)}`);
  // La ressemblance en dernier : elle ne décrit pas la photo mais le véhicule, et elle
  // n'existe que si une recherche par image a tourné. `null` couvre les deux causes
  // que l'écran n'a pas à distinguer — aucune requête, ou véhicule jamais encodé
  // parce que trop petit ou trop flou.
  //
  // **Elle dit à quoi elle ressemble**, et ce n'était pas le cas. Depuis ADR 0055 il
  // existe une seconde ressemblance — celle de deux véhicules entre eux — et la
  // modale de comparaison affiche les deux : son entête annonçait « Ressemblance
  // 100 % » (au jumeau) au-dessus de deux légendes « ressemblance 34 % » (à la photo
  // cherchée). Deux mesures différentes sous un seul mot, les deux chiffres
  // plausibles : l'erreur d'unité invisible que ce projet traque partout ailleurs.
  if (vehicle.matchScore != null) {
    parts.push(`ressemblance à la photo cherchée ${formatScore(vehicle.matchScore)}`);
  }
  return parts.join(" · ");
}
