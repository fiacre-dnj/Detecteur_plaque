/**
 * Ce que l'analyse **signale** — infractions au tracé, plaques recherchées.
 *
 * La feature ne connaît aucune autre feature : elle reçoit des franchissements, des
 * pistes, un tracé et une liste de plaques, et rend des alertes. Les règles qu'elle
 * applique vivent dans `shared/lib/lineRules.ts` et `shared/lib/lineViolations.ts`,
 * parce que le tableau de bord les compte et que le registre les affiche — trois
 * lecteurs, un seul juge.
 */

export { ALERT_LIMIT, isViolation, type Alert, type AlertKind, type AlertSeverity } from "./model/alerts";
export { matchPlate, plateHits, type PlateHit, type PlateMatch } from "./model/plateWatch";
export { alertsFromResult } from "./model/replayAlerts";
export { useAlertLog } from "./model/useAlertLog";
export { AlertCard } from "./ui/AlertCard";
export { AlertsPanel } from "./ui/AlertsPanel";
