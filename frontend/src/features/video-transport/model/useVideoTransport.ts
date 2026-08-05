/**
 * L'état de lecture, **miroité localement** depuis les événements média.
 *
 * Pourquoi un miroir plutôt que de lire `video.currentTime` à la demande : la
 * position doit se rafraîchir ~60 fois par seconde pour que la timeline soit
 * fluide. Si cette valeur vivait dans le state du studio, chaque image
 * re-rendrait le studio **et le canvas avec lui**, ce qui rendrait l'édition de
 * géométrie saccadée pendant la lecture. Elle vit donc dans ce hook, que seul le
 * composant de transport consomme.
 *
 * Trois obligations de la spécification, chacune correspondant à un bug visible :
 *
 * 1. **Réappliquer `playbackRate` sur `loadedmetadata`.** Le navigateur le remet à
 *    1 à chaque nouvelle source : sans cela, choisir 0,25× puis changer de vidéo
 *    repart à vitesse normale alors que le sélecteur affiche encore 0,25×.
 * 2. **Écouter `ended`.** Un clip qui se termine émet `ended`, **pas** `pause` :
 *    sans cet écouteur le bouton reste bloqué sur « Pause » à la fin de la vidéo.
 * 3. **Jamais `loop`.** Un clip qui repart en silence donnerait les mêmes
 *    véhicules à compter une seconde fois, et les compteurs doubleraient sans que
 *    rien ne l'explique.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { FRAME_STEP_S } from "./formatTime";

export interface TransportState {
  playing: boolean;
  currentTime: number;
  duration: number;
  rate: number;
  /** Erreur de chargement du média, en français. */
  error: string | null;
}

export interface VideoTransport extends TransportState {
  play: () => void;
  pause: () => void;
  toggle: () => void;
  seek: (seconds: number) => void;
  skip: (delta: number) => void;
  stepFrame: (direction: 1 | -1) => void;
  setRate: (rate: number) => void;
  /** Remet au début **sans** remettre les compteurs à zéro. */
  restart: () => void;
}

/**
 * Branche le transport sur un élément vidéo.
 *
 * @param video L'élément, ou `null` avant le montage / sans source.
 * @param onEnded Appelé à la fin de la lecture — le studio y affiche son bandeau.
 */
export function useVideoTransport(
  video: HTMLVideoElement | null,
  onEnded?: () => void,
): VideoTransport {
  const [state, setState] = useState<TransportState>({
    playing: false,
    currentTime: 0,
    duration: Number.NaN,
    rate: 1,
    error: null,
  });

  /**
   * Vitesse voulue, gardée dans un `ref`.
   *
   * Un `ref` parce que `loadedmetadata` doit la relire depuis un écouteur dont la
   * closure est créée une seule fois : lire le state y donnerait la valeur du
   * premier rendu, donc toujours 1, et la réapplication ne servirait à rien.
   */
  const wantedRate = useRef(1);

  /** `onEnded` dans un `ref` : sinon changer la callback réabonne tous les écouteurs. */
  const endedCallback = useRef(onEnded);
  endedCallback.current = onEnded;

  useEffect(() => {
    if (video === null) return;

    const syncTime = (): void => {
      setState((previous) => ({ ...previous, currentTime: video.currentTime }));
    };

    const handleLoadedMetadata = (): void => {
      // **L'obligation 1.** Le navigateur a remis `playbackRate` à 1 en chargeant
      // cette source ; on repose la valeur choisie par l'utilisateur.
      video.playbackRate = wantedRate.current;
      setState((previous) => ({
        ...previous,
        duration: video.duration,
        currentTime: video.currentTime,
        rate: wantedRate.current,
        error: null,
      }));
    };

    const handleEnded = (): void => {
      // **L'obligation 2.** Sans cet écouteur, `playing` resterait vrai et le
      // bouton afficherait « Pause » sur une vidéo terminée.
      setState((previous) => ({ ...previous, playing: false }));
      endedCallback.current?.();
    };

    const handleError = (): void => {
      setState((previous) => ({ ...previous, playing: false, error: mediaErrorMessage(video) }));
    };

    const handlePlay = (): void => setState((p) => ({ ...p, playing: true }));
    const handlePause = (): void => setState((p) => ({ ...p, playing: false }));
    const handleRateChange = (): void => setState((p) => ({ ...p, rate: video.playbackRate }));
    const handleDurationChange = (): void =>
      setState((p) => ({ ...p, duration: video.duration }));

    video.addEventListener("loadedmetadata", handleLoadedMetadata);
    video.addEventListener("durationchange", handleDurationChange);
    video.addEventListener("timeupdate", syncTime);
    // `seeked` en plus de `timeupdate` : un déplacement pendant une pause n'émet
    // pas `timeupdate`, et la position affichée resterait sur l'ancienne valeur.
    video.addEventListener("seeked", syncTime);
    video.addEventListener("play", handlePlay);
    video.addEventListener("playing", handlePlay);
    video.addEventListener("pause", handlePause);
    video.addEventListener("ended", handleEnded);
    video.addEventListener("ratechange", handleRateChange);
    video.addEventListener("error", handleError);

    return () => {
      video.removeEventListener("loadedmetadata", handleLoadedMetadata);
      video.removeEventListener("durationchange", handleDurationChange);
      video.removeEventListener("timeupdate", syncTime);
      video.removeEventListener("seeked", syncTime);
      video.removeEventListener("play", handlePlay);
      video.removeEventListener("playing", handlePlay);
      video.removeEventListener("pause", handlePause);
      video.removeEventListener("ended", handleEnded);
      video.removeEventListener("ratechange", handleRateChange);
      video.removeEventListener("error", handleError);
    };
  }, [video]);

  /**
   * Suivi fin de la position par `requestAnimationFrame` pendant la lecture.
   *
   * `timeupdate` ne se déclenche que ~4 fois par seconde : une timeline qui
   * n'avance que quatre fois par seconde paraît cassée, et les boîtes de la
   * relecture traîneraient visiblement derrière les véhicules.
   */
  useEffect(() => {
    if (video === null || !state.playing) return;

    let frame = 0;
    const tick = (): void => {
      setState((previous) =>
        previous.currentTime === video.currentTime
          ? previous
          : { ...previous, currentTime: video.currentTime },
      );
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [video, state.playing]);

  const play = useCallback(() => {
    // La promesse de `play()` rejette si la lecture est interrompue (changement de
    // source, onglet en arrière-plan). Ce n'est pas une erreur à afficher.
    void video?.play().catch(() => undefined);
  }, [video]);

  const pause = useCallback(() => video?.pause(), [video]);

  const toggle = useCallback(() => {
    if (video === null) return;
    if (video.paused) play();
    else video.pause();
  }, [video, play]);

  const seek = useCallback(
    (seconds: number) => {
      if (video === null) return;
      const max = Number.isFinite(video.duration) ? video.duration : seconds;
      video.currentTime = Math.max(0, Math.min(max, seconds));
    },
    [video],
  );

  const skip = useCallback(
    (delta: number) => {
      if (video === null) return;
      seek(video.currentTime + delta);
    },
    [video, seek],
  );

  const stepFrame = useCallback(
    (direction: 1 | -1) => {
      if (video === null) return;
      // **Met en pause d'abord** : avancer d'une image pendant la lecture serait
      // aussitôt écrasé par le flux, et le bouton paraîtrait sans effet.
      video.pause();
      seek(video.currentTime + direction * FRAME_STEP_S);
    },
    [video, seek],
  );

  const setRate = useCallback(
    (rate: number) => {
      wantedRate.current = rate;
      if (video !== null) video.playbackRate = rate;
      setState((previous) => ({ ...previous, rate }));
    },
    [video],
  );

  const restart = useCallback(() => {
    seek(0);
    play();
  }, [seek, play]);

  return { ...state, play, pause, toggle, seek, skip, stepFrame, setRate, restart };
}

/**
 * Traduit un `MediaError` en message français qui distingue les causes.
 *
 * Le code compte : « format non supporté » demande de convertir le fichier,
 * « décodage » suggère un fichier corrompu, et « réseau » concerne surtout le clip
 * de démonstration absent. Les confondre envoie l'utilisateur au mauvais endroit.
 */
export function mediaErrorMessage(video: HTMLVideoElement): string {
  const code = video.error?.code;

  switch (code) {
    case MediaError.MEDIA_ERR_ABORTED:
      return "Le chargement de la vidéo a été interrompu.";
    case MediaError.MEDIA_ERR_NETWORK:
      return "La vidéo n'a pas pu être téléchargée. Vérifiez que le fichier existe.";
    case MediaError.MEDIA_ERR_DECODE:
      return "Cette vidéo n'a pas pu être décodée : le fichier est peut-être endommagé.";
    case MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED:
      return (
        "Ce format n'est pas lisible par ce navigateur. Convertissez le clip en " +
        "MP4 (H.264), ou essayez un autre fichier."
      );
    default:
      return "La vidéo n'a pas pu être chargée.";
  }
}
