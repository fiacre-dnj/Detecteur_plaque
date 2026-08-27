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

import type {
  Box,
  CountingLine,
  DirectionSign,
  Point,
  TrackSnapshot,
  Zone,
} from "@/shared/api/contracts";
import { CANVAS, TRAJECTORY_ALPHA, classColor } from "@/shared/config/palettes";
import { directionName, directionRole } from "@/shared/lib/directions";
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
  /**
   * Estompe le nom de la ligne et les libellés de sens — jamais le trait, les
   * poignées, les zones ni les pistes.
   *
   * Pensé pour l'analyse serveur en cours : la géométrie est déjà validée à cet
   * instant, et c'est le train de boîtes et de compteurs qui mérite l'attention.
   * Un sens qui **vient de compter** reste net malgré tout — c'est l'événement qui
   * justifie de regarder l'écran, pas un défaut de l'estompage.
   */
  dimLabels: boolean;
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
  // **Toutes les étiquettes après tous les traits**, et en une seule passe.
  //
  // Deux raisons, et la seconde est celle qui a motivé le changement : un libellé
  // dessiné dans `drawLine` finissait sous le trait de la ligne suivante ; et surtout,
  // deux lignes parallèles proches posaient leurs libellés dans la même bande — celui
  // du dessous de l'une sur celui du dessus de l'autre. Une passe globale est le seul
  // endroit d'où l'on peut voir la collision pour l'écarter.
  drawLineLabels(ctx, view, options.lines, options.lineFlashes, options.dimLabels);
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
}

/**
 * Toutes les étiquettes de toutes les lignes, placées **sans se chevaucher**.
 *
 * Deux défauts se corrigent ici, et ils venaient du même endroit : chaque ligne
 * s'étiquetait seule, donc aucune ne pouvait voir ce que les autres avaient posé.
 *
 * 1. **le nom quittait le milieu** — il y entrait en collision avec le libellé du sens
 *    négatif dès que la ligne penchait, les deux se disputant le même axe
 *    perpendiculaire. Il se pose désormais près de la poignée A, comme les zones
 *    s'étiquettent sur leur premier sommet, et le milieu appartient aux deux sens ;
 * 2. **deux lignes parallèles proches** posaient leurs libellés dans la même bande.
 *    `resolveLabelCollisions` les écarte, chacun **le long de son propre normal** —
 *    donc sans jamais changer de côté, ce qui ferait mentir l'étiquette.
 */
function drawLineLabels(
  ctx: CanvasRenderingContext2D,
  view: Viewport,
  lines: readonly CountingLine[],
  flashes: ReadonlyMap<string, LineFlash>,
  dimmed: boolean,
): void {
  const wanted: LabelPlacement[] = [];
  const restingOpacity = dimmed ? DIMMED_LABEL_OPACITY : 1;

  // Les noms d'abord : ils sont **fixes**, donc ce sont les sens qui leur cèdent la
  // place. L'inverse ferait errer le nom loin de sa ligne.
  for (const line of lines) {
    const a = toCanvas(view, line.a);
    const b = toCanvas(view, line.b);
    wanted.push({
      key: `${line.id}:name`,
      text: line.name,
      color: line.color,
      centre: lineNameAnchor(a, b),
      escape: null,
      size: measureLabel(ctx, line.name),
      emphasis: 0,
      opacity: restingOpacity,
      // Fixe : le nom n'indique aucun sens, il n'a pas de flèche à porter.
      arrow: null,
    });
  }

  for (const line of lines) {
    const a = toCanvas(view, line.a);
    const b = toCanvas(view, line.b);
    const normal = positiveNormal(a, b);
    const negatedNormal = { x: -normal.x, y: -normal.y };
    const positive = directionText(line, "positive");
    const negative = directionText(line, "negative");
    const positiveRole = directionRole(line, "positive");
    const negativeRole = directionRole(line, "negative");
    // La flèche n'occupe la place qu'elle prend réellement (`ARROW_RESERVED_WIDTH`)
    // sur un sens qui déclare quelque chose : seul `neutral` n'en affiche pas, il
    // n'y a rien à orienter. Un sens **interdit** garde la sienne — c'est bien un
    // sens, et savoir de quel côté il est interdit est toute l'information.
    const positiveArrow = positiveRole === "neutral" ? null : normal;
    const negativeArrow = negativeRole === "neutral" ? null : negatedNormal;
    // Le rouge ne dit pas *quelle* ligne — le trait le dit déjà, dans sa propre
    // teinte, juste à côté. Il dit qu'on n'aurait pas dû passer là. C'est la seule
    // couleur du canvas qui encode une valeur plutôt qu'une identité, et elle est
    // volontairement bornée au mot « Interdit ».
    const positiveColor = positiveRole === "forbidden" ? CANVAS.forbidden : line.color;
    const negativeColor = negativeRole === "forbidden" ? CANVAS.forbidden : line.color;
    const sizes = {
      positive: withArrowWidth(measureLabel(ctx, positive), positiveArrow),
      negative: withArrowWidth(measureLabel(ctx, negative), negativeArrow),
    };
    const anchors = directionLabelAnchors(a, b, sizes);
    if (anchors === null) continue;

    const flash = flashes.get(line.id) ?? null;
    // Le flash **met en valeur le libellé qui existe déjà** au lieu d'en ajouter un
    // quatrième : c'est le sens qui vient de compter, pas une information nouvelle.
    // Une étiquette de plus, c'était une collision de plus.
    const lit = flash === null ? null : flash.direction >= 0 ? "positive" : "negative";

    wanted.push({
      key: `${line.id}:positive`,
      text: positive,
      color: positiveColor,
      centre: anchors.positive,
      escape: normal,
      size: sizes.positive,
      emphasis: lit === "positive" ? (flash?.intensity ?? 0) : 0,
      // Un sens qui vient de compter reste net même pendant l'analyse : c'est
      // l'événement qui justifie de regarder l'écran à cet instant précis.
      opacity: lit === "positive" ? 1 : restingOpacity,
      arrow: positiveArrow,
    });
    wanted.push({
      key: `${line.id}:negative`,
      text: negative,
      color: negativeColor,
      centre: anchors.negative,
      escape: negatedNormal,
      size: sizes.negative,
      emphasis: lit === "negative" ? (flash?.intensity ?? 0) : 0,
      opacity: lit === "negative" ? 1 : restingOpacity,
      arrow: negativeArrow,
    });
  }

  for (const placed of resolveLabelCollisions(wanted, view)) {
    drawLabelBox(ctx, placed);
  }
}

/**
 * Le libellé d'un sens tel qu'il est peint : longueur bornée, sans préfixe.
 *
 * La flèche n'est plus un caractère dans le texte — un glyphe unicode ne
 * pivote qu'à 45° près, ce qui la rendait *presque* perpendiculaire au trait,
 * jamais exactement. `drawLabelBox` la peint désormais en vecteur, à l'angle
 * réel du normal (`LabelPlacement.arrow`), avant le texte.
 */
function directionText(line: CountingLine, sign: DirectionSign): string {
  return truncateDirection(directionName(line, sign));
}

/**
 * Où poser le nom de la ligne : près de la poignée A, décalé vers l'intérieur.
 *
 * Décalé **le long du trait** pour ne pas recouvrir la poignée, et **le long du
 * normal** pour ne pas chevaucher le trait lui-même. Vers l'intérieur du segment
 * plutôt que vers l'extérieur : une ligne tracée jusqu'au bord de l'image aurait
 * sinon son nom hors cadre — le clamp le ramènerait, mais par-dessus la poignée.
 */
export function lineNameAnchor(a: Point, b: Point): Point {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const length = Math.hypot(dx, dy);
  if (length === 0) return { x: a.x, y: a.y - NAME_CLEARANCE };

  const tangent = { x: dx / length, y: dy / length };
  const normal = { x: -tangent.y, y: tangent.x };
  // Jamais au-delà du milieu : sur un segment très court, avancer de 28 px ferait
  // atterrir le nom du mauvais côté du centre, là où vivent les libellés de sens.
  const inward = Math.min(NAME_INSET, length / 2);
  return {
    x: a.x + tangent.x * inward - normal.x * NAME_CLEARANCE,
    y: a.y + tangent.y * inward - normal.y * NAME_CLEARANCE,
  };
}

/** Air laissé entre le trait et le bord le plus proche d'une étiquette de sens. */
export const DIRECTION_LABEL_CLEARANCE = 16;

/** Recul du nom de la ligne par rapport au trait, et avancée depuis la poignée A. */
const NAME_CLEARANCE = 14;
const NAME_INSET = 28;

/** Encombrement d'une étiquette, tel que `drawCentredLabel` la peint. */
export interface LabelSize {
  width: number;
  height: number;
}

/**
 * Où poser les deux libellés de sens : de part et d'autre du **milieu** du trait.
 *
 * Un placement aux extrémités a été essayé (l'un près de A comme le nom, l'autre
 * près de B) puis abandonné : à la relecture, le milieu se lit mieux — c'est là que
 * l'œil regarde une ligne de comptage en premier. Les collisions avec le nom de la
 * ligne restent gérées par `resolveLabelCollisions`, qui écarte les libellés de
 * sens **le long de leur propre normal** plutôt que de changer d'ancre.
 *
 * **Le décalage dépend de la taille de l'étiquette et de l'angle du trait**, et c'est
 * l'essentiel du correctif. Un décalage fixe de 30 px marchait sur une ligne
 * horizontale — où les deux boîtes s'éloignent par leur petit côté, 16 px de haut —
 * et **se chevauchait** dès que la ligne penchait : sur une ligne verticale, le
 * normal est horizontal, donc deux boîtes de 110 px de large se croisaient
 * allègrement à 60 px d'écart.
 *
 * L'encombrement d'une boîte alignée sur les axes, mesuré le long d'une direction `n`,
 * vaut `|n.x|·w/2 + |n.y|·h/2`. En l'ajoutant au dégagement, l'espace entre les deux
 * étiquettes devient **constant quel que soit l'angle** — c'est la propriété que le
 * test vérifie sur une batterie d'orientations.
 *
 * **Extraite pour être testable**, comme `plateLabelBaseline` et pour la même raison :
 * peindre demande un contexte 2D, ce calcul non, et il n'y a ni jsdom ni
 * testing-library dans ce projet. Mais surtout parce que c'est un **signe**. Un signe
 * s'inverse sans qu'on le remarque : les totaux resteraient justes et l'écran dirait
 * « Vers la droite » pour des véhicules qui vont à gauche. Une panne silencieuse, donc
 * à verrouiller par un test contre `sideOfLine` — comme `positiveNormal` l'est déjà.
 *
 * `null` sur un segment de longueur nulle : aucun côté n'existe, et poser deux
 * étiquettes au même point les rendrait illisibles.
 */
export function directionLabelAnchors(
  a: Point,
  b: Point,
  sizes: { positive: LabelSize; negative: LabelSize },
): { positive: Point; negative: Point } | null {
  const normal = positiveNormal(a, b);
  if (normal.x === 0 && normal.y === 0) return null;

  const centre = midpoint(a, b);
  const push = (size: LabelSize): number =>
    DIRECTION_LABEL_CLEARANCE +
    Math.abs(normal.x) * (size.width / 2) +
    Math.abs(normal.y) * (size.height / 2);

  const forward = push(sizes.positive);
  const backward = push(sizes.negative);
  return {
    positive: { x: centre.x + normal.x * forward, y: centre.y + normal.y * forward },
    negative: { x: centre.x - normal.x * backward, y: centre.y - normal.y * backward },
  };
}

/** Police des étiquettes. Déclarée une fois : `measureLabel` et le rendu doivent
 *  s'accorder au pixel, sinon le placement calculé ne décrit plus ce qui est peint. */
const LABEL_FONT = "600 12px Manrope, system-ui, sans-serif";
const LABEL_HEIGHT = 16;
const LABEL_PADDING = 4;

/**
 * Opacité du nom de ligne et des libellés de sens pendant l'analyse serveur.
 *
 * Assez bas pour se retirer visuellement au profit des boîtes et des compteurs,
 * assez haut pour rester lisible d'un coup d'œil — la géométrie reste la
 * référence si on veut vérifier qu'une ligne est bien à sa place pendant que ça
 * tourne.
 */
const DIMMED_LABEL_OPACITY = 0.4;

/** Encombrement d'une étiquette avant de la peindre — l'entrée du placement. */
export function measureLabel(ctx: CanvasRenderingContext2D, text: string): LabelSize {
  ctx.save();
  ctx.font = LABEL_FONT;
  const width = ctx.measureText(text).width + LABEL_PADDING * 2;
  ctx.restore();
  return { width, height: LABEL_HEIGHT };
}

/**
 * Place réservée à la flèche d'un libellé de sens, avant le texte.
 *
 * Vecteur, pas caractère : un glyphe unicode ne pivote qu'à 45° près, ce qui la
 * rendait *presque* perpendiculaire au trait — jamais exactement. `drawArrowGlyph`
 * la peint à l'angle réel du normal, dans cette largeur réservée.
 */
const ARROW_RESERVED_WIDTH = 14;

/** Ajoute la place de la flèche à un encombrement mesuré, si le sens en porte une. */
function withArrowWidth(size: LabelSize, arrow: Point | null): LabelSize {
  return arrow === null ? size : { width: size.width + ARROW_RESERVED_WIDTH, height: size.height };
}

/** Une étiquette voulue quelque part, et la direction dans laquelle elle peut fuir. */
export interface LabelPlacement {
  key: string;
  text: string;
  color: string;
  /** Position idéale du **centre** de l'étiquette. */
  centre: Point;
  /**
   * Direction unitaire dans laquelle l'étiquette peut s'écarter en cas de collision.
   *
   * `null` = fixe, elle ne bouge pas et les autres lui cèdent la place. Pour un
   * libellé de sens, c'est **son propre normal** : elle s'éloigne du trait sans jamais
   * changer de côté, sinon l'étiquette mentirait sur le sens qu'elle nomme.
   */
  escape: Point | null;
  size: LabelSize;
  /** 0 à 1 : contraste inversé pour marquer le sens qui vient de compter. */
  emphasis: number;
  /** 0 à 1 : opacité globale de l'étiquette — estompée pendant l'analyse serveur. */
  opacity: number;
  /**
   * Direction de la flèche peinte avant le texte, ou `null` — pas de flèche.
   *
   * `null` pour le nom de la ligne (aucun sens à indiquer) et pour un sens resté
   * `neutral` (rien à orienter). Distinct d'`escape` : celui-ci dit dans quel
   * sens l'étiquette peut s'écarter en cas de collision, celui-là ce qu'elle
   * dessine — les deux valent souvent le même vecteur, mais pas toujours.
   */
  arrow: Point | null;
}

/** Une étiquette placée, prête à peindre : coin supérieur gauche définitif. */
export interface PlacedLabel extends LabelPlacement {
  x: number;
  y: number;
}

/** Pas d'écartement, en pixels : une hauteur d'étiquette plus un filet d'air. */
const ESCAPE_STEP = LABEL_HEIGHT + 4;
/** Nombre maximal d'écartements avant d'abandonner et de poser quand même. */
const ESCAPE_ATTEMPTS = 6;

/**
 * Place une série d'étiquettes en évitant qu'elles se recouvrent.
 *
 * Glouton et dans l'ordre reçu : chaque étiquette cède aux précédentes. C'est pour
 * cela que l'appelant passe les **noms de ligne d'abord** — ils sont fixes, et un nom
 * qui errerait loin de son trait serait pire qu'un chevauchement.
 *
 * Une étiquette qui ne trouve pas de place après `ESCAPE_ATTEMPTS` est **posée quand
 * même**, à sa dernière position. Renoncer à l'afficher serait pire : un libellé absent
 * se lit comme un sens non configuré, alors qu'il l'est.
 *
 * Le bornage au canvas est appliqué **après** chaque écartement, jamais avant : borner
 * d'abord ferait osciller une étiquette contre un bord sans jamais la libérer.
 *
 * Pure et exportée pour être testée : ce genre de boucle se vérifie sur ses cas
 * dégénérés — deux lignes confondues, une étiquette plus large que le canvas — pas à
 * l'œil sur une capture.
 */
export function resolveLabelCollisions(
  placements: readonly LabelPlacement[],
  view: { width: number; height: number },
): PlacedLabel[] {
  const placed: PlacedLabel[] = [];

  for (const placement of placements) {
    let centre = placement.centre;
    let corner = clampLabel(centre, placement.size, view);

    for (let attempt = 0; attempt < ESCAPE_ATTEMPTS; attempt += 1) {
      if (placement.escape === null) break;
      if (!collides(corner, placement.size, placed)) break;
      centre = {
        x: centre.x + placement.escape.x * ESCAPE_STEP,
        y: centre.y + placement.escape.y * ESCAPE_STEP,
      };
      corner = clampLabel(centre, placement.size, view);
    }

    placed.push({ ...placement, x: corner.x, y: corner.y });
  }
  return placed;
}

/**
 * Borne une étiquette au canvas, à partir de son centre voulu.
 *
 * Pas un détail : une ligne tracée près d'un bord — le cas courant, puisqu'on trace en
 * travers de la chaussée — poussait son libellé hors cadre, où il était simplement
 * invisible.
 *
 * `Math.max(0, …)` en second : sur un canvas plus étroit que l'étiquette, mieux vaut la
 * tronquer à droite qu'à gauche, où le début du mot disparaîtrait.
 */
function clampLabel(centre: Point, size: LabelSize, view: { width: number; height: number }): Point {
  return {
    x: Math.max(0, Math.min(centre.x - size.width / 2, view.width - size.width)),
    y: Math.max(0, Math.min(centre.y - size.height / 2, view.height - size.height)),
  };
}

function collides(corner: Point, size: LabelSize, placed: readonly PlacedLabel[]): boolean {
  return placed.some(
    (other) =>
      corner.x < other.x + other.size.width &&
      other.x < corner.x + size.width &&
      corner.y < other.y + other.size.height &&
      other.y < corner.y + size.height,
  );
}

/**
 * Peint une étiquette déjà placée.
 *
 * `emphasis` inverse progressivement le contraste : fond dans la couleur de la ligne,
 * encre sombre. C'est ce qui marque le sens **qui vient de compter**, sans introduire
 * ni teinte nouvelle ni quatrième étiquette.
 *
 * `opacity` s'applique **par-dessus** : c'est l'estompage pendant l'analyse serveur
 * (`dimLabels`), qui n'a pas à savoir si l'étiquette est en train de flasher.
 */
function drawLabelBox(ctx: CanvasRenderingContext2D, label: PlacedLabel): void {
  const { x, y, size, color, emphasis, opacity } = label;

  ctx.save();
  ctx.font = LABEL_FONT;
  ctx.textBaseline = "bottom";
  ctx.globalAlpha = opacity;

  ctx.fillStyle = CANVAS.labelBackground;
  ctx.fillRect(x, y, size.width, size.height);
  if (emphasis > 0) {
    ctx.globalAlpha = opacity * Math.min(1, emphasis);
    ctx.fillStyle = color;
    ctx.fillRect(x, y, size.width, size.height);
    ctx.globalAlpha = opacity;
  }
  // Le filet de couleur sur le bord gauche : c'est lui qui rattache l'étiquette à sa
  // ligne quand plusieurs se côtoient — et il devient indispensable dès qu'une
  // étiquette a dû s'écarter de son trait. Inutile quand tout le fond porte déjà la
  // couleur.
  if (emphasis < 0.5) {
    ctx.fillStyle = color;
    ctx.fillRect(x, y, 2, size.height);
  }
  const ink = emphasis >= 0.5 ? CANVAS.labelBackground : CANVAS.labelInk;
  ctx.fillStyle = ink;

  // La flèche occupe sa place réservée, le texte commence juste après — jamais les
  // deux au même endroit, sinon l'un des deux serait illisible.
  let textX = x + LABEL_PADDING;
  if (label.arrow !== null) {
    const centre = { x: x + ARROW_RESERVED_WIDTH / 2, y: y + size.height / 2 };
    drawArrowGlyph(ctx, centre, label.arrow, ink);
    textX = x + ARROW_RESERVED_WIDTH;
  }
  ctx.fillText(label.text, textX, y + size.height - 3);
  ctx.restore();
}

/**
 * Une flèche peinte en **vecteur**, à l'angle exact de `direction` — jamais un
 * glyphe unicode, qui ne pivote qu'à 45° près et rendrait le sens *presque*
 * perpendiculaire au trait plutôt qu'exactement.
 *
 * Même silhouette que la flèche posée sur le trait lui-même (`drawLine`) : un
 * corps, une pointe en deux traits obliques. La cohérence entre les deux évite
 * qu'on lise deux conventions différentes sur le même écran.
 */
function drawArrowGlyph(
  ctx: CanvasRenderingContext2D,
  centre: Point,
  direction: Point,
  color: string,
): void {
  if (direction.x === 0 && direction.y === 0) return;
  const length = Math.hypot(direction.x, direction.y);
  const unit = { x: direction.x / length, y: direction.y / length };
  const half = ARROW_RESERVED_WIDTH / 2 - 2;
  const tail = { x: centre.x - unit.x * half, y: centre.y - unit.y * half };
  const tip = { x: centre.x + unit.x * half, y: centre.y + unit.y * half };
  const back = { x: -unit.x, y: -unit.y };
  const side = { x: -unit.y, y: unit.x };

  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(tail.x, tail.y);
  ctx.lineTo(tip.x, tip.y);
  ctx.moveTo(tip.x, tip.y);
  ctx.lineTo(tip.x + back.x * 3.5 + side.x * 2.5, tip.y + back.y * 3.5 + side.y * 2.5);
  ctx.moveTo(tip.x, tip.y);
  ctx.lineTo(tip.x + back.x * 3.5 - side.x * 2.5, tip.y + back.y * 3.5 - side.y * 2.5);
  ctx.stroke();
  ctx.restore();
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

  // `globalId === 0` = piste pas encore confirmée. On affiche alors le type **sans
  // numéro** : « #0 » se lirait comme un véhicule zéro, alors que la boîte en
  // pointillés dit déjà « pas encore retenue ».
  const parts = track.globalId > 0 ? [`#${track.globalId}`] : [];
  parts.push(track.identityLabel || track.label);
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
 *
 * `centred` centre l'étiquette **horizontalement** sur `position` au lieu de la poser
 * à droite. C'est ce que veulent les libellés de sens, ancrés de part et d'autre du
 * milieu du trait : posés à droite, celui du dessous partirait vers la voie voisine.
 */
function drawLabelAt(
  ctx: CanvasRenderingContext2D,
  position: Point,
  text: string,
  color: string,
  offset: { dy: number; centred?: boolean },
): void {
  ctx.save();
  ctx.font = "600 12px Manrope, system-ui, sans-serif";
  ctx.textBaseline = "bottom";
  const metrics = ctx.measureText(text);
  const padding = 4;
  const height = 16;
  const width = metrics.width + padding * 2;
  const x = offset.centred === true ? position.x - width / 2 : position.x;
  const y = position.y + offset.dy;

  ctx.fillStyle = CANVAS.labelBackground;
  ctx.fillRect(x, y - height, width, height);
  ctx.fillStyle = color;
  ctx.fillRect(x, y - height, 2, height);
  ctx.fillStyle = CANVAS.labelInk;
  ctx.fillText(text, x + padding, y - 3);
  ctx.restore();
}

/**
 * Tronque un libellé de sens à une longueur qui tient sur la vidéo.
 *
 * Deux étiquettes doivent cohabiter de part et d'autre d'un trait, souvent à côté
 * d'une autre ligne. Une chaîne libre de 60 caractères couvrirait la scène.
 * L'infobulle du panneau porte le nom complet ; ici on garde le début, qui est ce qui
 * distingue « Entrée rue Foch » de « Sortie rue Foch ».
 */
export const DIRECTION_LABEL_MAX = 18;

export function truncateDirection(text: string): string {
  return text.length <= DIRECTION_LABEL_MAX
    ? text
    : `${text.slice(0, DIRECTION_LABEL_MAX - 1)}…`;
}
