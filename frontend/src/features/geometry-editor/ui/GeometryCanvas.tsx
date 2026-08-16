/**
 * Le canvas d'édition, en superposition de la vidéo.
 *
 * **Le piège 42, et pourquoi le brouillon vit dans un `ref`.** Un double-clic
 * livre au navigateur deux `pointerdown` **et** le `dblclick` dans un seul cycle de
 * rendu React. Si le brouillon de polygone vivait dans un `state`, le second
 * `pointerdown` et le `dblclick` liraient tous les deux la valeur du rendu
 * précédent — donc une liste de sommets périmée, sans le dernier point posé. La
 * zone fermée perdrait un sommet, ou se fermerait sur une liste trop courte et
 * serait silencieusement ignorée.
 *
 * La source de vérité est donc `draftRef`. Un `state` la double **uniquement pour
 * déclencher le rendu** ; aucune décision ne le lit.
 *
 * Deux autres obligations :
 * - `touch-none` et `setPointerCapture` : le glisser fonctionne au doigt et ne se
 *   perd pas en sortant du canvas — sans capture, relâcher hors du cadre laisse la
 *   forme collée au curseur pour toujours ;
 * - un `ResizeObserver` redessine : la géométrie est en pixels source, donc un
 *   redimensionnement du lecteur ne change pas les données mais change leur
 *   conversion.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { CountingLine, Point, TrackSnapshot, Zone } from "@/shared/api/contracts";
import { clampToSource } from "@/shared/lib/geometry";

import { drawScene, type Viewport } from "../model/draw";
import { closesPolygon, hitTest, repeatsLastVertex, selectionOf, type Hit } from "../model/hitTest";
import type { LineFlash } from "../model/lineFlashes";

/** Aucun flash — table figée, pour ne pas rerendre le canvas à chaque image. */
const NO_FLASHES: ReadonlyMap<string, LineFlash> = new Map();

export interface GeometryCanvasProps {
  /** Dimensions de la **vidéo source** — le repère de toute la géométrie. */
  sourceWidth: number;
  sourceHeight: number;
  lines: readonly CountingLine[];
  zones: readonly Zone[];
  tracks: readonly TrackSnapshot[];
  trails: ReadonlyMap<number, readonly Point[]>;
  selectedId: string | null;
  drawingZone: boolean;
  showTrails: boolean;
  maskOutsideZones: boolean;
  minHits: number;
  /** Lignes qui viennent de compter. Omis hors comptage. */
  lineFlashes?: ReadonlyMap<string, LineFlash>;
  /**
   * Une analyse serveur est en cours — différée ou en direct.
   *
   * Estompe le nom de la ligne et les libellés de sens (`drawScene`), jamais le
   * reste : la géométrie est déjà validée à ce stade, c'est le train de boîtes et
   * de compteurs qui mérite l'attention. Un sens qui vient de compter reste net
   * malgré tout — voir `dimLabels` dans `draw.ts`.
   */
  analysing?: boolean;
  onSelect: (selection: { kind: "line" | "zone"; id: string } | null) => void;
  onMoveLine: (id: string, a: Point, b: Point) => void;
  onMoveZone: (id: string, points: Point[]) => void;
  onCompleteZone: (points: Point[]) => void;
  onCancelZone: () => void;
}

/** Un glisser en cours, avec son décalage de préhension. */
interface Drag {
  hit: Hit;
  /** Position de départ du curseur, en pixels source. */
  origin: Point;
  /** Géométrie au début du glisser — la translation part de là, pas du dernier pas. */
  lineStart?: { a: Point; b: Point };
  zoneStart?: Point[];
}

export function GeometryCanvas(props: GeometryCanvasProps) {
  const { sourceWidth, sourceHeight, drawingZone } = props;
  const canvas = useRef<HTMLCanvasElement>(null);

  /**
   * **La source de vérité du brouillon.** Lue par tous les gestionnaires
   * d'événements, jamais depuis le state.
   */
  const draftRef = useRef<Point[]>([]);
  /** Miroir du brouillon, uniquement pour provoquer un rendu. */
  const [draftVersion, setDraftVersion] = useState(0);
  const cursor = useRef<Point | null>(null);
  const drag = useRef<Drag | null>(null);
  const [, forceRedraw] = useState(0);

  /** Rapport pixels source / pixel CSS — l'inverse du facteur de dessin. */
  const sourcePerCssPixel = useCallback((): number => {
    const element = canvas.current;
    if (element === null || sourceWidth === 0) return 1;
    const rect = element.getBoundingClientRect();
    return rect.width === 0 ? 1 : sourceWidth / rect.width;
  }, [sourceWidth]);

  /** Convertit un événement pointeur en point de la **vidéo source**. */
  const toSource = useCallback(
    (event: React.PointerEvent | React.MouseEvent): Point => {
      const element = canvas.current;
      if (element === null) return { x: 0, y: 0 };
      const rect = element.getBoundingClientRect();
      const scaleX = rect.width === 0 ? 1 : sourceWidth / rect.width;
      const scaleY = rect.height === 0 ? 1 : sourceHeight / rect.height;
      return clampToSource(
        { x: (event.clientX - rect.left) * scaleX, y: (event.clientY - rect.top) * scaleY },
        sourceWidth,
        sourceHeight,
      );
    },
    [sourceWidth, sourceHeight],
  );

  /* ── Dessin ───────────────────────────────────────────────────────────── */

  const render = useCallback(() => {
    const element = canvas.current;
    if (element === null || sourceWidth === 0 || sourceHeight === 0) return;

    const rect = element.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;

    // `devicePixelRatio` : sans lui le canvas est flou sur tout écran moderne, et
    // les traits d'un pixel disparaissent purement et simplement.
    const dpr = window.devicePixelRatio || 1;
    const pixelWidth = Math.round(rect.width * dpr);
    const pixelHeight = Math.round(rect.height * dpr);
    if (element.width !== pixelWidth) element.width = pixelWidth;
    if (element.height !== pixelHeight) element.height = pixelHeight;

    const ctx = element.getContext("2d");
    if (ctx === null) return;

    const view: Viewport = {
      scaleX: pixelWidth / sourceWidth,
      scaleY: pixelHeight / sourceHeight,
      width: pixelWidth,
      height: pixelHeight,
    };

    drawScene(ctx, view, {
      lines: props.lines,
      zones: props.zones,
      tracks: props.tracks,
      trails: props.trails,
      draft: draftRef.current,
      cursor: cursor.current,
      selectedId: props.selectedId,
      showTrails: props.showTrails,
      maskOutsideZones: props.maskOutsideZones,
      minHits: props.minHits,
      lineFlashes: props.lineFlashes ?? NO_FLASHES,
      dimLabels: props.analysing ?? false,
    });
  }, [
    sourceWidth,
    sourceHeight,
    props.lines,
    props.zones,
    props.tracks,
    props.trails,
    props.selectedId,
    props.showTrails,
    props.maskOutsideZones,
    props.minHits,
    // Sans cette dépendance, le halo apparaîtrait à la première image et ne
    // s'éteindrait jamais : la boucle d'animation change la table, pas les
    // lignes, et le canvas ne redessinerait donc pas.
    props.lineFlashes,
    props.analysing,
  ]);

  // Redessine à chaque changement de données **et** de brouillon.
  useEffect(render, [render, draftVersion]);

  // Redessine au redimensionnement : les données sont en pixels source, mais leur
  // conversion dépend de la taille affichée.
  useEffect(() => {
    const element = canvas.current;
    if (element === null) return;
    const observer = new ResizeObserver(() => render());
    observer.observe(element);
    return () => observer.disconnect();
  }, [render]);

  /* ── Tracé de zone ────────────────────────────────────────────────────── */

  const bumpDraft = useCallback(() => setDraftVersion((version) => version + 1), []);

  const cancelDraft = useCallback(() => {
    draftRef.current = [];
    cursor.current = null;
    bumpDraft();
    props.onCancelZone();
  }, [bumpDraft, props]);

  const completeDraft = useCallback(() => {
    // Lu depuis le `ref` : c'est tout l'intérêt du dispositif.
    const points = draftRef.current;
    if (points.length >= 3) props.onCompleteZone([...points]);
    draftRef.current = [];
    cursor.current = null;
    bumpDraft();
  }, [bumpDraft, props]);

  // `Échap` annule le tracé. Écouté sur la fenêtre : le canvas n'a pas le focus
  // clavier pendant un tracé à la souris.
  useEffect(() => {
    if (!drawingZone) return;
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") cancelDraft();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawingZone, cancelDraft]);

  // Sortir du mode tracé jette le brouillon : le laisser réapparaîtrait à la
  // prochaine activation, ce que personne n'attend.
  useEffect(() => {
    if (!drawingZone && draftRef.current.length > 0) {
      draftRef.current = [];
      cursor.current = null;
      bumpDraft();
    }
  }, [drawingZone, bumpDraft]);

  /* ── Pointeur ─────────────────────────────────────────────────────────── */

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLCanvasElement>) => {
      const point = toSource(event);
      const scale = sourcePerCssPixel();

      if (drawingZone) {
        const draft = draftRef.current;
        // Clic sur le premier sommet : ferme. L'un des deux gestes de fermeture.
        if (closesPolygon(point, draft, scale)) {
          completeDraft();
          return;
        }
        // **Le garde du double-clic** : le second `pointerdown` ne doit pas
        // ajouter un sommet au même endroit, sinon la zone porte une arête de
        // longueur nulle.
        if (repeatsLastVertex(point, draft, scale)) return;

        draftRef.current = [...draft, point];
        bumpDraft();
        return;
      }

      const hit = hitTest(point, props.lines, props.zones, scale);
      props.onSelect(selectionOf(hit));
      if (hit.kind === "none") return;

      // **`setPointerCapture`** : sans lui, relâcher hors du canvas ne déclenche
      // pas `pointerup` et la forme reste collée au curseur pour toujours.
      event.currentTarget.setPointerCapture(event.pointerId);

      const line = props.lines.find((candidate) => candidate.id === hit.id);
      const zone = props.zones.find((candidate) => candidate.id === hit.id);
      drag.current = {
        hit,
        origin: point,
        ...(line !== undefined ? { lineStart: { a: line.a, b: line.b } } : {}),
        ...(zone !== undefined ? { zoneStart: [...zone.points] } : {}),
      };
    },
    [toSource, sourcePerCssPixel, drawingZone, completeDraft, bumpDraft, props],
  );

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLCanvasElement>) => {
      const point = toSource(event);

      if (drawingZone) {
        // Segment élastique vers le curseur : dans un `ref`, comme le brouillon,
        // parce qu'il change à chaque mouvement de souris et qu'un state ici
        // re-rendrait le composant soixante fois par seconde.
        cursor.current = point;
        forceRedraw((tick) => tick + 1);
        return;
      }

      const current = drag.current;
      if (current === null) return;

      // **Le décalage de préhension.** On applique le delta depuis l'origine du
      // glisser, jamais la position absolue du curseur : sinon la forme saute
      // sous la souris au premier pixel de mouvement.
      const delta = { x: point.x - current.origin.x, y: point.y - current.origin.y };

      switch (current.hit.kind) {
        case "lineHandle": {
          if (current.lineStart === undefined) return;
          const moved = clampToSource(point, sourceWidth, sourceHeight);
          const { a, b } = current.lineStart;
          props.onMoveLine(
            current.hit.id,
            current.hit.end === "a" ? moved : a,
            current.hit.end === "b" ? moved : b,
          );
          break;
        }
        case "lineBody": {
          if (current.lineStart === undefined) return;
          const a = { x: current.lineStart.a.x + delta.x, y: current.lineStart.a.y + delta.y };
          const b = { x: current.lineStart.b.x + delta.x, y: current.lineStart.b.y + delta.y };
          // Tout ou rien : borner chaque extrémité séparément ferait pivoter la
          // ligne au lieu de la faire glisser.
          if (inside(a, sourceWidth, sourceHeight) && inside(b, sourceWidth, sourceHeight)) {
            props.onMoveLine(current.hit.id, a, b);
          }
          break;
        }
        case "zoneVertex": {
          if (current.zoneStart === undefined) return;
          const points = [...current.zoneStart];
          points[current.hit.index] = clampToSource(point, sourceWidth, sourceHeight);
          props.onMoveZone(current.hit.id, points);
          break;
        }
        case "zoneBody": {
          if (current.zoneStart === undefined) return;
          const points = current.zoneStart.map((vertex) => ({
            x: vertex.x + delta.x,
            y: vertex.y + delta.y,
          }));
          if (points.every((vertex) => inside(vertex, sourceWidth, sourceHeight))) {
            props.onMoveZone(current.hit.id, points);
          }
          break;
        }
        case "none":
          break;
      }
    },
    [toSource, drawingZone, sourceWidth, sourceHeight, props],
  );

  const handlePointerUp = useCallback((event: React.PointerEvent<HTMLCanvasElement>) => {
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }, []);

  return (
    <canvas
      ref={canvas}
      // `touch-none` : sans lui, le navigateur interprète le glisser comme un
      // défilement de page et l'édition est impossible au doigt.
      className={[
        "absolute inset-0 size-full touch-none",
        drawingZone ? "cursor-crosshair" : "cursor-pointer",
      ].join(" ")}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      // Le second geste de fermeture. Le `ref` garantit qu'on lit ici les sommets
      // à jour, y compris celui que le `pointerdown` de ce même double-clic vient
      // d'ajouter.
      onDoubleClick={() => {
        if (drawingZone) completeDraft();
      }}
    />
  );
}

function inside(point: Point, width: number, height: number): boolean {
  return point.x >= 0 && point.x <= width && point.y >= 0 && point.y <= height;
}
