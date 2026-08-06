/**
 * La session de comptage en direct : WebSocket, capture, cadence, contrôle croisé.
 *
 * Ce hook ne contient **aucune** règle testable : la mise à l'échelle vit dans
 * `scale.ts`, la cadence dans `pacing.ts`, l'interprétation des fermetures dans
 * `connection.ts`, la capture dans `capture.ts`. Ce qui reste ici est du câblage et
 * de la gestion de cycle de vie — la partie qu'un test unitaire ne prouve pas et
 * qu'un `jsdom` simulerait mal, donc autant qu'elle soit courte et que tout le reste
 * soit ailleurs.
 *
 * **Le refus de compter en cas de désaccord de dimensions** est la décision de
 * conception la plus importante du fichier. Quand le serveur annonce des dimensions
 * différentes de celles qu'on croit envoyer, on ferme et on explique — on ne compte
 * pas « en attendant de comprendre ». Des chiffres faux qu'on affiche valent moins
 * que pas de chiffres du tout : le premier cas induit une décision erronée, le second
 * envoie chercher la cause.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type {
  AnalysisRequest,
  AnalysisStats,
  CrossingEvent,
  FrameResultMessage,
  ReadyMessage,
  ServerMessage,
  TrackSnapshot,
} from "@/shared/api/contracts";

import { createCaptureSurface, captureJpeg, hasFrame, type CaptureSurface } from "./capture";
import { closeVerdict, realtimeUrl } from "./connection";
import { EMPTY_PACING, FramePacer, sceneTimeMs, type PacingStats } from "./pacing";
import {
  dimensionMismatchMessage,
  dimensionsAgree,
  scaleFactor,
  scaleRequestGeometry,
  scaledSize,
} from "./scale";

/** État visible d'une session. */
export type RealtimeStatus =
  | "idle"
  /** WebSocket ouvert, `init` envoyé, `ready` pas encore reçu. */
  | "connecting"
  | "counting"
  | "stopped"
  | "error";

export interface RealtimeSessionState {
  status: RealtimeStatus;
  /** Message d'erreur ou de fin, en français. `null` quand il n'y a rien à dire. */
  message: string | null;
  /** Réessayer a-t-il un sens ? Décide de l'affichage du bouton. */
  retryable: boolean;
  /** Pistes de la dernière frame, **remises à l'échelle source** pour le dessin. */
  tracks: readonly TrackSnapshot[];
  /** Franchissements cumulés depuis le début de la session. */
  crossings: readonly CrossingEvent[];
  /**
   * Franchissements de la **dernière image seulement**.
   *
   * Distinct du cumul, et pas par commodité : ce qui vient de se produire est ce
   * qui doit clignoter à l'écran. Faire clignoter le cumul rallumerait toutes les
   * lignes à chaque image, et le signal ne voudrait plus rien dire.
   */
  lastCrossings: readonly CrossingEvent[];
  stats: AnalysisStats | null;
  pacing: PacingStats;
  /** Modèle et device **réellement** utilisés, tels que `ready` les a annoncés. */
  ready: ReadyMessage | null;
}

const IDLE: RealtimeSessionState = {
  status: "idle",
  message: null,
  retryable: false,
  tracks: [],
  crossings: [],
  lastCrossings: [],
  stats: null,
  pacing: EMPTY_PACING,
  ready: null,
};

export interface UseRealtimeSessionResult extends RealtimeSessionState {
  active: boolean;
  /** Le facteur d'envoi courant — l'interface l'affiche, c'est un chiffre qui rassure. */
  factor: number;
  start: (request: AnalysisRequest) => void;
  stop: () => void;
}

/**
 * Ouvre et pilote une session de comptage en direct sur l'élément vidéo donné.
 *
 * `video` est lu depuis un `ref` **à chaque tour de boucle** et non capturé : le
 * `<video>` peut être remonté par React pendant une session, et une référence
 * capturée pointerait alors un élément détaché dont `drawImage` peint du noir.
 */
export function useRealtimeSession(
  video: HTMLVideoElement | null,
): UseRealtimeSessionResult {
  const [state, setState] = useState<RealtimeSessionState>(IDLE);
  const [factor, setFactor] = useState(1);

  /**
   * Tout ce que la boucle manipule vit dans des `ref`.
   *
   * Un `state` serait relu à sa valeur capturée par la closure de l'animation frame,
   * donc périmé d'un tour — et pour la socket, cela signifierait envoyer sur une
   * connexion déjà fermée. Le `state` ne sert qu'à ce que React affiche.
   */
  const socket = useRef<WebSocket | null>(null);
  const surface = useRef<CaptureSurface | null>(null);
  const pacer = useRef(new FramePacer());
  const frameHandle = useRef<number | null>(null);
  const videoRef = useRef(video);
  const startedAt = useRef(0);
  const sendSize = useRef({ width: 0, height: 0 });
  const sendFactor = useRef(1);
  /** Vrai entre le `ready` et l'arrêt : la seule condition d'envoi d'une frame. */
  const counting = useRef(false);
  /** Franchissements accumulés — un `ref` parce que la boucle les concatène. */
  const crossings = useRef<CrossingEvent[]>([]);

  videoRef.current = video;

  /**
   * Arrête tout, dans l'ordre.
   *
   * L'ordre compte : couper la boucle **avant** de fermer la socket, sinon le tour
   * en cours envoie sur une connexion fermée et le navigateur lève. Et les deux
   * avant de toucher au `state`, pour qu'aucun rendu ne relance quoi que ce soit.
   */
  const teardown = useCallback(() => {
    counting.current = false;
    if (frameHandle.current !== null) {
      cancelAnimationFrame(frameHandle.current);
      frameHandle.current = null;
    }
    const open = socket.current;
    socket.current = null;
    if (open !== null) {
      // Les gestionnaires sont retirés avant la fermeture : sans cela notre propre
      // `close()` déclencherait `onclose`, qui écrirait un message de perte de
      // connexion alors que c'est l'utilisateur qui vient d'arrêter.
      open.onclose = null;
      open.onerror = null;
      open.onmessage = null;
      if (open.readyState === WebSocket.OPEN || open.readyState === WebSocket.CONNECTING) {
        open.close(1000, "Session arrêtée par l'utilisateur");
      }
    }
    pacer.current.reset();
  }, []);

  // Démontage : la même coupure. Sans cela, quitter la page laisse une session
  // active côté serveur, qui refuse la suivante en 1013 sans que rien ne l'explique.
  useEffect(() => teardown, [teardown]);

  const fail = useCallback(
    (message: string, retryable: boolean) => {
      teardown();
      setState((previous) => ({ ...previous, status: "error", message, retryable }));
    },
    [teardown],
  );

  /**
   * Un tour de boucle : capturer si le créneau est libre, sinon abandonner la frame.
   *
   * `requestAnimationFrame` et non `setInterval` : le navigateur suspend les
   * animation frames d'un onglet en arrière-plan, ce qui **est** le comportement
   * voulu — continuer à envoyer des images d'un onglet caché consommerait le serveur
   * pour un aperçu que personne ne regarde. Un `setInterval` continuerait, ralenti à
   * une cadence arbitraire, ce qui est le pire des deux mondes.
   */
  const tick = useCallback(() => {
    frameHandle.current = requestAnimationFrame(tick);

    const element = videoRef.current;
    const open = socket.current;
    if (!counting.current || element === null || open === null) return;
    if (open.readyState !== WebSocket.OPEN) return;
    if (!hasFrame(element)) return;

    const now = performance.now();
    if (!pacer.current.tryClaim(now)) {
      // Frame abandonnée. **Pas** mise en file : voir l'en-tête de `pacing.ts`.
      setState((previous) => ({ ...previous, pacing: pacer.current.snapshot() }));
      return;
    }

    const { width, height } = sendSize.current;
    const timestampMs = sceneTimeMs(startedAt.current, now);

    void (async () => {
      const active = surface.current;
      if (active === null) {
        pacer.current.abandon();
        return;
      }
      const blob = await captureJpeg(active, element, width, height);
      // La socket a pu se fermer pendant l'encodage — c'est asynchrone, et arrêter
      // le direct pendant un `toBlob` est un geste tout à fait normal.
      if (blob === null || socket.current === null || socket.current.readyState !== WebSocket.OPEN) {
        pacer.current.abandon();
        return;
      }
      // Les deux envois **collés** : le protocole exige l'annonce puis le binaire,
      // sans rien entre les deux. Un `await` intercalé laisserait une autre frame
      // s'insérer et le serveur associerait le mauvais JPEG au mauvais horodatage.
      socket.current.send(JSON.stringify({ type: "frame", timestampMs }));
      socket.current.send(await blob.arrayBuffer());
    })();
  }, []);

  const handleReady = useCallback(
    (message: ReadyMessage) => {
      // **Le contrôle croisé.** `frameWidth` est `null` ici — le serveur n'a pas
      // encore décodé d'image — donc `dimensionsAgree` passe. La vraie vérification
      // a lieu au premier `frameResult`, qui porte les dimensions réelles.
      counting.current = true;
      startedAt.current = performance.now();
      setState((previous) => ({
        ...previous,
        status: "counting",
        message: null,
        ready: message,
      }));
    },
    [],
  );

  const handleFrameResult = useCallback(
    (message: FrameResultMessage) => {
      pacer.current.complete(performance.now());

      // **Ici, et à chaque frame.** Répété plutôt que fait une seule fois : une
      // webcam peut renégocier sa résolution en cours de session, et la géométrie
      // envoyée à l'`init` deviendrait alors fausse sans que rien ne bouge à l'écran.
      const expected = sendSize.current;
      const reported = { width: message.frameWidth, height: message.frameHeight };
      if (!dimensionsAgree(expected, reported)) {
        fail(
          dimensionMismatchMessage(expected, reported),
          // Réessayer est légitime : la source a changé de résolution, relancer
          // renverra la géométrie à la bonne échelle.
          true,
        );
        return;
      }

      crossings.current = [...crossings.current, ...message.crossings];
      setState((previous) => ({
        ...previous,
        // Les boîtes restent en pixels **d'envoi** ici : le canvas reçoit le facteur
        // et fait la conversion au dessin, comme il le fait déjà pour la relecture.
        // Les redilater ici obligerait à le faire aussi pour les plaques et les
        // trajectoires, et un oubli passerait inaperçu.
        tracks: message.tracks,
        crossings: crossings.current,
        lastCrossings: message.crossings,
        stats: message.stats,
        pacing: pacer.current.snapshot(),
      }));
    },
    [fail],
  );

  const handleMessage = useCallback(
    (event: MessageEvent<string>) => {
      let message: ServerMessage;
      try {
        message = JSON.parse(event.data) as ServerMessage;
      } catch {
        // Un message illisible n'est pas fatal : le serveur en enverra d'autres.
        return;
      }

      switch (message.type) {
        case "ready":
          handleReady(message);
          return;
        case "frameResult":
          handleFrameResult(message);
          return;
        case "error":
          // Non fatal **par contrat** : une frame illisible est un incident normal.
          // Le créneau se libère sans compter d'envoi, et la session continue.
          pacer.current.abandon();
          setState((previous) => ({ ...previous, message: message.detail }));
          return;
      }
    },
    [handleReady, handleFrameResult],
  );

  const start = useCallback(
    (request: AnalysisRequest) => {
      const element = videoRef.current;
      if (element === null || !hasFrame(element)) {
        fail(
          "La caméra n'a pas encore produit d'image. Attendez l'aperçu, puis relancez.",
          true,
        );
        return;
      }

      teardown();
      crossings.current = [];

      if (surface.current === null) surface.current = createCaptureSurface();
      if (surface.current === null) {
        fail("Ce navigateur ne fournit pas de contexte 2D : le direct est impossible.", false);
        return;
      }

      // **La mise à l'échelle, ici et une seule fois.** Le facteur est figé pour la
      // session : le recalculer par frame ferait dériver la géométrie envoyée à
      // l'`init` de celle que le serveur applique.
      const computed = scaleFactor(element.videoWidth);
      const size = scaledSize(element.videoWidth, element.videoHeight, computed);
      sendFactor.current = computed;
      sendSize.current = size;
      setFactor(computed);

      const connection = new WebSocket(realtimeUrl(window.location));
      // Sans cela, `event.data` d'une frame binaire serait un `Blob` : on n'en reçoit
      // aucune du serveur aujourd'hui, mais l'oubli est le classique de ce protocole.
      connection.binaryType = "arraybuffer";
      socket.current = connection;

      setState({ ...IDLE, status: "connecting", pacing: EMPTY_PACING });

      connection.onopen = () => {
        connection.send(
          JSON.stringify({
            type: "init",
            request: scaleRequestGeometry(request, computed),
          }),
        );
      };

      connection.onmessage = handleMessage as (event: MessageEvent) => void;

      connection.onclose = (event) => {
        const verdict = closeVerdict(event.code, event.reason);
        counting.current = false;
        if (frameHandle.current !== null) {
          cancelAnimationFrame(frameHandle.current);
          frameHandle.current = null;
        }
        socket.current = null;
        setState((previous) => ({
          ...previous,
          // Un 1000 est une fin propre : `stopped`, pas `error`. Peindre en rouge une
          // fin normale apprend à ignorer le rouge.
          status: event.code === 1000 ? "stopped" : "error",
          message: verdict.message,
          retryable: verdict.retryable,
        }));
      };

      // `onerror` ne porte aucun détail exploitable par contrat — le navigateur les
      // cache pour ne pas divulguer d'information réseau. `onclose` suit toujours, et
      // c'est lui qui porte le code : on ne fait donc rien ici, volontairement.
      connection.onerror = () => {};

      if (frameHandle.current === null) frameHandle.current = requestAnimationFrame(tick);
    },
    [fail, teardown, handleMessage, tick],
  );

  const stop = useCallback(() => {
    teardown();
    setState((previous) => ({
      ...previous,
      status: "stopped",
      message: null,
      retryable: false,
      // Les compteurs de la session sont **conservés** : l'utilisateur vient
      // d'arrêter pour lire ses chiffres, les effacer serait le contraire de ce
      // qu'il demande.
    }));
  }, [teardown]);

  return {
    ...state,
    active: state.status === "connecting" || state.status === "counting",
    factor: sendFactor.current === 0 ? factor : sendFactor.current,
    start,
    stop,
  };
}
