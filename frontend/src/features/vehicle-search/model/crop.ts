/**
 * Découper l'image de requête avant l'envoi — le seul endroit qui touche un canvas.
 *
 * **Le recadrage se fait côté client, et c'est un choix de fond.** On n'envoie que la
 * vignette du véhicule, jamais la photo entière : cela borne ce qui traverse le
 * réseau, ce que le serveur voit, et donc ce qu'il pourrait retenir. Une photo de
 * téléphone contient un arrière-plan, des passants, parfois d'autres plaques — rien de
 * tout cela n'a de raison de partir.
 *
 * C'est aussi ce qui fait **converger les deux côtés de la comparaison** : le serveur
 * encode les véhicules de la vidéo depuis la vignette définie par `vehicle_crop`
 * (boîte du détecteur plus 6 % de marge), donc la requête doit lui ressembler. Une
 * photo pleine, étirée à 208 px par le réseau, mettrait la voiture sur un tiers de
 * l'entrée là où la galerie la met sur la totalité — deux cadrages différents rendent
 * des embeddings différents, et la similarité resterait plausible sans rapport avec la
 * ressemblance réelle.
 */

import type { CropRect } from "./query";

/**
 * Côté maximal de la vignette envoyée, en pixels.
 *
 * L'entrée du réseau fait 208 px : au-delà de deux fois cette taille, on transporte
 * des pixels que le redimensionnement du serveur va jeter. 480 est aussi la borne de
 * `MAX_VEHICLE_SIDE_PX` côté serveur, ce qui garde les deux vignettes comparables.
 */
export const MAX_QUERY_SIDE_PX = 480;

/** Qualité JPEG. La même que celle des captures serveur, pour la même raison. */
export const QUERY_JPEG_QUALITY = 0.82;

/**
 * Rend la vignette recadrée en JPEG, ou `null` si le découpage ne donne rien.
 *
 * `null` plutôt qu'une exception, comme tout ce qui touche aux pixels dans ce projet :
 * un canvas refusé — image non chargée, origine croisée, dimension nulle — ne doit pas
 * faire échouer un lancement d'analyse. L'appelant affiche alors que la recherche n'a
 * pas pu être préparée.
 */
export async function cropToJpeg(
  image: HTMLImageElement,
  crop: CropRect,
): Promise<Blob | null> {
  const sourceWidth = image.naturalWidth;
  const sourceHeight = image.naturalHeight;
  if (sourceWidth < 1 || sourceHeight < 1) return null;

  const sx = Math.round(crop.x * sourceWidth);
  const sy = Math.round(crop.y * sourceHeight);
  const sw = Math.max(1, Math.round(crop.width * sourceWidth));
  const sh = Math.max(1, Math.round(crop.height * sourceHeight));

  // **Jamais d'agrandissement**, même règle que `fit` côté serveur : une vignette de
  // 60 px étirée à 480 n'apporte aucun détail, elle coûte du réseau et donne
  // l'illusion d'une image nette.
  const scale = Math.min(1, MAX_QUERY_SIDE_PX / Math.max(sw, sh));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(sw * scale));
  canvas.height = Math.max(1, Math.round(sh * scale));

  const context = canvas.getContext("2d");
  if (context === null) return null;
  // `imageSmoothingQuality` haute parce qu'on réduit : le défaut échantillonne au lieu
  // de moyenner, ce qui fait apparaître du crénelage sur les arêtes du véhicule —
  // exactement ce que l'encodeur d'apparence regarde.
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(image, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);

  return new Promise<Blob | null>((resolve) => {
    canvas.toBlob((blob) => resolve(blob), "image/jpeg", QUERY_JPEG_QUALITY);
  });
}
