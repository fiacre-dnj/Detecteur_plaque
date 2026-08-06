/**
 * La vidéo locale suit l'analyse du serveur.
 *
 * C'est ce qui transforme des boîtes en validation : dessiner les pistes du
 * serveur sur une image arrêtée ne prouve rien, les dessiner sur **l'image que le
 * serveur est en train d'analyser** prouve tout. Le fichier déposé et le fichier
 * lu par la balise `<video>` sont le même, donc le temps de scène de l'aperçu
 * désigne exactement la même image des deux côtés.
 *
 * La vidéo est **pilotée par calage** (`currentTime`), jamais par lecture : une
 * lecture normale avancerait à 25 images par seconde pendant que l'analyse en
 * traite trois, et l'overlay dériverait sans jamais rattraper.
 *
 * Deux règles pour ne pas se battre avec l'utilisateur :
 *
 * 1. **désactivé ⇒ aucune écriture.** Le suivi se coupe, la vidéo reste où elle
 *    est, et la barre de transport reprend la main sans lutte ;
 * 2. **un seul calage en vol.** Écrire `currentTime` pendant qu'un calage
 *    précédent n'est pas terminé fait bégayer le décodeur ; la cible est
 *    mémorisée et appliquée à la fin du calage en cours.
 */

import { useEffect, useRef } from "react";

/**
 * Écart en dessous duquel on ne cale pas.
 *
 * Une image à 25 fps dure 40 ms : en dessous, la vidéo montre déjà la bonne
 * image, et écrire `currentTime` ne ferait que provoquer un aller-retour du
 * décodeur — donc un scintillement, pour rien.
 */
export const SEEK_TOLERANCE_MS = 40;

/** Faut-il caler la vidéo ? Prédicat pur, c'est ici que vit la décision. */
export function shouldSeek(
  currentMs: number,
  targetMs: number | null,
  toleranceMs: number = SEEK_TOLERANCE_MS,
): boolean {
  if (targetMs === null || !Number.isFinite(targetMs) || targetMs < 0) return false;
  return Math.abs(currentMs - targetMs) > toleranceMs;
}

/**
 * Cale la vidéo sur l'image que le serveur vient d'analyser.
 *
 * @param video   La balise, ou `null` tant qu'elle n'est pas montée.
 * @param targetMs Temps de scène de l'aperçu, `null` s'il n'y en a pas.
 * @param enabled  Le suivi est-il demandé ? À `false`, ce hook ne touche à rien.
 */
export function useFollowAnalysis(
  video: HTMLVideoElement | null,
  targetMs: number | null,
  enabled: boolean,
): void {
  /** Cible en attente, posée quand un calage est déjà en cours. */
  const pending = useRef<number | null>(null);

  useEffect(() => {
    if (video === null || !enabled) return;

    // La lecture et le suivi sont deux pilotes du même curseur : les laisser
    // coexister ferait sauter l'image en avant puis en arrière à chaque aperçu.
    if (!video.paused) video.pause();

    const apply = (ms: number): void => {
      if (video.seeking) {
        pending.current = ms;
        return;
      }
      pending.current = null;
      video.currentTime = ms / 1000;
    };

    const onSeeked = (): void => {
      const next = pending.current;
      if (next !== null) apply(next);
    };
    video.addEventListener("seeked", onSeeked);

    if (targetMs !== null && shouldSeek(video.currentTime * 1000, targetMs)) {
      apply(targetMs);
    }

    return () => {
      video.removeEventListener("seeked", onSeeked);
      pending.current = null;
    };
  }, [video, targetMs, enabled]);
}
