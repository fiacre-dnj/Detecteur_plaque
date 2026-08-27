/**
 * Les adresses des fichiers d'un job — vidéo et captures.
 *
 * **Des chaînes et non des `fetch`.** Ces ressources sont consommées en `src` d'une
 * balise : la vidéo est lue **par plages** (`Accept-Ranges`), ce qui rend le
 * déplacement dans la timeline immédiat, et les images profitent du cache du
 * navigateur et de `loading="lazy"`. Les charger par `request()` annulerait les deux
 * — et ce client est de toute façon JSON seulement.
 *
 * **Dans `shared/api/` et non dans une feature** : le registre affiche les vignettes,
 * les alertes les affichent aussi, et une feature n'importe jamais une autre feature.
 * `inputVideoUrl` a déménagé ici pour la même raison, et `analysis-job` le réexporte
 * pour ne rien casser.
 *
 * Toujours relatives : même origine en développement (proxy Vite) et en production
 * (le backend sert le build). Aucune URL de base nulle part.
 *
 * `jobId` est un identifiant **généré par le serveur** et `globalId` un entier : rien
 * de ce qui compose ces chemins ne vient d'une saisie, d'où l'absence
 * d'échappement — la même convention que le reste de ce module.
 */

/**
 * La vidéo analysée, à poser sur `video.src`.
 *
 * Peut répondre 409 `input_missing` : la vidéo est purgée plus tôt que le résultat.
 * Ce n'est pas une panne — les chiffres restent affichables, c'est l'incrustation sur
 * l'image qui demande de redéposer le fichier. L'erreur remonte par l'événement
 * `error` de la balise, pas par une exception ici.
 */
export function inputVideoUrl(jobId: string): string {
  return `/api/v1/jobs/${jobId}/input`;
}

/**
 * La photo du véhicule, prise sur l'image dont sa plaque a été le mieux lue.
 *
 * Peut répondre 409 `snapshot_missing`, et c'est le cas **courant** : soit aucune
 * plaque n'a été lue sur ce véhicule, soit les captures ont été purgées avec la
 * vidéo — elles suivent son TTL. Comme pour la vidéo, l'échec arrive par l'événement
 * `error` de la balise, et l'interface montre un repère muet plutôt qu'une image
 * cassée.
 */
export function vehicleSnapshotUrl(jobId: string, globalId: number): string {
  return `/api/v1/jobs/${jobId}/vehicles/${globalId}/snapshot.jpg`;
}

/**
 * La vignette de plaque, extraite de **la même image** que la photo du véhicule.
 *
 * Un second fichier et non une image composée : c'est elle qui prouve une lecture, et
 * elle doit pouvoir être montrée seule, plus grande, à côté d'une plaque recherchée.
 */
export function platePhotoUrl(jobId: string, globalId: number): string {
  return `/api/v1/jobs/${jobId}/vehicles/${globalId}/plate.jpg`;
}
