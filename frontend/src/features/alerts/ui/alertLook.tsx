/**
 * L'apparence d'une alerte : son mot, son icône, sa teinte.
 *
 * **La couleur encode la gravité, l'icône encode la nature**, et jamais l'inverse.
 * Une infraction et une plaque trouvée à coup sûr sont toutes deux rouges parce
 * qu'elles sont toutes deux certaines ; ce qui les distingue est le pictogramme et
 * le titre. Teinter par famille demanderait de retenir une convention de plus, sur
 * un écran qui en compte déjà deux — la couleur d'une ligne, la couleur d'une
 * classe.
 *
 * C'est aussi un amendement assumé à la règle d'ADR 0004 telle que
 * `StaleResultBanner` la formule (« le rouge est réservé aux échecs ») : il y
 * voulait dire « l'application a échoué », il veut désormais **aussi** dire « la
 * scène présente une infraction ». Le titre porte la différence — « Sens interdit »
 * ne se confond pas avec « Échec de l'analyse » — et la règle de fond tient
 * toujours : le rouge n'est jamais décoratif.
 *
 * Une table exhaustive plutôt qu'une cascade : le jour où une nature d'alerte
 * s'ajoute, c'est la compilation qui le signale, et non un écran qui affiche une
 * carte sans titre.
 */

import {
  Ban,
  Car,
  CarFront,
  ScanSearch,
  ShieldAlert,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

import type { AlertKind, AlertSeverity } from "../model/alerts";

export interface AlertLook {
  title: string;
  Icon: LucideIcon;
  /** Ce que l'alerte affirme, en une phrase, sous le titre. */
  describe: (context: { lineName: string | null; watched: string | null }) => string;
}

export const ALERT_LOOK: Readonly<Record<AlertKind, AlertLook>> = {
  "wrong-way": {
    title: "Sens interdit",
    Icon: Ban,
    describe: ({ lineName }) => `A remonté ${lineName ?? "la ligne"} dans le sens interdit.`,
  },
  "closed-line": {
    title: "Ligne infranchissable",
    Icon: Ban,
    describe: ({ lineName }) => `A franchi ${lineName ?? "la ligne"}, interdite dans les deux sens.`,
  },
  "reserved-lane": {
    title: "Voie réservée",
    Icon: ShieldAlert,
    describe: ({ lineName }) => `N'a pas le droit d'emprunter ${lineName ?? "cette ligne"}.`,
  },
  "plate-exact": {
    title: "Plaque recherchée",
    Icon: ScanSearch,
    describe: ({ watched }) => `Correspond exactement à ${watched ?? "la plaque recherchée"}.`,
  },
  "plate-partial": {
    title: "Plaque probable",
    Icon: TriangleAlert,
    // Le mot « probable » est dans le titre **et** dans la phrase, délibérément : une
    // correspondance partielle présentée comme une certitude est le seul faux positif
    // que cette fonctionnalité puisse produire, et il doit se voir sans être cherché.
    describe: ({ watched }) =>
      `Ressemble à ${watched ?? "la plaque recherchée"} — l'OCR perd souvent un caractère.`,
  },
  "vehicle-exact": {
    title: "Véhicule recherché",
    Icon: CarFront,
    describe: () => "Ressemble fortement à l'image recherchée — à vérifier sur la capture.",
  },
  "vehicle-partial": {
    title: "Véhicule possible",
    Icon: Car,
    // « possible » et non « probable » : le mot « probable » est déjà pris par les
    // plaques, et les deux ne valent pas la même chose. Une plaque partielle a une
    // cause connue (l'OCR perd le premier caractère, ADR 0029) ; une ressemblance
    // faible n'a que le recouvrement des distributions, qui est bien plus large.
    describe: () => "Ressemble à l'image recherchée — vérification nécessaire.",
  },
};

/** L'écrin d'une carte, selon la gravité. Deux niveaux, pas trois. */
export const SEVERITY_SURFACE: Readonly<Record<AlertSeverity, string>> = {
  critical: "bg-negative/10 ring-negative/40",
  warning: "bg-warning/10 ring-warning/40",
};

/** L'encre du titre et de l'icône. */
export const SEVERITY_INK: Readonly<Record<AlertSeverity, string>> = {
  critical: "text-negative",
  warning: "text-warning",
};

/**
 * Le filet vertical du bord gauche de la carte.
 *
 * Séparé de `SEVERITY_SURFACE`, qui teinte le fond à 10 % : le filet est **opaque**,
 * et c'est lui qui rend une pile de cartes parcourable sans lecture — l'œil suit
 * une colonne de traits et repère les rouges parmi les orange. Un fond à 10 %
 * distingue mal deux teintes voisines sur un thème sombre.
 */
export const SEVERITY_RAIL: Readonly<Record<AlertSeverity, string>> = {
  critical: "border-negative",
  warning: "border-warning",
};
