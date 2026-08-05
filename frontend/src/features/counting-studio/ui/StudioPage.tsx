/**
 * Le Studio — l'écran unique de comptage.
 *
 * Disposition : la scène à gauche, les réglages à droite, les résultats en pleine
 * largeur dessous. Cette proportion rend l'édition de géométrie confortable : le
 * canvas a besoin de largeur, les curseurs n'en ont pas besoin.
 *
 * **Ce que ce composant fait, et ne fait pas.** Il câble les features entre elles
 * et détient l'état partagé : la source, la géométrie, les dimensions de la scène.
 * Il ne dessine rien lui-même, ne calcule aucune géométrie et ne parle pas au
 * réseau — chacune de ces responsabilités vit dans sa feature.
 *
 * Le lot 10 s'arrête au dépôt et au tracé. Le bouton « Lancer l'analyse » sait déjà
 * dire pourquoi il est désactivé, mais l'envoi lui-même arrive au lot 11.
 */

import { useCallback, useReducer, useRef, useState } from "react";

import { useHealth } from "@/app/layout/useHealth";
import {
  EMPTY_GEOMETRY,
  geometryReducer,
  hasGeometry,
  type Selection,
} from "@/entities/geometry";
import { GeometryCanvas, GeometryPanel } from "@/features/geometry-editor";
import { SourcePicker, VideoScene, useMediaSource } from "@/features/media-source";
import { TransportBar, useVideoTransport } from "@/features/video-transport";
import type { Point } from "@/shared/api/contracts";
import { Button } from "@/shared/ui/Button";
import { MetricCard } from "@/shared/ui/MetricCard";

/** Dimensions de la vidéo source. `null` avant `loadedmetadata`. */
interface SceneSize {
  width: number;
  height: number;
}

/**
 * Valeur de `minHits` utilisée pour l'affichage tant que le panneau « Comptage »
 * n'existe pas (lot 12). La même que le défaut du serveur, pour que les pointillés
 * du canvas correspondent à ce qu'une analyse ferait réellement.
 */
const DEFAULT_MIN_HITS = 2;

/** Aucune trajectoire hors relecture — la carte est vide au lot 10. */
const NO_TRAILS: ReadonlyMap<number, readonly Point[]> = new Map();

export function StudioPage() {
  const { data: health } = useHealth();
  const serverReady = health != null;

  const media = useMediaSource();
  const [geometry, dispatch] = useReducer(geometryReducer, EMPTY_GEOMETRY);
  const [scene, setScene] = useState<SceneSize | null>(null);
  const [showTrails, setShowTrails] = useState(true);

  const video = useRef<HTMLVideoElement>(null);
  const transport = useVideoTransport(video.current, undefined);

  /**
   * Les métadonnées sont connues : on ancre la géométrie **et on amorce une
   * première ligne**.
   *
   * L'amorce n'est pas un gadget : un écran sans ligne ne compte rien, et
   * l'utilisateur qui lance une analyse et obtient zéro ne devine pas que c'est
   * parce qu'il n'a rien tracé. La ligne pré-tracée transforme un écran muet en
   * point de départ modifiable.
   */
  const handleMetadata = useCallback(
    (size: SceneSize) => {
      if (size.width === 0 || size.height === 0) return;
      setScene(size);
      if (!hasGeometry(geometry)) {
        dispatch({ type: "addLine", width: size.width, height: size.height });
      }
    },
    [geometry],
  );

  /**
   * Changer de source **remet tout à zéro**.
   *
   * La géométrie est en pixels de la source : la garder d'une vidéo 1920×1080 à
   * une 640×480 laisserait des lignes hors cadre, invisibles et pourtant
   * présentes dans la requête.
   */
  const resetForNewSource = useCallback(() => {
    dispatch({ type: "clear" });
    setScene(null);
  }, []);

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

  const selectedId =
    geometry.selection.kind === "none" ? null : geometry.selection.id;
  const isCamera = media.source?.kind === "camera";
  const canAnalyse = serverReady && media.source?.file !== undefined && hasGeometry(geometry);

  return (
    <div className="space-y-6">
      <SourcePicker
        activeKind={media.source?.kind ?? null}
        disabled={false}
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

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="space-y-3">
          <VideoScene source={media.source} onMetadata={handleMetadata} videoRef={video}>
            {scene !== null && (
              <GeometryCanvas
                sourceWidth={scene.width}
                sourceHeight={scene.height}
                lines={geometry.lines}
                zones={geometry.zones}
                tracks={[]}
                trails={NO_TRAILS}
                selectedId={selectedId}
                drawingZone={geometry.drawingZone}
                showTrails={showTrails}
                maskOutsideZones={false}
                minHits={DEFAULT_MIN_HITS}
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

            {/* HUD discret : les dimensions réellement reçues. C'est le premier
                filet contre une géométrie mal ancrée — un chiffre inattendu ici
                explique immédiatement des compteurs faux. */}
            {scene !== null && (
              <p className="pointer-events-none absolute end-2 top-2 rounded-badge bg-base/80 px-2 py-1 text-micro text-ink-muted">
                {scene.width}×{scene.height}
              </p>
            )}
          </VideoScene>

          {media.source !== null && (
            <TransportBar transport={transport} seekable={!isCamera} />
          )}
        </div>

        <aside aria-label="Réglages" className="space-y-4">
          <GeometryPanel
            lines={geometry.lines}
            zones={geometry.zones}
            selection={geometry.selection}
            drawingZone={geometry.drawingZone}
            disabled={scene === null}
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
            <h3 className="label-micro">Détection</h3>
            <p className="mt-3 text-small text-ink-dim">
              {serverReady
                ? `Modèle par défaut : ${health.defaultModelId} · ${health.device === "cpu" ? "CPU" : "CUDA"}`
                : "Le serveur est injoignable : le sélecteur de modèle sera disponible à sa reconnexion."}
            </p>
            <label className="mt-3 flex items-center gap-2 text-small text-ink-muted">
              <input
                type="checkbox"
                checked={showTrails}
                onChange={(event) => setShowTrails(event.target.checked)}
                className="accent-accent"
              />
              Afficher les trajectoires
            </label>
          </div>

          <Button
            variant="primary"
            className="w-full"
            disabled={!canAnalyse}
            title={analyseTooltip(serverReady, media.source?.file !== undefined, geometry)}
          >
            Lancer l'analyse serveur
          </Button>

          {media.source !== null && (
            <Button variant="ghost" className="w-full" onClick={handleClose}>
              Fermer la source
            </Button>
          )}
        </aside>
      </div>

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
    </div>
  );
}

/**
 * Explique **pourquoi** le bouton est désactivé.
 *
 * Trois causes distinctes, trois actions différentes de la part de l'utilisateur.
 * Un bouton grisé sans explication est le défaut d'interface le plus frustrant
 * qui soit : on ne sait pas quoi faire pour l'activer.
 */
function analyseTooltip(
  serverReady: boolean,
  hasFile: boolean,
  geometry: { lines: unknown[]; zones: unknown[] },
): string {
  if (!serverReady) return "Le serveur est injoignable";
  if (!hasFile) return "Déposez un fichier vidéo : la caméra passe par le mode temps réel";
  if (geometry.lines.length === 0 && geometry.zones.length === 0) {
    return "Ajoutez d'abord une ligne de comptage";
  }
  return "Envoyer la vidéo au serveur pour analyse";
}
