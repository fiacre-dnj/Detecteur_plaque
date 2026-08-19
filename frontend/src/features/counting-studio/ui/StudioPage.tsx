/**
 * Le Studio — l'écran unique de comptage.
 *
 * **Disposition** : une barre collante en haut (importer, puis quatre tiroirs de
 * réglages, puis les compteurs techniques), la scène et son lecteur à gauche, les
 * chiffres du carrefour à droite, les sections de résultats et la chronologie
 * dessous.
 *
 * Elle a été inversée une première fois : les réglages occupaient la colonne de
 * droite en permanence — trois accordéons dans 20 rem — et les résultats vivaient
 * sous la grille. Cela donnait le meilleur emplacement de l'écran à ce qu'on règle
 * une fois avant de lancer, et repoussait sous la ligne de flottaison ce qu'on
 * regarde pendant et après. Puis, le bas de page s'étant allongé, **tout ce qui
 * reste utile en défilant a été rassemblé à deux endroits** :
 *
 * - la **barre**, désormais collée sous l'entête de l'application, porte l'import,
 *   les quatre tiroirs — Détection, Comptage, Affichage & analyse, **Géométrie** —
 *   et, à son extrémité, les trois chiffres de machine (`TechnicalMetrics`). La
 *   géométrie y remplace un panneau permanent de la colonne de droite : elle se
 *   règle comme les autres, une fois, avant de lancer ;
 * - le **lecteur** porte les deux rails — position, intervalle d'analyse, de même
 *   longueur —, la vitesse, puis « Lancer l'analyse » et « Fermer ». On choisit sa
 *   portion de vidéo, puis on lance, sans traverser l'écran ;
 * - la **colonne de droite** ne porte plus que des chiffres : le bilan du carrefour,
 *   la Répartition par type qui le découpe, et les messages qui expliquent une
 *   absence de chiffre ;
 * - la **chronologie** reste en bas, et reste affichée **après** l'analyse — c'est
 *   la seule vue qui dise *quand* et *dans quel sens*.
 *
 * **Ce que ce composant fait, et ne fait pas.** Il câble les features entre elles et
 * détient l'état partagé — la source, la géométrie, les dimensions de la scène, la
 * session d'analyse. Il ne dessine rien lui-même, ne calcule aucune géométrie et ne
 * parle pas directement au réseau : chacune de ces responsabilités vit dans sa
 * feature, et c'est ce qui garde ce fichier lisible malgré ce qu'il coordonne.
 *
 * Les statistiques affichées viennent de `statsAt(result, timeMs)` **et pas** de
 * `result.stats` : elles suivent la tête de lecture, donc reculer dans la vidéo fait
 * baisser les chiffres. Sans cela, l'image et les nombres racontent deux histoires
 * différentes.
 *
 * **Pendant** l'analyse, la même règle vaut avec une autre source : tout le bas de
 * page lit l'aperçu SSE — compteurs *et* registre des véhicules — parce que la vidéo
 * locale se cale sur l'image analysée. Une seule sélection, `dashboardStats`, pour
 * que les deux phases ne soient pas deux branches à garder d'accord (ADR 0026).
 */

import { Suspense, lazy, useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useLocation } from "react-router";

import { useHealth } from "@/app/layout/useHealth";
import {
  EMPTY_GEOMETRY,
  geometryReducer,
  geometrySignature,
  hasGeometry,
  type Selection,
} from "@/entities/geometry";
import { preloadModel, useDetectableClasses, useModels } from "@/entities/model";
import {
  FULL_RANGE,
  clampRange,
  secondsToMs,
  type AnalysisRange,
} from "@/entities/analysis-range";
import {
  CrossingTimeline,
  JobProgressBar,
  LaunchDialog,
  inputVideoUrl,
  useFollowAnalysis,
} from "@/features/analysis-job";
import {
  SettingsPanels,
  downloadNotice,
  loadSettings,
  sanitiseClassIds,
  saveSettings,
  toRequest,
  type AnalysisSettings,
} from "@/features/analysis-settings";
import { GeometryCanvas, GeometryPanel, useLineFlashes } from "@/features/geometry-editor";
import {
  DropZone,
  SourceBadge,
  SourcePicker,
  VideoScene,
  useMediaSource,
} from "@/features/media-source";
import {
  RealtimePanel,
  scaledSize,
  unscaleTracks,
  useRealtimeSession,
} from "@/features/realtime-counting";
import {
  LineFlowDashboard,
  ResultsDashboard,
  TechnicalMetrics,
  crossingVehicles,
  entriesByClass,
} from "@/features/results-dashboard";
import { crossingsUpTo, useReplay, vehiclesAt } from "@/features/timeline-replay";
import { VehicleRegistry } from "@/features/vehicle-registry";
import { PlaybackFpsBadge, TransportBar } from "@/features/video-transport";
import type { CrossingEvent, Point, Preset } from "@/shared/api/contracts";
import { isTerminal } from "@/shared/api/contracts";
import { VEHICLE_CLASSES } from "@/shared/lib/classes";
import { Button } from "@/shared/ui/Button";
import { MetricCard } from "@/shared/ui/MetricCard";

import { useAnalysisSession } from "../model/useAnalysisSession";
import { PlaybackEndedBanner, StaleResultBanner } from "./StaleResultBanner";

/**
 * Les deux graphiques sont **chargés paresseusement** : ils n'apparaissent
 * qu'après une analyse, et les faire payer au premier chargement taxerait tous
 * ceux qui n'analysent rien.
 */
const LineFlowChart = lazy(() =>
  import("@/features/results-dashboard/ui/LineFlowChart").then((module) => ({
    default: module.LineFlowChart,
  })),
);
const ClassEntriesChart = lazy(() =>
  import("@/features/results-dashboard/ui/ClassEntriesChart").then((module) => ({
    default: module.ClassEntriesChart,
  })),
);

/**
 * La modale des presets, **chargée paresseusement** elle aussi.
 *
 * Elle embarque son propre accès réseau et sa liste ; la faire payer au premier
 * rendu taxerait tous ceux qui n'enregistrent jamais de géométrie — c'est-à-dire la
 * majorité, puisqu'un preset ne sert qu'à partir de la deuxième vidéo.
 */
const PresetDialog = lazy(() =>
  import("@/features/geometry-presets").then((module) => ({ default: module.PresetDialog })),
);

interface SceneSize {
  width: number;
  height: number;
}

const NO_TRAILS: ReadonlyMap<number, readonly Point[]> = new Map();
/** Référence figée : un tableau vide recréé à chaque rendu relancerait les flashs. */
const NO_CROSSINGS: readonly CrossingEvent[] = [];

export function StudioPage() {
  const { data: health } = useHealth();
  const serverReady = health != null;

  const { data: catalogue } = useModels();
  const { data: detectableClasses } = useDetectableClasses();
  const location = useLocation();
  const media = useMediaSource();
  const [geometry, dispatch] = useReducer(geometryReducer, EMPTY_GEOMETRY);
  const [scene, setScene] = useState<SceneSize | null>(null);
  const [ended, setEnded] = useState(false);
  const [presetsOpen, setPresetsOpen] = useState(false);

  /**
   * La portion de vidéo qui sera analysée, et l'ouverture de la modale qui la choisit.
   *
   * **Détenue ici et nulle part ailleurs**, pour la même raison que la géométrie :
   * trois features s'en servent — le lecteur la dessine, la modale la fait choisir,
   * l'envoi la transporte — et aucune n'a le droit d'importer les autres.
   *
   * **Jamais persistée**, contrairement aux réglages d'analyse. « De 00:34 à 05:00 »
   * décrit *cette* vidéo ; relue au chargement suivant, la même fenêtre découperait
   * un autre fichier au hasard. Elle est donc remise à neuf par `resetForNewSource`,
   * comme la géométrie qui est en pixels de la source.
   */
  const [range, setRange] = useState<AnalysisRange>(FULL_RANGE);
  const [launchOpen, setLaunchOpen] = useState(false);
  /**
   * Position de lecture **figée à l'ouverture** de la modale.
   *
   * Un instantané et non un abonnement : `useVideoTransport` vit dans `TransportBar`
   * précisément pour que ses soixante mises à jour par seconde ne re-rendent pas
   * tout le studio, canvas compris. Remonter la position ici annulerait ce gain
   * pour un chiffre qu'on ne lit qu'une fois, au moment du clic.
   */
  const [launchTimeMs, setLaunchTimeMs] = useState(0);

  /**
   * Les réglages, relus du stockage **une seule fois** à l'initialisation.
   *
   * `useState(loadSettings)` et non `useState(loadSettings())` : la seconde forme
   * lirait le stockage à chaque rendu, pour une valeur que React ignore après le
   * premier.
   */
  const [settings, setSettings] = useState<AnalysisSettings>(loadSettings);

  // Persistés à chaque changement. Un `useEffect` plutôt qu'une écriture dans
  // `updateSettings` : ainsi un réglage modifié par un autre chemin (chargement
  // d'un preset, relance depuis l'historique) est persisté lui aussi.
  useEffect(() => saveSettings(settings), [settings]);

  const updateSettings = useCallback((patch: Partial<AnalysisSettings>) => {
    setSettings((previous) => ({ ...previous, ...patch }));
  }, []);

  /**
   * Configuration reçue de l'historique — « Ouvrir » ou « Relancer ».
   *
   * Appliquée **une seule fois** : sans ce garde, chaque rendu réécraserait les
   * modifications que l'utilisateur vient de faire depuis son arrivée, ce qui rend
   * l'écran impossible à utiliser sans qu'on comprenne pourquoi.
   */
  const applied = useRef(false);
  useEffect(() => {
    if (applied.current) return;
    const incoming = (location.state as { config?: unknown } | null)?.config;
    if (incoming === undefined) return;
    applied.current = true;

    const loaded = incoming as {
      lines?: typeof geometry.lines;
      zones?: typeof geometry.zones;
    } & Partial<AnalysisSettings>;

    dispatch({
      type: "replace",
      lines: [...(loaded.lines ?? [])],
      zones: [...(loaded.zones ?? [])],
    });
    // La géométrie **et** les réglages : relancer avec les mêmes lignes mais
    // d'autres seuils ne serait pas « la même configuration ».
    setSettings((previous) => ({ ...previous, ...stripGeometry(loaded) }));
  }, [location.state]);

  /**
   * Aligne le modèle sur le défaut du **serveur** si celui retenu n'existe plus.
   *
   * Le cas concret : un réglage persisté cite `yolo11m`, puis le catalogue change
   * (nouvelle version, modèle retiré). Sans ce recalage, le sélecteur n'aurait
   * aucune option cochée et l'analyse partirait avec un identifiant que le serveur
   * refuserait en 404 — après le clic sur « Lancer ».
   */
  useEffect(() => {
    if (catalogue === null || catalogue === undefined) return;
    const known = catalogue.models.some((model) => model.id === settings.modelId);
    if (!known) {
      const fallback = catalogue.models.find((model) => model.isDefault) ?? catalogue.models[0];
      if (fallback !== undefined) updateSettings({ modelId: fallback.id });
    }
  }, [catalogue, settings.modelId, updateSettings]);

  /**
   * Même recalage pour les classes cochées, et pour la même raison.
   *
   * Une sélection persistée peut citer une classe que le serveur ne propose plus —
   * version antérieure, catalogue changé. Sans ce nettoyage, l'envoi partirait avec
   * un identifiant refusé et l'utilisateur verrait un 422 sur un écran dont toutes
   * les cases paraissent valides. La comparaison porte sur le **contenu** : recaler
   * sur une nouvelle référence de tableau à chaque rendu relancerait l'effet en
   * boucle.
   */
  useEffect(() => {
    if (detectableClasses === null || detectableClasses === undefined) return;
    const cleaned = sanitiseClassIds(settings.classIds, detectableClasses);
    if (cleaned.join(",") !== settings.classIds.join(",")) {
      updateSettings({ classIds: cleaned });
    }
  }, [detectableClasses, settings.classIds, updateSettings]);

  const video = useRef<HTMLVideoElement>(null);
  const session = useAnalysisSession();

  /**
   * « Ouvrir » depuis l'historique : rejouer une analyse archivée.
   *
   * **C'est ici que « Ouvrir » et « Relancer » cessent d'être le même bouton.** Les
   * deux drapeaux voyageaient déjà dans l'état de navigation ; personne ne les
   * lisait, donc les deux gestes rechargeaient la géométrie et rien d'autre, et
   * l'infobulle « recharge le résultat et sa géométrie » promettait la moitié de ce
   * qu'elle faisait.
   *
   * Un effet séparé de celui qui applique la configuration, et **placé après**
   * `session` : il en dépend, et le déclarer plus haut le mettrait dans la zone
   * morte temporelle de la constante.
   *
   * L'ordre des deux appels est **obligatoire**. `resetForNewSource` vide la session
   * à tout changement de source ; poser la vidéo après l'adoption effacerait donc le
   * résultat qu'on vient d'aller chercher. La source d'abord, le résultat ensuite.
   */
  const adopted = useRef(false);
  useEffect(() => {
    if (adopted.current) return;
    const state = location.state as { jobId?: unknown; replay?: unknown; fileName?: unknown } | null;
    if (state?.replay !== true || typeof state.jobId !== "string") return;
    adopted.current = true;

    const jobId = state.jobId;
    const label = typeof state.fileName === "string" ? state.fileName : "Analyse archivée";
    media.selectArchived(inputVideoUrl(jobId), label);
    session.adopt(jobId);
  }, [location.state, media, session]);

  const handleEnded = useCallback(() => setEnded(true), []);

  /**
   * Revoir depuis le début, **sans passer par l'état du transport**.
   *
   * `useVideoTransport` vit maintenant dans `TransportBar` : le studio n'a plus
   * besoin de son état, seulement de ce geste-là. Deux lignes sur la balise
   * suffisent, et cela évite de remonter soixante mises à jour de position par
   * seconde jusqu'ici pour un unique bouton.
   */
  const replayFromStart = useCallback(() => {
    const element = video.current;
    if (element === null) return;
    element.currentTime = 0;
    setEnded(false);
    void element.play().catch(() => undefined);
  }, []);

  // La **référence**, pas `video.current` : ce dernier était lu au rendu, donc le
  // hook pouvait s'abonner à `null` et ne jamais se réabonner — la relecture restait
  // alors figée sur les chiffres finaux, justes et immobiles.
  const replay = useReplay(video, session.result);
  const live = useRealtimeSession(video.current);

  /**
   * Amorce la scène depuis les dimensions du **résultat**, faute de vidéo.
   *
   * `scene` ne venait que de `loadedmetadata`, et le canvas comme l'incrustation y
   * sont conditionnés. Sur une analyse rouverte dont la vidéo a été purgée, on avait
   * donc tous les chiffres et aucune géométrie visible — les lignes qui ont produit
   * ces chiffres restaient invisibles, ce qui est précisément ce qu'on vient
   * regarder.
   *
   * Ne fait rien quand la vidéo a déjà parlé : `loadedmetadata` est la source de
   * vérité dès qu'elle existe, et l'écraser rouvrirait le désaccord de repère que
   * l'avertissement d'aperçu existe pour signaler.
   */
  useEffect(() => {
    if (scene !== null || session.result === null) return;
    const { width, height } = session.result.video;
    if (width > 0 && height > 0) setScene({ width, height });
  }, [scene, session.result]);

  const handleMetadata = useCallback(
    (size: SceneSize) => {
      if (size.width === 0 || size.height === 0) return;
      setScene(size);
      // Un écran sans ligne ne compte rien, et l'utilisateur qui obtient zéro ne
      // devine pas que c'est parce qu'il n'a rien tracé.
      if (!hasGeometry(geometry)) {
        dispatch({ type: "addLine", width: size.width, height: size.height });
      }
    },
    [geometry],
  );

  /**
   * Changer de source remet tout à zéro : la géométrie est en pixels de la source.
   *
   * **Le direct est coupé ici**, et c'est obligatoire : les dimensions d'envoi sont
   * figées au démarrage de la session. Continuer à capturer après un changement de
   * caméra enverrait des images d'une résolution que la géométrie ne décrit plus —
   * exactement le désaccord que `dimensionsAgree` détecte, mais autant ne pas
   * l'atteindre. C'est aussi ce qui rend la place de session côté serveur, sans quoi
   * la suivante serait refusée en 1013 sans explication.
   */
  const resetForNewSource = useCallback(() => {
    live.stop();
    dispatch({ type: "clear" });
    setScene(null);
    setEnded(false);
    // L'intervalle avec le reste : il est en temps de **cette** vidéo. Hérité d'un
    // fichier précédent, il découperait le nouveau à un endroit que personne n'a
    // choisi — et une borne au-delà de sa durée le ferait refuser en 422, sur un
    // écran dont toutes les valeurs paraissent valides.
    setRange(FULL_RANGE);
    session.reset();
  }, [session, live]);

  const handleFile = useCallback(
    (file: File) => {
      resetForNewSource();
      media.selectFile(file);
    },
    [media, resetForNewSource],
  );

  /* Les points d'entrée « démonstration » et « caméra » ont été retirés de l'écran
     avec leurs cartes : elles étaient désactivées, et occupaient les deux tiers d'un
     bandeau permanent pour annoncer « indisponible ».

     **Rien d'autre n'a été supprimé.** `media.selectDemo` et `media.selectCamera`
     existent toujours, `isCamera` gouverne toujours `RealtimePanel`, et toute la
     feature `realtime-counting` — WebSocket, cadence, mise à l'échelle d'envoi,
     garde de résolution — reste en place et testée. Rouvrir la porte est un
     `useCallback` de trois lignes et un bouton dans la barre, pas une
     réimplémentation. C'est écrit ici pour que la prochaine lecture ne conclue pas
     que le direct a disparu du produit. */

  const handleClose = useCallback(() => {
    resetForNewSource();
    media.clear();
  }, [media, resetForNewSource]);

  /**
   * Le lancement **effectif** — ce que la modale déclenche, et ce que les deux
   * bandeaux de relance appellent directement.
   *
   * Les bandeaux (« résultat périmé », « modèle indisponible ») ne repassent pas par
   * la modale, et c'est voulu : ils relancent *la même* analyse après un changement
   * de géométrie ou un préchargement, sur l'intervalle déjà choisi. Redemander la
   * portion à chaque relance ferait cliquer deux fois pour répéter un geste.
   */
  const launch = useCallback(() => {
    const file = media.source?.file;
    if (file === undefined || !serverReady) return;

    setLaunchOpen(false);
    setEnded(false);
    void session.start(
      file,
      // `toRequest` est le seul endroit qui traduit les réglages en requête : il
      // résout `confidenceThreshold: null` en défaut, met l'échelle nulle à `null`,
      // et désactive le masque quand aucune zone n'existe.
      toRequest(settings, geometry.lines, geometry.zones, range),
      geometry.lines,
      geometry.zones,
    );
  }, [media.source, serverReady, settings, geometry, session, range]);

  /**
   * Ouvre la modale, en y **figeant la position de lecture** du moment.
   *
   * C'est le seul endroit qui lit `video.current.currentTime`, et c'est une lecture
   * unique : le studio ne s'abonne pas à la position pour ne pas se re-rendre
   * soixante fois par seconde. `clampRange` est rejoué à l'ouverture parce que la
   * durée peut n'avoir été connue qu'après la saisie d'un intervalle — sur une vidéo
   * lente à charger, les métadonnées arrivent après le premier réglage.
   */
  const openLaunch = useCallback(() => {
    const element = video.current;
    const durationMs = secondsToMs(element?.duration ?? 0);
    setLaunchTimeMs(secondsToMs(element?.currentTime ?? 0));
    setRange((previous) => clampRange(previous, durationMs));
    setLaunchOpen(true);
  }, []);

  /**
   * Le résultat décrit-il encore la géométrie affichée ?
   *
   * Comparaison de signatures, et non des objets : la signature exclut le nom et la
   * couleur, et arrondit les coordonnées. Avertir pour un renommage ou un
   * déplacement invisible apprendrait à ignorer l'avertissement.
   */
  const stale = useMemo(() => {
    if (session.launchSignature === null || session.result === null) return false;
    return geometrySignature(geometry.lines, geometry.zones) !== session.launchSignature;
  }, [session.launchSignature, session.result, geometry.lines, geometry.zones]);

  /*
   * `lineNames` — une table `id → nom` bâtie pour le seul journal — est
   * **supprimée** : la chronologie reçoit `geometry.lines` en entier, parce qu'elle
   * nomme le *rôle* du sens (« Entrée », « Sortie ») et colore son nœud à la couleur
   * de la ligne. Ni l'un ni l'autre ne se lit dans une table de noms.
   */

  /**
   * Les véhicules **du trafic**, à la tête de lecture : vus, et ayant franchi
   * au moins une ligne.
   *
   * Les deux filtres se composent et aucun n'est facultatif : `vehiclesAt` cale
   * le registre sur la vidéo (afficher les 400 véhicules d'un clip à la dixième
   * seconde ferait mentir le tableau), `crossingVehicles` écarte le
   * stationnement. Sans le second, le registre publiait des lignes à « — » que
   * rien ne permettait de vérifier, et le chiffre de tête annonçait 106 objets
   * suivis sous 28 entrées.
   *
   * Calculé **ici** et passé aux deux consommateurs plutôt que refait dans
   * chacun : le registre et le tableau de bord doivent parler du même ensemble,
   * sinon un véhicule est dans le total sans être dans la liste qui le justifie.
   *
   * **Deux sources, une seule forme.** Après l'analyse, la liste vient du résultat
   * complet, filtrée par la tête de lecture. **Pendant**, elle vient du registre
   * que l'aperçu SSE transporte : les mêmes `VehicleRecord`, produits par le même
   * agrégat serveur et le même sérialiseur. C'est ce qui remplit le tableau et la
   * statistique en cours d'analyse sans reconstruire quoi que ce soit ici — un
   * agrégat client divergerait, et ni le vote de classe ni celui de plaque ne se
   * refont depuis les images échantillonnées (invariants 3 et 4).
   *
   * Pas de `vehiclesAt` sur la branche vivante : l'aperçu *est* déjà l'état à
   * l'instant analysé, et la vidéo locale s'y cale (`useFollowAnalysis`). Le
   * filtrer par la tête de lecture reviendrait à filtrer par lui-même.
   *
   * `session.preview` et non le `preview` garde-fou du dessin : un désaccord de
   * dimensions suspend les *boîtes*, jamais les compteurs — c'est exactement ce
   * que dit le message affiché dans ce cas.
   */
  const countedVehicles = useMemo(() => {
    if (session.result !== null) {
      return crossingVehicles(vehiclesAt(session.result, replay.timeMs));
    }
    // `crossingVehicles` reste appliqué alors que le serveur a déjà restreint sa
    // liste : le prédicat client reste l'autorité (`crossedVehicles.ts` en est le
    // seul juge), et l'appliquer deux fois ne coûte qu'un parcours.
    return crossingVehicles(session.preview?.vehicles ?? []);
  }, [session.result, session.preview?.vehicles, replay.timeMs]);

  /**
   * La classe personne a-t-elle été cochée pour cette analyse ?
   *
   * Décidé ici, pas dans `results-dashboard` : cette feature ne connaît que
   * `AnalysisStats`/`CountingLine[]`, jamais le catalogue de classes ni les
   * réglages — même règle que `ClassPicker` dans `analysis-settings`, dont ce
   * calcul reprend le filtre par catégorie.
   */
  const hasPersonClass = useMemo(
    () =>
      (detectableClasses ?? []).some(
        (entry) => entry.category === "person" && settings.classIds.includes(entry.id),
      ),
    [detectableClasses, settings.classIds],
  );

  const selectedId = geometry.selection.kind === "none" ? null : geometry.selection.id;
  const isCamera = media.source?.kind === "camera";
  const analysing = session.job !== null && !isTerminal(session.job.status);
  const busy = analysing || session.starting || live.active;

  /**
   * L'analyse a échoué — **et le dire ne dépend plus de `busy`**.
   *
   * `busy` exclut les statuts terminaux : à la seconde où le job passe en
   * `error`, il devient faux. La barre de progression était montée sur `busy`
   * seul, et comme elle est le seul endroit du Studio qui rende `job.error`, le
   * message d'échec était démonté à l'instant précis où il devenait utile.
   */
  const failed = session.job?.status === "error";
  const canAnalyse = serverReady && media.source?.file !== undefined && hasGeometry(geometry) && !busy;

  /**
   * L'attente cachée du premier usage d'un modèle, dite **avant** le clic.
   *
   * Le catalogue annonce vingt modèles, le disque du serveur en porte trois : la
   * plupart des choix déclenchent un téléchargement qui n'a lieu qu'à la première
   * image analysée, donc après le passage en « en cours ». Sans cette phrase,
   * l'écran affiche 0 % pendant une à deux minutes et se lit comme une panne.
   */
  const pendingDownload = useMemo(
    () => downloadNotice(catalogue?.models ?? [], settings.modelId),
    [catalogue?.models, settings.modelId],
  );

  /** Le nom lisible du modèle retenu — l'identifiant si le catalogue l'ignore. */
  const selectedModelLabel = useMemo(
    () =>
      catalogue?.models.find((model) => model.id === settings.modelId)?.label ??
      settings.modelId,
    [catalogue?.models, settings.modelId],
  );

  /** Démarre le direct sur la géométrie **courante**, mise à l'échelle par le hook. */
  const startLive = useCallback(() => {
    live.start(toRequest(settings, geometry.lines, geometry.zones));
  }, [live, settings, geometry.lines, geometry.zones]);

  /**
   * Dimensions d'envoi, affichées dans le panneau.
   *
   * Recalculées ici depuis la scène plutôt que lues du hook : elles doivent être
   * visibles **avant** le démarrage, pour que l'utilisateur sache ce qui sera envoyé.
   */
  const sendSize = useMemo(
    () => (scene === null ? { width: 0, height: 0 } : scaledSize(scene.width, scene.height, live.factor)),
    [scene, live.factor],
  );

  /**
   * L'aperçu de l'analyse en cours — **s'il décrit bien la vidéo affichée**.
   *
   * La comparaison de dimensions est le filet de la panne silencieuse : la balise
   * `<video>` et le décodeur du serveur peuvent ne pas être d'accord sur la taille
   * d'une source exotique (SAR non carré, rotation portée par les métadonnées).
   * Dessiner quand même produirait des boîtes décalées que rien n'expliquerait, et
   * on conclurait à un défaut de détection. Mieux vaut ne rien dessiner et le dire.
   */
  const previewMismatch =
    session.preview !== null &&
    scene !== null &&
    (session.preview.frameWidth !== scene.width || session.preview.frameHeight !== scene.height);

  const preview = previewMismatch || live.active ? null : session.preview;

  /**
   * La vidéo se cale sur l'image que le serveur analyse.
   *
   * Uniquement sur une source **fichier** : la vidéo locale est alors le même
   * fichier que celui envoyé, donc le temps de scène désigne exactement la même
   * image des deux côtés. Une caméra n'a pas de temps de scène commun.
   */
  useFollowAnalysis(video.current, preview?.timestampMs ?? null, media.source?.file !== undefined);

  /**
   * Les pistes à dessiner : le direct s'il tourne, sinon l'aperçu de l'analyse en
   * cours, sinon la relecture.
   *
   * **Remises à l'échelle source** avant d'atteindre le canvas, qui ne connaît qu'un
   * seul repère. Faire la conversion ici et non dans le canvas évite une branche
   * « si direct » dans le code de dessin, qui finirait par diverger. L'aperçu, lui,
   * est déjà en pixels source : le serveur analyse la vidéo telle qu'elle est.
   */
  const canvasTracks = useMemo(() => {
    if (live.active) return unscaleTracks(live.tracks, live.factor);
    if (preview !== null) return preview.tracks;
    return replay.tracks;
  }, [live.active, live.tracks, live.factor, preview, replay.tracks]);

  /**
   * Les statistiques à afficher : direct, puis aperçu, puis tête de lecture.
   *
   * Une seule source pour tout l'écran — badge du canvas, tableau de bord, registre.
   * Deux chemins de statistiques finiraient par se contredire à l'écran, et
   * l'utilisateur n'aurait aucun moyen de savoir lequel croire.
   */
  const liveStats = live.active ? live.stats : (preview?.stats ?? replay.stats);

  /**
   * Le bloc de résultats à afficher, et **d'où vient sa cadence**.
   *
   * Les trois situations donnaient déjà trois `ResultsDashboard` dans une ternaire à
   * quatre branches, chacune avec sa propre `processingFps`. Les réunir ici sert la
   * réorganisation : les cartes montent dans la colonne, les détails descendent dans
   * les onglets, et les deux endroits doivent afficher **la même** source sans que la
   * sélection soit écrite deux fois.
   *
   * `null` avant toute analyse : l'écran montre alors son état vide, jamais des zéros
   * qui se liraient comme un comptage à blanc.
   */
  const resultStats =
    live.active && live.stats !== null
      ? {
          stats: live.stats,
          // En direct, la cadence du serveur se déduit de la latence aller-retour :
          // la seule mesure de performance honnête dont on dispose ici.
          processingFps: live.pacing.latencyMs === null ? 0 : 1000 / live.pacing.latencyMs,
          replaying: false,
        }
      : preview !== null
        ? { stats: preview.stats, processingFps: session.job?.processingFps ?? 0, replaying: false }
        : replay.stats !== null && session.result !== null
          ? {
              stats: replay.stats,
              processingFps: session.result.processingFps,
              replaying: true,
            }
          : null;

  /**
   * Les compteurs du **bas de page** : Statistique, camemberts, Registre.
   *
   * Distinct de `resultStats`, et la différence est le direct : ces trois sections
   * parlent de véhicules autant que de passages, et le direct n'a pas de registre —
   * pas d'aperçu SSE, donc pas de `vehicles`. Les alimenter avec ses statistiques
   * afficherait « 0 véhicule ayant traversé » sous des franchissements qui montent,
   * ce qui se lit comme un comptage en panne. La Répartition, elle, ne lit que
   * `by_class` et reste donc branchée sur `resultStats` dans les trois modes.
   *
   * Sinon : l'aperçu pendant l'analyse, la tête de lecture après. Les deux portent
   * la même forme, donc les sections ne connaissent pas la différence.
   */
  const dashboardStats =
    session.result !== null ? replay.stats : (session.preview?.stats ?? null);

  /**
   * Le journal que la chronologie affiche — **pendant l'analyse comme après**.
   *
   * La section des franchissements disparaissait à l'instant où l'analyse
   * terminait : elle ne lisait que `session.events`, le journal que le suivi SSE
   * accumule, et sa condition d'affichage exigeait `session.result === null`. Or
   * c'est justement après coup qu'on vérifie un comptage — la vidéo est relisible,
   * le registre est là, et c'est le seul endroit qui dise *quand* et *dans quel
   * sens* chaque passage a eu lieu.
   *
   * Après l'analyse, le journal vient donc du résultat complet et **suit la tête de
   * lecture** (`crossingsUpTo`), comme tout le reste du bas de page : la
   * chronologie ne montre jamais un franchissement que la vidéo n'a pas encore
   * atteint. C'est la fonction qui existait pour cela et avait perdu son
   * consommateur.
   *
   * Deux sources, une seule forme — le plus récent en tête, borné à 200 entrées de
   * part et d'autre (`LOG_LIMIT`), donc la section ne connaît pas la différence.
   *
   * `null` avant toute analyse : la section n'existe alors pas, plutôt que
   * d'afficher un vide qui se lirait comme « aucun franchissement ».
   */
  const timelineEvents = useMemo<readonly CrossingEvent[] | null>(() => {
    if (session.result !== null) return crossingsUpTo(session.result, replay.timeMs);
    return analysing || session.events.length > 0 ? session.events : null;
  }, [session.result, session.events, replay.timeMs, analysing]);

  /**
   * Les franchissements qui viennent d'être comptés — ceux qui font clignoter leur
   * ligne. La **dernière salve**, jamais le cumul : rallumer toutes les lignes à
   * chaque image ferait d'un signal un bruit de fond.
   */
  const flashCrossings = live.active ? live.lastCrossings : (preview?.crossings ?? NO_CROSSINGS);
  const lineFlashes = useLineFlashes(flashCrossings);

  /**
   * Charge un preset **déjà mis à l'échelle par le serveur**.
   *
   * La géométrie arrive dans le repère de la vidéo courante : elle remplace donc le
   * tracé sans conversion supplémentaire. Reconvertir ici appliquerait le facteur
   * deux fois, et les lignes se retrouveraient au quart de leur distance du bord.
   *
   * Le réglage de masque suit la géométrie parce qu'il n'a de sens qu'avec les zones
   * qui l'accompagnent — recharger un masque sans ses zones ne masquerait rien.
   */
  const loadPreset = useCallback((preset: Preset) => {
    dispatch({ type: "replace", lines: [...preset.lines], zones: [...preset.zones] });
    setSettings((previous) => ({ ...previous, maskOutsideZones: preset.maskOutsideZones }));
  }, []);

  /** Pourquoi le direct est indisponible — quatre causes, quatre actions. */
  const liveBlockedReason = useMemo(() => {
    if (!isCamera) return "Le direct nécessite la caméra comme source.";
    if (!serverReady) return "Le serveur est injoignable.";
    if (scene === null) return "En attente du premier aperçu de la caméra.";
    if (!hasGeometry(geometry)) return "Ajoutez d'abord une ligne de comptage.";
    if (analysing || session.starting) return "Une analyse de fichier est en cours.";
    return null;
  }, [isCamera, serverReady, scene, geometry, analysing, session.starting]);

  return (
    <div className="space-y-4">
      {/* ── La barre : importer, puis régler ───────────────────────────────
          Les réglages sont passés au-dessus de la vidéo, au même niveau que
          l'import. Ils occupaient auparavant une colonne permanente de 20 rem
          pour des panneaux qu'on ouvre une fois avant de lancer, et repoussaient
          les résultats sous la ligne de flottaison. `leading` est l'emplacement
          que `SettingsPanels` réserve : la feature des réglages n'a pas à
          connaître celle de la source, c'est le studio qui les met côte à côte. */}
      <SettingsPanels
        leading={
          <SourcePicker
            activeLabel={media.source?.label ?? null}
            disabled={busy}
            onFile={handleFile}
          />
        }
        // Tout à droite de la barre (`ms-auto` dans `SettingsPanels`) : les quatre
        // chiffres **d'instant**, objets suivis compris. Ils tenaient quatre des six
        // cartes de tête de la colonne de résultats, au même poids visuel que le
        // bilan du comptage — les deux tiers du meilleur emplacement de l'écran pour
        // de la métrologie qu'on surveille du coin de l'œil. Le nom du fichier, qui
        // occupait cette place, est passé sur la vidéo qu'il nomme.
        trailing={
          resultStats !== null ? (
            <TechnicalMetrics
              processingFps={resultStats.processingFps}
              stats={resultStats.stats}
            />
          ) : null
        }
        settings={settings}
        models={catalogue?.models ?? []}
        detectableClasses={detectableClasses ?? []}
        plateAvailable={catalogue?.plateAvailable ?? false}
        // **De `/health` et non du catalogue de modèles** : c'est le seul endroit qui
        // porte le verdict de l'auto-test — poids présents, chargement en échec —,
        // l'état qui laissait cocher l'ANPR pour qu'elle ne rende jamais rien.
        // `undefined` (santé pas encore reçue) devient `null` : « pas encore testé »,
        // qui n'est pas un échec et ne doit rien désactiver.
        plateLoadable={health?.plateLoadable ?? null}
        plateOcrAvailable={catalogue?.plateOcrAvailable ?? false}
        hasZones={geometry.zones.length > 0}
        // Pour nommer les lignes des quasi-franchissements dans le diagnostic : le
        // serveur les publie par identifiant, et un identifiant ne dit rien à l'œil.
        lines={geometry.lines}
        // Le diagnostic **vivant** pendant l'analyse, celui de la dernière sinon :
        // comprendre pendant que ça tourne pourquoi un véhicule n'est pas compté —
        // masqué, pas confirmé, écarté — au lieu de l'apprendre à la fin. `null`
        // avant toute analyse, plutôt que six zéros qui se liraient comme un
        // résultat.
        diagnostics={liveStats?.diagnostics ?? session.result?.stats.diagnostics ?? null}
        disabled={busy}
        // Régler la détection, le comptage ou l'affichage n'a rien à quoi
        // s'appliquer sans source : les trois tiroirs restent grisés jusque-là.
        hasSource={media.source !== null}
        onChange={updateSettings}
        // **Géométrie devient le quatrième tiroir**, au même niveau que Détection,
        // Comptage et Affichage. Il occupait un panneau permanent de la colonne de
        // droite alors qu'il se règle comme les autres — une fois, avant de lancer —
        // et il repoussait les chiffres qu'on vient lire sous la ligne de flottaison.
        // Passé par `panels` et non importé là-bas : `analysis-settings` ne connaît
        // pas `geometry-editor`, c'est le studio qui câble les deux.
        panels={[
          {
            id: "geometrie",
            label: "Géométrie",
            content: (
              <GeometryPanel
                lines={geometry.lines}
                zones={geometry.zones}
                selection={geometry.selection}
                drawingZone={geometry.drawingZone}
                disabled={scene === null || busy}
                onAddLine={() =>
                  scene !== null &&
                  dispatch({ type: "addLine", width: scene.width, height: scene.height })
                }
                onToggleDrawZone={() =>
                  dispatch({ type: "setDrawingZone", drawing: !geometry.drawingZone })
                }
                onSelect={(selection) => dispatch({ type: "select", selection })}
                onRenameLine={(id, name) => dispatch({ type: "renameLine", id, name })}
                onRenameZone={(id, name) => dispatch({ type: "renameZone", id, name })}
                onSetDirectionRole={(id, sign, role) =>
                  dispatch({ type: "setDirectionRole", id, sign, role })
                }
                onSetLineZone={(id, zoneId) => dispatch({ type: "setLineZone", id, zoneId })}
                onSetLineLength={(id, lengthMeters) =>
                  dispatch({ type: "setLineLength", id, lengthMeters })
                }
                onRemoveLine={(id) => dispatch({ type: "removeLine", id })}
                onRemoveZone={(id) => dispatch({ type: "removeZone", id })}
                onOpenPresets={() => setPresetsOpen(true)}
              />
            ),
          },
        ]}
      />

      {media.error !== null && (
        <p role="alert" className="text-caption text-negative">
          {media.error}
        </p>
      )}
      {/* L'alerte de haut de page — désormais **réellement alimentée** par un
          échec serveur, et persistante : elle ne dépend d'aucun `busy`.
          Sur `model_unavailable`, elle porte l'action qui répare, parce qu'un
          message qui nomme la cause sans proposer le geste laisse l'utilisateur
          chercher où précharger un modèle. */}
      {session.error !== null && (
        <div role="alert" className="space-y-2">
          <p className="text-caption text-negative">{session.error}</p>
          {session.errorCode === "model_unavailable" && (
            <PreloadRetry
              modelId={settings.modelId}
              modelLabel={selectedModelLabel}
              canRelaunch={canAnalyse}
              onRelaunch={launch}
            />
          )}
        </div>
      )}

      {/* La colonne de droite porte désormais les **résultats**, pas les réglages :
          les chiffres se lisent à côté de la scène qui les produit, au lieu d'être
          repoussés sous elle. 24 rem plutôt que 20 : neuf cartes en deux colonnes y
          tiennent sans que les libellés se coupent. */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="space-y-3">
          <DropZone disabled={busy} onFile={handleFile}>
          <VideoScene
            source={media.source}
            onMetadata={handleMetadata}
            videoRef={video}
            onFile={handleFile}
            disabled={busy}
          >
            {scene !== null && (
              <GeometryCanvas
                sourceWidth={scene.width}
                sourceHeight={scene.height}
                lines={geometry.lines}
                zones={geometry.zones}
                tracks={canvasTracks}
                // Pas de trajectoires en direct : elles se construisent en accumulant
                // les positions d'une timeline, et le direct n'en garde aucune — les
                // fabriquer côté client dupliquerait un calcul du serveur, avec les
                // frames abandonnées comme trous.
                trails={
                  settings.showTrails && !live.active && preview === null
                    ? replay.trails
                    : NO_TRAILS
                }
                lineFlashes={lineFlashes}
                // Estompe le nom de ligne et les libellés de sens pendant l'analyse
                // serveur, différée ou en direct : la géométrie est déjà validée à
                // ce stade, c'est le train de boîtes et de compteurs qui compte.
                analysing={busy}
                selectedId={selectedId}
                drawingZone={geometry.drawingZone}
                showTrails={settings.showTrails}
                // Le masque n'est dessiné que s'il sera **réellement appliqué** :
                // `toRequest` le désactive sans zone, et montrer un voile que le
                // serveur ignorerait serait un mensonge visuel.
                maskOutsideZones={settings.maskOutsideZones && geometry.zones.length > 0}
                // Les pointillés « pas encore confirmée » suivent le réglage réel,
                // donc ce que le canvas montre correspond à ce que l'analyse fera.
                minHits={settings.minHits}
                onSelect={(selection) =>
                  dispatch({
                    type: "select",
                    selection: (selection ?? { kind: "none" }) as Selection,
                  })
                }
                onMoveLine={(id, a, b) => dispatch({ type: "moveLine", id, a, b })}
                onMoveZone={(id, points) => dispatch({ type: "moveZone", id, points })}
                onCompleteZone={(points) => dispatch({ type: "addZone", points })}
                onCancelZone={() => dispatch({ type: "setDrawingZone", drawing: false })}
              />
            )}

            {/* Le nom du fichier **sur la scène**, coin haut-gauche, dans le même
                écrin que le badge de dimensions d'en face : deux repères de même
                nature — « quoi je regarde », « dans quel repère » — dessinés
                différemment se liraient comme deux niveaux d'information. Il vivait
                à l'extrémité de la barre, que les compteurs techniques occupent
                maintenant. */}
            {media.source !== null && (
              <div className="pointer-events-none absolute start-2 top-2">
                <SourceBadge label={media.source.label} />
              </div>
            )}

            {scene !== null && (
              <div className="pointer-events-none absolute end-2 top-2 flex flex-col items-end gap-1">
                {/* Les dimensions **réellement reçues** : premier filet contre une
                    géométrie mal ancrée. Un chiffre inattendu ici explique
                    immédiatement des compteurs faux. */}
                <p className="rounded-badge bg-base/80 px-2 py-1 text-micro text-ink-muted tabular">
                  {scene.width}×{scene.height}
                </p>
                {/* La cadence **réellement affichée**, à côté de la cadence serveur
                    du tableau de bord. L'écart entre les deux est ce qui explique
                    une relecture saccadée : le décodage et l'inférence se battent
                    pour les mêmes cœurs.

                    Composant autonome, qui tient son propre état : mesurée ici, la
                    cadence re-rendrait `GeometryCanvas` à chaque image. */}
                <PlaybackFpsBadge videoRef={video} />
                {/* En direct, les dimensions **d'envoi** en plus de celles de la
                    scène : c'est le repère dans lequel le serveur compte, et le voir
                    à côté de la source rend la réduction évidente. */}
                {live.active && sendSize.width > 0 && (
                  <p className="rounded-badge bg-base/80 px-2 py-1 text-micro text-ink-muted tabular">
                    → {sendSize.width}×{sendSize.height}
                  </p>
                )}
              </div>
            )}
          </VideoScene>
          </DropZone>

          {/* La vidéo se cale **toujours** sur l'image analysée pendant l'analyse
              (`useFollowAnalysis`) : plus de case à décocher pour reprendre la
              main, le gel est inconditionnel tant que ça tourne. Griser
              inconditionnellement laissait l'utilisateur devant une vidéo figée
              et des boutons morts, sans un mot d'explication — d'où le message
              juste en dessous. */}
          {media.source !== null && (
            <TransportBar
              videoRef={video}
              seekable={!isCamera}
              disabled={busy}
              onEnded={handleEnded}
              // Le direct n'a pas d'intervalle à choisir : un flux caméra n'a ni
              // début ni fin, et le serveur ignore les deux bornes en temps réel.
              // Les omettre masque le rail plutôt que d'afficher un réglage sans
              // effet — la panne la plus démoralisante d'une interface.
              range={isCamera ? undefined : range}
              onRangeChange={isCamera ? undefined : setRange}
              // Grisé pendant l'analyse **seule** : se déplacer dans la vidéo reste
              // utile pour regarder l'aperçu, déplacer les bornes ne l'est plus —
              // elles sont déjà parties au serveur.
              rangeDisabled={busy}
              // Les deux actions de la source, à l'extrémité de la rangée de
              // commandes. Elles occupaient le bas de la colonne de résultats, à un
              // écran de défilement du lecteur qu'on vient de régler : on choisit sa
              // portion sur le rail, puis on lance — deux gestes voisins, désormais
              // au même endroit. L'intervalle retenu se lit deux rangées au-dessus,
              // ce qui remplace le rappel « Portion retenue » écrit sous l'ancien
              // bouton.
              actions={
                <>
                  <Button
                    variant="primary"
                    size="sm"
                    disabled={!canAnalyse}
                    onClick={openLaunch}
                    title={analyseTooltip(
                      serverReady,
                      media.source?.file !== undefined,
                      geometry,
                      busy,
                    )}
                  >
                    Lancer l'analyse
                  </Button>
                  <Button variant="ghost" size="sm" onClick={handleClose} disabled={busy}>
                    Fermer
                  </Button>
                </>
              }
            />
          )}

          {/* Le gel expliqué, à l'endroit exact où il se constate. Sans cette
              phrase, « la vidéo ne bouge plus et les boutons sont gris » se lit
              comme un plantage — c'est la lecture qui a produit le rapport
              « j'augmente la vitesse avant d'analyser et l'écran se fige ». */}
          {analysing && media.source?.file !== undefined && (
            <p role="status" className="text-caption text-ink-muted">
              Lecture suspendue : la vidéo se cale sur l'image analysée.
            </p>
          )}

          {(busy || failed) && (
            <JobProgressBar
              upload={session.upload}
              job={session.job}
              modelLabel={selectedModelLabel}
              onCancel={session.cancel}
              onPause={session.pause}
              onResume={session.resume}
            />
          )}

          {/* Le désaccord de dimensions : dit, jamais tu. Sans ce message, l'écran
              montrerait une analyse qui progresse et un canvas vide, ce qui se lit
              comme « le modèle ne détecte rien ». */}
          {previewMismatch && (
            <p role="alert" className="text-caption text-negative">
              L'aperçu est suspendu : le serveur analyse des images de{" "}
              {session.preview?.frameWidth}×{session.preview?.frameHeight} pixels, alors
              que le lecteur affiche du {scene?.width}×{scene?.height}. Les compteurs,
              eux, restent justes — seul le dessin est suspendu.
            </p>
          )}

          {stale && <StaleResultBanner onRelaunch={launch} canRelaunch={canAnalyse} />}

          {ended && session.result !== null && (
            <PlaybackEndedBanner onReplay={replayFromStart} />
          )}
        </div>

        <aside aria-label="Résultats" className="space-y-4">
          {/* Les chiffres **en tête de colonne**, à hauteur de la scène. C'est ce
              que l'utilisateur vient lire, et c'était en bas de page.

              La colonne ne porte plus que cela : la géométrie est devenue le
              quatrième tiroir de la barre, et les deux boutons de la source sont
              passés dans le lecteur. Ce qui reste ici est homogène — des chiffres,
              et les messages qui expliquent pourquoi il n'y en a pas.

              La **Répartition par type** est dans ces mêmes cartes depuis qu'elle a
              perdu sa section : elle découpe le chiffre de tête, et les séparer par
              un écran de défilement obligeait à retenir un nombre pour vérifier
              l'autre. */}
          {resultStats !== null && (
            <ResultsDashboard
              stats={resultStats.stats}
              lines={geometry.lines}
              includePerson={hasPersonClass}
            />
          )}

          {/* Le direct quand la caméra est la source : c'est l'action qu'on vient
              chercher, et la placer sous vingt curseurs obligerait à défiler pour
              la trouver. */}
          {isCamera && (
            <RealtimePanel
              status={live.status}
              message={live.message}
              retryable={live.retryable}
              pacing={live.pacing}
              stats={live.stats}
              modelId={live.ready?.modelId ?? null}
              device={live.ready?.device ?? null}
              factor={live.factor}
              sendWidth={sendSize.width}
              sendHeight={sendSize.height}
              canStart={liveBlockedReason === null}
              blockedReason={liveBlockedReason}
              onStart={startLive}
              onStop={live.stop}
            />
          )}

          {!serverReady && (
            <p className="text-small text-ink-dim">
              Le serveur est injoignable : l'analyse est indisponible.
            </p>
          )}

          {/* L'attente cachée du premier usage, dite avant le clic et non après.
              `role="status"` et non `alert` : ce n'est pas une erreur, c'est une
              information sur ce qui va se passer. */}
          {pendingDownload !== null && !busy && (
            <p role="status" className="text-small text-warning">
              {pendingDownload}
            </p>
          )}

          {/* « Lancer l'analyse » et « Fermer » sont **dans le lecteur**, à
              l'extrémité de sa rangée de commandes : on choisit sa portion sur le
              rail d'intervalle, puis on lance — deux gestes voisins, qui étaient
              séparés par toute la hauteur de cette colonne. Le rappel « Portion
              retenue » disparaît avec eux : l'intervalle est écrit deux rangées
              au-dessus du bouton, dans l'entête du rail qui le dessine. */}
        </aside>
      </div>

      {/* ── Sous la vidéo : Statistique, camemberts, Registre ───────────────
          Remplace l'ancienne chronologie cliquable et ses cinq onglets : trop
          de détail brut pour une lecture d'ensemble. La barre de lecture
          standard suffit à se déplacer dans le temps ; ce qui reste ici se
          consulte, ne se pilote plus.

          **Ces sections vivent maintenant pendant l'analyse**, plus
          seulement après. Elles n'attendaient la fin que pour une raison
          technique — l'aperçu SSE ne transportait pas de registre — et l'écran
          affichait donc des compteurs qui montaient au-dessus d'une page vide,
          jusqu'à ce que tout apparaisse d'un coup. Un seul jeu de sections, deux
          sources de même forme : plus de branche « pendant » et « après » à
          garder d'accord.

          **La Répartition n'est plus ici** : ses quatre cartes ont rejoint les
          Résultats, dans la colonne de droite. Elle découpe le chiffre de tête
          « Passages en entrée » — leur somme lui est égale par construction — et
          un écran de défilement entre les deux obligeait à retenir un nombre pour
          vérifier l'autre. Le bilan par ligne y a suivi le même chemin, en
          cartes ; ce qui reste ici est ce qu'une colonne de 24 rem ne porte pas —
          les comparatifs entre lignes et le total de véhicules distincts. */}
      {dashboardStats !== null && (
        <>
          <LineFlowDashboard
            stats={dashboardStats}
            lines={geometry.lines}
            vehicles={countedVehicles}
          />

          {/* Deux camemberts côte à côte : la même question, « quelle part »,
              posée sur deux axes différents — par ligne, par type de
              véhicule. */}
          <Suspense
            fallback={
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="h-48 rounded-card bg-surface" />
                <div className="h-48 rounded-card bg-surface" />
              </div>
            }
          >
            <div className="grid gap-3 sm:grid-cols-2">
              <LineFlowChart stats={dashboardStats} lines={geometry.lines} />
              <ClassEntriesChart
                entries={entriesByClass(dashboardStats, geometry.lines)}
                classes={hasPersonClass ? [...VEHICLE_CLASSES, "person"] : VEHICLE_CLASSES}
              />
            </div>
          </Suspense>

          {/* Pas de titre « Registre » ici : `VehicleRegistry` porte déjà le
              sien (« Registre des véhicules »), et l'empiler donnait deux
              titres pour une seule section. */}
          <VehicleRegistry
            result={session.result}
            vehicles={countedVehicles}
            lines={geometry.lines}
            // Suit le réglage réel : la note expliquant les px/s ne doit
            // apparaître que quand l'échelle manque **effectivement**.
            hasScale={settings.pixelsPerMeter !== null && settings.pixelsPerMeter > 0}
          />
        </>
      )}

      {/* La chronologie, **pendant l'analyse et après** — c'est le changement.
          Elle était conditionnée à `session.result === null` et disparaissait donc
          à la seconde où l'analyse terminait, c'est-à-dire au moment précis où l'on
          commence à vérifier un comptage : la vidéo est relisible, le registre dit
          *lesquels*, et cette section est la seule à dire *quand* et *dans quel
          sens*. Après coup, elle lit le résultat complet à la tête de lecture
          (`timelineEvents`), comme tout ce qui l'entoure.

          Elle reste **en dernier** parce qu'elle défile — la mettre au-dessus
          repousserait les sections stables hors de l'écran à chaque franchissement.

          `!live.active` reste, et corrige un panneau vide par construction :
          `session.events` vient du suivi SSE d'un **job**, et le direct n'en a pas.
          En caméra, la section s'affichait avec son « aucun franchissement pour
          l'instant » pour toute la session, sous des compteurs qui montaient — ce qui
          se lit comme un comptage en panne. Le direct n'a pas de journal, et c'est ce
          qu'il faut dire en n'affichant rien plutôt qu'un vide qui ne se remplira
          jamais. */}
      {timelineEvents !== null && !live.active && (
        <CrossingTimeline events={timelineEvents} lines={geometry.lines} live={analysing} />
      )}

      {/* `media.source !== null` en plus de `resultStats === null` : sans vidéo,
          il n'y a même pas de tracé possible, et ce squelette qui promet des
          chiffres n'a pas sa place sur un écran d'arrivée vide. */}
      {resultStats === null && media.source !== null && (
        <section aria-labelledby="results-title">
          <h2 id="results-title" className="label-micro mb-3">
            Résultats
          </h2>
          {/* Le même libellé, la même taille **et la même place** que le tableau de
              bord réel : un écran vide qui promet des chiffres qu'on ne verra
              jamais est pire que pas d'écran vide du tout. Une seule carte, parce
              que le tableau réel n'a plus qu'une tête de lecture — « Objets
              suivis » est passé dans la barre, où rien ne s'affiche avant la
              première analyse. */}
          <MetricCard
            size="lg"
            label="Passages en entrée"
            value="—"
            hint="Total des passages sur les sens marqués « entrée », toutes lignes"
          />
        </section>
      )}

      {/* Monté seulement une fois ouvert : le `<dialog>` est un composant lourd
          — liste réseau comprise — dont personne n'a besoin avant le clic.
          Aucun `fallback` visible : un squelette derrière une modale fermée
          n'aurait rien à montrer. */}
      {/* La modale de lancement, montée seulement une fois ouverte — même règle
          que celle des presets. Elle n'est **pas** chargée paresseusement, elle :
          c'est le passage obligé de l'action principale de l'écran, et faire
          attendre un aller-retour réseau au clic sur « Lancer » échangerait un
          gain invisible contre une latence sur le geste le plus fréquent.

          `durationMs` est relue de la balise à l'ouverture, comme la position :
          la remonter en état obligerait le studio à s'abonner au transport, ce
          que `TransportBar` existe justement pour éviter. */}
      {launchOpen && (
        <LaunchDialog
          open={launchOpen}
          durationMs={secondsToMs(video.current?.duration ?? 0)}
          currentTimeMs={launchTimeMs}
          range={range}
          onRangeChange={setRange}
          onLaunch={launch}
          onCancel={() => setLaunchOpen(false)}
        />
      )}

      {presetsOpen && (
        <Suspense fallback={null}>
          <PresetDialog
            open={presetsOpen}
            scene={scene}
            lines={geometry.lines}
            zones={geometry.zones}
            maskOutsideZones={settings.maskOutsideZones}
            onClose={() => setPresetsOpen(false)}
            onLoad={loadPreset}
          />
        </Suspense>
      )}
    </div>
  );
}

/**
 * L'action qui répare un échec « modèle indisponible ».
 *
 * Un message qui nomme la cause sans proposer le geste laisse l'utilisateur
 * chercher où précharger un modèle — et l'endroit où le faire n'existe nulle part
 * dans l'interface. Ce bouton fait payer le téléchargement **ici**, à un moment
 * choisi, puis relance ; c'est exactement ce que `POST /models/{id}/preload`
 * existe pour permettre.
 *
 * L'état est local à ce composant : il ne survit pas à l'échec qu'il répare, et le
 * remonter dans `StudioPage` ajouterait deux champs à un état déjà large pour une
 * information dont personne d'autre n'a besoin.
 */
function PreloadRetry({
  modelId,
  modelLabel,
  canRelaunch,
  onRelaunch,
}: {
  modelId: string;
  modelLabel: string;
  canRelaunch: boolean;
  onRelaunch: () => void;
}) {
  const [state, setState] = useState<"idle" | "loading" | "failed">("idle");
  const [failure, setFailure] = useState<string | null>(null);

  const run = useCallback(() => {
    setState("loading");
    setFailure(null);
    preloadModel(modelId)
      .then(() => {
        setState("idle");
        // Relance seulement si l'écran s'y prête encore : la source a pu être
        // fermée pendant le téléchargement, et relancer sur rien produirait un
        // second échec dont la cause n'aurait plus aucun rapport avec le premier.
        if (canRelaunch) onRelaunch();
      })
      .catch((cause: unknown) => {
        setState("failed");
        setFailure(cause instanceof Error ? cause.message : "Le préchargement a échoué.");
      });
  }, [modelId, canRelaunch, onRelaunch]);

  return (
    <div className="space-y-1">
      <Button variant="ghost" disabled={state === "loading"} onClick={run}>
        {state === "loading"
          ? `Téléchargement de « ${modelLabel} »…`
          : `Précharger « ${modelLabel} » puis relancer`}
      </Button>
      {state === "loading" && (
        <p className="text-micro text-ink-dim">
          Plusieurs dizaines de mégaoctets : l'opération peut prendre une à deux minutes.
        </p>
      )}
      {failure !== null && <p className="text-micro text-negative">{failure}</p>}
    </div>
  );
}

/**
 * Retire de la configuration reçue ce qui n'est pas un réglage.
 *
 * `lines` et `zones` vont au reducer de géométrie, pas dans les réglages : les y
 * laisser polluerait l'objet persisté en `localStorage` avec une géométrie qui
 * n'appartient pas à la vidéo courante.
 */
function stripGeometry(
  config: Record<string, unknown>,
): Partial<AnalysisSettings> {
  const { lines: _lines, zones: _zones, ...settings } = config;
  return settings as Partial<AnalysisSettings>;
}

/**
 * Explique **pourquoi** le bouton est désactivé.
 *
 * Quatre causes, quatre actions différentes. Un bouton grisé sans explication est le
 * défaut d'interface le plus frustrant : on ne sait pas quoi faire pour l'activer.
 */
function analyseTooltip(
  serverReady: boolean,
  hasFile: boolean,
  geometry: { lines: unknown[]; zones: unknown[] },
  busy: boolean,
): string {
  if (busy) return "Une analyse est déjà en cours";
  if (!serverReady) return "Le serveur est injoignable";
  if (!hasFile) return "Déposez un fichier vidéo : la caméra passe par le mode temps réel";
  if (geometry.lines.length === 0 && geometry.zones.length === 0) {
    return "Ajoutez d'abord une ligne de comptage";
  }
  return "Envoyer la vidéo au serveur pour analyse";
}
