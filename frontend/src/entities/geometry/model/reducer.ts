/**
 * Le reducer d'édition de la géométrie.
 *
 * Un reducer et non des `useState` dispersés, pour une raison précise : plusieurs
 * actions doivent modifier **deux choses à la fois** de façon cohérente.
 * Supprimer une zone doit aussi détacher les lignes qui s'y référaient — sinon la
 * requête part avec une `zoneId` qui n'existe plus et le serveur la refuse en 422,
 * après que l'utilisateur a cliqué « Lancer ». Avec des états séparés, cette
 * cohérence dépend de l'ordre des appels ; ici elle est structurelle.
 *
 * Toutes les coordonnées sont en **pixels de la vidéo source**.
 */

import type {
  CountingLine,
  DirectionRole,
  DirectionSign,
  Point,
  Zone,
} from "@/shared/api/contracts";
import { nextGeometryColor } from "@/shared/config/palettes";
import { clampToSource } from "@/shared/lib/geometry";

import { EMPTY_GEOMETRY, NO_SELECTION, type GeometryState } from "./types";

export type GeometryAction =
  | { type: "addLine"; width: number; height: number }
  | { type: "addZone"; points: Point[] }
  | { type: "moveLine"; id: string; a: Point; b: Point }
  | { type: "moveZone"; id: string; points: Point[] }
  | { type: "renameLine"; id: string; name: string }
  | { type: "renameZone"; id: string; name: string }
  | { type: "renameDirection"; id: string; sign: DirectionSign; name: string }
  | { type: "setDirectionRole"; id: string; sign: DirectionSign; role: DirectionRole }
  | { type: "setLineZone"; id: string; zoneId: string | null }
  | { type: "removeLine"; id: string }
  | { type: "removeZone"; id: string }
  | { type: "select"; selection: GeometryState["selection"] }
  | { type: "setDrawingZone"; drawing: boolean }
  | { type: "replace"; lines: CountingLine[]; zones: Zone[] }
  | { type: "clear" };

/**
 * Une ligne horizontale dans le **tiers inférieur** de l'image.
 *
 * C'est la ligne amorcée automatiquement au chargement d'une vidéo : un écran sans
 * ligne ne compte rien, et l'utilisateur qui lance une analyse et obtient zéro ne
 * devine pas que c'est parce qu'il n'a rien tracé. Le tiers inférieur est
 * l'emplacement le plus souvent utile — le premier plan d'une caméra de trafic.
 *
 * Marges de 8 % : une ligne qui touche exactement les bords a ses poignées
 * hors d'atteinte de la souris.
 */
export function defaultLine(width: number, height: number, index: number): CountingLine {
  const y = height * (index === 0 ? 0.66 : 0.5);
  return {
    id: freshId("l"),
    name: `Ligne ${index + 1}`,
    color: nextGeometryColor(index),
    zoneId: null,
    a: { x: width * 0.08, y },
    b: { x: width * 0.92, y },
    // Le nom libre n'est plus qu'un vestige de compatibilité (voir
    // `withDirectionDefaults`) : le panneau de géométrie ne l'écrit plus jamais.
    positiveName: "",
    negativeName: "",
    // Le rôle est **obligatoire** depuis que le panneau ne propose plus « ni
    // entrée ni sortie ». Une paire par défaut plutôt qu'un état non tranché : une
    // ligne fraîchement tracée a déjà un bilan entrée/sortie exploitable sans que
    // l'utilisateur touche à rien, et il reste libre d'inverser ou de changer les
    // deux côtés à sa guise.
    positiveRole: "entry",
    negativeRole: "exit",
  };
}

/**
 * Complète une ligne venue d'ailleurs avec les défauts des champs de sens.
 *
 * Un preset enregistré ou un `configJson` archivé **avant** les sens nommés ne les
 * porte pas. Sans ce complément, `line.positiveRole` vaudrait `undefined` là où le
 * type promet un `DirectionRole`, et les agrégations d'entrées/sorties compareraient
 * silencieusement contre rien — un total qui reste à zéro sans qu'aucune erreur ne
 * l'explique.
 *
 * Le repli reste `neutral`, **délibérément différent** de `defaultLine` : deviner
 * entrée ou sortie pour une ligne tracée avant que le choix soit obligatoire
 * fausserait un bilan que personne n'a demandé. Le panneau de géométrie affiche
 * alors un repère « à préciser » qui force un choix explicite au premier contact,
 * plutôt qu'un bilan silencieusement faux.
 */
export function withDirectionDefaults(line: CountingLine): CountingLine {
  return {
    ...line,
    positiveName: line.positiveName ?? "",
    negativeName: line.negativeName ?? "",
    positiveRole: line.positiveRole ?? "neutral",
    negativeRole: line.negativeRole ?? "neutral",
  };
}

export function geometryReducer(state: GeometryState, action: GeometryAction): GeometryState {
  switch (action.type) {
    case "addLine": {
      const line = defaultLine(action.width, action.height, state.lines.length);
      return {
        ...state,
        lines: [...state.lines, line],
        // Sélectionnée d'emblée : l'utilisateur vient de la créer, il va la
        // déplacer ou la renommer.
        selection: { kind: "line", id: line.id },
      };
    }

    case "addZone": {
      // Moins de trois sommets n'est pas une surface. Le canvas ne devrait pas
      // envoyer ce cas, mais le reducer est la dernière barrière avant une
      // requête que le serveur refusera.
      if (action.points.length < 3) return state;

      const zone: Zone = {
        id: freshId("z"),
        name: `Zone ${state.zones.length + 1}`,
        color: nextGeometryColor(state.lines.length + state.zones.length),
        points: action.points,
      };
      return {
        ...state,
        zones: [...state.zones, zone],
        selection: { kind: "zone", id: zone.id },
        // Le mode tracé se referme de lui-même : enchaîner deux zones sans le
        // vouloir est plus surprenant qu'utile.
        drawingZone: false,
      };
    }

    case "moveLine":
      return {
        ...state,
        lines: state.lines.map((line) =>
          line.id === action.id ? { ...line, a: action.a, b: action.b } : line,
        ),
      };

    case "moveZone":
      return {
        ...state,
        zones: state.zones.map((zone) =>
          zone.id === action.id ? { ...zone, points: action.points } : zone,
        ),
      };

    case "renameLine":
      return {
        ...state,
        lines: state.lines.map((line) =>
          line.id === action.id ? { ...line, name: action.name } : line,
        ),
      };

    case "renameZone":
      return {
        ...state,
        zones: state.zones.map((zone) =>
          zone.id === action.id ? { ...zone, name: action.name } : zone,
        ),
      };

    case "renameDirection":
      return {
        ...state,
        lines: state.lines.map((line) =>
          line.id === action.id
            ? { ...line, [`${action.sign}Name`]: action.name }
            : line,
        ),
      };

    case "setDirectionRole": {
      // Entrée et sortie sont **mutuellement exclusives** depuis ADR 0021 : une
      // ligne à deux sens ne peut pas dire l'entrée des deux côtés à la fois.
      // Poser un sens tranche donc l'autre automatiquement, plutôt que de laisser
      // l'utilisateur corriger à la main un second menu que le premier choix
      // rendait déjà évident.
      //
      // `neutral` ne bascule rien : ce rôle n'est plus atteignable depuis le
      // panneau (il ne survit que sur une ligne héritée), et il n'a pas
      // d'opposé à imposer.
      const opposite = action.role === "entry" ? "exit" : action.role === "exit" ? "entry" : null;
      return {
        ...state,
        lines: state.lines.map((line) => {
          if (line.id !== action.id) return line;
          const chosen: CountingLine =
            action.sign === "positive"
              ? { ...line, positiveRole: action.role }
              : { ...line, negativeRole: action.role };
          if (opposite === null) return chosen;
          return action.sign === "positive"
            ? { ...chosen, negativeRole: opposite }
            : { ...chosen, positiveRole: opposite };
        }),
      };
    }

    case "setLineZone":
      return {
        ...state,
        lines: state.lines.map((line) =>
          line.id === action.id ? { ...line, zoneId: action.zoneId } : line,
        ),
      };

    case "removeLine":
      return {
        ...state,
        lines: state.lines.filter((line) => line.id !== action.id),
        selection: clearIfSelected(state.selection, "line", action.id),
      };

    case "removeZone":
      return {
        ...state,
        zones: state.zones.filter((zone) => zone.id !== action.id),
        // **Le cas qui justifie le reducer.** Une ligne qui référence une zone
        // supprimée ferait échouer la requête en 422, après le clic sur
        // « Lancer » — donc au pire moment.
        lines: state.lines.map((line) =>
          line.zoneId === action.id ? { ...line, zoneId: null } : line,
        ),
        selection: clearIfSelected(state.selection, "zone", action.id),
      };

    case "select":
      return { ...state, selection: action.selection };

    case "setDrawingZone":
      return {
        ...state,
        drawingZone: action.drawing,
        // Entrer en mode tracé désélectionne : les poignées de la forme
        // sélectionnée capteraient les clics destinés aux sommets.
        selection: action.drawing ? NO_SELECTION : state.selection,
      };

    case "replace":
      // Chargement d'un preset ou d'un job de l'historique. La sélection est
      // remise à zéro : elle pointerait sur des identifiants disparus.
      //
      // **C'est le seul point d'entrée de lignes que nous n'avons pas fabriquées**,
      // donc le seul endroit où compléter les champs de sens d'une configuration
      // enregistrée avant qu'ils existent.
      return {
        ...state,
        lines: action.lines.map(withDirectionDefaults),
        zones: action.zones,
        selection: NO_SELECTION,
        drawingZone: false,
      };

    case "clear":
      return EMPTY_GEOMETRY;
  }
}

function clearIfSelected(
  selection: GeometryState["selection"],
  kind: "line" | "zone",
  id: string,
): GeometryState["selection"] {
  return selection.kind === kind && selection.id === id ? NO_SELECTION : selection;
}

/**
 * Déplace une ligne entière en conservant le **décalage de préhension**.
 *
 * Le décalage est ce qui empêche la forme de sauter sous le curseur au premier
 * pixel de mouvement : on déplace de `delta`, on ne recentre pas sur la souris.
 * Sans lui, saisir une ligne par son extrémité la téléporterait.
 *
 * Le déplacement est **refusé en bloc** s'il sortirait du cadre, plutôt que borné
 * point par point : borner séparément déformerait la ligne — un bout s'arrête,
 * l'autre continue, et la ligne pivote au lieu de glisser.
 */
export function translateLine(
  line: CountingLine,
  delta: Point,
  width: number,
  height: number,
): { a: Point; b: Point } {
  const a = { x: line.a.x + delta.x, y: line.a.y + delta.y };
  const b = { x: line.b.x + delta.x, y: line.b.y + delta.y };

  if (inside(a, width, height) && inside(b, width, height)) return { a, b };
  return { a: line.a, b: line.b };
}

/** Même logique pour une zone : tout ou rien, sinon le polygone se déforme. */
export function translateZone(
  zone: Zone,
  delta: Point,
  width: number,
  height: number,
): Point[] {
  const moved = zone.points.map((point) => ({ x: point.x + delta.x, y: point.y + delta.y }));
  return moved.every((point) => inside(point, width, height)) ? moved : zone.points;
}

/**
 * Déplace **un seul** sommet ou poignée. Borné, lui, au cadre.
 *
 * Ici le bornage est le bon comportement : déformer est précisément l'intention
 * de l'utilisateur qui saisit une poignée.
 */
export function moveHandle(point: Point, width: number, height: number): Point {
  return clampToSource(point, width, height);
}

function inside(point: Point, width: number, height: number): boolean {
  return point.x >= 0 && point.x <= width && point.y >= 0 && point.y <= height;
}

/**
 * Identifiant court, unique dans la session.
 *
 * `crypto.randomUUID()` serait plus solide mais produit des identifiants de 36
 * caractères qui alourdissent la requête et les journaux pour rien : ces
 * identifiants ne vivent que le temps d'une analyse, et le serveur ne les
 * interprète pas. Un compteur monotone évite la collision qu'un `Math.random`
 * tronqué finirait par produire.
 */
let counter = 0;
function freshId(prefix: string): string {
  counter += 1;
  return `${prefix}${counter}`;
}

/** Remet le compteur à zéro — réservé aux tests, pour des identifiants stables. */
export function resetIdCounter(): void {
  counter = 0;
}
