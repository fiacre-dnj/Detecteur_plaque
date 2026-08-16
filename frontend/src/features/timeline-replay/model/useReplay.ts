/**
 * Le suivi de la tête de lecture, par `requestAnimationFrame`.
 *
 * **Pas par `timeupdate`.** Cet événement ne se déclenche que ~4 fois par seconde
 * selon la spécification HTML, et les navigateurs s'en tiennent à ce minimum. Les
 * boîtes traîneraient donc visiblement derrière les véhicules — un décalage de 250
 * ms est parfaitement perceptible, et il donne l'impression que la détection est
 * mauvaise alors que c'est l'affichage qui est en retard.
 *
 * `requestAnimationFrame` se cale sur le rafraîchissement de l'écran et s'arrête de
 * lui-même quand l'onglet passe en arrière-plan — exactement le comportement voulu.
 *
 * **Un résultat fraîchement reçu s'affiche avant toute relecture** : `timeMs` part
 * de la fin du résultat, pas de zéro. Sans cela, l'écran resterait vide sur une
 * analyse pourtant terminée, et l'utilisateur croirait qu'elle a échoué.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import type { AnalysisResult } from "@/shared/api/contracts";

import { frameIndexAt, statsAt, trailsAt } from "./replay";

export interface ReplayState {
  /** Position de relecture, en millisecondes de **temps de scène**. */
  timeMs: number;
  /** Index de la frame affichée, `-1` avant la première. */
  frameIndex: number;
}

/**
 * Suit la position d'un élément vidéo et rend ce qu'il faut dessiner à cet instant.
 *
 * @param videoRef La **référence** vers la balise suivie.
 * @param result Le résultat à relire, ou `null` (aucune analyse).
 *
 * **Une référence et non l'élément.** Le hook recevait `videoRef.current`, lu au
 * rendu. Cela fonctionnait — mais par ricochet : remplir un `ref` ne déclenche aucun
 * rendu, donc l'abonnement dépendait d'un rendu ultérieur provoqué par autre chose,
 * en l'occurrence le `setScene` de `loadedmetadata`. Le jour où ce rendu-là
 * disparaît ou change d'ordre, l'effet reste abonné à `null` et ses dépendances
 * `[video, result]` ne bougeant plus, il ne se réabonne jamais.
 *
 * Le mode de panne serait silencieux, ce qui justifie de ne pas s'en remettre au
 * hasard : `timeMs` resterait figé sur sa valeur initiale — la fin du résultat —
 * donc l'écran afficherait les **chiffres finaux, corrects**, et immobiles. Déplacer
 * la vidéo ne changerait aucun compteur, aucune boîte, aucune mise en évidence. Un
 * écran juste et inerte se lit comme « la relecture n'est pas implémentée », jamais
 * comme un abonnement raté.
 *
 * `TransportBar` documente longuement le même piège ; c'est son patron qui est
 * repris ici — un état rempli par un effet de montage, quand la balise existe
 * forcément.
 *
 * **Note pour qui déboguera la relecture** : `requestAnimationFrame` ne se déclenche
 * pas dans un onglet caché (`document.hidden`). Une page pilotée sans être affichée
 * — un navigateur sans tête, un panneau replié — voit donc les compteurs rester
 * figés alors que `video.currentTime` avance, et le suivi paraît cassé sans l'être.
 * `timeupdate` continue, lui, de se déclencher : c'est pourquoi la barre de
 * transport, qui l'écoute, reste juste dans ces conditions.
 */
export function useReplay(
  videoRef: React.RefObject<HTMLVideoElement | null>,
  result: AnalysisResult | null,
) {
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  useEffect(() => setVideo(videoRef.current), [videoRef]);

  /**
   * Position initiale : **la fin du résultat**.
   *
   * C'est ce qui fait qu'une analyse terminée affiche immédiatement ses chiffres
   * finaux, au lieu d'un écran vide en attendant que l'utilisateur relise.
   */
  const [timeMs, setTimeMs] = useState(0);

  useEffect(() => {
    setTimeMs(result === null ? 0 : result.video.durationMs);
  }, [result]);

  /** Dernière valeur poussée, pour éviter un rendu par frame identique. */
  const lastPushed = useRef(-1);

  useEffect(() => {
    if (video === null || result === null) return;

    let frame = 0;
    const tick = (): void => {
      // **Ne suivre que si la balise porte réellement un média.**
      //
      // `VideoScene` monte son `<video>` en permanence, même sans source : la
      // référence n'est donc jamais nulle, et un `currentTime` de 0 sur une balise
      // vide se lisait comme « la tête de lecture est au début ». Conséquence
      // exacte, sur une analyse rouverte depuis l'historique dont la vidéo n'a pas
      // été redéposée : `statsAt(result, 0)` écrasait par des zéros la position de
      // fin posée juste au-dessus, et l'écran affichait 0 véhicule, 0 franchissement
      // sur un résultat parfaitement intact. Le symptôme se lit comme une analyse
      // vide, jamais comme un défaut de repère temporel.
      //
      // `duration` est le bon signal : `NaN` sans média, `0` sur un flux caméra.
      // `readyState` ne suffirait pas — il repasse à 0 pendant un changement de
      // source, ce qui ferait clignoter les compteurs.
      if (!Number.isFinite(video.duration) || video.duration <= 0) {
        frame = requestAnimationFrame(tick);
        return;
      }
      const nextMs = video.currentTime * 1000;
      // Seuil d'un dixième de milliseconde : sans lui, le bruit en virgule
      // flottante provoquerait un rendu à chaque image même sur une vidéo en pause.
      if (Math.abs(nextMs - lastPushed.current) > 0.1) {
        lastPushed.current = nextMs;
        setTimeMs(nextMs);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [video, result]);

  const frameIndex = useMemo(
    () => (result === null ? -1 : frameIndexAt(result.timeline, timeMs)),
    [result, timeMs],
  );

  /**
   * Les pistes, trajectoires et statistiques de l'instant.
   *
   * `useMemo` sur `frameIndex` et non sur `timeMs` : entre deux frames de la
   * timeline, `timeMs` change soixante fois par seconde alors que le contenu à
   * dessiner est identique. Mémoïser sur l'index évite donc ~59 recalculs par
   * frame — y compris le rejeu des événements de `statsAt`.
   */
  const tracks = useMemo(() => {
    if (result === null || frameIndex < 0) return [];
    return result.timeline[frameIndex]?.tracks ?? [];
  }, [result, frameIndex]);

  const trails = useMemo(
    () => (result === null ? new Map() : trailsAt(result.timeline, frameIndex)),
    [result, frameIndex],
  );

  /**
   * Horodatage de la frame affichée — et non la position exacte du curseur.
   *
   * C'est la clé qui rend le calcul des statistiques honnête **et** économe. Les
   * statistiques sont calculées au temps de la frame visible : l'image et les
   * chiffres décrivent alors exactement le même instant. Utiliser la position
   * exacte ferait recalculer le rejeu des événements soixante fois par seconde
   * pour un résultat qui ne change qu'à chaque frame — deux ordres de grandeur de
   * calcul gaspillés — et pourrait afficher un franchissement dont le véhicule
   * n'est pas encore visible.
   */
  const frameTimeMs = useMemo(() => {
    if (result === null || frameIndex < 0) return 0;
    return result.timeline[frameIndex]?.timestampMs ?? 0;
  }, [result, frameIndex]);

  const stats = useMemo(
    () => (result === null ? null : statsAt(result, frameTimeMs)),
    [result, frameTimeMs],
  );

  return { timeMs, frameIndex, tracks, trails, stats };
}
