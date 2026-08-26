/**
 * La vidéo locale suit l'analyse du serveur, et **les boîtes suivent la vidéo**.
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
 * ## Ce que ce module a cessé de faire, et pourquoi
 *
 * Il *demandait* un calage et considérait son travail fini. Or `currentTime = …`
 * ne fait que **demander** une image : le décodage et l'affichage arrivent des
 * dizaines à centaines de millisecondes plus tard, pendant que le canvas, lui,
 * peint au rendu React qui suit la trame SSE. L'overlay montrait donc la frame N
 * sur une image encore à la frame N−k — « le tracker est en avance sur le
 * véhicule ». Deux défauts rendaient la panne indétectable de l'intérieur :
 *
 * - le prédicat comparait `video.currentTime`, c'est-à-dire la cible **demandée**,
 *   jamais l'image **affichée**. Le retard ne pouvait donc ni se voir ni se
 *   rattraper ;
 * - l'écouteur `seeked` était réabonné à chaque aperçu — dix fois par seconde — et
 *   son nettoyage remettait la cible en attente à `null`. Un `seeked` tombé entre
 *   le nettoyage et le réabonnement la perdait.
 *
 * Ce module **rend désormais l'aperçu affichable** : il ne publie les boîtes de
 * l'aperçu *N* qu'au moment où le navigateur a **présenté** l'image *N*.
 * L'invariant devient vrai par construction — *les boîtes dessinées décrivent
 * l'image affichée* — quels que soient le bridage, la vitesse, une pause ou un
 * déplacement manuel du curseur.
 *
 * **La contrepartie redoutée est illusoire.** L'image, déjà aujourd'hui, ne change
 * qu'au rythme des calages aboutis : la balise ne peut pas afficher plus vite que
 * son décodeur. Ce qui change n'est pas la fréquence de l'image — inchangée — mais
 * celle des boîtes, qui cessent de courir devant. Elles se mettent à jour
 * *exactement aussi souvent que l'image*, ce qui est la définition de synchronisé.
 *
 * **Ce qui ne passe PAS par ce tampon** : les compteurs, le journal, la barre de
 * progression. La règle tient en une phrase, et `StudioPage` la répète sur place :
 * *les boîtes suivent l'image, les compteurs suivent le serveur.* Le badge ✓, lui,
 * voyage dans `track.counted` donc *avec* la boîte — il décrit un véhicule dessiné.
 *
 * **Écarté** : interpoler les boîtes vers l'image affichée. Ce serait fabriquer des
 * positions qu'aucune inférence n'a produites, sur une surface dont l'unique
 * fonction est de *valider* une inférence — même famille de refus que « lisser la
 * trajectoire du centroïde » dans ADR 0018.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { JobPreview } from "@/shared/api/contracts";

/**
 * Écart en dessous duquel l'image affichée est déjà la bonne.
 *
 * Une image à 25 images par seconde dure 40 ms : en dessous, la vidéo montre déjà
 * l'image analysée, et écrire `currentTime` ne ferait qu'un aller-retour du
 * décodeur — donc un scintillement, pour rien.
 *
 * **La valeur n'a pas changé, l'opérande si**, et c'était tout le défaut : elle
 * s'applique désormais à l'instant de l'image **présentée** et non à la cible
 * demandée. La réduire ne gagnerait rien — on cale de toute façon *exactement* sur
 * la cible — et provoquerait des calages inutiles.
 */
export const SEEK_TOLERANCE_MS = 40;

/**
 * Sans image présentée depuis ce délai, on promeut l'aperçu tel quel.
 *
 * Le chien de garde du seul vrai risque de gel : un calage qui n'aboutit jamais
 * (source exotique, GOP très long, onglet mis en veille par le navigateur). On rend
 * alors temporairement le comportement d'avant — des boîtes possiblement en avance
 * — plutôt qu'un écran figé, ce qui est le moindre mal et se voit au chiffre
 * « Écart image ».
 */
export const STALL_PROMOTE_MS = 700;

/** Ce que le tampon retient entre deux événements. Trois instants de scène. */
export interface SyncState {
  /** Instant de l'image **réellement présentée**, `null` avant la première. */
  shownMs: number | null;
  /** Cible du calage en cours, `null` si aucun n'est en vol. */
  inFlightMs: number | null;
  /**
   * **UN** emplacement d'attente, écrasé par la cible la plus récente — jamais une
   * file. C'est ce qui interdit structurellement l'accumulation de retard : si le
   * décodeur prend 300 ms là où les aperçus arrivent toutes les 100 ms, on saute
   * deux aperçus au lieu d'en rejouer trois avec un tour de retard.
   */
  pendingMs: number | null;
}

/** L'état d'un tampon qui n'a encore rien vu. */
export const IDLE_SYNC: SyncState = { shownMs: null, inFlightMs: null, pendingMs: null };

/**
 * Quel aperçu devient l'aperçu affiché, s'il y en a un.
 *
 * Un nom plutôt qu'un booléen : le réducteur ne raisonne que sur des instants,
 * c'est l'appelant qui tient les objets. Lui dire *lequel* promouvoir évite qu'il
 * ait à le redéduire — et qu'il se trompe.
 */
export type Promotion = "incoming" | "inFlight" | "pending" | null;

/** La décision : l'état suivant, le calage à émettre, l'aperçu à promouvoir. */
export interface SyncStep {
  state: SyncState;
  seekTo: number | null;
  promote: Promotion;
}

/**
 * Faut-il caler la vidéo ?
 *
 * `shownMs` est l'instant de l'image **AFFICHÉE**, et c'est tout le correctif :
 * comparer la cible demandée à elle-même ne pouvait jamais détecter un retard.
 * `null` — rien n'a encore été présenté — cale toujours.
 */
export function shouldSeek(
  shownMs: number | null,
  targetMs: number | null,
  toleranceMs: number = SEEK_TOLERANCE_MS,
): boolean {
  if (targetMs === null || !Number.isFinite(targetMs) || targetMs < 0) return false;
  if (shownMs === null) return true;
  return Math.abs(shownMs - targetMs) > toleranceMs;
}

/** Un aperçu vient d'arriver du serveur. */
export function onIncoming(
  state: SyncState,
  targetMs: number | null,
  toleranceMs: number = SEEK_TOLERANCE_MS,
): SyncStep {
  // Cible aberrante — un `NaN` s'obtient d'un JSON tronqué, et l'écrire dans
  // `currentTime` lève une exception qui casserait le rendu au lieu de sauter une
  // image. On ne promeut pas non plus : ces boîtes n'ont pas d'image connue.
  if (targetMs === null || !Number.isFinite(targetMs) || targetMs < 0) {
    return { state, seekTo: null, promote: null };
  }

  // L'image affichée est **déjà** celle que le serveur vient d'analyser : rien à
  // caler, et surtout il faut promouvoir tout de suite. Sans cette branche, un
  // aperçu tombant sur l'image courante ne serait jamais dessiné.
  if (!shouldSeek(state.shownMs, targetMs, toleranceMs)) {
    return { state, seekTo: null, promote: "incoming" };
  }

  if (state.inFlightMs === null) {
    return {
      state: { ...state, inFlightMs: targetMs, pendingMs: null },
      seekTo: targetMs,
      promote: null,
    };
  }

  // Un calage est déjà en vol : on écrase l'attente. En écrire un second
  // maintenant ferait bégayer le décodeur, et c'est la raison d'origine de ce
  // mécanisme.
  return { state: { ...state, pendingMs: targetMs }, seekTo: null, promote: null };
}

/**
 * Le navigateur vient de **présenter** une image.
 *
 * `presentedMs` vient de `requestVideoFrameCallback` (`mediaTime`, l'instant
 * réellement composé) ou, en repli, de `currentTime` au moment du `seeked`.
 *
 * Le calage en vol est considéré terminé **dans tous les cas** : l'opération a
 * rendu la main. On ne promeut que si l'image présentée est bien celle qu'on
 * attendait — l'utilisateur a pu déplacer le curseur à la main, et ses boîtes ne
 * sont alors les boîtes de personne. Le prochain aperçu recalera, donc le tampon
 * se répare seul.
 */
export function onPresented(
  state: SyncState,
  presentedMs: number,
  toleranceMs: number = SEEK_TOLERANCE_MS,
): SyncStep {
  const promote: Promotion =
    state.inFlightMs !== null && Math.abs(presentedMs - state.inFlightMs) <= toleranceMs
      ? "inFlight"
      : null;

  if (state.pendingMs !== null) {
    return {
      state: { shownMs: presentedMs, inFlightMs: state.pendingMs, pendingMs: null },
      seekTo: state.pendingMs,
      promote,
    };
  }
  return {
    state: { shownMs: presentedMs, inFlightMs: null, pendingMs: null },
    seekTo: null,
    promote,
  };
}

/**
 * Rien n'a été présenté depuis trop longtemps.
 *
 * On promeut la cible la plus récente et on **relance** le calage : mieux vaut des
 * boîtes en avance, comme avant ce module, qu'un overlay gelé. `shownMs` est posé
 * à la cible de façon optimiste — on affirme ce qu'on vient de décider d'afficher.
 */
export function onStall(state: SyncState): SyncStep {
  if (state.pendingMs !== null) {
    const target = state.pendingMs;
    return {
      state: { shownMs: target, inFlightMs: target, pendingMs: null },
      seekTo: target,
      promote: "pending",
    };
  }
  if (state.inFlightMs !== null) {
    const target = state.inFlightMs;
    return {
      state: { shownMs: target, inFlightMs: target, pendingMs: null },
      seekTo: target,
      promote: "inFlight",
    };
  }
  return { state, seekTo: null, promote: null };
}

/** Ce que le hook rend au studio. */
export interface SyncedPreview {
  /** L'aperçu dont les boîtes décrivent l'image actuellement affichée. */
  preview: JobPreview | null;
  /**
   * Écart mesuré entre l'image affichée et l'image analysée, en millisecondes.
   *
   * `null` quand on ne l'a pas mesuré — repli `seeked`, suivi désactivé, rien
   * encore présenté. On ne publie jamais un chiffre qu'on n'a pas.
   */
  displayLagMs: number | null;
}

/**
 * Cale la vidéo sur l'image analysée, et ne rend les boîtes qu'une fois l'image là.
 *
 * @param videoRef La **référence** à la balise, jamais l'élément : remplir un `ref`
 *   ne déclenche aucun rendu, donc lire `ref.current` au rendu ferait dépendre
 *   l'abonnement d'un rendu ultérieur que rien ne garantit — les premiers aperçus
 *   d'une analyse étaient perdus par ce chemin. Patron identique à
 *   `PlaybackFpsBadge` et `TransportBar`.
 * @param incoming L'aperçu vivant du serveur, `null` s'il n'y en a pas.
 * @param enabled Le suivi est-il demandé ? À `false` (caméra, pas de fichier local),
 *   ce hook est un **passe-plat** : il rend `incoming` inchangé et ne touche à rien.
 */
export function useSyncedPreview(
  videoRef: React.RefObject<HTMLVideoElement | null>,
  incoming: JobPreview | null,
  enabled: boolean,
): SyncedPreview {
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  useEffect(() => setVideo(videoRef.current), [videoRef]);

  const [shown, setShown] = useState<JobPreview | null>(null);
  const [displayLagMs, setDisplayLagMs] = useState<number | null>(null);

  const sync = useRef<SyncState>(IDLE_SYNC);
  const inFlightPreview = useRef<JobPreview | null>(null);
  const pendingPreview = useRef<JobPreview | null>(null);
  const stallTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  /**
   * Applique une décision du réducteur : promotion, calage, chien de garde.
   *
   * Ne dépend de rien, donc **stable** entre deux aperçus — c'est ce qui permet
   * d'abonner les écouteurs une seule fois par `(balise, activé)` au lieu de dix
   * fois par seconde, et donc de ne plus perdre de cible au nettoyage.
   */
  const applyStep = useCallback(
    (element: HTMLVideoElement, step: SyncStep, arriving: JobPreview | null): void => {
      sync.current = step.state;

      if (step.promote === "incoming" && arriving !== null) setShown(arriving);
      else if (step.promote === "inFlight" && inFlightPreview.current !== null) {
        setShown(inFlightPreview.current);
      } else if (step.promote === "pending" && pendingPreview.current !== null) {
        setShown(pendingPreview.current);
      }

      if (step.seekTo !== null) {
        // La cible qui part en vol est celle qui attendait, s'il y en avait une.
        if (pendingPreview.current !== null) {
          inFlightPreview.current = pendingPreview.current;
          pendingPreview.current = null;
        } else if (arriving !== null) {
          inFlightPreview.current = arriving;
        }
        // La lecture et le suivi sont deux pilotes du même curseur : les laisser
        // coexister ferait sauter l'image en avant puis en arrière à chaque aperçu.
        if (!element.paused) element.pause();
        element.currentTime = step.seekTo / 1000;
      } else if (arriving !== null && step.promote === null) {
        // Rien n'est parti : cet aperçu attend son tour, et il écrase le précédent.
        pendingPreview.current = arriving;
      }

      clearTimeout(stallTimer.current);
      if (sync.current.inFlightMs !== null) {
        stallTimer.current = setTimeout(
          () => applyStep(element, onStall(sync.current), null),
          STALL_PROMOTE_MS,
        );
      }
    },
    [],
  );

  // Une image a été présentée. Abonné **une fois** par balise et par activation.
  useEffect(() => {
    const element = video;
    if (element === null || !enabled) return;

    let handle = 0;

    const present = (presentedMs: number, measured: boolean): void => {
      const target = sync.current.inFlightMs;
      if (measured && target !== null) setDisplayLagMs(presentedMs - target);
      applyStep(element, onPresented(sync.current, presentedMs), null);
    };

    // `requestVideoFrameCallback` donne l'instant **réellement composé**, seul
    // moyen de fermer la boucle et de chiffrer l'écart. Le test d'existence reste
    // indispensable malgré `lib.dom`, qui déclare la méthode sur tout
    // `HTMLVideoElement` alors que Firefox ne l'implémente pas.
    const byFrameCallback = typeof element.requestVideoFrameCallback === "function";
    if (byFrameCallback) {
      const onFrame = (_now: number, metadata: VideoFrameCallbackMetadata): void => {
        present(metadata.mediaTime * 1000, true);
        handle = element.requestVideoFrameCallback(onFrame);
      };
      handle = element.requestVideoFrameCallback(onFrame);
    }

    // Repli : `seeked` dit que le calage est terminé, pas que l'image est
    // composée. Assez pour synchroniser, pas assez pour publier un écart — d'où
    // `measured: false`, et « — » à l'écran plutôt qu'un chiffre inventé.
    const onSeeked = (): void => {
      if (byFrameCallback) return;
      present(element.currentTime * 1000, false);
    };
    element.addEventListener("seeked", onSeeked);

    return () => {
      element.removeEventListener("seeked", onSeeked);
      if (byFrameCallback) element.cancelVideoFrameCallback(handle);
      clearTimeout(stallTimer.current);
    };
  }, [video, enabled, applyStep]);

  // Un aperçu arrive. Effet minuscule : toute la décision vit dans le réducteur.
  useEffect(() => {
    const element = video;
    if (element === null || !enabled || incoming === null) return;
    applyStep(element, onIncoming(sync.current, incoming.timestampMs), incoming);
  }, [video, enabled, incoming, applyStep]);

  // Fin d'analyse, bascule en direct, changement de source : on repart à neuf,
  // sinon un aperçu périmé resterait dessiné sur la vidéo suivante.
  useEffect(() => {
    if (incoming !== null && enabled) return;
    sync.current = IDLE_SYNC;
    inFlightPreview.current = null;
    pendingPreview.current = null;
    clearTimeout(stallTimer.current);
    setShown(null);
    setDisplayLagMs(null);
  }, [incoming, enabled]);

  if (!enabled) return { preview: incoming, displayLagMs: null };
  return { preview: incoming === null ? null : shown, displayLagMs };
}
