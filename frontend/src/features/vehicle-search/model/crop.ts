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
 * des pixels que le redimensionnement du serveur va jeter.
 *
 * Cette docstring a revendiqué une parité avec `MAX_VEHICLE_SIDE_PX` du serveur, et
 * la revendication était fausse : ces 480 px et la qualité 82 sont ceux de
 * l'**encodeur de captures**, celui qui fabrique les JPEG montrés à l'écran. Le
 * chemin de l'encodeur d'apparence, lui, reçoit le recadrage à sa **résolution
 * native** et le réduit directement à 208. La requête subit donc un
 * redimensionnement de plus que la galerie — asymétrie connue, de second ordre, et
 * qu'on ne corrige pas à l'aveugle : voir ADR 0048.
 */
export const MAX_QUERY_SIDE_PX = 480;

/** Qualité JPEG. La même que celle des captures serveur, pour la même raison. */
export const QUERY_JPEG_QUALITY = 0.82;

/**
 * Marge ajoutée autour du cadrage de l'utilisateur, en fraction de ses côtés.
 *
 * **Le jumeau de `VEHICLE_MARGIN` côté serveur**, et il doit lui rester égal : la
 * galerie encode la boîte du détecteur *plus 6 %*, donc une requête cadrée au ras du
 * véhicule met la voiture sur 100 % de la tuile 208² là où la galerie la met sur
 * ~89 %. Le même véhicule y paraît 12 % plus gros, et la similarité s'en ressent sans
 * que rien ne le signale.
 *
 * Le nombre vit des deux côtés de la frontière de langage, ce qui est un doublon
 * assumé faute de mécanisme pour le partager. Un test **backend**
 * (`test_recherche_par_image.py`) verrouille `VEHICLE_MARGIN == 0.06` en nommant ce
 * fichier, de sorte qu'une dérive casse un test qui dit où aller — même procédé que
 * `MIN_PLATE_CROP_SIDE_PX`.
 */
export const QUERY_MARGIN = 0.06;

/**
 * Le cadrage de l'utilisateur, élargi de `QUERY_MARGIN` et borné à l'image.
 *
 * Pur, donc testable, contrairement au découpage qui suit — c'est là que vit la seule
 * règle de cette étape.
 *
 * **La marge est perdue asymétriquement sur un bord de l'image**, exactement comme
 * côté serveur, où `crop` borne chaque arête indépendamment (`max(0, …)` /
 * `min(width, …)`). Une voiture cadrée contre le bord de la photo reçoit donc sa
 * marge d'un seul côté, dans les deux chaînes : l'asymétrie est **la même**, et c'est
 * tout ce qu'on demande à cette fonction.
 */
export function withMargin(crop: CropRect): CropRect {
  const padX = crop.width * QUERY_MARGIN;
  const padY = crop.height * QUERY_MARGIN;
  const left = Math.max(0, crop.x - padX);
  const top = Math.max(0, crop.y - padY);
  return {
    x: left,
    y: top,
    width: Math.min(1, crop.x + crop.width + padX) - left,
    height: Math.min(1, crop.y + crop.height + padY) - top,
  };
}

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

  // La marge est appliquée **ici et pas au geste** : le rectangle bleu doit montrer ce
  // que l'utilisateur a cadré, pas ce que la comparaison exige. Élargir l'aperçu
  // laisserait croire à un cadrage plus lâche que celui qu'on a demandé.
  const framed = withMargin(crop);
  const sx = Math.round(framed.x * sourceWidth);
  const sy = Math.round(framed.y * sourceHeight);
  const sw = Math.max(1, Math.round(framed.width * sourceWidth));
  const sh = Math.max(1, Math.round(framed.height * sourceHeight));

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
