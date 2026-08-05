/** `features/geometry-editor` — tracer et manipuler lignes et zones sur la scène. */

export { drawScene, toCanvas, type DrawOptions, type Viewport } from "./model/draw";
export {
  HANDLE_RADIUS_SCREEN,
  LINE_RADIUS_SCREEN,
  closesPolygon,
  hitTest,
  repeatsLastVertex,
  selectionOf,
  type Hit,
} from "./model/hitTest";
export { GeometryCanvas } from "./ui/GeometryCanvas";
export { GeometryPanel } from "./ui/GeometryPanel";
