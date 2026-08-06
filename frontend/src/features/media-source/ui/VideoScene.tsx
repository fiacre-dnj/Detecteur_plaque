/**
 * La scène : l'élément `<video>` et le canvas en superposition.
 *
 * **Le piège 36 est appliqué ici**, et c'est le seul endroit où les deux modes de
 * source se rencontrent. La spécification HTML impose que `video.src` soit
 * **ignoré** tant que `video.srcObject` est posé. Conséquence mesurée : après une
 * session caméra, charger un fichier ne produit rien — pas d'image, et **aucun
 * événement `error`** pour le dire. On cherche alors le bug dans le décodage du
 * fichier, très loin de la cause.
 *
 * La prévention tient en une règle appliquée sans exception : à chaque changement
 * de source, on remet **les deux** attributs, dans le bon ordre — `srcObject` à
 * `null` avant de poser `src`, et `removeAttribute("src")` avant de poser
 * `srcObject`. Poser l'un sans neutraliser l'autre est exactement le bug.
 *
 * `muted` et `playsInline` sont obligatoires : sans `muted`, la lecture
 * automatique est refusée par tous les navigateurs ; sans `playsInline`, iOS passe
 * la vidéo en plein écran et le canvas disparaît.
 *
 * **Jamais `loop`** : un clip qui repart en silence donnerait les mêmes véhicules
 * à compter une seconde fois, et les compteurs doubleraient sans explication.
 */

import { useEffect, useRef } from "react";

import type { MediaSource } from "../model/useMediaSource";

interface VideoSceneProps {
  source: MediaSource | null;
  /** Appelé quand les dimensions réelles sont connues — elles ancrent la géométrie. */
  onMetadata: (size: { width: number; height: number }) => void;
  /** Superposition : le canvas d'édition, et le HUD. */
  children?: React.ReactNode;
  /** Reçoit l'élément, pour que le transport s'y branche. */
  videoRef: React.RefObject<HTMLVideoElement | null>;
}

export function VideoScene({ source, onMetadata, children, videoRef }: VideoSceneProps) {
  /** `onMetadata` dans un `ref` : sinon changer la callback réabonne l'écouteur. */
  const metadataCallback = useRef(onMetadata);
  metadataCallback.current = onMetadata;

  /**
   * Applique la source à l'élément — **le cœur de la prévention du piège 36**.
   *
   * Un `useEffect` et non des attributs JSX : React ne sait pas poser `srcObject`
   * (ce n'est pas un attribut HTML mais une propriété), et l'ordre des opérations
   * compte ici plus que leur valeur finale.
   */
  useEffect(() => {
    const video = videoRef.current;
    if (video === null) return;

    if (source === null) {
      video.srcObject = null;
      video.removeAttribute("src");
      // `load()` vide le tampon interne : sans lui, la dernière image de la vidéo
      // précédente reste affichée sous un canvas désormais vide.
      video.load();
      return;
    }

    if (source.stream !== undefined) {
      // Flux caméra : on **retire `src`** avant de poser `srcObject`, sinon les
      // deux coexistent et le comportement dépend du navigateur.
      video.removeAttribute("src");
      video.srcObject = source.stream;
      void video.play().catch(() => undefined);
      return;
    }

    if (source.url !== undefined) {
      // Fichier ou démo : **`srcObject = null` d'abord**. C'est cette ligne qui
      // évite le « le fichier suivant ne se charge jamais ».
      video.srcObject = null;
      video.src = source.url;
      video.load();
    }
  }, [source, videoRef]);

  useEffect(() => {
    const video = videoRef.current;
    if (video === null) return;

    const handleMetadata = (): void => {
      // Les dimensions **réelles** de la source, pas celles demandées : la caméra
      // peut rendre autre chose que le 1280×720 souhaité, et toute la géométrie
      // s'ancre sur ce que l'on a effectivement reçu.
      metadataCallback.current({ width: video.videoWidth, height: video.videoHeight });
    };

    video.addEventListener("loadedmetadata", handleMetadata);
    // La caméra peut connaître ses dimensions après `loadedmetadata`.
    video.addEventListener("resize", handleMetadata);
    return () => {
      video.removeEventListener("loadedmetadata", handleMetadata);
      video.removeEventListener("resize", handleMetadata);
    };
  }, [videoRef]);

  return (
    <section
      aria-label="Scène"
      className="relative aspect-video overflow-hidden rounded-section bg-surface shadow-card"
    >
      <video
        ref={videoRef}
        muted
        playsInline
        preload="metadata"
        // Ni `controls` (la barre native recouvre la zone de tracé) ni `loop`
        // (les compteurs doubleraient).
        className="size-full object-contain"
      />
      {source === null ? (
        <p className="absolute inset-0 grid place-items-center p-6 text-center text-caption text-ink-dim">
          Choisissez une source pour afficher la scène et tracer vos lignes de
          comptage.
        </p>
      ) : (
        children
      )}
    </section>
  );
}
