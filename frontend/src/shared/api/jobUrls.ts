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
 * L'instant de la capture, ajouté à l'adresse — **et il n'est pas décoratif**.
 *
 * Le serveur sert ces images en `max-age=31536000, immutable`, ce qui était vrai
 * tant qu'elles étaient écrites une fois, à la fin. Depuis ADR 0046 elles sont
 * écrites au fil de l'eau et **remplacées** dès qu'une lecture bat la précédente :
 * une adresse figée pour un an garderait dans le navigateur la première capture,
 * souvent la moins bonne, pour toute la session.
 *
 * `snapshotMs` change exactement quand le fichier change — `record_snapshot` pose
 * le score et l'instant ensemble — donc l'adresse versionnée identifie le triplet
 * job + véhicule + capture, qui, lui, est réellement immuable. Le serveur ignore la
 * requête : rien à changer côté route.
 *
 * `null`/`undefined` rend l'adresse nue, celle d'avant : un appelant qui ne connaît
 * pas l'instant reste servi, au risque d'une vignette de 40 px en retard d'une
 * amélioration.
 *
 * **`retry` est ici, et pas chez l'appelant.** Deux composants le concaténaient
 * eux-mêmes, chacun en devinant la ponctuation de l'autre : le registre écrivait
 * `&retry=` en supposant `?v=` présent, la pile d'alertes `?retry=` en supposant
 * l'inverse. Aucun des deux n'était faux, et les deux le devenaient au premier
 * changement d'appelant — c'est-à-dire maintenant, les alertes recevant leur version.
 * Composer la requête au seul endroit qui connaît le chemin ferme le piège.
 *
 * `retry` à `0` n'ajoute rien : c'est la première tentative, et la faire porter un
 * paramètre priverait la vignette du cache pour toutes les rangées visibles.
 */
function versioned(
  path: string,
  capturedMs: number | null | undefined,
  retry: number | null | undefined,
): string {
  const query = [
    capturedMs == null ? null : `v=${capturedMs}`,
    retry == null || retry === 0 ? null : `retry=${retry}`,
  ].filter((part) => part !== null);
  return query.length === 0 ? path : `${path}?${query.join("&")}`;
}

/**
 * La photo du véhicule, prise sur l'image qui la méritait le plus.
 *
 * « Le plus » dépend de la cause (`snapshotKind`) : la meilleure lecture de plaque,
 * la plus large plaque repérée, ou la plus large vue encodée pour une recherche par
 * image.
 *
 * Peut répondre 409 `snapshot_missing`, et c'est le cas **courant** : soit rien n'a
 * été vu à montrer sur ce véhicule, soit la capture n'est pas encore écrite —
 * l'analyse tourne —, soit les captures ont été purgées avec la vidéo, dont elles
 * suivent le TTL. Comme pour la vidéo, l'échec arrive par l'événement `error` de la
 * balise, et l'interface montre un repère muet plutôt qu'une image cassée.
 *
 * `capturedMs` est le `snapshotMs` du `VehicleRecord` — voir `versioned`.
 */
export function vehicleSnapshotUrl(
  jobId: string,
  globalId: number,
  capturedMs?: number | null,
  retry?: number | null,
): string {
  return versioned(`/api/v1/jobs/${jobId}/vehicles/${globalId}/snapshot.jpg`, capturedMs, retry);
}

/**
 * La vignette de plaque, extraite de **la même image** que la photo du véhicule.
 *
 * Un second fichier et non une image composée : c'est elle qui prouve une lecture, et
 * elle doit pouvoir être montrée seule, plus grande, à côté d'une plaque recherchée.
 *
 * Elle porte la **même** version que la photo du véhicule, forcément : les deux
 * sortent de la même image, et les désynchroniser montrerait la plaque d'une prise
 * de vue sous la voiture d'une autre.
 *
 * **Elle n'existe pas pour toute capture** : une photo retenue pour la ressemblance
 * du véhicule n'a aucune plaque à recadrer, et cette adresse rend alors 409. Demander
 * à `snapshotHasPlateFace` avant d'y aller, plutôt que d'attendre l'échec.
 */
export function platePhotoUrl(
  jobId: string,
  globalId: number,
  capturedMs?: number | null,
  retry?: number | null,
): string {
  return versioned(`/api/v1/jobs/${jobId}/vehicles/${globalId}/plate.jpg`, capturedMs, retry);
}
