/**
 * Le tiroir « Recherche » — importer une photo, la cadrer, régler la ressemblance.
 *
 * Fourni au studio comme `ExtraPanel`, exactement comme « Géométrie » et « Alertes » :
 * `analysis-settings` ne connaît pas cette feature, c'est le studio qui câble.
 *
 * **Trois choses que cet écran doit dire, et qui ne se devinent pas :**
 *
 * - **le cadrage sert à quelque chose de précis**, et l'aide le dit : le serveur
 *   compare la vignette envoyée à des vignettes de véhicules détectés. Une photo pleine
 *   met la voiture sur un tiers de l'entrée du réseau là où la galerie la met sur la
 *   totalité, et la similarité devient sans rapport avec la ressemblance ;
 * - **le résultat est une liste de candidats, pas un verdict.** Mesuré : deux vues du
 *   même véhicule descendent à 0,387 de similarité, deux véhicules différents montent
 *   à 0,891. Le curseur est donc un arbitrage rappel / précision que l'utilisateur doit
 *   voir, pas un seuil de justesse caché ;
 * - **le curseur ne demande aucune réanalyse**, parce que le serveur publie le score
 *   brut. Le dire évite qu'on relance une analyse de dix minutes pour l'ajuster.
 */

import { ImageOff, Search, Upload, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/shared/ui/Button";

import {
  clampCrop,
  DEFAULT_MATCH_THRESHOLD,
  FULL_CROP,
  type CropRect,
  type VehicleQuery,
} from "../model/query";

export interface VehicleSearchPanelProps {
  query: VehicleQuery;
  onChange: (patch: Partial<VehicleQuery>) => void;
  /** Grisé pendant une analyse ou un direct : la requête part au lancement. */
  disabled: boolean;
  /**
   * L'encodeur est-il installé côté serveur ?
   *
   * Faux ⇒ on le **dit** au lieu de laisser importer une photo qui ne servira à rien.
   * C'est la même honnêteté que les trois états de l'ANPR : une option qui accepte un
   * réglage sans effet est pire qu'une option absente.
   */
  available: boolean;
  /** L'auto-test a-t-il échoué ? `null` = pas encore testé, ce n'est pas un échec. */
  loadable: boolean | null;
}

export function VehicleSearchPanel({
  query,
  onChange,
  disabled,
  available,
  loadable,
}: VehicleSearchPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (file: File | null) => {
      if (file === null) return;
      // L'ancienne adresse est révoquée **avant** d'en créer une autre : un
      // `createObjectURL` non révoqué retient l'image entière pour la vie de l'onglet,
      // et une recherche s'ajuste par essais successifs.
      if (query.previewUrl !== null) URL.revokeObjectURL(query.previewUrl);
      onChange({ file, previewUrl: URL.createObjectURL(file), crop: FULL_CROP });
    },
    [onChange, query.previewUrl],
  );

  const clear = useCallback(() => {
    if (query.previewUrl !== null) URL.revokeObjectURL(query.previewUrl);
    onChange({ file: null, previewUrl: null, crop: FULL_CROP });
  }, [onChange, query.previewUrl]);

  if (!available) {
    return (
      <p className="text-sm text-muted">
        La recherche par image demande un encodeur d'apparence que ce serveur n'a pas.
        Récupérez-le avec <code>scripts/fetch_reid_model.py</code>, puis redémarrez. Les
        comptages, les plaques et les captures ne dépendent pas de ce fichier.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {loadable === false && (
        <p role="status" className="text-sm text-warning">
          Les poids de l'encodeur sont présents mais ne se chargent pas : la recherche
          restera muette. Le suffixe <code>.onnx</code> fait partie du contrat, et un
          graphe dont la sortie n'a pas 512 dimensions est refusé.
        </p>
      )}

      {query.file === null ? (
        <button
          type="button"
          disabled={disabled}
          onClick={() => inputRef.current?.click()}
          className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-line px-4 py-6 text-sm text-muted transition hover:border-accent hover:text-fg disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Upload aria-hidden className="size-5" />
          <span>Importer la photo du véhicule à rechercher</span>
          <span className="text-xs">
            Cadrez-la sur la voiture seule : c'est ce qui décide de la qualité de la
            comparaison.
          </span>
        </button>
      ) : (
        <CropEditor
          previewUrl={query.previewUrl}
          crop={query.crop}
          onCrop={(crop) => onChange({ crop })}
          onClear={clear}
          disabled={disabled}
          fileName={query.file.name}
        />
      )}

      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => handleFile(event.target.files?.[0] ?? null)}
      />

      <label className="flex flex-col gap-1">
        <span className="flex items-baseline justify-between text-sm">
          <span>Ressemblance minimale</span>
          <span className="font-mono text-muted">{query.threshold.toFixed(2)}</span>
        </span>
        <input
          type="range"
          min={0}
          max={0.95}
          step={0.01}
          value={query.threshold}
          disabled={disabled}
          onChange={(event) => onChange({ threshold: Number(event.target.value) })}
          className="accent-accent"
        />
        <span className="text-xs text-muted">
          Descendre trouve plus de candidats et plus de faux. Mesuré : deux vues du même
          véhicule peuvent tomber à 0,39, deux véhicules différents monter à 0,89 — donc
          ce curseur classe, il ne tranche pas.{" "}
          <strong>Il ne demande aucune réanalyse</strong> : le serveur publie le score
          brut.
        </span>
      </label>

      <button
        type="button"
        disabled={disabled || query.threshold === DEFAULT_MATCH_THRESHOLD}
        onClick={() => onChange({ threshold: DEFAULT_MATCH_THRESHOLD })}
        className="self-start text-xs text-muted underline disabled:no-underline disabled:opacity-40"
      >
        Défaut
      </button>
    </div>
  );
}

interface CropEditorProps {
  previewUrl: string | null;
  crop: CropRect;
  onCrop: (crop: CropRect) => void;
  onClear: () => void;
  disabled: boolean;
  fileName: string;
}

/**
 * Le cadrage : un rectangle glissable sur l'aperçu, en **fractions** de l'image.
 *
 * Fractions et non pixels, même raison que l'invariant 2 côté serveur : l'aperçu est
 * affiché à une largeur CSS qui n'a rien à voir avec l'image réelle, et retenir des
 * pixels d'affichage donnerait un recadrage qui se déplace quand la fenêtre change de
 * taille.
 */
function CropEditor({
  previewUrl,
  crop,
  onCrop,
  onClear,
  disabled,
  fileName,
}: CropEditorProps) {
  const frameRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const [broken, setBroken] = useState(false);

  useEffect(() => setBroken(false), [previewUrl]);

  const pointFor = useCallback((event: PointerEvent | React.PointerEvent) => {
    const frame = frameRef.current;
    if (frame === null) return null;
    const bounds = frame.getBoundingClientRect();
    if (bounds.width < 1 || bounds.height < 1) return null;
    return {
      x: (event.clientX - bounds.left) / bounds.width,
      y: (event.clientY - bounds.top) / bounds.height,
    };
  }, []);

  const handleDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (disabled) return;
      const point = pointFor(event);
      if (point === null) return;
      // `setPointerCapture` : sans lui, sortir de l'aperçu en glissant perd le
      // rectangle en cours et laisse un cadrage à moitié posé. Même geste que
      // `GeometryCanvas`.
      event.currentTarget.setPointerCapture(event.pointerId);
      setDrag(point);
      onCrop(clampCrop({ x: point.x, y: point.y, width: 0, height: 0 }));
    },
    [disabled, onCrop, pointFor],
  );

  const handleMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (drag === null) return;
      const point = pointFor(event);
      if (point === null) return;
      onCrop(
        clampCrop({
          x: Math.min(drag.x, point.x),
          y: Math.min(drag.y, point.y),
          width: Math.abs(point.x - drag.x),
          height: Math.abs(point.y - drag.y),
        }),
      );
    },
    [drag, onCrop, pointFor],
  );

  const full = crop.width >= 1 && crop.height >= 1;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="truncate text-muted" title={fileName}>
          {fileName}
        </span>
        <Button variant="ghost" size="sm" onClick={onClear} disabled={disabled}>
          <X aria-hidden className="size-3.5" />
          Retirer
        </Button>
      </div>

      {previewUrl === null || broken ? (
        <p className="flex items-center gap-2 rounded-lg border border-line px-3 py-6 text-sm text-muted">
          <ImageOff aria-hidden className="size-4" />
          Cette image n'a pas pu être affichée.
        </p>
      ) : (
        <div
          ref={frameRef}
          onPointerDown={handleDown}
          onPointerMove={handleMove}
          onPointerUp={() => setDrag(null)}
          onPointerCancel={() => setDrag(null)}
          className="relative touch-none select-none overflow-hidden rounded-lg border border-line"
        >
          <img
            src={previewUrl}
            alt="Véhicule recherché"
            onError={() => setBroken(true)}
            className="block max-h-64 w-full object-contain"
            draggable={false}
          />
          {!full && (
            <div
              aria-hidden
              className="pointer-events-none absolute border-2 border-accent bg-accent/10"
              style={{
                left: `${crop.x * 100}%`,
                top: `${crop.y * 100}%`,
                width: `${crop.width * 100}%`,
                height: `${crop.height * 100}%`,
              }}
            />
          )}
        </div>
      )}

      <p className="flex items-start gap-1.5 text-xs text-muted">
        <Search aria-hidden className="mt-0.5 size-3.5 shrink-0" />
        <span>
          {full
            ? "Glissez sur l'image pour cadrer la voiture seule. Sans cadrage, toute la photo est envoyée — l'arrière-plan compte alors dans la comparaison."
            : "Reglissez pour recadrer. Seule cette zone part au serveur."}
        </span>
      </p>
    </div>
  );
}
