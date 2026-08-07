/**
 * Le dessin du canvas. **L'ordre des passes est le contrat visuel**, pas un détail.
 *
 * `prompt/09` §2.4 le fixe, et chaque position a une raison :
 *
 * 1. **le masque even-odd d'abord** — l'utilisateur doit voir exactement ce que le
 *    détecteur reçoit ; dessiné après, il voilerait les boîtes et on ne saurait
 *    plus si un véhicule a été masqué ou simplement raté ;
 * 2. zones, puis 3. trajectoires, puis 4. boîtes — du contexte vers le détail ;
 * 5. **les lignes après les boîtes** — une ligne cachée sous un camion serait
 *    insaisissable à la souris, alors que c'est l'objet qu'on manipule le plus ;
 * 6. le polygone en cours **tout en haut** — c'est l'action présente.
 *
 * Tout est stocké en **pixels source** et converti au dessin (invariant 2). La
 * conversion inclut le `devicePixelRatio` : sans lui, le canvas est flou sur tout
 * écran moderne, et les traits fins d'un pixel disparaissent complètement.
 */

import type { Box, CountingLine, Point, TrackSnapshot, Zone } from "@/shared/api/contracts";
import { CANVAS, TRAJECTORY_ALPHA, classColor } from "@/shared/config/palettes";
import { midpoint, positiveNormal } from "@/shared/lib/geometry";
import { bestReadPlate, plateLabel } from "@/shared/lib/plate";

import type { LineFlash } from "./lineFlashes";

/** Conversion pixels source → pixels de dessin du canvas. */
export interface Viewport {
  /** Facteur d'échelle, `devicePixelRatio` inclus. */
  scaleX: number;
  scaleY: number;
  /** Dimensions du canvas en pixels de dessin. */
  width: number;
  height: number;
}

export interface DrawOptions {
  lines: readonly CountingLine[];
  zones: readonly Zone[];
  /** Pistes de la frame courante — vide hors relecture. */
  tracks: readonly TrackSnapshot[];
  /** Trajectoires par identité, reconstituées côté client. */
  trails: ReadonlyMap<number, readonly Point[]>;
  /** Brouillon de polygone, **lu depuis un `ref`** (voir `GeometryCanvas`). */
  draft: readonly Point[];
  /** Position du curseur, pour le segment élastique du tracé. */
  cursor: Point | null;
  selectedId: string | null;
  showTrails: boolean;
  maskOutsideZones: boolean;
  /** Images minimales avant qu'une piste puisse compter — pointillés en dessous. */
  minHits: number;
  /**
   * Lignes qui viennent de compter, par identifiant.
   *
   * Vide en dehors d'un franchissement. C'est ce qui relie à l'œil le tracé et le
   * compteur : un total qui monte ne dit pas **quelle** ligne a compté ni dans
   * quel sens, et sur trois lignes proches c'est précisément ce qui manque pour
   * valider une géométrie.
   */
  lineFlashes: ReadonlyMap<string, LineFlash>;
}

/** Dessine la scène complète, dans l'ordre imposé. */
export function drawScene(
  ctx: CanvasRenderingContext2D,
  view: Viewport,
  options: DrawOptions,
): void {
  ctx.clearRect(0, 0, view.width, view.height);
  ctx.lineJoin = "round";
  ctx.lineCap = "round";

  if (options.maskOutsideZones && options.zones.length > 0) {
    drawMask(ctx, view, options.zones);
  }
  for (const zone of options.zones) {
    drawZone(ctx, view, zone, zone.id === options.selectedId);
  }
  if (options.showTrails) {
    drawTrails(ctx, view, options.tracks, options.trails);
  }
  for (const track of options.tracks) {
    drawTrack(ctx, view, track, options.minHits);
  }
  for (const line of options.lines) {
    drawLine(
      ctx,
      view,
      line,
      line.id === options.selectedId,
      options.lineFlashes.get(line.id) ?? null,
    );
  }
  if (options.draft.length > 0) {
    drawDraft(ctx, view, options.draft, options.cursor);
  }
}

/**
 * Le voile des zones masquées, en règle **even-odd**.
 *
 * Un seul chemin : le rectangle de l'image entière, puis chaque zone. La règle
 * even-odd « perce » les zones dans le voile, ce qui montre littéralement ce que
 * le détecteur reçoit. Dessiner un voile par zone donnerait des recouvrements plus
 * sombres là où deux zones se chevauchent — l'inverse de l'information voulue.
 */
function drawMask(ctx: CanvasRenderingContext2D, view: Viewport, zones: readonly Zone[]): void {
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, 0, view.width, view.height);
  for (const zone of zones) {
    if (zone.points.length < 3) continue;
    traceePolygon(ctx, view, zone.points);
  }
  ctx.fillStyle = CANVAS.maskFill;
  ctx.fill("evenodd");
  ctx.restore();
}

function drawZone(
  ctx: CanvasRenderingContext2D,
  view: Viewport,
  zone: Zone,
  selected: boolean,
): void {
  if (zone.points.length < 3) return;

  ctx.save();
  ctx.beginPath();
  traceePolygon(ctx, view, zone.points);
  // `+"1f"` : l'alpha en hexadécimal, comme le veut `prompt/09` — un remplissage
  // à 12 % qui teinte sans masquer la scène.
  ctx.fillStyle = `${zone.color}1f`;
  ctx.fill();
  ctx.strokeStyle = zone.color;
  ctx.lineWidth = selected ? 3 : 2;
  ctx.stroke();
  ctx.restore();

  for (const point of zone.points) {
    drawHandle(ctx, view, point, zone.color, selected);
  }

  const anchor = zone.points[0];
  if (anchor !== undefined) {
    drawLabel(ctx, view, anchor, zone.name, zone.color, { dy: -14 });
  }
}

/**
 * Une ligne de comptage : le trait, ses poignées A/B, son étiquette, et la
 * **flèche du sens positif**.
 *
 * La flèche vient de `positiveNormal`, dont le signe est vérifié par un test
 * contre `sideOfLine` : c'est elle qui dit à l'utilisateur quel sens le serveur
 * appellera `+1`. Une flèche inversée ferait lire des sens faux sous des totaux
 * justes — le pire mode de défaillance, parce qu'il est silencieux.
 *
 * `flash` marque le moment où **cette** ligne compte : un halo dans sa propre
 * couleur, et le sens écrit à côté. Pas de teinte nouvelle — la couleur d'une
 * ligne dit déjà de quelle ligne il s'agit, lui faire dire aussi un sens
 * rendrait les deux illisibles.
 */
function drawLine(
  ctx: CanvasRenderingContext2D,
  view: Viewport,
  line: CountingLine,
  selected: boolean,
  flash: LineFlash | null,
): void {
  const a = toCanvas(view, line.a);
  const b = toCanvas(view, line.b);

  ctx.save();
  if (flash !== null) {
    // Le halo d'abord, sous le trait : dessiné par-dessus, il l'effacerait.
    ctx.save();
    ctx.globalAlpha = flash.intensity;
    ctx.strokeStyle = line.color;
    ctx.lineWidth = 3 + 14 * flash.intensity;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
    ctx.restore();
  }
  ctx.strokeStyle = line.color;
  ctx.lineWidth = selected ? 4 : 3;
  ctx.beginPath();
  ctx.moveTo(a.x, a.y);
  ctx.lineTo(b.x, b.y);
  ctx.stroke();

  // Flèche au milieu, orientée vers le côté positif.
  const centre = midpoint(a, b);
  const normal = positiveNormal(a, b);
  if (normal.x !== 0 || normal.y !== 0) {
    const tip = { x: centre.x + normal.x * 18, y: centre.y + normal.y * 18 };
    ctx.beginPath();
    ctx.moveTo(centre.x, centre.y);
    ctx.lineTo(tip.x, tip.y);
    ctx.lineWidth = 2;
    ctx.stroke();
    // Pointe : deux traits obliques, plus lisibles qu'un triangle rempli à cette
    // taille.
    const back = { x: -normal.x, y: -normal.y };
    const side = { x: -normal.y, y: normal.x };
    ctx.beginPath();
    ctx.moveTo(tip.x, tip.y);
    ctx.lineTo(tip.x + back.x * 6 + side.x * 4, tip.y + back.y * 6 + side.y * 4);
    ctx.moveTo(tip.x, tip.y);
    ctx.lineTo(tip.x + back.x * 6 - side.x * 4, tip.y + back.y * 6 - side.y * 4);
    ctx.stroke();
  }
  ctx.restore();

  drawHandle(ctx, view, line.a, line.color, selected);
  drawHandle(ctx, view, line.b, line.color, selected);
  drawLabelAt(ctx, midpoint(a, b), line.name, line.color, { dy: -16 });

  if (flash !== null) {
    // Le sens en toutes lettres, sous l'étiquette : c'est ce qui distingue
    // « la ligne a compté » de « la ligne a compté dans ce sens-là », et c'est
    // la seconde information qui permet de valider une géométrie.
    ctx.save();
    ctx.globalAlpha = Math.min(1, 0.35 + flash.intensity);
    drawLabelAt(
      ctx,
      midpoint(a, b),
      flash.direction >= 0 ? "+1" : "−1",
      line.color,
      { dy: 18 },
    );
    ctx.restore();
  }
}

/** Trajectoires, reconstituées côté client depuis les frames précédentes. */
function drawTrails(
  ctx: CanvasRenderingContext2D,
  view: Viewport,
  tracks: readonly TrackSnapshot[],
  trails: ReadonlyMap<number, readonly Point[]>,
): void {
  ctx.save();
  ctx.globalAlpha = TRAJECTORY_ALPHA;
  ctx.lineWidth = 2;
  for (const track of tracks) {
    const trail = trails.get(track.globalId);
    if (trail === undefined || trail.length < 2) continue;

    // Couleur de la classe **votée** : une lecture qui vacille ne doit pas faire
    // clignoter la trajectoire.
    ctx.strokeStyle = classColor(track.identityLabel || track.label);
    ctx.beginPath();
    trail.forEach((point, index) => {
      const canvasPoint = toCanvas(view, point);
      if (index === 0) ctx.moveTo(canvasPoint.x, canvasPoint.y);
      else ctx.lineTo(canvasPoint.x, canvasPoint.y);
    });
    ctx.stroke();
  }
  ctx.restore();
}

/**
 * Une piste : boîte, centroïde, badge, plaques.
 *
 * **Pointillés tant que `hits < minHits`.** C'est la forme, et non la couleur, qui
 * dit « pas encore confirmée » — parce que la couleur est déjà prise par la classe
 * et que le vert est réservé à l'interface (ADR 0004).
 *
 * Le badge ✓ signale « compté ». Il dérive de `counted`, que le serveur calcule
 * depuis le tally : un franchissement supprimé par le garde d'identité ne doit pas
 * peindre ✓ (invariant 5).
 *
 * **L'étiquette de plaque est peinte après celle du véhicule**, sous le rectangle de la
 * plaque et non au-dessus de la boîte : celle du véhicule occupe déjà `box.y - 6`, et
 * deux étiquettes au même endroit se recouvriraient sur tout véhicule dont la plaque
 * est haute dans la boîte — un deux-roues, une camionnette vue de face.
 */
function drawTrack(
  ctx: CanvasRenderingContext2D,
  view: Viewport,
  track: TrackSnapshot,
  minHits: number,
): void {
  const color = classColor(track.identityLabel || track.label);
  const confirmed = track.hits >= minHits;
  const box = toCanvasBox(view, track.box);

  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = confirmed ? 2 : 1.5;
  // La forme porte l'état, pas la couleur.
  ctx.setLineDash(confirmed ? [] : [6, 4]);
  ctx.strokeRect(box.x, box.y, box.width, box.height);
  ctx.setLineDash([]);

  // Centroïde — le point que le comptage suit côté serveur. Blanc, donc jamais
  // confondu avec une couleur de classe.
  ctx.fillStyle = CANVAS.centroid;
  ctx.beginPath();
  ctx.arc(box.x + box.width / 2, box.y + box.height / 2, 2.5, 0, Math.PI * 2);
  ctx.fill();

  for (const plate of track.plates) {
    const plateBox = toCanvasBox(view, plate.box);
    ctx.strokeStyle = CANVAS.plate;
    // Trait plus fin pour une boîte **reprojetée** : le serveur étrangle son
    // détecteur de plaques et estime les images qu'il saute à partir de la
    // dernière détection réelle. Le trait fin dit « estimée » sans changer de
    // couleur — la couleur du canvas encode une donnée, pas un état de
    // confiance — et c'est le même vocabulaire que les pistes non confirmées en
    // pointillés. Sans cette distinction, une estimation se lirait comme une
    // mesure ; sans le rectangle du tout, il clignoterait.
    ctx.lineWidth = plate.stale === true ? 0.75 : 1.5;
    ctx.strokeRect(plateBox.x, plateBox.y, plateBox.width, plateBox.height);
  }
  ctx.restore();

  const parts = [`#${track.globalId}`, track.identityLabel || track.label];
  if (track.reidCount > 0) parts.push(`↻${track.reidCount}`);
  parts.push(track.counted ? "✓" : "…");
  drawLabelAt(ctx, { x: box.x, y: box.y }, parts.join(" "), color, { dy: -6 });

  // Le texte **voté** (`plateText`), jamais `plates[].text` : l'OCR est étranglée côté
  // serveur et ne remplit ce dernier qu'une image sur trois, donc l'étiquette
  // clignoterait. Même raison qu'`identityLabel` face à `label`.
  //
  // Une seule étiquette, même sur un poids lourd qui porte deux plaques : deux
  // rectangles de texte sur 80 pixels de large se masqueraient. `bestReadPlate` ne
  // choisit que le point d'ancrage — la mieux lue, plutôt que l'ordre du détecteur.
  const plateText = plateLabel(track.plateText, track.plateTextScore);
  if (plateText !== null) {
    const anchor = bestReadPlate(track.plates);
    const plateBox = anchor === null ? box : toCanvasBox(view, anchor.box);
    drawLabelAt(
      ctx,
      { x: plateBox.x, y: plateLabelBaseline(plateBox, view.height) },
      plateText,
      CANVAS.plate,
      { dy: 0 },
    );
  }
}

/** Hauteur d'une étiquette, telle que `drawLabelAt` la peint. */
const LABEL_HEIGHT = 16;
/** Écart entre le rectangle de plaque et son étiquette. */
const PLATE_LABEL_GAP = 2;

/**
 * Ligne de base de l'étiquette de plaque : **sous** le rectangle, ou au-dessus quand il
 * n'y a plus la place.
 *
 * Pourquoi la bascule et pas un simple décalage vers le bas : une plaque lisible est
 * une plaque proche, donc basse dans l'image. Sans bascule, l'étiquette sortirait du
 * canvas précisément dans le cas où elle porte l'information la plus sûre — et le seul
 * symptôme serait « ça ne s'affiche pas », sans rien à déboguer.
 *
 * Exporté pour être testé : `drawLabelAt` a besoin d'un contexte 2D, ce calcul non.
 */
export function plateLabelBaseline(plateBox: Box, canvasHeight: number): number {
  const below = plateBox.y + plateBox.height + PLATE_LABEL_GAP + LABEL_HEIGHT;
  return below <= canvasHeight ? below : plateBox.y - PLATE_LABEL_GAP;
}

/**
 * Le polygone en cours de tracé, avec son segment élastique vers le curseur.
 *
 * Dessiné en dernier, donc au-dessus de tout : c'est l'action en cours, elle doit
 * rester visible même au-dessus d'une boîte.
 */
function drawDraft(
  ctx: CanvasRenderingContext2D,
  view: Viewport,
  draft: readonly Point[],
  cursor: Point | null,
): void {
  ctx.save();
  ctx.strokeStyle = CANVAS.handle;
  ctx.lineWidth = 2;
  ctx.setLineDash([6, 4]);
  ctx.beginPath();
  draft.forEach((point, index) => {
    const canvasPoint = toCanvas(view, point);
    if (index === 0) ctx.moveTo(canvasPoint.x, canvasPoint.y);
    else ctx.lineTo(canvasPoint.x, canvasPoint.y);
  });
  if (cursor !== null) {
    const canvasCursor = toCanvas(view, cursor);
    ctx.lineTo(canvasCursor.x, canvasCursor.y);
  }
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.restore();

  for (const point of draft) {
    drawHandle(ctx, view, point, CANVAS.handle, true);
  }
}

/* ── Primitives ─────────────────────────────────────────────────────────── */

/** Convertit un point source en point de dessin. */
export function toCanvas(view: Viewport, point: Point): Point {
  return { x: point.x * view.scaleX, y: point.y * view.scaleY };
}

function toCanvasBox(view: Viewport, box: Box): Box {
  return {
    x: box.x * view.scaleX,
    y: box.y * view.scaleY,
    width: box.width * view.scaleX,
    height: box.height * view.scaleY,
  };
}

function traceePolygon(
  ctx: CanvasRenderingContext2D,
  view: Viewport,
  points: readonly Point[],
): void {
  points.forEach((point, index) => {
    const canvasPoint = toCanvas(view, point);
    if (index === 0) ctx.moveTo(canvasPoint.x, canvasPoint.y);
    else ctx.lineTo(canvasPoint.x, canvasPoint.y);
  });
  ctx.closePath();
}

/**
 * Une poignée : disque coloré, contour sombre.
 *
 * Le contour sombre n'est pas cosmétique : sans lui, une poignée claire sur une
 * scène claire disparaît, et l'utilisateur ne sait plus où saisir.
 */
function drawHandle(
  ctx: CanvasRenderingContext2D,
  view: Viewport,
  point: Point,
  color: string,
  emphasised: boolean,
): void {
  const centre = toCanvas(view, point);
  ctx.save();
  ctx.beginPath();
  ctx.arc(centre.x, centre.y, emphasised ? 6 : 5, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = CANVAS.handleStroke;
  ctx.stroke();
  ctx.restore();
}

function drawLabel(
  ctx: CanvasRenderingContext2D,
  view: Viewport,
  anchor: Point,
  text: string,
  color: string,
  offset: { dy: number },
): void {
  drawLabelAt(ctx, toCanvas(view, anchor), text, color, offset);
}

/**
 * Une étiquette sur fond opaque.
 *
 * Le fond est ce qui la garde lisible : du texte blanc sur une route claire est
 * illisible, et une bordure ne suffit pas à cette taille.
 */
function drawLabelAt(
  ctx: CanvasRenderingContext2D,
  position: Point,
  text: string,
  color: string,
  offset: { dy: number },
): void {
  ctx.save();
  ctx.font = "600 12px Manrope, system-ui, sans-serif";
  ctx.textBaseline = "bottom";
  const metrics = ctx.measureText(text);
  const padding = 4;
  const height = 16;
  const x = position.x;
  const y = position.y + offset.dy;

  ctx.fillStyle = CANVAS.labelBackground;
  ctx.fillRect(x, y - height, metrics.width + padding * 2, height);
  ctx.fillStyle = color;
  ctx.fillRect(x, y - height, 2, height);
  ctx.fillStyle = CANVAS.labelInk;
  ctx.fillText(text, x + padding, y - 3);
  ctx.restore();
}
