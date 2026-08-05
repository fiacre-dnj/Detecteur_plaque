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

import { Suspense, lazy, useCallback, useMemo, useReducer, useRef, useState } from "react";

import { useHealth } from "@/app/layout/useHealth";
import {
  EMPTY_GEOMETRY,
  geometryReducer,
  geometrySignature,
  hasGeometry,
  type Selection,
} from "@/entities/geometry";
import { JobProgressBar } from "@/features/analysis-job";
import { GeometryCanvas, GeometryPanel } from "@/features/geometry-editor";
import { SourcePicker, VideoScene, useMediaSource } from "@/features/media-source";
import { ResultsDashboard } from "@/features/results-dashboard";
import { chooseBucketMs, flowBuckets, useReplay, vehiclesAt } from "@/features/timeline-replay";
import { VehicleRegistry } from "@/features/vehicle-registry";
import { TransportBar, useVideoTransport } from "@/features/video-transport";
import type { AnalysisRequest, Point } from "@/shared/api/contracts";
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

/**
 * Réglages par défaut, identiques à ceux du serveur.
 *
 * Le panneau qui les rend modifiables arrive au lot 12. Les aligner sur les défauts
 * du backend garantit qu'entre-temps l'affichage du canvas (pointillés sous
 * `minHits`) correspond à ce qu'une analyse fait réellement.
 */
const DEFAULTS = {
  confidenceThreshold: 0.35,
  iouThreshold: 0.45,
  minHits: 2,
  maxLostMs: 2_500,
  reidMinSimilarity: 0.8,
  frameStride: 1,
} as const;

const NO_TRAILS: ReadonlyMap<number, readonly Point[]> = new Map();

export function StudioPage() {
  const { data: health } = useHealth();
  const serverReady = health != null;

  const media = useMediaSource();
  const [geometry, dispatch] = useReducer(geometryReducer, EMPTY_GEOMETRY);
  const [scene, setScene] = useState<SceneSize | null>(null);
  const [showTrails, setShowTrails] = useState(true);
  const [maskOutsideZones, setMaskOutsideZones] = useState(false);
  const [ended, setEnded] = useState(false);

  const video = useRef<HTMLVideoElement>(null);
  const session = useAnalysisSession();

  const handleEnded = useCallback(() => setEnded(true), []);
  const transport = useVideoTransport(video.current, handleEnded);
  const replay = useReplay(video.current, session.result);

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

  /** Changer de source remet tout à zéro : la géométrie est en pixels de la source. */
  const resetForNewSource = useCallback(() => {
    dispatch({ type: "clear" });
    setScene(null);
    setEnded(false);
    session.reset();
  }, [session]);

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

    const request: AnalysisRequest = {
      modelId: health.defaultModelId,
      ...DEFAULTS,
      maskOutsideZones,
      detectPlates: false,
      plateConfidence: null,
      pixelsPerMeter: null,
      lines: [...geometry.lines],
      zones: [...geometry.zones],
    };
    setEnded(false);
    void session.start(file, request, geometry.lines, geometry.zones);
  }, [media.source, serverReady, health, maskOutsideZones, geometry, session]);

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
  const busy = analysing || session.starting;
  const canAnalyse = serverReady && media.source?.file !== undefined && hasGeometry(geometry) && !busy;

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
                tracks={replay.tracks}
                trails={showTrails ? replay.trails : NO_TRAILS}
                selectedId={selectedId}
                drawingZone={geometry.drawingZone}
                showTrails={showTrails}
                maskOutsideZones={maskOutsideZones}
                minHits={DEFAULTS.minHits}
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
                {replay.stats !== null && (
                  <p className="rounded-badge bg-base/80 px-2 py-1 text-micro text-ink-muted tabular">
                    Uniques : {replay.stats.uniqueVehicles}
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

          <div className="rounded-section bg-surface p-4 shadow-card">
            <h3 className="label-micro">Affichage</h3>
            <p className="mt-3 text-small text-ink-dim">
              {serverReady
                ? `Modèle : ${health.defaultModelId} · ${health.device === "cpu" ? "CPU" : "CUDA"}`
                : "Le serveur est injoignable : l'analyse est indisponible."}
            </p>
            <label className="mt-3 flex items-center gap-2 text-small text-ink-muted">
              <input
                type="checkbox"
                checked={showTrails}
                onChange={(event) => setShowTrails(event.target.checked)}
                className="accent-accent"
              />
              Trajectoires
            </label>
            <label
              className="mt-2 flex items-center gap-2 text-small text-ink-muted"
              title={
                geometry.zones.length === 0
                  ? "Tracez d'abord une zone : sans zone, il n'y a rien à masquer."
                  : "Le détecteur ne reçoit que l'intérieur des zones."
              }
            >
              <input
                type="checkbox"
                checked={maskOutsideZones}
                disabled={geometry.zones.length === 0 || busy}
                onChange={(event) => setMaskOutsideZones(event.target.checked)}
                className="accent-accent disabled:opacity-50"
              />
              Ignorer hors zone
            </label>
          </div>

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

      {replay.stats !== null && session.result !== null ? (
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
            hasScale={false}
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
