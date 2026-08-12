/**
 * Le Studio — l'écran unique de comptage.
 *
 * Disposition : la scène à gauche, les réglages à droite, les résultats en pleine
 * largeur dessous. Cette proportion rend l'édition de géométrie confortable : le
 * canvas a besoin de largeur, les curseurs n'en ont pas besoin.
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
import { CrossingLog, JobProgressBar, useFollowAnalysis } from "@/features/analysis-job";
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
import { SourcePicker, VideoScene, useMediaSource } from "@/features/media-source";
import {
  RealtimePanel,
  scaledSize,
  unscaleTracks,
  useRealtimeSession,
} from "@/features/realtime-counting";
import { ResultsDashboard } from "@/features/results-dashboard";
import {
  chooseBucketMs,
  crossingsUpTo,
  flowBuckets,
  useReplay,
  vehiclesAt,
} from "@/features/timeline-replay";
import { VehicleRegistry } from "@/features/vehicle-registry";
import { TransportBar } from "@/features/video-transport";
import type { CrossingEvent, Point, Preset } from "@/shared/api/contracts";
import { isTerminal } from "@/shared/api/contracts";
import { Button } from "@/shared/ui/Button";
import { MetricCard } from "@/shared/ui/MetricCard";

import { useAnalysisSession } from "../model/useAnalysisSession";
import { PlaybackEndedBanner, StaleResultBanner } from "./StaleResultBanner";

/**
 * L'histogramme est **chargé paresseusement** : il n'apparaît qu'après une analyse,
 * et le faire payer au premier chargement taxerait tous ceux qui n'analysent rien.
 */
const FlowHistogram = lazy(() =>
  import("@/features/results-dashboard/ui/FlowHistogram").then((module) => ({
    default: module.FlowHistogram,
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
   * La vidéo suit-elle l'analyse ?
   *
   * Activé par défaut : c'est la raison d'être de l'aperçu — voir le modèle
   * travailler sur l'image qu'il analyse. Désactivable parce qu'on veut parfois
   * s'arrêter sur une image pour la regarder pendant que l'analyse continue.
   */
  const [follow, setFollow] = useState(true);

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

  const replay = useReplay(video.current, session.result);
  const live = useRealtimeSession(video.current);

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
    session.reset();
  }, [session, live]);

  const handleFile = useCallback(
    (file: File) => {
      resetForNewSource();
      media.selectFile(file);
    },
    [media, resetForNewSource],
  );

  const handleDemo = useCallback(() => {
    resetForNewSource();
    media.selectDemo();
  }, [media, resetForNewSource]);

  const handleCamera = useCallback(() => {
    resetForNewSource();
    void media.selectCamera();
  }, [media, resetForNewSource]);

  const handleClose = useCallback(() => {
    resetForNewSource();
    media.clear();
  }, [media, resetForNewSource]);

  const launch = useCallback(() => {
    const file = media.source?.file;
    if (file === undefined || !serverReady) return;

    setEnded(false);
    void session.start(
      file,
      // `toRequest` est le seul endroit qui traduit les réglages en requête : il
      // résout `confidenceThreshold: null` en défaut, met l'échelle nulle à `null`,
      // et désactive le masque quand aucune zone n'existe.
      toRequest(settings, geometry.lines, geometry.zones),
      geometry.lines,
      geometry.zones,
    );
  }, [media.source, serverReady, settings, geometry, session]);

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

  const lineNames = useMemo(
    () => new Map(geometry.lines.map((line) => [line.id, line.name])),
    [geometry.lines],
  );

  const buckets = useMemo(
    () =>
      session.result === null
        ? []
        : flowBuckets(session.result.crossings, session.result.video.durationMs),
    [session.result],
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
  useFollowAnalysis(
    video.current,
    preview?.timestampMs ?? null,
    follow && media.source?.file !== undefined,
  );

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
    <div className="space-y-6">
      <SourcePicker
        activeKind={media.source?.kind ?? null}
        disabled={busy}
        requestingCamera={media.requestingCamera}
        onFile={handleFile}
        onDemo={handleDemo}
        onCamera={handleCamera}
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

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="space-y-3">
          <VideoScene source={media.source} onMetadata={handleMetadata} videoRef={video}>
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

            {scene !== null && (
              <div className="pointer-events-none absolute end-2 top-2 flex flex-col items-end gap-1">
                {/* Les dimensions **réellement reçues** : premier filet contre une
                    géométrie mal ancrée. Un chiffre inattendu ici explique
                    immédiatement des compteurs faux. */}
                <p className="rounded-badge bg-base/80 px-2 py-1 text-micro text-ink-muted tabular">
                  {scene.width}×{scene.height}
                </p>
                {/* En direct, les dimensions **d'envoi** en plus de celles de la
                    scène : c'est le repère dans lequel le serveur compte, et le voir
                    à côté de la source rend la réduction évidente. */}
                {live.active && sendSize.width > 0 && (
                  <p className="rounded-badge bg-base/80 px-2 py-1 text-micro text-ink-muted tabular">
                    → {sendSize.width}×{sendSize.height}
                  </p>
                )}
                {/* L'image analysée, pendant l'analyse. Un décalage entre la vidéo
                    et l'overlay s'explique alors d'un coup d'œil, au lieu de se
                    lire comme un défaut de détection. */}
                {preview !== null && (
                  <p className="rounded-badge bg-base/80 px-2 py-1 text-micro text-ink-muted tabular">
                    Image {preview.frameIndex}
                  </p>
                )}
                {liveStats !== null && (
                  <p className="rounded-badge bg-base/80 px-2 py-1 text-micro text-ink-muted tabular">
                    Uniques : {liveStats.uniqueVehicles}
                  </p>
                )}
              </div>
            )}
          </VideoScene>

          {/* `busy && follow` et non `busy` seul : le gel de la vidéo est **voulu**
              — `useFollowAnalysis` la cale sur l'image analysée — mais il n'est
              subi que tant que le suivi est coché. Décocher rend donc la main,
              conformément à la règle « désactivé ⇒ aucune écriture » du hook.
              Griser inconditionnellement laissait l'utilisateur devant une vidéo
              figée et des boutons morts, sans un mot d'explication. */}
          {media.source !== null && (
            <TransportBar
              videoRef={video}
              seekable={!isCamera}
              disabled={busy && follow}
              onEnded={handleEnded}
            />
          )}

          {/* Le gel expliqué, à l'endroit exact où il se constate. Sans cette
              phrase, « la vidéo ne bouge plus et les boutons sont gris » se lit
              comme un plantage — c'est la lecture qui a produit le rapport
              « j'augmente la vitesse avant d'analyser et l'écran se fige ». */}
          {analysing && follow && media.source?.file !== undefined && (
            <p role="status" className="text-caption text-ink-muted">
              Lecture suspendue : la vidéo se cale sur l'image analysée. Décochez
              « Suivre l'analyse » pour reprendre la main.
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

          {analysing && media.source?.file !== undefined && (
            <label className="flex items-center gap-2 text-small text-ink-muted">
              <input
                type="checkbox"
                checked={follow}
                onChange={(event) => setFollow(event.target.checked)}
                className="size-4 accent-accent"
              />
              Suivre l'analyse — la vidéo se cale sur l'image analysée
            </label>
          )}


          {stale && <StaleResultBanner onRelaunch={launch} canRelaunch={canAnalyse} />}

          {ended && session.result !== null && (
            <PlaybackEndedBanner onReplay={replayFromStart} />
          )}
        </div>

        <aside aria-label="Réglages" className="space-y-4">
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
            onSetLineZone={(id, zoneId) => dispatch({ type: "setLineZone", id, zoneId })}
            onRemoveLine={(id) => dispatch({ type: "removeLine", id })}
            onRemoveZone={(id) => dispatch({ type: "removeZone", id })}
            onOpenPresets={() => setPresetsOpen(true)}
          />

          {/* Le direct **avant** les réglages quand la caméra est la source : c'est
              l'action qu'on vient chercher, et la placer sous vingt curseurs
              obligerait à défiler pour la trouver. */}
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

          <SettingsPanels
            settings={settings}
            models={catalogue?.models ?? []}
            // Le catalogue de classes vient du serveur, jamais d'une liste écrite
            // côté interface : c'est lui qui valide `classIds` à l'envoi.
            detectableClasses={detectableClasses ?? []}
            // Faux si le serveur n'a pas le modèle de plaques : l'option est alors
            // désactivée **avec sa raison**, plutôt que de produire une analyse
            // sans plaques que rien n'expliquerait.
            plateAvailable={catalogue?.plateAvailable ?? false}
            plateOcrAvailable={catalogue?.plateOcrAvailable ?? false}
            hasZones={geometry.zones.length > 0}
            // Le diagnostic **vivant** pendant l'analyse, celui de la dernière
            // sinon. C'est ce qui permet de comprendre pendant que ça tourne
            // pourquoi un véhicule n'est pas compté — masqué, pas confirmé,
            // écarté comme doublon — au lieu de l'apprendre à la fin.
            // `null` avant toute analyse : le panneau ne montre alors rien plutôt
            // que six zéros, qui se liraient comme un résultat.
            diagnostics={
              liveStats?.diagnostics ?? session.result?.stats.diagnostics ?? null
            }
            disabled={busy}
            onChange={updateSettings}
          />

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

          <Button
            variant="primary"
            className="w-full"
            disabled={!canAnalyse}
            onClick={launch}
            title={analyseTooltip(serverReady, media.source?.file !== undefined, geometry, busy)}
          >
            Lancer l'analyse serveur
          </Button>

          {media.source !== null && (
            <Button variant="ghost" className="w-full" onClick={handleClose} disabled={busy}>
              Fermer la source
            </Button>
          )}
        </aside>
      </div>

      {/* Le direct affiche le tableau de bord **sans** histogramme ni registre : ces
          deux-là dérivent de la timeline complète, qui n'existe qu'en différé. Montrer
          un histogramme vide se lirait comme « aucun véhicule ». */}
      {live.active && live.stats !== null ? (
        <ResultsDashboard
          stats={live.stats}
          lines={geometry.lines}
          zones={geometry.zones}
          // Le débit d'analyse en direct est celui du serveur, déduit de la latence
          // aller-retour : la seule mesure de performance honnête dont on dispose ici.
          processingFps={live.pacing.latencyMs === null ? 0 : 1000 / live.pacing.latencyMs}
          replaying={false}
        />
      ) : preview !== null ? (
        // Pendant l'analyse : les compteurs montent en direct, sans histogramme ni
        // registre — les deux dérivent de la timeline complète, qui n'existe qu'à
        // la fin. Un histogramme vide se lirait comme « aucun véhicule ».
        <ResultsDashboard
          stats={preview.stats}
          lines={geometry.lines}
          zones={geometry.zones}
          // La cadence du serveur, telle que la progression la rapporte.
          processingFps={session.job?.processingFps ?? 0}
          replaying={false}
        >
          {/* Le journal juste après la répartition : c'est lui qui rend le total
              vérifiable événement par événement, au moment où il est compté. Il
              se lit donc à côté des chiffres qu'il détaille, et non sous la
              vidéo, où il éloignait la scène de ses résultats. */}
          <CrossingLog events={session.events} lineNames={lineNames} />
        </ResultsDashboard>
      ) : replay.stats !== null && session.result !== null ? (
        <div className="space-y-6">
          <ResultsDashboard
            stats={replay.stats}
            lines={geometry.lines}
            zones={geometry.zones}
            processingFps={session.result.processingFps}
            replaying
          >
            {/* Le journal survit à la fin de l'analyse, calé sur la tête de lecture.
                Sans lui, la plaque au moment du comptage disparaissait avec l'aperçu :
                le registre dit *lesquels*, le journal dit *quand*. */}
            <CrossingLog
              events={crossingsUpTo(session.result, replay.timeMs)}
              lineNames={lineNames}
              title="Franchissements jusqu'ici"
            />
          </ResultsDashboard>

          <Suspense fallback={<div className="h-24 rounded-card bg-surface" />}>
            <FlowHistogram
              buckets={buckets}
              bucketMs={chooseBucketMs(session.result.video.durationMs)}
            />
          </Suspense>

          <VehicleRegistry
            result={session.result}
            vehicles={vehiclesAt(session.result, replay.timeMs)}
            lineNames={lineNames}
            // Suit le réglage réel : la note de bas de tableau expliquant les px/s
            // ne doit apparaître que quand l'échelle manque **effectivement**.
            hasScale={settings.pixelsPerMeter !== null && settings.pixelsPerMeter > 0}
          />
        </div>
      ) : (
        <section aria-labelledby="results-title">
          <h2 id="results-title" className="label-micro mb-3">
            Résultats
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Véhicules uniques" value="—" hint="Tous types confondus" />
            <MetricCard label="Franchissements" value="—" hint="Somme des deux sens" />
            <MetricCard label="Ré-identifications" value="—" hint="Retours après occlusion" />
            <MetricCard
              label="Débit estimé"
              value="—"
              hint="Disponible après 3 s de flux analysé"
            />
          </div>
        </section>
      )}

      {/* Monté seulement une fois ouvert : le `<dialog>` est un composant lourd
          — liste réseau comprise — dont personne n'a besoin avant le clic.
          Aucun `fallback` visible : un squelette derrière une modale fermée
          n'aurait rien à montrer. */}
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
