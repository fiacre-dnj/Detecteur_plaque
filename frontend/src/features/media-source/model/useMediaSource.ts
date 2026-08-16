/**
 * La source à analyser : fichier, clip de démonstration, ou caméra.
 *
 * Ce module gère la **source** : quel flux ou quel fichier est sélectionné, et la
 * libération de ce qui doit l'être. Il ne touche jamais à l'élément `<video>`,
 * qu'il ne connaît pas.
 *
 * **Où vit la prévention du piège 36.** La spécification HTML impose que, tant que
 * `video.srcObject` est posé, `video.src` soit **ignoré** : après une session
 * caméra, charger un fichier ne fait rien du tout — pas d'image, et aucun événement
 * `error` pour le signaler. La remise à `null` de `srcObject` doit donc avoir lieu
 * sur l'élément lui-même, et c'est **`VideoScene`** qui le fait, pas `stop()`
 * ci-dessous : ce hook n'a aucune référence vers le `<video>`. Chercher la
 * protection ici serait perdre son temps — elle est dans
 * `features/media-source/ui/VideoScene.tsx`.
 *
 * Ce que `stop()` fait, et qui lui appartient réellement :
 *
 * - **couper les pistes de la caméra.** Sans cela le voyant reste allumé, ce que
 *   l'utilisateur interprète — à raison — comme une caméra qui espionne ;
 * - **libérer l'URL `blob:`** du fichier précédent. Chaque `createObjectURL`
 *   retient le fichier entier en mémoire jusqu'à sa révocation ; quelques vidéos
 *   de 500 Mo enchaînées suffisent à faire tomber l'onglet.
 */

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * D'où vient l'image affichée.
 *
 * `archived` est une vidéo **resservie par le serveur**, celle d'une analyse
 * rouverte depuis l'historique. Distincte de `file` bien que les deux affichent une
 * vidéo : elle n'a pas de `File`, donc elle ne peut pas être renvoyée pour une
 * nouvelle analyse. Les confondre ferait proposer « Lancer l'analyse » sur une source
 * que `POST /jobs` ne peut pas recevoir.
 */
export type SourceKind = "file" | "demo" | "camera" | "archived";

export interface MediaSource {
  kind: SourceKind;
  /** URL à poser sur `video.src` — absente pour la caméra, qui passe par `srcObject`. */
  url?: string;
  /** Flux de la caméra — posé sur `srcObject`, jamais sur `src`. */
  stream?: MediaStream;
  /** Nom affiché, et nom du fichier envoyé au serveur. */
  label: string;
  /** Le fichier lui-même, requis pour `POST /jobs`. La caméra n'en a pas. */
  file?: File;
}

/** Chemin du clip de démonstration, servi depuis `public/`. */
export const DEMO_VIDEO_URL = "/demo/traffic.mp4";

/**
 * Message d'absence du clip de démo — il **dit où le déposer**.
 *
 * Un « échec de chargement » laisserait l'utilisateur sans recours ; le chemin
 * exact lui permet d'agir.
 */
export const DEMO_MISSING_MESSAGE =
  "La vidéo de démonstration est absente. Déposez un fichier MP4 dans " +
  "« frontend/public/demo/traffic.mp4 », ou choisissez un fichier depuis votre disque.";

/** Extensions acceptées — les mêmes que celles du serveur, qui refuse les autres. */
export const ACCEPTED_EXTENSIONS = [".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"] as const;

export const ACCEPT_ATTRIBUTE = ACCEPTED_EXTENSIONS.join(",");

/** Résolution demandée à la caméra. Le navigateur peut en rendre une autre. */
const CAMERA_CONSTRAINTS: MediaStreamConstraints = {
  video: { width: 1280, height: 720 },
  audio: false,
};

export interface UseMediaSourceResult {
  source: MediaSource | null;
  error: string | null;
  /** Vrai pendant la demande d'autorisation caméra, qui peut durer. */
  requestingCamera: boolean;
  selectFile: (file: File) => void;
  selectDemo: () => void;
  selectCamera: () => Promise<void>;
  /**
   * Affiche la vidéo d'une analyse archivée, servie par le serveur.
   *
   * Pas de `File` et pas d'`URL.createObjectURL` : la vidéo reste sur le serveur et
   * le navigateur la lit par plages. C'est ce qui rend le déplacement dans la
   * timeline praticable sans retélécharger des centaines de mégaoctets.
   */
  selectArchived: (url: string, label: string) => void;
  clear: () => void;
}

/**
 * Gère la source courante et **tout son nettoyage**.
 *
 * Le nettoyage est centralisé dans `stop()` plutôt que réparti dans chaque
 * sélecteur : c'est la seule façon de garantir qu'il a lieu à chaque changement
 * de source, y compris ceux ajoutés plus tard.
 */
export function useMediaSource(): UseMediaSourceResult {
  const [source, setSource] = useState<MediaSource | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requestingCamera, setRequestingCamera] = useState(false);

  /**
   * Ressources à libérer, gardées dans un `ref`.
   *
   * Un `ref` et non un state : `stop()` est appelé depuis des callbacks stables
   * et depuis le démontage, où lire un state donnerait la valeur capturée à la
   * création de la closure — donc l'ancienne, donc la mauvaise à libérer.
   */
  const objectUrl = useRef<string | null>(null);
  const stream = useRef<MediaStream | null>(null);

  const stop = useCallback(() => {
    // 1. Couper les pistes. Sans cela le voyant de la webcam reste allumé, ce
    //    que l'utilisateur interprète — à raison — comme une caméra qui espionne.
    if (stream.current !== null) {
      for (const track of stream.current.getTracks()) track.stop();
      stream.current = null;
    }

    // 2. Révoquer l'URL blob. Chaque `createObjectURL` retient le fichier entier
    //    en mémoire jusqu'ici.
    if (objectUrl.current !== null) {
      URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = null;
    }
  }, []);

  // Démontage : les mêmes libérations. Sans cela, quitter la page en pleine
  // session caméra laisse le voyant allumé jusqu'à la fermeture de l'onglet.
  useEffect(() => stop, [stop]);

  const selectFile = useCallback(
    (file: File) => {
      stop();
      setError(null);
      const url = URL.createObjectURL(file);
      objectUrl.current = url;
      setSource({ kind: "file", url, label: file.name, file });
    },
    [stop],
  );

  const selectDemo = useCallback(() => {
    stop();
    setError(null);
    // Pas de vérification préalable de l'existence du fichier : une requête
    // `HEAD` doublerait le temps de chargement pour un cas rare. L'absence est
    // rapportée par l'événement `error` de la vidéo, que le lecteur relaie.
    setSource({ kind: "demo", url: DEMO_VIDEO_URL, label: "Vidéo de démonstration" });
  }, [stop]);

  const selectArchived = useCallback(
    (url: string, label: string) => {
      stop();
      setError(null);
      // Aucun `objectUrl.current` à retenir : l'URL pointe le serveur, il n'y a
      // rien à révoquer. La poser ici ferait révoquer une URL qui n'est pas un blob,
      // ce qui est sans effet mais ment sur ce que le nettoyage a à faire.
      setSource({ kind: "archived", url, label });
    },
    [stop],
  );

  const selectCamera = useCallback(async () => {
    stop();
    setError(null);
    setRequestingCamera(true);
    try {
      const media = await navigator.mediaDevices.getUserMedia(CAMERA_CONSTRAINTS);
      stream.current = media;
      setSource({ kind: "camera", stream: media, label: "Caméra" });
    } catch (cause) {
      setSource(null);
      setError(cameraErrorMessage(cause));
    } finally {
      setRequestingCamera(false);
    }
  }, [stop]);

  const clear = useCallback(() => {
    stop();
    setSource(null);
    setError(null);
  }, [stop]);

  return {
    source,
    error,
    requestingCamera,
    selectFile,
    selectDemo,
    selectCamera,
    selectArchived,
    clear,
  };
}

/**
 * Traduit un refus de `getUserMedia` en message qui dit **quoi faire**.
 *
 * Les noms d'erreur du navigateur (`NotAllowedError`…) sont normalisés mais
 * imprononçables pour un utilisateur. Chaque cas a une action différente : ouvrir
 * les réglages du navigateur, brancher une caméra, ou fermer l'application qui la
 * retient.
 */
export function cameraErrorMessage(cause: unknown): string {
  const name = cause instanceof Error ? cause.name : "";

  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return (
        "L'accès à la caméra a été refusé. Autorisez-le dans les réglages du " +
        "navigateur pour ce site, puis réessayez."
      );
    case "NotFoundError":
    case "OverconstrainedError":
      return "Aucune caméra n'a été trouvée sur cet appareil.";
    case "NotReadableError":
      return (
        "La caméra est déjà utilisée par une autre application. Fermez-la, puis " +
        "réessayez."
      );
    default:
      return "La caméra n'a pas pu être démarrée sur cet appareil.";
  }
}

/**
 * Le fichier a-t-il une extension que le serveur accepte ?
 *
 * Sur l'extension et non sur le `type` MIME : celui que le navigateur devine est
 * souvent vide pour un `.mkv`, et refuser un fichier valide est plus agaçant que
 * de laisser le serveur trancher. La validation réelle est son `probe()`.
 */
export function hasAcceptedExtension(name: string): boolean {
  const lower = name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((extension) => lower.endsWith(extension));
}
