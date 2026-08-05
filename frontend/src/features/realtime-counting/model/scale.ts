/**
 * La mise à l'échelle de la géométrie — **le point le plus dangereux du mode direct**.
 *
 * Le client réduit ses frames à 960 px de large avant de les envoyer : une frame
 * 1280×720 en JPEG pleine résolution ne tient pas le débit, et le décodage serveur
 * coûte plus que l'inférence. Mais les lignes et les zones ont été tracées sur la
 * vidéo **source**, en pixels source (invariant 2).
 *
 * Si la géométrie part sans être réduite du même facteur, il ne se passe **rien** :
 * pas d'exception, pas de 422, pas de journal. Le serveur applique consciencieusement
 * une ligne tracée pour du 1280 px à une image de 960, donc **25 % à côté**. Les
 * chiffres restent plausibles — des véhicules sont comptés, juste pas les bons — et
 * personne ne peut savoir que le résultat est faux. C'est le pire mode de défaillance
 * qu'un logiciel de mesure puisse avoir : silencieux et crédible.
 *
 * D'où ce module minuscule, son test unitaire, et le contrôle croisé contre les
 * dimensions que `ready` renvoie. Trois filets pour une multiplication, parce que la
 * multiplication oubliée ne se voit pas.
 */

import type { AnalysisRequest, Box, CountingLine, Point, Zone } from "@/shared/api/contracts";

/**
 * Largeur d'envoi visée.
 *
 * 960 px est un compromis mesuré : en dessous, les véhicules lointains tombent sous
 * la taille minimale de détection de YOLO et disparaissent des comptes ; au-dessus,
 * l'encodage JPEG côté navigateur devient le goulot et la latence dérive.
 */
export const TARGET_WIDTH = 960;

/**
 * Facteur de réduction pour une largeur source donnée.
 *
 * **Borné à 1 :** on ne *grandit* jamais une frame. Agrandir coûterait de la bande
 * passante et du temps d'inférence pour de l'information inventée par
 * l'interpolation — le modèle ne détecte pas mieux sur du flou agrandi.
 *
 * Une largeur nulle ou négative rend 1 plutôt que de lever : la fonction est appelée
 * pendant le montage, avant que la vidéo ait des dimensions, et faire échouer ce
 * chemin serait une panne pour un état transitoire d'une demi-seconde.
 */
export function scaleFactor(sourceWidth: number): number {
  if (!Number.isFinite(sourceWidth) || sourceWidth <= 0) return 1;
  return Math.min(1, TARGET_WIDTH / sourceWidth);
}

/**
 * Dimensions d'envoi, en entiers.
 *
 * Arrondies parce qu'un canvas n'a pas de dimension fractionnaire : demander
 * 540,5 px de haut donne 540, et la hauteur réellement encodée diffère alors de
 * celle qu'on croit avoir demandée. On arrondit donc ici, une fois, et on utilise
 * *ces* nombres partout ensuite.
 *
 * Bornées à 1 : une hauteur de 0 produirait un canvas invalide dont `toBlob` rend
 * `null`, et la session s'arrêterait sans raison lisible.
 */
export function scaledSize(
  sourceWidth: number,
  sourceHeight: number,
  factor: number,
): { width: number; height: number } {
  return {
    width: Math.max(1, Math.round(sourceWidth * factor)),
    height: Math.max(1, Math.round(sourceHeight * factor)),
  };
}

function scalePoint(point: Point, factor: number): Point {
  return { x: point.x * factor, y: point.y * factor };
}

/**
 * Met une requête complète à l'échelle d'envoi.
 *
 * **`pixelsPerMeter` est mis à l'échelle lui aussi**, et c'est le piège dans le
 * piège. L'échelle est un rapport pixels/mètre : sur une image réduite de 25 %, un
 * mètre couvre 25 % de pixels en moins. Laisser la valeur source ferait des vitesses
 * surestimées d'un tiers — encore une fois sans aucune erreur, et sur une grandeur
 * que personne ne peut vérifier de tête.
 *
 * Ce qui n'est **pas** mis à l'échelle : les seuils (`confidenceThreshold`,
 * `iouThreshold`), qui sont sans dimension ; `minHits` et `maxLostMs`, qui comptent
 * des images et des millisecondes ; les identifiants, noms et couleurs, qui sont
 * rejoués à l'identique.
 *
 * `factor === 1` rend une requête équivalente à l'entrée — c'est ce que le test
 * vérifie d'abord, parce que la source déjà en dessous de 960 px est le cas le plus
 * courant sur une webcam et qu'il ne doit rien perturber.
 */
export function scaleRequestGeometry(request: AnalysisRequest, factor: number): AnalysisRequest {
  return {
    ...request,
    pixelsPerMeter:
      request.pixelsPerMeter === null ? null : request.pixelsPerMeter * factor,
    lines: request.lines.map((line) => scaleLine(line, factor)),
    zones: request.zones.map((zone) => scaleZone(zone, factor)),
  };
}

/** Une ligne mise à l'échelle. Nom, couleur et rattachement de zone intacts. */
export function scaleLine(line: CountingLine, factor: number): CountingLine {
  return { ...line, a: scalePoint(line.a, factor), b: scalePoint(line.b, factor) };
}

/** Une zone mise à l'échelle. L'ordre des sommets est préservé : il porte l'orientation. */
export function scaleZone(zone: Zone, factor: number): Zone {
  return { ...zone, points: zone.points.map((point) => scalePoint(point, factor)) };
}

/**
 * Remet une boîte reçue à l'échelle **source**, pour le dessin.
 *
 * Le chemin retour du même piège : le serveur renvoie des boîtes en pixels de
 * l'image qu'il a reçue, donc réduite. Les dessiner sans les redilater les
 * placerait dans le coin supérieur gauche de la scène, décalées et trop petites.
 * Celui-là au moins se voit immédiatement — mais autant ne pas l'écrire.
 *
 * `factor` est le facteur d'**aller** ; on divise donc. Un facteur nul ou non fini
 * rend la boîte inchangée plutôt que des `Infinity` qui feraient disparaître le
 * dessin sans message.
 */
export function unscaleBox(box: Box, factor: number): Box {
  if (!Number.isFinite(factor) || factor <= 0) return box;
  return {
    x: box.x / factor,
    y: box.y / factor,
    width: box.width / factor,
    height: box.height / factor,
  };
}

/**
 * Les dimensions annoncées par le serveur correspondent-elles à ce qu'on croit envoyer ?
 *
 * **La question à laquelle tout ce module sert de réponse.** Le serveur dit ce qu'il
 * a décodé ; le client sait ce qu'il a encodé. Un écart signifie que la géométrie et
 * l'image ne sont pas dans le même repère, donc que les chiffres sont faux — et le
 * seul comportement acceptable est alors de s'arrêter, pas de compter quand même.
 *
 * La tolérance d'un pixel n'est pas de la complaisance : un encodeur JPEG peut
 * ajuster d'un pixel pour un alignement de bloc 8×8, et refuser pour cela
 * rendrait le mode direct inutilisable sur du matériel parfaitement sain.
 */
export const DIMENSION_TOLERANCE_PX = 1;

export function dimensionsAgree(
  expected: { width: number; height: number },
  reported: { width: number | null; height: number | null },
): boolean {
  // `null` : le serveur n'a pas encore décodé de frame. Ce n'est pas un désaccord,
  // c'est une absence de réponse — et traiter l'absence comme un échec bloquerait
  // toutes les sessions, puisque `ready` précède forcément la première frame.
  if (reported.width === null || reported.height === null) return true;
  return (
    Math.abs(reported.width - expected.width) <= DIMENSION_TOLERANCE_PX &&
    Math.abs(reported.height - expected.height) <= DIMENSION_TOLERANCE_PX
  );
}

/** Message d'écart de dimensions — il **donne les deux nombres**, pas un verdict. */
export function dimensionMismatchMessage(
  expected: { width: number; height: number },
  reported: { width: number; height: number },
): string {
  return (
    `Le serveur a reçu des images de ${reported.width}×${reported.height} px alors que ` +
    `le client en envoie de ${expected.width}×${expected.height} px. La géométrie ne ` +
    `serait pas au bon endroit et les comptages seraient faux : le direct est arrêté.`
  );
}
