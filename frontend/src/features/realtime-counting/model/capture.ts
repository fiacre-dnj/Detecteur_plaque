/**
 * La capture d'une frame de `<video>` en JPEG, réduite à la largeur d'envoi.
 *
 * Isolée du hook parce que c'est la seule partie qui touche le DOM et l'encodeur, et
 * que la logique de cadence qui l'appelle mérite d'être lisible sans elle.
 *
 * **Le canvas est réutilisé d'un appel à l'autre.** Un `document.createElement`
 * par frame, à 15 images par seconde, alloue et abandonne 900 canvas par minute ;
 * le ramasse-miettes finit par s'en occuper, mais par des pauses visibles qui font
 * saccader l'aperçu — précisément pendant qu'on demande à l'utilisateur de juger la
 * fluidité du direct.
 */

/** Qualité JPEG d'envoi. */
export const JPEG_QUALITY = 0.8;

/**
 * Le canvas de travail et son contexte, créés à la première capture.
 *
 * `willReadFrequently` n'est **pas** demandé : on ne relit jamais les pixels
 * (`toBlob` encode côté navigateur). Le demander ferait basculer le contexte en
 * rendu logiciel sur plusieurs navigateurs, et le `drawImage` deviendrait plus lent
 * que l'inférence qu'il alimente.
 */
export interface CaptureSurface {
  canvas: HTMLCanvasElement;
  context: CanvasRenderingContext2D;
}

export function createCaptureSurface(): CaptureSurface | null {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (context === null) return null;
  return { canvas, context };
}

/**
 * La vidéo a-t-elle une image à capturer ?
 *
 * `readyState >= HAVE_CURRENT_DATA` et non `>= HAVE_METADATA` : avec les seules
 * métadonnées, les dimensions sont connues mais aucun pixel n'est décodé, et
 * `drawImage` peint alors un rectangle **noir**. Le serveur reçoit une image valide,
 * n'y détecte rien, et l'utilisateur voit un direct qui « ne compte rien » sans
 * qu'aucune erreur ne l'explique.
 */
export function hasFrame(video: HTMLVideoElement): boolean {
  return (
    video.readyState >= 2 /* HAVE_CURRENT_DATA */ &&
    video.videoWidth > 0 &&
    video.videoHeight > 0
  );
}

/**
 * Encode l'image courante de la vidéo en JPEG à la taille demandée.
 *
 * Rend `null` plutôt que de lever quand l'encodage échoue — ce qui arrive vraiment,
 * sur un flux dont la piste vient d'être coupée. Le hook appelant traite `null`
 * comme « pas de frame cette fois » et réessaie au tour suivant : une session ne
 * doit pas mourir parce qu'une image a manqué.
 */
export async function captureJpeg(
  surface: CaptureSurface,
  video: HTMLVideoElement,
  width: number,
  height: number,
): Promise<Blob | null> {
  if (!hasFrame(video)) return null;

  // Redimensionner le canvas efface son contenu — sans effet ici, puisqu'on
  // repeint tout, mais c'est pourquoi on ne le fait que si la taille a changé.
  if (surface.canvas.width !== width || surface.canvas.height !== height) {
    surface.canvas.width = width;
    surface.canvas.height = height;
  }

  try {
    surface.context.drawImage(video, 0, 0, width, height);
  } catch {
    // `SecurityError` sur une vidéo d'une autre origine : le canvas est souillé.
    // Le cas ne concerne pas la caméra, mais un `<video>` pointant un fichier
    // distant, et il ne doit pas remonter en exception non capturée.
    return null;
  }

  return await new Promise<Blob | null>((resolve) => {
    surface.canvas.toBlob((blob) => resolve(blob), "image/jpeg", JPEG_QUALITY);
  });
}
