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
import { useModels } from "@/entities/model";
import { JobProgressBar } from "@/features/analysis-job";
import {
  SettingsPanels,
  loadSettings,
  saveSettings,
  toRequest,
  type AnalysisSettings,
} from "@/features/analysis-settings";
import { GeometryCanvas, GeometryPanel } from "@/features/geometry-editor";
import { SourcePicker, VideoScene, useMediaSource } from "@/features/media-source";
import {
  RealtimePanel,
  scaledSize,
  unscaleTracks,
  useRealtimeSession,
} from "@/features/realtime-counting";
import { ResultsDashboard } from "@/features/results-dashboard";
import { chooseBucketMs, flowBuckets, useReplay, vehiclesAt } from "@/features/timeline-replay";
import { VehicleRegistry } from "@/features/vehicle-registry";
import { TransportBar, useVideoTransport } from "@/features/video-transport";
import type { Point } from "@/shared/api/contracts";
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

interface SceneSize {
  width: number;
  height: number;
}

const NO_TRAILS: ReadonlyMap<number, readonly Point[]> = new Map();

export function StudioPage() {
  const { data: health } = useHealth();
  const serverReady = health != null;

  const { data: catalogue } = useModels();
  const location = useLocation();
  const media = useMediaSource();
  const [geometry, dispatch] = useReducer(geometryReducer, EMPTY_GEOMETRY);
  const [scene, setScene] = useState<SceneSize | null>(null);
  const [ended, setEnded] = useState(false);

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

  const video = useRef<HTMLVideoElement>(null);
  const session = useAnalysisSession();

  const handleEnded = useCallback(() => setEnded(true), []);
  const transport = useVideoTransport(video.current, handleEnded);
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
  const canAnalyse = serverReady && media.source?.file !== undefined && hasGeometry(geometry) && !busy;

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
   * Les pistes à dessiner : celles du direct s'il tourne, sinon celles de la relecture.
   *
   * **Remises à l'échelle source** avant d'atteindre le canvas, qui ne connaît qu'un
   * seul repère. Faire la conversion ici et non dans le canvas évite une branche
   * « si direct » dans le code de dessin, qui finirait par diverger.
   */
  const canvasTracks = useMemo(
    () => (live.active ? unscaleTracks(live.tracks, live.factor) : replay.tracks),
    [live.active, live.tracks, live.factor, replay.tracks],
  );

  /**
   * Les statistiques à afficher : celles du direct pendant une session, sinon celles
   * de la tête de lecture.
   *
   * Une seule source pour tout l'écran — badge du canvas, tableau de bord, registre.
   * Deux chemins de statistiques finiraient par se contredire à l'écran, et
   * l'utilisateur n'aurait aucun moyen de savoir lequel croire.
   */
  const liveStats = live.active ? live.stats : replay.stats;

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
      {session.error !== null && (
        <p role="alert" className="text-caption text-negative">
          {session.error}
        </p>
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
                trails={settings.showTrails && !live.active ? replay.trails : NO_TRAILS}
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
                {liveStats !== null && (
                  <p className="rounded-badge bg-base/80 px-2 py-1 text-micro text-ink-muted tabular">
                    Uniques : {liveStats.uniqueVehicles}
                  </p>
                )}
              </div>
            )}
          </VideoScene>

          {media.source !== null && (
            <TransportBar transport={transport} seekable={!isCamera} disabled={busy} />
          )}

          {busy && (
            <JobProgressBar upload={session.upload} job={session.job} onCancel={session.cancel} />
          )}

          {stale && <StaleResultBanner onRelaunch={launch} canRelaunch={canAnalyse} />}

          {ended && session.result !== null && (
            <PlaybackEndedBanner onReplay={transport.restart} />
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
            // Faux si le serveur n'a pas le modèle de plaques : l'option est alors
            // désactivée **avec sa raison**, plutôt que de produire une analyse
            // sans plaques que rien n'expliquerait.
            plateAvailable={catalogue?.plateAvailable ?? false}
            hasZones={geometry.zones.length > 0}
            // Le diagnostic de la dernière analyse. `null` avant : le panneau ne
            // montre alors rien plutôt que six zéros, qui se liraient comme un
            // résultat.
            diagnostics={session.result?.stats.diagnostics ?? null}
            disabled={busy}
            onChange={updateSettings}
          />

          {!serverReady && (
            <p className="text-small text-ink-dim">
              Le serveur est injoignable : l'analyse est indisponible.
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
      ) : replay.stats !== null && session.result !== null ? (
        <div className="space-y-6">
          <ResultsDashboard
            stats={replay.stats}
            lines={geometry.lines}
            zones={geometry.zones}
            processingFps={session.result.processingFps}
            replaying
          />

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
