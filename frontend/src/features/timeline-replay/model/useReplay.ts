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
 * @param video L'élément dont on suit la position, ou `null`.
 * @param result Le résultat à relire, ou `null` (aucune analyse).
 */
export function useReplay(video: HTMLVideoElement | null, result: AnalysisResult | null) {
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
