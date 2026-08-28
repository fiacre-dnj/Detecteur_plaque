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
 *   longueur —, la vitesse de lecture, puis « Lancer l'analyse » et « Fermer ». On choisit sa
 *   portion de vidéo, puis on lance, sans traverser l'écran ;
 * - la **colonne de droite** ne porte plus que des chiffres : le bilan du carrefour,
 *   la Répartition par type qui le découpe, et les messages qui expliquent une
 *   absence de chiffre ;
 * - **une troisième colonne apparaît quand l'analyse a quelque chose à signaler**
 *   (une règle posée sur le tracé, ou une plaque recherchée) : les alertes y vivent,
 *   à hauteur d'œil et à côté de la scène. Elles étaient à deux endroits, tous deux
 *   mauvais — une pile flottante **posée sur la vidéo**, illisible sur du bitume et
 *   qui masquait l'image qu'elle faisait regarder, et une section en bas de page où
 *   personne n'était pendant l'analyse. Les gouttières de la page se sont resserrées
 *   dans le même mouvement (`--app-gutter`) : la colonne est prise sur la marge,
 *   pas sur la scène ;
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
  AlertBellBadge,
  AlertBellIcon,
  AlertsPanel,
  alertsFromResult,
  matchPlate,
  useAlertLog,
} from "@/features/alerts";
import {
  CrossingTimeline,
  JobProgressBar,
  LaunchDialog,
  inputVideoUrl,
  useSyncedPreview,
} from "@/features/analysis-job";
import {
  KEEP_PANELS_OPEN_ATTR,
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
  crossedByClass,
  crossingVehicles,
  visibleClasses,
} from "@/features/results-dashboard";
import { crossingsUpTo, useReplay, vehiclesAt } from "@/features/timeline-replay";
import { VehicleRegistry } from "@/features/vehicle-registry";
import {
  cropToJpeg,
  isArmed as queryIsArmed,
  NO_QUERY,
  VehicleSearchPanel,
  type VehicleQuery,
} from "@/features/vehicle-search";
import { PlaybackFpsBadge, TransportBar } from "@/features/video-transport";
import type { CrossingEvent, Point, Preset, TrackSnapshot } from "@/shared/api/contracts";
import { isTerminal } from "@/shared/api/contracts";
import { platePhotoUrl, vehicleSnapshotUrl } from "@/shared/api/jobUrls";
import { VEHICLE_CLASSES, classLabel } from "@/shared/lib/classes";
import { lineRules } from "@/shared/lib/lineRules";
import { hasAnyRule } from "@/shared/lib/lineViolations";
import { violationCounts } from "@/shared/lib/violationTally";
import { formatSceneTimePrecise } from "@/shared/lib/sceneTime";
import { Button } from "@/shared/ui/Button";
import { SnapshotDialog } from "@/shared/ui/SnapshotDialog";

import { analysisSummaryRows } from "../model/analysisSummary";
import { useAnalysisSession } from "../model/useAnalysisSession";
import { AnalysisSummary } from "./AnalysisSummary";
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
/**
 * La chronologie des franchissements est **masquée**, pas supprimée.
 *
 * `CrossingTimeline`, son modèle (`analysis-job/model/crossingTimeline.ts`) et
 * leurs tests sont intacts : remettre ce drapeau à `true` la rend telle quelle. Elle
 * a laissé sa place à la section « Alertes », qui répond à la question voisine et
 * plus urgente — non pas « qu'est-il passé » mais « qu'est-ce qui mérite qu'on aille
 * voir ».
 *
 * Typé `boolean` et non laissé au littéral : sans cette annotation, TypeScript
 * réduit le type à `false` et l'analyse de lint signale une condition inutile — sur
 * une constante dont l'intérêt est justement de pouvoir changer d'un mot.
 */
const SHOW_CROSSING_TIMELINE: boolean = false;

const NO_CROSSINGS: readonly CrossingEvent[] = [];

/**
 * Le même figé pour les pistes, et pour la même raison référentielle : un tableau
 * neuf à chaque rendu relancerait les effets qui accumulent les alertes.
 */
const NO_TRACKS: readonly TrackSnapshot[] = [];

/**
 * L'identifiant du tiroir « Géométrie », **nommé une fois**.
 *
 * Il sert à deux endroits qui doivent rester d'accord : la déclaration du tiroir
 * passée à `SettingsPanels`, et l'ouverture automatique déclenchée par un clic sur
 * la scène. Deux chaînes littérales finiraient par diverger, et la panne serait
 * muette — un clic sur une ligne qui n'ouvre rien.
 */
const GEOMETRY_PANEL_ID = "geometrie";

/**
 * L'identifiant du tiroir « Alertes ».
 *
 * Nommé pour la même raison que celui de la géométrie, même si un seul endroit
 * l'ouvre aujourd'hui : c'est la clé d'exclusivité de `SettingsPanels`, et une
 * chaîne littérale posée dans un `panels` est exactement ce qu'on recopie ailleurs
 * six mois plus tard.
 */
const ALERTS_PANEL_ID = "alertes";

/**
 * L'identifiant du tiroir de recherche par image.
 *
 * Nommé une fois, comme les deux autres : deux littéraux `"recherche"` finiraient par
 * diverger, et la panne serait muette — une pilule qui n'ouvre plus rien.
 */
const SEARCH_PANEL_ID = "recherche";

export function StudioPage() {
  const { data: health } = useHealth();
  const serverReady = health != null;
  /**
   * L'encodeur d'apparence est-il installé côté serveur ?
   *
   * De `/health` et non d'un réglage : sans ce fichier le tiroir « Recherche » n'est
   * pas monté du tout, exactement comme la cloche d'alertes sans règle posée. Une
   * pilule qui ouvre un panneau annonçant sa propre indisponibilité est du bruit.
   */
  const reidAvailable = health?.reidAvailable ?? false;

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
   * Appliquée **une seule fois par navigation** : sans ce garde, chaque rendu
   * réécraserait les modifications que l'utilisateur vient de faire depuis son
   * arrivée, ce qui rend l'écran impossible à utiliser sans qu'on comprenne
   * pourquoi.
   *
   * Le garde retient **l'état de navigation appliqué**, et non un simple « c'est
   * fait ». La distinction est devenue nécessaire le jour où cette page a cessé
   * d'être démontée en changeant d'onglet (`KeepAlivePages`) : un booléen posé une
   * fois pour toutes ne se réarmerait plus jamais, et le deuxième « Ouvrir » depuis
   * l'historique ne ferait plus rien. `navigate` construit un objet neuf à chaque
   * appel, y compris pour le même job — comparer les identités suffit donc, et
   * c'est ce qui distingue « une nouvelle demande » d'« un rendu de plus ».
   */
  const appliedConfig = useRef<unknown>(null);
  useEffect(() => {
    if (appliedConfig.current === location.state) return;
    const incoming = (location.state as { config?: unknown } | null)?.config;
    if (incoming === undefined) return;
    appliedConfig.current = location.state;

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
  const adopted = useRef<unknown>(null);
  useEffect(() => {
    // Indexé sur l'état de navigation et non sur le montage, même raison que le
    // garde de la configuration ci-dessus : la page survit au changement d'onglet.
    if (adopted.current === location.state) return;
    const state = location.state as { jobId?: unknown; replay?: unknown; fileName?: unknown } | null;
    if (state?.replay !== true || typeof state.jobId !== "string") return;
    adopted.current = location.state;

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
   * Terminer une zone, et **cocher « Ignorer hors zone » avec la première**.
   *
   * Tracer une zone est un geste qui dit « ce qui m'intéresse est là-dedans ». Sans
   * ce défaut, il n'avait pourtant aucun effet sur les chiffres tant qu'une case
   * restée décochée dans un autre tiroir n'était pas trouvée : l'utilisateur voyait
   * son polygone dessiné, comptait toujours ce qui passait dehors, et n'avait
   * aucune raison d'aller chercher la cause dans « Détection ».
   *
   * Trois bornes, et elles sont ce qui distingue un défaut d'une contrainte :
   *
   * - **la première zone seulement.** Décocher puis tracer une deuxième zone
   *   recocherait la case : ce serait combattre un choix explicite, pas en proposer
   *   un. Le passage de « aucune zone » à « une zone » est le seul moment où la
   *   question n'a jamais été posée ;
   * - **le tracé, pas le chargement.** Un preset porte son propre
   *   `maskOutsideZones` (`handleApplyPreset`) et l'impose : c'est la géométrie
   *   enregistrée qui décide, pas ce défaut-ci. Passer par un effet sur
   *   `zones.length` les ferait entrer en collision — le preset poserait `false`,
   *   l'effet le verrait passer à une zone et le remettrait à `true` ;
   * - **rien n'est verrouillé.** La case reste décochable dans « Détection », et
   *   `toRequest` retombe de toute façon à `false` s'il ne reste aucune zone.
   */
  const handleCompleteZone = useCallback(
    (points: Point[]) => {
      dispatch({ type: "addZone", points });
      if (geometry.zones.length === 0) updateSettings({ maskOutsideZones: true });
    },
    [geometry.zones.length, updateSettings],
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
  /**
   * La recherche par véhicule en cours.
   *
   * Ici et non dans `settings`, pour la même raison que l'intervalle d'analyse vit
   * dans `entities/analysis-range` : elle décrit *cette vidéo-ci* et *cette
   * recherche-ci*, pas une préférence. Et surtout `AnalysisSettings` est persisté —
   * une photo de véhicule y tomberait sous le cran de confidentialité que
   * `plateWatchlist` se fait déjà retirer avant l'écriture.
   */
  const [query, setQuery] = useState<VehicleQuery>(NO_QUERY);
  const patchQuery = useCallback(
    (patch: Partial<VehicleQuery>) => setQuery((previous) => ({ ...previous, ...patch })),
    [],
  );

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
    // Les plaques recherchées suivent l'intervalle, et pour la même raison : elles
    // décrivent une **recherche en cours**, pas une préférence. Héritées d'un
    // fichier précédent, elles feraient clignoter des alertes sur une vidéo où
    // personne ne cherchait rien — et l'utilisateur n'aurait aucune raison d'aller
    // voir dans le tiroir Détection pourquoi.
    updateSettings({ plateWatchlist: [] });
    // La recherche par image part avec la vidéo, même raison que la liste de plaques :
    // elle décrit une recherche en cours. `revokeObjectURL` est obligatoire — une
    // adresse non révoquée retient l'image entière pour la vie de l'onglet.
    setQuery((previous) => {
      if (previous.previewUrl !== null) URL.revokeObjectURL(previous.previewUrl);
      return { ...NO_QUERY, threshold: previous.threshold };
    });
    session.reset();
  }, [session, live, updateSettings]);

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
    // La vignette est découpée **au lancement** et non au cadrage : c'est le seul
    // moment où elle sert, et l'obtenir demande un `toBlob` asynchrone qu'il serait
    // absurde de rejouer à chaque déplacement de la souris. Un échec de découpage
    // n'empêche pas l'analyse — elle part alors sans recherche, ce que le tiroir dit.
    void (async () => {
      const thumb = await queryThumbnail(query);
      void session.start(
        file,
        // `toRequest` est le seul endroit qui traduit les réglages en requête : il
        // résout `confidenceThreshold: null` en défaut, met l'échelle nulle à `null`,
        // et désactive le masque quand aucune zone n'existe.
        toRequest(settings, geometry.lines, geometry.zones, range),
        geometry.lines,
        geometry.zones,
        thumb,
      );
    })();
  }, [media.source, serverReady, settings, geometry, session, range, query]);

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
   * Les classes cochées dans « Objets à compter », par **nom COCO**.
   *
   * Décidé ici, pas dans `results-dashboard` : cette feature ne connaît que
   * `AnalysisStats`/`CountingLine[]`, jamais le catalogue de classes ni les
   * réglages — même règle que `ClassPicker` dans `analysis-settings`, dont ce
   * calcul reprend la source.
   *
   * **Le nom COCO et pas l'identifiant** : `cocoName` est la clé des `byClass` du
   * résultat, l'identifiant ne l'est nulle part. La traduction se fait ici, une
   * fois, contre le catalogue qui valide la requête — jamais contre une table
   * recopiée, qui divergerait en silence.
   *
   * Repli sur les quatre véhicules tant que le catalogue n'a pas répondu : sans
   * lui, aucune carte ne s'afficherait sur un résultat pourtant complet, et un
   * serveur momentanément muet effacerait l'écran de résultats.
   */
  const selectedClasses = useMemo<readonly string[]>(() => {
    const known = detectableClasses ?? [];
    if (known.length === 0) return VEHICLE_CLASSES;
    return known
      .filter((entry) => settings.classIds.includes(entry.id))
      .map((entry) => entry.cocoName);
  }, [detectableClasses, settings.classIds]);

  const selectedId = geometry.selection.kind === "none" ? null : geometry.selection.id;

  /**
   * Le tiroir de réglages ouvert, tenu **ici** et non dans `SettingsPanels`.
   *
   * Parce que deux endroits l'ouvrent désormais, et qu'un seul des deux est la
   * barre : cliquer une ligne sur la vidéo déplie « Géométrie ». Le geste et le
   * réglage sont le même acte — on clique un trait pour le nommer, lui donner ses
   * rôles de sens ou sa longueur réelle — et le studio est le seul à voir la scène
   * *et* la barre.
   */
  const [openPanel, setOpenPanel] = useState<string | null>(null);
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

  /**
   * Les règles du tracé — sens interdits et voies réservées — lues sur la géométrie
   * **courante**.
   *
   * Calculées ici et non dans les features qui les consomment : elles demandent le
   * catalogue de classes du serveur, que ni `results-dashboard`, ni
   * `vehicle-registry`, ni `alerts` ne connaissent. Le studio est le seul à voir les
   * deux, comme pour `selectedClasses` juste au-dessus.
   *
   * Sur la géométrie courante, donc : déclarer un sens interdit **après** une
   * analyse fait apparaître ses alertes, son KPI et sa colonne de registre sans rien
   * réanalyser — exactement comme basculer un sens entrée ↔ sortie.
   */
  const alertRules = useMemo(
    () => lineRules(geometry.lines, detectableClasses ?? []),
    [geometry.lines, detectableClasses],
  );

  /**
   * Les rangées du récapitulatif d'avant-analyse.
   *
   * Assemblées ici et pas dans le composant, pour la raison qui vaut partout dans
   * ce fichier : le récapitulatif traverse quatre features — le modèle, les classes
   * détectables, la géométrie, l'intervalle — et seul le studio les connaît toutes.
   */
  const summaryRows = useMemo(
    () =>
      analysisSummaryRows({
        modelLabel: selectedModelLabel,
        // Les libellés du **catalogue serveur**, jamais une liste recopiée : une
        // classe cochée que le serveur ne propose plus disparaît d'elle-même,
        // exactement comme `sanitiseClassIds` la retire de l'envoi.
        classLabels: (detectableClasses ?? [])
          .filter((entry) => settings.classIds.includes(entry.id))
          .map((entry) => entry.label),
        lineCount: geometry.lines.length,
        zoneCount: geometry.zones.length,
        // Compté sur les règles **résolues** et non sur les champs bruts : une voie
        // réservée dont aucune classe n'est reconnue par le catalogue ne restreint
        // rien, et l'annoncer ferait attendre des alertes qui ne viendraient pas.
        ruledLineCount: [...alertRules.values()].filter((rule) => rule.restricted).length,
        range,
        detectPlates: settings.detectPlates,
        readPlateText: settings.detectPlates && settings.readPlateText,
        watchedPlateCount: settings.plateWatchlist.length,
        analysisSpeed: settings.analysisSpeed,
        maxAnalysisFps: settings.maxAnalysisFps,
      }),
    [
      selectedModelLabel,
      detectableClasses,
      settings.classIds,
      settings.detectPlates,
      settings.readPlateText,
      settings.plateWatchlist.length,
      settings.analysisSpeed,
      settings.maxAnalysisFps,
      alertRules,
      geometry.lines.length,
      geometry.zones.length,
      range,
    ],
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
   * La vidéo se cale sur l'image que le serveur analyse, **et les boîtes attendent
   * que cette image soit là**.
   *
   * Uniquement sur une source **fichier** : la vidéo locale est alors le même
   * fichier que celui envoyé, donc le temps de scène désigne exactement la même
   * image des deux côtés. Une caméra n'a pas de temps de scène commun, et le hook
   * y est un passe-plat.
   *
   * La **référence** et non `video.current` : remplir un `ref` ne déclenche aucun
   * rendu, donc le lire ici faisait dépendre l'abonnement d'un rendu ultérieur que
   * rien ne garantit — les premiers aperçus d'une analyse pouvaient être perdus.
   */
  const { preview: shownPreview, displayLagMs } = useSyncedPreview(
    video,
    preview,
    media.source?.file !== undefined,
  );

  /**
   * Les pistes à dessiner : le direct s'il tourne, sinon l'aperçu de l'analyse en
   * cours, sinon la relecture.
   *
   * **Remises à l'échelle source** avant d'atteindre le canvas, qui ne connaît qu'un
   * seul repère. Faire la conversion ici et non dans le canvas évite une branche
   * « si direct » dans le code de dessin, qui finirait par diverger. L'aperçu, lui,
   * est déjà en pixels source : le serveur analyse la vidéo telle qu'elle est.
   *
   * **`shownPreview` et non `preview`, et c'est toute la règle de cet écran :
   * les boîtes suivent l'image, les compteurs suivent le serveur.** `preview` est
   * l'aperçu que le serveur vient d'envoyer ; `shownPreview` est celui dont l'image
   * est réellement à l'écran. Dessiner le premier faisait courir l'overlay devant
   * la vidéo de tout le temps de décodage — « on dirait que le tracker est en
   * avance ». Les compteurs, eux, restent branchés sur `preview` : eux n'ont pas
   * d'image à attendre, et les ralentir pour rien rendrait le comptage tardif.
   */
  const canvasTracks = useMemo(() => {
    if (live.active) return unscaleTracks(live.tracks, live.factor);
    if (shownPreview !== null) return shownPreview.tracks;
    return replay.tracks;
  }, [live.active, live.tracks, live.factor, shownPreview, replay.tracks]);

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
   * La ventilation par type du camembert, calculée **une fois**.
   *
   * Le camembert la reçoit en prop, et `visibleClasses` la relit pour décider
   * quelles parts tracer : deux appels à `crossedByClass` sur les mêmes véhicules
   * seraient un parcours de plus à chaque image d'aperçu.
   *
   * **Elle vient des véhicules et non de `stats` depuis ADR 0045** : le camembert
   * découpe « Passages globaux », donc il compte les mêmes véhicules distincts.
   * `countedVehicles` est déjà la population du registre — la source unique de ce
   * chiffre à l'écran comme dans le tableau.
   */
  const dashboardEntries = useMemo(
    () => crossedByClass(countedVehicles),
    [countedVehicles],
  );

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
   *
   * **`preview` et non `shownPreview`, à l'inverse des boîtes**, et la raison tient
   * à la nature de la donnée : une boîte est un *état*, qu'on peut sauter sans rien
   * perdre — l'image suivante le redonne. Un franchissement est un *événement* :
   * l'aperçu qui le porte est le seul à le porter. Le tampon d'affichage écrase sa
   * cible en attente quand le décodeur prend du retard, donc y faire passer les
   * flashs les ferait purement et simplement disparaître. Même raison que
   * `session.events`, qui accumule le journal sur l'aperçu vivant.
   */
  const flashCrossings = live.active ? live.lastCrossings : (preview?.crossings ?? NO_CROSSINGS);
  const lineFlashes = useLineFlashes(flashCrossings);

  /**
   * Le journal d'alertes **vivant**, alimenté par l'aperçu.
   *
   * Il sert les deux modes : les infractions se dérivent des franchissements, que le
   * différé comme le direct publient. Les plaques, non — le direct n'a pas d'ANPR,
   * donc ses pistes arrivent sans texte et aucune alerte de plaque n'en sort.
   */
  const liveAlerts = useAlertLog({
    crossings: flashCrossings,
    // L'aperçu **vivant** : une alerte est un événement, elle suit le serveur, là où
    // une boîte suit l'image (voir `flashCrossings` juste au-dessus).
    tracks: preview?.tracks ?? NO_TRACKS,
    timestampMs: preview?.timestampMs ?? 0,
    rules: alertRules,
    watchlist: settings.plateWatchlist,
    // Les véhicules de l'aperçu **vivant** : c'est là que vit `matchScore`, les
    // pistes d'une image ne le portant pas. `null` quand rien n'est cherché.
    vehicles: session.preview?.vehicles ?? null,
    matchThreshold: queryIsArmed(query) ? query.threshold : null,
    // Le job identifie la course ; `"live"` couvre la caméra, qui n'a pas de job.
    // Un changement vide le journal, sinon les alertes de l'analyse précédente
    // s'afficheraient au-dessus des nouvelles avec des horodatages qui ne désignent
    // plus rien.
    runId: session.job?.jobId ?? (live.active ? "live" : null),
  });

  /**
   * Les alertes d'un résultat **terminé**, relues à la tête de lecture.
   *
   * Elles remplacent le journal vivant plutôt que de s'y ajouter : le journal est
   * borné, le résultat ne l'est pas, et les règles y sont relues sur le tracé
   * courant. `null` tant qu'aucun résultat n'existe.
   */
  const replayAlerts = useMemo(() => {
    if (session.result === null) return null;
    return alertsFromResult({
      crossings: session.result.crossings,
      // **Tous** les véhicules apparus, pas seulement ceux qui ont franchi une
      // ligne : une plaque recherchée peut appartenir à un véhicule à l'arrêt, et le
      // restreindre ferait manquer exactement le cas qu'on cherche.
      vehicles: vehiclesAt(session.result, replay.timeMs),
      timeMs: replay.timeMs,
      rules: alertRules,
      watchlist: settings.plateWatchlist,
      // `null` quand aucune recherche n'est armée, et **pas** `0` : le second
      // signalerait tout véhicule encodé, donc la totalité du trafic.
      matchThreshold: queryIsArmed(query) ? query.threshold : null,
    });
    // `query` entier et non ses deux champs : `queryIsArmed` lit `file` et le seuil
    // vient de `threshold`, mais l'objet est remplacé à chaque `patchQuery`, donc le
    // décomposer ne gagnerait aucun rendu et ferait mentir la liste de dépendances.
  }, [session.result, replay.timeMs, alertRules, settings.plateWatchlist, query]);

  const alerts = replayAlerts ?? liveAlerts;

  /**
   * Y a-t-il quelque chose à signaler ?
   *
   * Sans règle posée ni plaque recherchée, ni la cloche ni son tiroir n'existent :
   * une cloche muette inviterait à ouvrir un panneau vide, et un panneau « Alertes »
   * vide se lit « rien à signaler » alors que la vérité est « on n'a rien demandé de
   * signaler ».
   */
  const alertsArmed =
    hasAnyRule(alertRules) || settings.plateWatchlist.length > 0 || queryIsArmed(query);

  /**
   * Les totaux d'infraction du résumé, **du même juge que le KPI des Résultats**.
   *
   * Calculés ici et passés au tiroir plutôt que recalculés dedans : `features/alerts`
   * n'a pas le droit d'importer `features/results-dashboard`, et surtout le résumé
   * doit afficher **exactement** le chiffre que « Franchissements interdits » montre
   * à côté. Deux définitions du même total, sur deux surfaces lues à quelques
   * secondes d'intervalle, finiraient par en donner deux.
   *
   * `null` avant toute statistique : le résumé se tait plutôt que d'annoncer zéro
   * infraction sur une analyse qui n'a pas commencé.
   */
  const alertViolations = useMemo(
    () =>
      dashboardStats === null
        ? null
        : violationCounts(dashboardStats, geometry.lines, alertRules),
    [dashboardStats, geometry.lines, alertRules],
  );

  /**
   * La capture ouverte en grand depuis une **alerte**.
   *
   * Tenue ici et non dans `alerts` : la modale a besoin du texte lu, donc du
   * registre complet, que seule cette page possède. Le registre a la sienne, et les
   * deux sont indépendantes — ce sont deux surfaces, pas un état partagé.
   */
  const [alertSnapshot, setAlertSnapshot] = useState<number | null>(null);
  /**
   * Le job dont on peut demander une capture — **en cours ou terminé**.
   *
   * Nommé une fois : le registre, le tiroir d'alertes et la modale doivent viser le
   * même job, et trois expressions identiques recopiées finiraient par diverger le
   * jour où l'une des trois change.
   */
  const snapshotJobId = session.result?.jobId ?? session.job?.jobId ?? null;
  /**
   * Le véhicule de la capture ouverte, cherché **dans la source courante**.
   *
   * Le résultat complet après l'analyse ; le registre de l'aperçu pendant, sans
   * quoi une alerte cliquée en cours d'analyse n'ouvrirait rien — c'est pourtant
   * là que la preuve est le plus attendue, une plaque recherchée se validant à
   * l'œil au moment où elle tombe.
   */
  const alertSnapshotVehicle =
    alertSnapshot === null
      ? null
      : ((session.result?.vehicles ?? countedVehicles).find(
          (entry) => entry.globalId === alertSnapshot,
        ) ?? null);

  /**
   * Amène la vidéo à l'instant d'une alerte.
   *
   * Le seul endroit de cet écran où un clic déplace la lecture, et c'est assumé :
   * l'ancienne chronologie cliquable a été retirée parce qu'on y **parcourait** le
   * temps, ce que la barre de lecture fait déjà. Ici on saute à un fait précis, dont
   * l'instant est justement ce qu'on vient de lire — et une alerte invérifiable ne
   * vaut rien.
   *
   * Inutilisable pendant une analyse ou un direct : la vidéo y est pilotée par
   * l'aperçu, et la déplacer se battrait avec le calage image par image.
   */
  const seekToAlert = useCallback(
    (timestampMs: number) => {
      const element = video.current;
      if (element === null) return;
      element.currentTime = Math.max(0, timestampMs / 1000);
    },
    [],
  );

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
              displayLagMs={displayLagMs}
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
        openPanel={openPanel}
        onOpenPanel={setOpenPanel}
        // **Géométrie devient le quatrième tiroir**, au même niveau que Détection,
        // Comptage et Affichage. Il occupait un panneau permanent de la colonne de
        // droite alors qu'il se règle comme les autres — une fois, avant de lancer —
        // et il repoussait les chiffres qu'on vient lire sous la ligne de flottaison.
        // Passé par `panels` et non importé là-bas : `analysis-settings` ne connaît
        // pas `geometry-editor`, c'est le studio qui câble les deux.
        //
        // **Et les alertes en cinquième**, pour la même raison de câblage et une
        // raison d'écran : elles tenaient une colonne de 18 rem prise sur la vidéo,
        // en permanence, pour une liste qu'on consulte par à-coups. Repliées derrière
        // une cloche elles ne coûtent rien tant qu'on ne les ouvre pas, et la
        // pastille dit l'essentiel sans qu'on ouvre — combien, et est-ce grave
        // (ADR 0044).
        panels={[
          {
            id: GEOMETRY_PANEL_ID,
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
                // Le catalogue vient du serveur et traverse le studio : la feature
                // `geometry-editor` ne connaît ni `analysis-settings` ni la route qui
                // le publie — même câblage que `onOpenPresets` juste dessous.
                classes={detectableClasses ?? []}
                onSetLineKind={(id, kind) => dispatch({ type: "setLineKind", id, kind })}
                onSwapDirections={(id) => dispatch({ type: "swapLineDirections", id })}
                onSetLineClasses={(id, classIds) =>
                  dispatch({ type: "setLineClasses", id, classIds })
                }
                onSetLineZone={(id, zoneId) => dispatch({ type: "setLineZone", id, zoneId })}
                onRemoveLine={(id) => dispatch({ type: "removeLine", id })}
                onRemoveZone={(id) => dispatch({ type: "removeZone", id })}
                onOpenPresets={() => setPresetsOpen(true)}
              />
            ),
          },
          // **Le tiroir n'est monté que s'il y a de quoi le remplir**, exactement
          // comme la colonne qu'il remplace : sans règle posée ni plaque
          // recherchée, une cloche muette inviterait à ouvrir un panneau vide.
          // `AlertsPanel` connaît déjà ce garde (`armed`), et le refaire ici est ce
          // qui retire aussi la **pilule** — un panneau qui rend `null` laisserait
          // sinon un bouton qui n'ouvre rien.
          ...(reidAvailable
            ? [
                {
                  id: SEARCH_PANEL_ID,
                  label: "Recherche",
                  content: (
                    <VehicleSearchPanel
                      query={query}
                      onChange={patchQuery}
                      disabled={busy}
                      available={reidAvailable}
                      loadable={health?.reidLoadable ?? null}
                    />
                  ),
                },
              ]
            : []),
          ...(alertsArmed
            ? [
                {
                  id: ALERTS_PANEL_ID,
                  label: "Alertes",
                  icon: <AlertBellIcon alerts={alerts} />,
                  badge: <AlertBellBadge alerts={alerts} live={analysing || live.active} />,
                  content: (
                    <AlertsPanel
                      alerts={alerts}
                      lines={geometry.lines}
                      armed={alertsArmed}
                      // Le **même** juge que le KPI « Franchissements interdits »
                      // des Résultats, calculé une fois ici : deux appels sur les
                      // mêmes chiffres passeraient encore, deux *définitions* du
                      // total non.
                      violations={alertViolations}
                      live={analysing || live.active}
                      // Le job **en cours ou terminé** : les captures sont écrites
                      // au fil de l'eau depuis ADR 0046, donc une vignette demandée
                      // pendant l'analyse arrive. C'est le moment où une alerte a le
                      // plus besoin de sa preuve.
                      jobId={snapshotJobId}
                      onOpenSnapshot={setAlertSnapshot}
                      // Aucun déplacement de la vidéo pendant qu'elle est pilotée
                      // par l'aperçu : le calage image par image reprendrait la main
                      // aussitôt, et le clic paraîtrait sans effet.
                      onSeek={
                        session.result !== null && !analysing && !live.active
                          ? seekToAlert
                          : undefined
                      }
                    />
                  ),
                },
              ]
            : []),
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
          repoussés sous elle. 23 rem plutôt que 20 : neuf cartes en deux colonnes y
          tiennent sans que les libellés se coupent, et les cartes par ligne — nom
          tronqué, entrées, sorties, solde, barre — y gardent exactement leur
          rendu.

          **Deux pistes, et plus trois.** Les alertes ont occupé une troisième
          colonne de 18 rem, prise sur la scène et sur les résultats (23 → 20 rem).
          Elle réglait tout ce qu'on lui demandait et coûtait sa largeur **en
          permanence** à la vidéo, pour une liste qu'on consulte par à-coups : la
          vidéo est ce qu'on regarde, les alertes sont ce qu'on va chercher. Elles
          sont désormais derrière une cloche dans la barre du studio, où elles ne
          coûtent rien tant qu'on ne les ouvre pas — voir `panels` plus haut et
          ADR 0044. La grille redevient donc inconditionnelle, ce qui supprime du
          même coup la classe calculée et le point de rupture `2xl` qu'elle
          imposait. */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_23rem]">
        <div className="space-y-3">
          <DropZone disabled={busy} onFile={handleFile}>
          <VideoScene
            source={media.source}
            onMetadata={handleMetadata}
            videoRef={video}
            onFile={handleFile}
            disabled={busy}
          >
            {/* `display: contents` : l'enveloppe ne porte que l'attribut, et ne
                génère aucune boîte — le canvas reste positionné par rapport à la
                scène, son bloc conteneur.

                Ce que l'attribut dit : la surface de tracé **pilote** le tiroir de
                réglages (un clic de ligne ouvre « Géométrie »), donc elle n'est pas
                un « en dehors » qui le referme. Sans lui, ouverture et fermeture
                tomberaient dans le même événement — le gestionnaire de document de
                `SettingsPanels` s'exécute après celui de React, donc la fermeture
                gagnerait. */}
            {scene !== null && (
              <div className="contents" {...{ [KEEP_PANELS_OPEN_ATTR]: "" }}>
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
                // Sélectionner une forme sur la scène **déplie « Géométrie »** :
                // cliquer un trait est déjà le début du réglage, et l'utilisateur
                // cliquait puis cherchait dans la barre où le renommer, lui donner
                // ses rôles de sens ou sa longueur réelle.
                //
                // Deux bornes. Rien pendant une analyse ou un direct (`busy`) : le
                // panneau est alors grisé, et ouvrir un formulaire intouchable
                // par-dessus la vidéo qu'on regarde tourner serait du bruit. Et rien
                // sur un clic dans le vide (`null`), qui **désélectionne** — la
                // conclusion d'un réglage, pas son début. Ce que le clic ne fait pas
                // non plus : refermer le tiroir, laissé à `Échap`, au re-clic sur la
                // pilule et au clic hors de la scène.
                onSelect={(selection) => {
                  dispatch({
                    type: "select",
                    selection: (selection ?? { kind: "none" }) as Selection,
                  });
                  if (selection !== null && !busy) setOpenPanel(GEOMETRY_PANEL_ID);
                }}
                onMoveLine={(id, a, b) => dispatch({ type: "moveLine", id, a, b })}
                onMoveZone={(id, points) => dispatch({ type: "moveZone", id, points })}
                onCompleteZone={handleCompleteZone}
                onCancelZone={() => dispatch({ type: "setDrawingZone", drawing: false })}
              />
              </div>
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
            {/* **Rien d'autre sur la scène.** La pile d'alertes flottante vivait ici,
                en bas à droite de l'image : trois cartes sur du bitume, illisibles
                dès que le fond est clair, et qui couvraient la voie de droite —
                c'est-à-dire souvent le véhicule même qu'elles signalaient. Les
                alertes sont maintenant dans la troisième colonne, à côté de la
                scène : visibles pendant l'analyse sans rien recouvrir. */}
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

        {/* Les deux colonnes de droite portent **les mêmes** classes de calage, et
            c'est ce qui fait qu'elles se lisent comme une paire : collées sous la
            barre, alignées en haut de la rangée (`self-start`, sans quoi un enfant
            de grille s'étire et `sticky` n'a plus rien à faire), et chacune avec son
            propre défilement borné à la hauteur de la fenêtre.

            Sans le défilement propre, la colonne la plus longue — dix lignes tracées
            d'un côté, deux cents alertes de l'autre — imposerait sa hauteur à la
            rangée, donc à la scène : la vidéo se retrouverait en haut d'un bloc de
            trois écrans de vide. */}
        <aside
          aria-label="Résultats"
          className={[
            "min-w-0 space-y-4 panel-scroll",
            "2xl:sticky 2xl:top-[calc(var(--app-header-h,0px)+3.75rem)] 2xl:self-start",
            // `panel-scroll` : la barre du système fait 17 px opaques sur Windows,
            // soit 5 % d'une colonne de 20 rem, et `scrollbar-gutter: stable` évite
            // que les cartes sautent au moment où la barre apparaît.
            "2xl:max-h-[calc(100dvh-var(--app-header-h,0px)-5rem)] 2xl:overflow-y-auto",
          ].join(" ")}
        >
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
              rules={alertRules}
              stats={resultStats.stats}
              lines={geometry.lines}
              // **La même liste qu'au registre, et c'est le point.** « Passages
              // globaux » vaut le nombre de rangées du tableau ; les faire lire
              // deux sources différentes les ferait diverger d'un véhicule sans
              // que rien ne plante, et c'est exactement le contrôle que
              // l'utilisateur fait en les comparant.
              vehicles={countedVehicles}
              selectedClasses={selectedClasses}
              // Le même repère « en direct » que la colonne des alertes, et pour la
              // même raison : ces cartes sont **identiques** pendant l'analyse et
              // après, un seul jeu de composants pour deux sources de même forme. Ce
              // qu'aucun chiffre ne dit, c'est laquelle on regarde.
              live={analysing || live.active}
            />
          )}

          {/* Ce qui remplit la colonne avant la première analyse : les réglages qui partiront au
              serveur, relus d'un coup. Ils vivent dans quatre tiroirs de la barre,
              et les vérifier demandait d'ouvrir les quatre — pendant que la place
              pour les lire tous ensemble restait inoccupée juste à côté.

              Pas en caméra : le direct n'a ni portion à choisir ni plaques, et
              `RealtimePanel` occupe déjà cette place avec ce qui le concerne. */}
          {resultStats === null && media.source !== null && !isCamera && (
            <AnalysisSummary rows={summaryRows} />
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
          « Passages globaux » — leur somme lui est égale par construction — et
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
              posée sur deux axes différents — par ligne, par type de véhicule.

              **`lg` et non `sm` pour les mettre côte à côte** : chaque camembert est
              un dessin de 7 rem plus une légende dont la largeur utile est de 11 rem,
              et à 640 px de large en deux colonnes la légende passait sous le dessin
              — deux blocs étroits et hauts au lieu de deux graphiques. Au-delà, les
              deux légendes se mettent d'elles-mêmes en deux colonnes (`auto-fill`),
              ce qui est exactement ce qu'il faut quand le tracé porte dix lignes. */}
          <Suspense
            fallback={
              <div className="grid gap-3 lg:grid-cols-2">
                <div className="h-48 rounded-card bg-surface" />
                <div className="h-48 rounded-card bg-surface" />
              </div>
            }
          >
            <div className="grid items-stretch gap-3 lg:grid-cols-2">
              <LineFlowChart stats={dashboardStats} lines={geometry.lines} />
              <ClassEntriesChart
                entries={dashboardEntries}
                // Mêmes classes que les cartes de `ResultsDashboard`, par le
                // même juge : deux listes divergeraient sur un décochage, et le
                // camembert montrerait une part que les KPI ne montrent pas.
                classes={visibleClasses(selectedClasses, dashboardEntries)}
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
            rules={alertRules}
            // Le job **en cours ou terminé** depuis ADR 0046 : les captures sont
            // écrites au moment où elles sont retenues, donc la colonne se remplit
            // pendant que le tableau se remplit. Elle apparaît d'elle-même — sans
            // ANPR ni OCR aucun véhicule ne porte de `snapshotScore`, donc
            // `hasSnapshots` reste faux et la colonne n'existe pas.
            jobId={snapshotJobId}
            // Le **même** seuil que celui du tiroir d'alertes, passé plutôt que
            // recalculé : `vehicle-registry` n'importe pas `vehicle-search`, et un
            // véhicule signalé dans les alertes doit être teinté ici. `null` retire
            // la colonne — pas de recherche, rien à classer.
            matchThreshold={queryIsArmed(query) ? query.threshold : null}
            // Autorise le seul réessai de vignette. Aucun chiffre, aucune colonne.
            live={analysing}
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
      {SHOW_CROSSING_TIMELINE && timelineEvents !== null && !live.active && (
        <CrossingTimeline events={timelineEvents} lines={geometry.lines} live={analysing} />
      )}

      {/* La capture ouverte depuis une alerte. Montée seulement une fois ouverte :
          un `<dialog>` fermé ne rend rien, et ses deux images ne doivent pas se
          charger tant que personne ne les regarde.

          **Elle s'ouvre aussi pendant l'analyse** depuis ADR 0046 : la condition
          était `session.result !== null`, ce qui rendait la vignette d'une alerte
          cliquable et sans effet au moment précis où l'on veut vérifier une plaque
          recherchée. Le garde est maintenant l'existence d'un job, quel que soit son
          état. */}
      {snapshotJobId !== null && alertSnapshotVehicle !== null && (
        <SnapshotDialog
          open
          onClose={() => setAlertSnapshot(null)}
          title={`${classLabel(alertSnapshotVehicle.label)} #${alertSnapshotVehicle.globalId}`}
          subtitle={
            alertSnapshotVehicle.snapshotMs == null
              ? undefined
              : `capturée à ${formatSceneTimePrecise(alertSnapshotVehicle.snapshotMs)}`
          }
          vehicleSrc={vehicleSnapshotUrl(
            snapshotJobId,
            alertSnapshotVehicle.globalId,
            alertSnapshotVehicle.snapshotMs,
          )}
          plateSrc={platePhotoUrl(
            snapshotJobId,
            alertSnapshotVehicle.globalId,
            alertSnapshotVehicle.snapshotMs,
          )}
          plateText={alertSnapshotVehicle.plateText}
          // La plaque **recherchée** sous la plaque **lue** : c'est là que
          // l'opérateur tranche, en regardant la vignette. Une correspondance
          // annoncée « probable » ne se valide pas autrement.
          watched={matchPlate(alertSnapshotVehicle.plateText, settings.plateWatchlist)?.watched}
        />
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
/**
 * La vignette à envoyer, ou `null` — pas de recherche, ou image inexploitable.
 *
 * Hors du composant : elle ne lit aucun état React et n'a pas à être recréée à chaque
 * rendu. Elle charge l'image **une fois de plus** depuis son `previewUrl`, parce qu'un
 * `HTMLImageElement` déjà décodé par le navigateur pour l'aperçu n'est pas accessible
 * d'ici — et que le coût est un décodage local sur une photo de quelques centaines de
 * kilooctets, au moment d'un clic.
 */
async function queryThumbnail(query: VehicleQuery): Promise<Blob | null> {
  if (query.file === null || query.previewUrl === null) return null;
  const image = new Image();
  const url = query.previewUrl;
  const loaded = await new Promise<boolean>((resolve) => {
    image.addEventListener("load", () => resolve(true), { once: true });
    image.addEventListener("error", () => resolve(false), { once: true });
    image.src = url;
  });
  if (!loaded) return null;
  return cropToJpeg(image, query.crop);
}

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
