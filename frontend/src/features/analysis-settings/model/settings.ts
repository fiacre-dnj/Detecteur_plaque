/**
 * Les réglages d'analyse, et leur **persistance tolérante aux versions**.
 *
 * Deux décisions méritent d'être lues avant de modifier ce module.
 *
 * **1. `confidenceThreshold` est `number | null`.** `null` signifie « suivre le
 * défaut », une valeur explicite signifie « je sais ce que je fais ». La distinction
 * compte parce qu'elle survit au changement de modèle : sans elle, régler la
 * confiance puis changer de modèle écraserait silencieusement le réglage — ou le
 * conserverait alors que l'utilisateur voulait repartir du défaut, et rien à l'écran
 * ne dirait lequel des deux s'est produit. Le bouton « Défaut » est le chemin de
 * retour ; avant lui, c'était le seul réglage sans réinitialisation.
 *
 * **2. Une lecture de schéma périmé rend les valeurs par défaut, jamais une
 * exception.** Un `localStorage` écrit par une version antérieure de l'application
 * est le cas **normal** après une mise à jour, pas une anomalie. Faire tomber
 * l'écran de comptage parce qu'un réglage a changé de forme serait absurde ; on
 * repart des défauts et l'utilisateur ne remarque rien.
 */

import { FULL_RANGE, type AnalysisRange } from "@/entities/analysis-range";
import type { AnalysisRequest, CountingLine, Zone } from "@/shared/api/contracts";

/**
 * Version du schéma persisté.
 *
 * **À incrémenter dès qu'un champ change de nom, de type ou de sens.** Une valeur
 * relue sous un sens différent est bien pire qu'une valeur perdue : elle produit une
 * analyse dont les réglages ne sont pas ceux que l'écran affiche.
 */
export const SETTINGS_SCHEMA_VERSION = 2;

/**
 * Le seul plafond absolu que la version 1 posait sans que personne le choisisse.
 *
 * ADR 0049 le retire du défaut ; une valeur **déjà persistée** y survivrait pourtant,
 * `mergeSettings` ne réécrivant jamais un choix — donc le correctif n'atteindrait
 * aucun poste existant. La migration ne relâche que **cette** valeur-là : un `60`
 * ou un `null` en base est un choix explicite, et le défaire serait pire que le bug.
 */
const V1_DEFAULT_FPS_CAP = 30;

const STORAGE_KEY = "traffic-analysis.settings.v1";

export interface AnalysisSettings {
  modelId: string;
  /** `null` = suivre le défaut du modèle. Voir la décision 1 ci-dessus. */
  confidenceThreshold: number | null;
  iouThreshold: number;
  minHits: number;
  maxLostMs: number;
  maskOutsideZones: boolean;
  frameStride: number;
  detectPlates: boolean;
  plateConfidence: number | null;
  /**
   * Plancher de confiance d'une **lecture** — `null` = suivre le défaut du serveur.
   *
   * Même convention que `confidenceThreshold`, et pour la même raison : `null`
   * signifie « suivre le défaut du déploiement » et une valeur explicite « je sais ce
   * que je fais ». Le bouton « Défaut » est le chemin de retour.
   *
   * Il ne décide pas ce qui est **lu** mais ce qui est **cru** : une lecture sous ce
   * seuil ne vote pas, donc ne peut rien publier, et le véhicule reste sans plaque
   * avec la raison « lecture incertaine ». Il ne fait donc économiser aucune
   * inférence — c'est un réglage de justesse, jamais de vitesse.
   */
  plateTextConfidence: number | null;
  /**
   * Lire le **texte** des plaques, en plus de les encadrer.
   *
   * Subordonné à `detectPlates` — sans boîte, il n'y a rien à lire — et gardé par
   * `plateOcrAvailable`, qui décrit un **autre** fichier que `plateAvailable`.
   *
   * Pas d'incrément de `SETTINGS_SCHEMA_VERSION` pour ce champ : la fusion est champ
   * par champ, donc un `localStorage` écrit avant lui reprend simplement le défaut.
   * La version se réserve aux champs qui changent de **sens**, où relire une valeur
   * ancienne produirait une analyse différente de ce que l'écran affiche.
   */
  readPlateText: boolean;
  /**
   * Plaques recherchées pendant l'analyse — la liste de surveillance.
   *
   * **Le seul réglage qui n'est pas persisté**, et c'est délibéré à deux titres.
   * Il décrit une *recherche en cours* et non une préférence — comme l'intervalle
   * d'analyse, qui vit pour la même raison dans `entities/analysis-range`. Et
   * écrire un numéro de plaque dans le `localStorage` du poste franchit le cran de
   * confidentialité que ce projet impose déjà en laissant l'OCR décoché par
   * défaut : on ne persiste pas silencieusement ce qu'on a demandé un
   * consentement explicite pour lire.
   *
   * `mergeSettings` ne la relit donc pas et `saveSettings` ne l'écrit pas — le
   * champ vit dans l'état du studio, remis à neuf à chaque nouvelle source.
   *
   * Les entrées sont stockées **telles que l'utilisateur les tape**. La forme
   * comparable est calculée à la comparaison, par `normalisePlate` — la même
   * fonction que la recherche du registre. Une seule définition de « la même
   * plaque » dans toute l'application.
   */
  plateWatchlist: string[];
  /**
   * Classes à détecter et à compter, par identifiant COCO.
   *
   * Le **catalogue** vient du serveur (`GET /api/v1/models/classes`) ; seule la
   * sélection vit ici. Ne jamais recopier le catalogue dans ce module : une case
   * cochable que le serveur refuse à l'envoi est le mode de panne exact que la
   * publication du catalogue existe pour empêcher.
   *
   * Une sélection persistée peut contenir un identifiant que le serveur ne propose
   * plus. `sanitiseClassIds` s'en charge à la lecture — plutôt que de laisser un
   * 422 arriver sur un réglage que l'écran affiche comme valide.
   */
  classIds: number[];
  /**
   * Cadence maximale de l'analyse, en multiples de la vitesse réelle de la scène.
   * `null` = aucune borne.
   *
   * Le seul réglage d'analyse qui ne change **aucun** chiffre : il ne décide que de
   * la vitesse à laquelle l'aperçu défile. Sans borne, un serveur à 55 images par
   * seconde sur une source à 25 fps montre un aperçu 2,2× trop rapide — le curseur
   * est calé sur le temps de scène analysé, pas lu.
   *
   * Pas d'incrément de `SETTINGS_SCHEMA_VERSION` : la fusion est champ par champ,
   * donc un `localStorage` antérieur reprend simplement le défaut ci-dessous
   * (ADR 0019).
   */
  analysisSpeed: number | null;
  /**
   * Plafond **absolu** de l'analyse, en images analysées par seconde réelle —
   * `null` = aucune borne.
   *
   * Indépendant d'`analysisSpeed` : celui-ci borne une vitesse *relative* au
   * temps de la scène (« pas plus vite que la vidéo »), celui-ci borne le débit
   * *absolu* du serveur (« jamais plus de N images par seconde », quelle que
   * soit la cadence de la source). Les deux peuvent être réglés ensemble — le
   * plus restrictif s'applique — et chacun agit même quand l'autre vaut `null`.
   *
   * Pas d'incrément de `SETTINGS_SCHEMA_VERSION` : la fusion est champ par
   * champ, donc un `localStorage` antérieur reprend simplement le défaut.
   */
  maxAnalysisFps: number | null;
  showTrails: boolean;
}

/** Défauts alignés sur ceux du serveur, pour que l'écran ne mente pas. */
export const DEFAULT_SETTINGS: AnalysisSettings = {
  modelId: "yolov8n",
  confidenceThreshold: null,
  iouThreshold: 0.45,
  minHits: 2,
  maxLostMs: 2_500,
  maskOutsideZones: false,
  frameStride: 1,
  detectPlates: false,
  plateConfidence: null,
  plateTextConfidence: null,
  // Faux par défaut : l'OCR est un surcoût, et persister un texte de plaque franchit
  // un cran de confidentialité qui doit être choisi, pas hérité.
  readPlateText: false,
  plateWatchlist: [],
  // Les quatre véhicules de COCO : voiture, moto, bus, camion. C'est le
  // comportement historique de l'application, donc qui ne touche à rien retrouve
  // exactement ses chiffres d'avant. Les personnes se cochent quand on les veut.
  classIds: [2, 3, 5, 7],
  // Temps réel par défaut, depuis ADR 0019 : sans borne, l'aperçu défile à la
  // vitesse de l'analyse (jusqu'à 1,7× mesuré) et la lecture locale, calée dessus,
  // paraît accélérée ou ralentie selon la charge du serveur — un défaut qui
  // surprend plutôt qu'un choix. `1` fait durer l'analyse la durée de la vidéo ;
  // « Illimitée » reste un choix explicite pour qui veut ses chiffres au plus vite.
  analysisSpeed: 1,
  // **Illimité par défaut depuis ADR 0049**, qui abroge le `30` d'ADR 0022. Ce
  // `30` était justifié par « la cadence vidéo la plus courante, qui ne borne
  // rien en pratique » — et c'est faux dès qu'on filme à 60. `ScenePacer` retient
  // la période la **plus longue** des deux bridages : sur une source 60 fps,
  // `analysisSpeed: 1` demande 16,7 ms et ce plafond en impose 33,3, donc le
  // plafond gagne et l'aperçu défile à **0,5×** — exactement l'inverse de ce
  // qu'`analysisSpeed: 1` existe pour garantir (ADR 0019).
  //
  // La cadence de scène reste le bridage pertinent et elle est toujours à `1` :
  // le partage de la machine n'est donc pas relâché, c'est le second plafond qui
  // redevient ce qu'ADR 0020 décrivait — un choix explicite pour brider une
  // machine partagée, pas un défaut qui contredit l'autre réglage.
  maxAnalysisFps: null,
  showTrails: true,
};

/**
 * Les cadences proposées, et **pourquoi il n'y en a que trois**.
 *
 * Un curseur continu inviterait à régler 1,37× — un chiffre qui ne répond à aucune
 * question. Les seules cadences qui en répondent une sont : « le plus vite
 * possible », « je regarde » et « je regarde, mais pressé ».
 */
export const ANALYSIS_SPEEDS: readonly { value: number | null; label: string }[] = [
  { value: null, label: "Illimitée" },
  { value: 1, label: "Temps réel" },
  { value: 2, label: "2×" },
];

/**
 * Les plafonds absolus proposés, en images par seconde.
 *
 * Deux valeurs seulement, comme pour `ANALYSIS_SPEEDS` et pour la même raison :
 * ce sont les deux cadences vidéo courantes (30 et 60 fps), pas un curseur
 * continu qui inviterait à régler un chiffre arbitraire.
 */
export const ANALYSIS_FPS_CAPS: readonly { value: number | null; label: string }[] = [
  { value: null, label: "Illimité" },
  { value: 30, label: "30 img/s" },
  { value: 60, label: "60 img/s" },
];

/**
 * Nettoie une sélection de classes contre le catalogue **du serveur**.
 *
 * Trois cas réels, et aucun ne doit produire un 422 :
 *
 * - un identifiant que le serveur ne propose plus — réglage persisté par une
 *   version antérieure — est écarté ;
 * - les doublons sont écartés en gardant l'ordre du catalogue, qui est celui de
 *   l'affichage ;
 * - une sélection **vide** retombe sur les cases par défaut. Le serveur la
 *   refuserait, et à raison : elle ne restreindrait rien et compterait les 80
 *   classes de COCO. Retomber sur le défaut vaut mieux qu'un message d'erreur sur
 *   un écran où l'utilisateur a simplement tout décoché.
 */
export function sanitiseClassIds(
  selected: readonly number[],
  catalogue: readonly { id: number; defaultSelected: boolean }[],
): number[] {
  if (catalogue.length === 0) return [...selected];
  const wanted = new Set(selected);
  const kept = catalogue.filter((entry) => wanted.has(entry.id)).map((entry) => entry.id);
  if (kept.length > 0) return kept;
  return catalogue.filter((entry) => entry.defaultSelected).map((entry) => entry.id);
}

/** Confiance effective quand l'utilisateur suit le défaut. */
export const DEFAULT_CONFIDENCE = 0.35;

/* ── La liste de plaques recherchées : les bornes du serveur, recopiées ─────────
   Les dépasser vaudrait un 422 sur un écran dont toutes les valeurs paraissent
   valides — le mode de panne que ce module existe pour éviter. Miroir de
   `MAX_WATCHED_PLATES`, `MAX_WATCHED_PLATE_LENGTH` et `MIN_WATCHED_PLATE_CHARS`
   dans `counting/application/request_schema.py`. */

/** Au-delà, ce n'est plus une surveillance mais un fichier. */
export const MAX_WATCHED_PLATES = 10;

/** Longueur maximale d'une entrée, séparateurs compris. */
export const MAX_WATCHED_PLATE_LENGTH = 16;

/**
 * En dessous, une entrée correspondrait à trop de plaques pour signaler quoi que ce
 * soit : elle serait un générateur de fausses alertes, pas une recherche.
 */
export const MIN_WATCHED_PLATE_CHARS = 4;

/**
 * Les entrées que le serveur acceptera, dans l'ordre de saisie.
 *
 * **Un filtre et non une correction** : une entrée trop courte ou trop longue est
 * écartée, jamais tronquée ni complétée. Corriger une plaque à la place de
 * l'utilisateur produirait une recherche qu'il n'a pas demandée, et qui trouverait
 * peut-être quelque chose — le pire des deux résultats.
 *
 * Le champ de saisie refuse déjà ces cas ; ce garde couvre le chemin qui l'aurait
 * évité, exactement comme `analysisWindow` pour les bornes de la fenêtre.
 */
export function watchlistForRequest(entries: readonly string[]): string[] {
  const kept: string[] = [];
  for (const raw of entries) {
    const entry = raw.trim();
    if (entry.length > MAX_WATCHED_PLATE_LENGTH) continue;
    if (countAlphanumeric(entry) < MIN_WATCHED_PLATE_CHARS) continue;
    if (!kept.includes(entry)) kept.push(entry);
  }
  return kept.slice(0, MAX_WATCHED_PLATES);
}

function countAlphanumeric(entry: string): number {
  return entry.replace(/[^0-9A-Za-z]/g, "").length;
}

/**
 * Plancher de lecture effectif quand l'utilisateur suit le défaut.
 *
 * Miroir de `plate_ocr_min_text_score` côté serveur. Recopié ici pour que le curseur
 * parte de la valeur qui s'appliquera réellement : le montrer à zéro laisserait croire
 * qu'aucune lecture n'est refusée, alors que le serveur en refuse depuis toujours.
 */
export const DEFAULT_PLATE_TEXT_CONFIDENCE = 0.5;

/** Bornes acceptées par le serveur — les dépasser produirait un 422. */
export const BOUNDS = {
  confidenceThreshold: { min: 0.01, max: 0.99, step: 0.01 },
  iouThreshold: { min: 0.05, max: 0.95, step: 0.05 },
  minHits: { min: 1, max: 10, step: 1 },
  maxLostMs: { min: 200, max: 15_000, step: 100 },
  frameStride: { min: 1, max: 5, step: 1 },
  plateConfidence: { min: 0.05, max: 0.95, step: 0.05 },
  // Descend jusqu'à `0` — « accepte toutes les lectures » — là où le seuil de
  // localisation part de 0,05 : un détecteur à confiance nulle rendrait des
  // rectangles partout, alors qu'une lecture, elle, est déjà filtrée par la
  // normalisation du domaine et par le vote. La borne haute s'arrête à 0,95 parce
  // qu'à 1,0 plus aucune lecture ne passerait jamais.
  plateTextConfidence: { min: 0, max: 0.95, step: 0.05 },
} as const;

/**
 * Construit la requête envoyée au serveur.
 *
 * C'est **le seul endroit** où `confidenceThreshold: null` devient un nombre : le
 * serveur n'accepte pas `null`, et résoudre le défaut plus tôt ferait perdre
 * l'information « je suis le défaut ».
 */
export function toRequest(
  settings: AnalysisSettings,
  lines: readonly CountingLine[],
  zones: readonly Zone[],
  range: AnalysisRange = FULL_RANGE,
): AnalysisRequest {
  return {
    modelId: settings.modelId,
    confidenceThreshold: settings.confidenceThreshold ?? DEFAULT_CONFIDENCE,
    iouThreshold: settings.iouThreshold,
    minHits: settings.minHits,
    maxLostMs: settings.maxLostMs,
    maskOutsideZones: settings.maskOutsideZones && zones.length > 0,
    frameStride: settings.frameStride,
    detectPlates: settings.detectPlates,
    plateConfidence: settings.detectPlates ? settings.plateConfidence : null,
    // Subordonné à la **lecture** et non à la seule détection : c'est un plancher
    // sur ce que l'OCR rend, et sans OCR il n'y a rien à filtrer. L'envoyer quand
    // même demanderait au serveur d'arbitrer une incohérence que le client pouvait
    // éviter — même règle que `readPlateText` juste dessous.
    plateTextConfidence:
      settings.detectPlates && settings.readPlateText ? settings.plateTextConfidence : null,
    // Subordonné à `detectPlates`, comme côté serveur : lire sans détecter n'a pas de
    // sens, et laisser passer `true` seul demanderait au serveur d'arbitrer une
    // incohérence que le client pouvait éviter.
    readPlateText: settings.detectPlates && settings.readPlateText,
    // Subordonnée à la **lecture**, comme le plancher de confiance juste au-dessus :
    // sans texte lu, il n'y a rien à comparer, et envoyer quand même la liste
    // afficherait dans « Configuration système » une recherche que rien ne peut
    // satisfaire. Le tiroir Détection avertit séparément si une liste survit à un
    // décochage de l'OCR — c'est la panne silencieuse à éviter, pas le tri fait ici.
    plateWatchlist:
      settings.detectPlates && settings.readPlateText
        ? watchlistForRequest(settings.plateWatchlist)
        : [],
    // Jamais vide : le serveur refuse une liste vide, et il a raison. Le repli sur
    // les quatre véhicules est le même que celui de `sanitiseClassIds` — l'écran
    // reste utilisable quand l'utilisateur a tout décoché.
    classIds: settings.classIds.length > 0 ? [...settings.classIds] : [...DEFAULT_SETTINGS.classIds],
    // Borné aux cadences que le serveur accepte : une valeur hors de [0,25 ; 8] —
    // relue d'un `localStorage` bricolé — vaudrait un 422 sur un écran qui paraît
    // valide. Hors bornes ⇒ aucune borne, qui est le défaut.
    analysisSpeed: isSupportedSpeed(settings.analysisSpeed) ? settings.analysisSpeed : null,
    // Même logique que pour `analysisSpeed` : hors bornes ⇒ aucun plafond.
    maxAnalysisFps: isSupportedFpsCap(settings.maxAnalysisFps) ? settings.maxAnalysisFps : null,
    // **L'intervalle n'est pas persisté avec les autres réglages, et c'est
    // délibéré.** Les bornes décrivent *cette* vidéo — « de 00:34 à 05:00 » n'a
    // aucun sens sur le fichier suivant, et une fenêtre héritée d'une vidéo
    // précédente analyserait un morceau que personne n'a choisi. Elles voyagent
    // donc en argument, depuis l'état du studio, remis à neuf à chaque source.
    //
    // Bornes négatives écartées plutôt que corrigées : `clampRange` les a déjà
    // ramenées, et ce garde-ci n'existe que pour que le serveur ne reçoive jamais
    // ce que son schéma refuse en 422 — même rôle que pour les cadences.
    ...analysisWindow(range),
    lines: [...lines],
    zones: [...zones],
  };
}

/**
 * Les deux bornes de la fenêtre, sous la forme **exacte** que le serveur accepte.
 *
 * Dernier filet avant l'envoi, comme pour les cadences : le schéma refuse un début
 * négatif (`ge=0`), une fin nulle ou négative (`gt=0`) et une fin qui n'est pas
 * strictement après le début. `clampRange` a normalement déjà tout rattrapé — ce
 * garde couvre le chemin qui l'aurait évité, et un 422 sur un écran dont toutes les
 * valeurs paraissent valides est précisément ce que ce projet cherche à ne pas
 * produire.
 *
 * **Le début est normalisé d'abord, et c'est ce qui rend le garde correct.**
 * Comparer la fin au `startMs` *brut* laissait passer `{-10 ; -1}` : la fin est bien
 * après le début, et pourtant les deux valeurs sont refusées. C'est la version
 * précédente de ce code, attrapée par le test.
 */
function analysisWindow(range: AnalysisRange): { startMs: number; endMs: number | null } {
  const startMs = Number.isFinite(range.startMs) && range.startMs > 0 ? range.startMs : 0;
  const endMs =
    range.endMs !== null && Number.isFinite(range.endMs) && range.endMs > startMs
      ? range.endMs
      : null;
  return { startMs, endMs };
}

/**
 * Bornes du bridage côté serveur — les dépasser produirait un 422.
 *
 * Elles ne sont pas dans `BOUNDS` : ce n'est pas un curseur, et les afficher comme
 * un intervalle continu suggérerait des cadences que l'écran ne propose pas.
 */
export const SPEED_BOUNDS = { min: 0.25, max: 8 } as const;

/** Bornes du plafond absolu côté serveur — les dépasser produirait un 422. */
export const FPS_CAP_BOUNDS = { min: 1, max: 240 } as const;

function isSupportedSpeed(value: number | null): boolean {
  if (value === null) return true;
  return Number.isFinite(value) && value >= SPEED_BOUNDS.min && value <= SPEED_BOUNDS.max;
}

function isSupportedFpsCap(value: number | null): boolean {
  if (value === null) return true;
  return Number.isFinite(value) && value >= FPS_CAP_BOUNDS.min && value <= FPS_CAP_BOUNDS.max;
}

/**
 * Relit les réglages persistés, en repartant des défauts au moindre doute.
 *
 * **Ne lève jamais.** Les trois cas d'échec — pas de stockage (navigation privée),
 * JSON illisible, schéma d'une autre version — mènent tous au même résultat : les
 * défauts. C'est le comportement attendu après une mise à jour de l'application.
 *
 * La fusion est champ par champ et **typée** : un champ absent prend son défaut, un
 * champ du mauvais type est ignoré. Un `Object.assign` global laisserait passer une
 * chaîne là où un nombre est attendu, et le serveur refuserait la requête en 422
 * sans que l'utilisateur comprenne quel réglage est en cause.
 */
export function loadSettings(storage: Pick<Storage, "getItem"> | null = safeStorage()): AnalysisSettings {
  if (storage === null) return { ...DEFAULT_SETTINGS };

  let raw: string | null;
  try {
    raw = storage.getItem(STORAGE_KEY);
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
  if (raw === null) return { ...DEFAULT_SETTINGS };

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { ...DEFAULT_SETTINGS };
  }

  if (typeof parsed !== "object" || parsed === null) return { ...DEFAULT_SETTINGS };
  const record = parsed as Record<string, unknown>;

  // Version différente = forme inconnue. On ne devine pas : une valeur relue sous
  // un sens différent produirait une analyse dont les réglages ne sont pas ceux
  // que l'écran affiche. La version 1 est la **seule** exception, parce qu'on sait
  // exactement ce qui a changé entre elle et la 2 — voir `migrateV1`.
  if (record.version !== SETTINGS_SCHEMA_VERSION && record.version !== 1) {
    return { ...DEFAULT_SETTINGS };
  }

  const settings = record.settings;
  if (typeof settings !== "object" || settings === null) return { ...DEFAULT_SETTINGS };

  const source = record.settings as Record<string, unknown>;
  return mergeSettings(record.version === 1 ? migrateV1(source) : source);
}

/**
 * Version 1 → 2 : relâche le plafond de cadence que personne n'avait choisi.
 *
 * **Une migration ciblée plutôt qu'une remise à zéro.** Faire tomber la version 1
 * sur les défauts marcherait, et coûterait à l'utilisateur son modèle, ses classes,
 * ses seuils de plaques et sa liste de recherche — pour un seul champ à corriger.
 *
 * Le champ est **retiré** et non réécrit à `null` : `mergeSettings` traite un champ
 * absent comme « prend son défaut », donc le jour où le défaut rebougera, un poste
 * migré suivra au lieu de rester figé sur la valeur d'aujourd'hui.
 */
function migrateV1(source: Record<string, unknown>): Record<string, unknown> {
  if (source.maxAnalysisFps !== V1_DEFAULT_FPS_CAP) return source;
  const { maxAnalysisFps: _relache, ...reste } = source;
  return reste;
}

/** Fusion typée, champ par champ. */
function mergeSettings(source: Record<string, unknown>): AnalysisSettings {
  const merged = { ...DEFAULT_SETTINGS };

  if (typeof source.modelId === "string" && source.modelId !== "") {
    merged.modelId = source.modelId;
  }
  merged.confidenceThreshold = nullableNumber(source.confidenceThreshold, merged.confidenceThreshold);
  merged.iouThreshold = boundedNumber(source.iouThreshold, merged.iouThreshold, BOUNDS.iouThreshold);
  merged.minHits = boundedNumber(source.minHits, merged.minHits, BOUNDS.minHits);
  merged.maxLostMs = boundedNumber(source.maxLostMs, merged.maxLostMs, BOUNDS.maxLostMs);
  merged.frameStride = boundedNumber(source.frameStride, merged.frameStride, BOUNDS.frameStride);
  merged.plateConfidence = nullableNumber(source.plateConfidence, merged.plateConfidence);
  merged.plateTextConfidence = nullableNumber(
    source.plateTextConfidence,
    merged.plateTextConfidence,
  );
  // Écarté plutôt que borné, contrairement aux curseurs : une cadence hors bornes
  // n'est pas un intervalle qui a changé entre deux versions, c'est une valeur qui
  // ne correspond à aucun des trois choix de l'écran. La ramener à 8× afficherait
  // « Illimitée » tout en bridant — un réglage que l'écran contredirait.
  const speed = nullableNumber(source.analysisSpeed, merged.analysisSpeed);
  merged.analysisSpeed = isSupportedSpeed(speed) ? speed : merged.analysisSpeed;
  const fpsCap = nullableNumber(source.maxAnalysisFps, merged.maxAnalysisFps);
  merged.maxAnalysisFps = isSupportedFpsCap(fpsCap) ? fpsCap : merged.maxAnalysisFps;

  // Les identifiants non numériques sont écartés un par un plutôt que de faire
  // tomber toute la liste : un `localStorage` bricolé à la main ne doit pas coûter
  // la sélection entière. La confrontation au catalogue du serveur, elle, a lieu
  // dans `sanitiseClassIds` — ce module ne connaît pas le catalogue.
  if (Array.isArray(source.classIds)) {
    const ids = source.classIds.filter(
      (value): value is number => typeof value === "number" && Number.isInteger(value),
    );
    if (ids.length > 0) merged.classIds = [...new Set(ids)];
  }

  if (typeof source.maskOutsideZones === "boolean") merged.maskOutsideZones = source.maskOutsideZones;
  if (typeof source.detectPlates === "boolean") merged.detectPlates = source.detectPlates;
  if (typeof source.readPlateText === "boolean") merged.readPlateText = source.readPlateText;
  if (typeof source.showTrails === "boolean") merged.showTrails = source.showTrails;

  return merged;
}

function boundedNumber(
  value: unknown,
  fallback: number,
  bounds: { min: number; max: number },
): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  // Borné plutôt que rejeté : une valeur légèrement hors bornes vient d'un
  // changement de bornes entre versions, et la ramener dans l'intervalle respecte
  // mieux l'intention de l'utilisateur que de l'oublier.
  return Math.min(bounds.max, Math.max(bounds.min, value));
}

function nullableNumber(value: unknown, fallback: number | null): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  return value;
}

/**
 * Écrit les réglages. Silencieux en cas d'échec : ce n'est pas critique.
 *
 * **`plateWatchlist` est retirée avant l'écriture**, et c'est le seul champ dans ce
 * cas. Elle décrit une recherche en cours et non une préférence ; et surtout, écrire
 * un numéro de plaque dans le `localStorage` du poste franchirait le cran de
 * confidentialité que ce projet impose déjà en laissant l'OCR décoché par défaut.
 * Ce qu'on demande un consentement explicite pour **lire** ne se persiste pas par
 * effet de bord.
 *
 * Le retrait est fait ici et pas seulement à la relecture : un champ absent du
 * stockage ne peut pas y rester après une mise à jour qui changerait `mergeSettings`.
 */
export function saveSettings(
  settings: AnalysisSettings,
  storage: Pick<Storage, "setItem"> | null = safeStorage(),
): void {
  if (storage === null) return;
  const { plateWatchlist: _unsaved, ...persisted } = settings;
  try {
    storage.setItem(
      STORAGE_KEY,
      JSON.stringify({ version: SETTINGS_SCHEMA_VERSION, settings: persisted }),
    );
  } catch {
    // Quota dépassé ou navigation privée : perdre une préférence n'est pas une
    // raison de faire échouer une analyse.
  }
}

/**
 * `localStorage` s'il est accessible.
 *
 * Y accéder **lève** dans un iframe restreint ou avec les cookies tiers bloqués :
 * ce n'est pas seulement `null`, c'est une exception au premier accès.
 */
function safeStorage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}
