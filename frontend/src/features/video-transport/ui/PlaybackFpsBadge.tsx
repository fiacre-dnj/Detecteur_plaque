/**
 * Cadence **réelle** de la vidéo affichée, mesurée image par image.
 *
 * Distincte de « Cadence (serveur) » du tableau de bord, et il faut que les deux
 * soient lisibles ensemble : celle-ci dit à quelle vitesse le navigateur *affiche*,
 * l'autre à quelle vitesse le serveur *analyse*. Un écart entre les deux explique
 * une relecture saccadée — le décodage se bat avec l'inférence pour les mêmes cœurs,
 * ce que `TRAFFIC_INFERENCE_THREADS` documente longuement.
 *
 * **Le composant possède son propre état, et ce n'est pas un détail de style.** Une
 * mesure de cadence se met à jour au rythme de la vidéo ; tenue dans `StudioPage`,
 * elle re-rendrait `GeometryCanvas` à 30-60 Hz et rendrait l'édition de géométrie
 * saccadée dès qu'on lit la vidéo. C'est exactement le bug corrigé par
 * `f9a4da1 perf(counting-studio): supprime deux sources de re-rendu pendant
 * l'analyse`, et `TransportBar` porte la même contrainte — d'où le même patron :
 * recevoir la **référence**, la lire dans un effet de montage, jamais au rendu.
 */

import { useEffect, useState } from "react";

/**
 * Fenêtre de mesure. Une seconde : assez long pour que la moyenne ne saute pas à
 * chaque image décodée en retard, assez court pour qu'un ralentissement se voie
 * pendant qu'il a lieu.
 */
const WINDOW_MS = 1000;

/**
 * Au-delà, on considère que la lecture s'est arrêtée et on efface la mesure.
 *
 * Sans ce délai, mettre la vidéo en pause figerait le dernier chiffre à l'écran —
 * « 25 img/s » sur une vidéo immobile, ce qui est faux et se lit comme un compteur
 * bloqué.
 */
const IDLE_MS = 1500;

interface PlaybackFpsBadgeProps {
  /**
   * La balise à mesurer, `null` avant son montage.
   *
   * La **référence** et non l'élément : remplir un `ref` ne déclenche aucun rendu,
   * donc lire `ref.current` au rendu ferait dépendre l'abonnement d'un rendu
   * ultérieur que rien ne garantit.
   */
  videoRef: React.RefObject<HTMLVideoElement | null>;
}

export function PlaybackFpsBadge({ videoRef }: PlaybackFpsBadgeProps) {
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  useEffect(() => setVideo(videoRef.current), [videoRef]);

  const [fps, setFps] = useState<number | null>(null);

  useEffect(() => {
    const element = video;
    // `requestVideoFrameCallback` est le **seul** moyen de compter les images
    // réellement composées : un `requestAnimationFrame` mesurerait la cadence de
    // l'écran (60 Hz), pas celle de la vidéo (25).
    //
    // Le test d'existence est indispensable malgré le typage : `lib.dom` déclare la
    // méthode comme présente sur tout `HTMLVideoElement`, alors que Firefox ne
    // l'implémente pas. Sans lui, la pilule planterait au lieu de s'abstenir.
    if (element === null || typeof element.requestVideoFrameCallback !== "function") return;

    let handle = 0;
    let frames = 0;
    let windowStart = 0;
    let idleTimer: ReturnType<typeof setTimeout> | undefined;

    const onFrame = (now: number): void => {
      if (windowStart === 0) windowStart = now;
      frames += 1;
      const elapsed = now - windowStart;
      if (elapsed >= WINDOW_MS) {
        setFps((frames / elapsed) * 1000);
        frames = 0;
        windowStart = now;
      }
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => setFps(null), IDLE_MS);
      handle = element.requestVideoFrameCallback(onFrame);
    };

    handle = element.requestVideoFrameCallback(onFrame);
    return () => {
      clearTimeout(idleTimer);
      element.cancelVideoFrameCallback(handle);
    };
  }, [video]);

  if (fps === null) return null;

  return (
    <p className="rounded-badge bg-base/80 px-2 py-1 text-micro text-ink-muted tabular">
      {fps.toFixed(1)} img/s
    </p>
  );
}
