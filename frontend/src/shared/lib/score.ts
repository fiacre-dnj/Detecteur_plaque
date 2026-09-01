/**
 * Un score de confiance, en pourcentage — **un seul juge**.
 *
 * Il vivait dans `results-dashboard/model/labels.ts`, et trois features le lisent
 * désormais : les Résultats, le registre et le tiroir d'alertes. Même raison qui a
 * déplacé `classLabel`, `directions.ts` et `vehicleMatch.ts` ici — une feature
 * n'importe jamais une autre feature, et deux arrondis du même score finiraient par
 * afficher « 71 % » ici et « 70,5 % » là.
 *
 * **Arrondi et jamais tronqué**, et le score brut reste disponible en infobulle là où
 * l'écart d'un point compte — c'est le registre qui le fait, sur la colonne dont le
 * curseur de ressemblance décide.
 */

/** Formate un score (0 → 1) en pourcentage. `null` n'est pas `0 %`. */
export function formatScore(score: number | null): string {
  return score === null ? "—" : `${Math.round(score * 100)} %`;
}
