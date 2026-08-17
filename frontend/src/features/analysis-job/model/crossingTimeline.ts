/**
 * La **chronologie** des franchissements : ce qu'un tableau de lignes ne dit pas.
 *
 * Le journal a toujours répondu à « qui a franchi quoi, quand ». Sous forme de
 * tableau, il ne répondait qu'à cela : chaque ligne était un fait isolé, et tout ce
 * qui se lit *entre* deux faits — le rythme du trafic, le temps qu'un véhicule met à
 * traverser le carrefour, deux passages tombés dans la même seconde — restait à
 * reconstituer de tête devant l'écran. Ce module calcule ces relations une fois, en
 * un seul parcours, pour que l'affichage n'ait plus qu'à les rendre.
 *
 * Trois relations, et chacune répond à une question qu'on se posait sans pouvoir y
 * répondre :
 *
 * - **`gapMs`** — l'écart avec le franchissement précédent, toutes lignes
 *   confondues. C'est le rythme : quatre passages en une seconde et demie ne
 *   décrivent pas le même carrefour que quatre passages en deux minutes, et le
 *   tableau les affichait identiquement ;
 * - **`previous`** — le passage précédent du **même véhicule**, quand il est encore
 *   dans le journal. Une entrée suivie d'une sortie donne le **temps de traversée
 *   du carrefour**, la seule mesure de ce genre que l'interface produise ;
 * - **`passageIndex`** — le rang de ce passage dans la vie du véhicule. Un `2` dit
 *   « aller-retour, deux lignes en travers de la même voie, ou piste coupée par une
 *   occlusion » (invariant 6) là où deux entrées identiques se lisaient comme un
 *   doublon d'affichage.
 *
 * **Tout est relatif au journal, jamais à l'analyse.** Le journal est borné à
 * `LOG_LIMIT` (200) : passé ce seuil, les plus anciens sont oubliés, donc
 * `passageIndex` peut sous-compter et `gapMs` du plus ancien est `null`. Rien ici ne
 * doit donc servir de total — les totaux restent ceux du serveur, dérivés de
 * `stats.byLine` (invariant 3). C'est pourquoi l'écran annonce explicitement la
 * borne dès qu'elle est atteinte : un compteur de journal qui plafonne sans le dire
 * contredirait le tableau de bord juste au-dessus.
 */

import type {
  CountingLine,
  CrossingEvent,
  DirectionRole,
  DirectionSign,
} from "@/shared/api/contracts";
import { directionArrow, directionName, directionRole, signOf } from "@/shared/lib/directions";
import { arrowRotationDeg, positiveNormal } from "@/shared/lib/geometry";

/**
 * Le passage précédent du même véhicule, tel que la chronologie le voit.
 *
 * `deltaMs` est un temps de scène, comme tout le reste (invariant 1) : sur une paire
 * entrée → sortie, c'est le temps passé dans le carrefour.
 */
export interface PreviousPassage {
  role: DirectionRole;
  lineName: string;
  timestampMs: number;
  deltaMs: number;
}

/** Un franchissement, **replacé dans sa chronologie**. */
export interface CrossingEntry {
  event: CrossingEvent;
  /**
   * Le rôle du sens emprunté, lu sur le **tracé courant**.
   *
   * `neutral` couvre deux cas que l'affichage distingue par ailleurs : une ligne
   * tracée avant qu'ADR 0021 rende le rôle obligatoire, et une ligne retirée du
   * tracé depuis l'analyse (`lineColor === null`). Comme dans le registre, le rôle
   * n'est jamais inventé : le serveur ne le connaît pas et ne le lira jamais.
   */
  role: DirectionRole;
  /** « Entrée », « Sortie », ou le nom du sens d'une ligne restée neutre. */
  directionName: string;
  /**
   * Angle de la flèche du franchissement, en degrés, `null` si incalculable.
   *
   * C'est l'angle **réel du tracé** — la perpendiculaire au trait, orientée du côté
   * d'arrivée — et non un symbole conventionnel. Une flèche pivotée à cet angle est
   * la même que celle du panneau de géométrie et du canvas pour ce sens-là : le
   * regard fait donc le lien entre la rangée du journal et le trait à l'écran, ce
   * qu'aucun pictogramme d'« entrée » ou de « sortie » ne permet.
   *
   * `null` uniquement quand la géométrie ne peut rien dire : ligne retirée du tracé
   * depuis l'analyse, ou segment de longueur nulle. Poser `0` à la place ferait
   * pointer une flèche vers le haut, donc affirmerait un angle que personne n'a
   * mesuré — même discipline que le rôle, jamais inventé.
   */
  headingDeg: number | null;
  lineName: string;
  /** `null` quand la ligne n'est plus tracée : l'événement reste, sa couleur n'existe plus. */
  lineColor: string | null;
  /** Écart avec le franchissement précédent **du journal**. `null` sur le plus ancien. */
  gapMs: number | null;
  /** Rang de ce passage dans la vie du véhicule, **vu du journal**. `1` au premier. */
  passageIndex: number;
  previous: PreviousPassage | null;
}

/**
 * Replace chaque franchissement dans sa chronologie.
 *
 * Entrée **et** sortie dans l'ordre du journal — le plus récent en tête. Le calcul,
 * lui, remonte le temps dans l'autre sens : « précédent » ne peut se calculer que sur
 * un fait déjà vu, et le parcours antichronologique demanderait de revenir en
 * arrière pour chaque véhicule.
 */
export function describeCrossings(
  events: readonly CrossingEvent[],
  lines: readonly CountingLine[],
): readonly CrossingEntry[] {
  const chronological = [...events].reverse();
  /** Dernier passage vu de chaque véhicule, pour lier une sortie à son entrée. */
  const lastOf = new Map<number, CrossingEntry>();
  const built: CrossingEntry[] = [];
  let previousMs: number | null = null;

  for (const event of chronological) {
    const line = lines.find((candidate) => candidate.id === event.lineId);
    const sign = signOf(event.direction);
    const before = lastOf.get(event.globalId);

    const entry: CrossingEntry = {
      event,
      role: line === undefined ? "neutral" : directionRole(line, sign),
      // La flèche brute pour une ligne effacée : inventer « Entrée » fabriquerait un
      // rôle que personne n'a déclaré. Même règle que `crossingsWithRole` au registre.
      directionName:
        line === undefined ? `sens ${directionArrow(event.direction)}` : directionName(line, sign),
      headingDeg: line === undefined ? null : crossingHeadingDeg(line, sign),
      lineName: line?.name ?? event.lineId,
      lineColor: line?.color ?? null,
      // `Math.max(0, …)` : deux franchissements de la même image portent le même
      // horodatage, et un écart négatif serait le signe d'un journal désordonné —
      // à afficher comme zéro plutôt que comme « −0,1 s ».
      gapMs: previousMs === null ? null : Math.max(0, event.timestampMs - previousMs),
      passageIndex: before === undefined ? 1 : before.passageIndex + 1,
      previous:
        before === undefined
          ? null
          : {
              role: before.role,
              lineName: before.lineName,
              timestampMs: before.event.timestampMs,
              deltaMs: Math.max(0, event.timestampMs - before.event.timestampMs),
            },
    };

    built.push(entry);
    lastOf.set(event.globalId, entry);
    previousMs = event.timestampMs;
  }

  return built.reverse();
}

/**
 * L'angle, en degrés, d'une flèche qui pointe dans le sens du franchissement.
 *
 * **Le même calcul que le panneau de géométrie et le canvas**, aux mêmes fonctions
 * partagées près (`positiveNormal` puis `arrowRotationDeg`) : c'est ce qui garantit
 * que la flèche d'une rangée du journal et celle du trait à l'écran pointent au même
 * endroit. Recalculer une perpendiculaire ici ferait vivre la même règle à deux
 * endroits, et `shared/lib/geometry.ts` documente précisément ce mode de panne — un
 * signe inversé donne des sens faux sous des totaux justes, sans que rien ne plante.
 *
 * Le franchissement traverse la ligne **perpendiculairement** au trait, vers le côté
 * d'arrivée : le sens positif suit `positiveNormal`, le négatif son opposé. L'angle
 * est donc celui du trait tourné d'un quart de tour, ce qui est exactement ce qu'on
 * voit sur le canvas — une ligne horizontale se franchit verticalement.
 *
 * `null` sur un segment de longueur nulle : aucune orientation n'existe, et
 * `arrowRotationDeg` y rendrait `0`, soit une flèche vers le haut affirmée sans
 * mesure.
 */
export function crossingHeadingDeg(line: CountingLine, sign: DirectionSign): number | null {
  const normal = positiveNormal(line.a, line.b);
  if (normal.x === 0 && normal.y === 0) return null;
  return arrowRotationDeg(sign === "positive" ? normal : { x: -normal.x, y: -normal.y });
}

/* ═══════════════════════════════════════════════════════════════════════════
   Filtrage — lire le journal par rôle et par ligne.
   ═══════════════════════════════════════════════════════════════════════════ */

/** `all` plutôt qu'un `null` : le filtre porte trois valeurs de rôle, pas deux. */
export type RoleFilter = DirectionRole | "all";

export interface CrossingFilter {
  role: RoleFilter;
  /** `null` = toutes les lignes. */
  lineId: string | null;
}

/** Le filtre neutre. Gelé et partagé : les lecteurs ne le mutent jamais. */
export const NO_CROSSING_FILTER: CrossingFilter = Object.freeze({ role: "all", lineId: null });

/** Le filtre laisse-t-il tout passer ? Décide de l'affichage du « réinitialiser ». */
export function isFilterEmpty(filter: CrossingFilter): boolean {
  return filter.role === "all" && filter.lineId === null;
}

/**
 * Applique le filtre.
 *
 * Rend le tableau **inchangé** quand le filtre est neutre — identité référentielle,
 * comme `appendCrossings` : le journal se rerend cinq fois par seconde pendant une
 * analyse, et allouer une copie à chaque aperçu pour n'écarter personne serait du
 * gaspillage sur un chemin chaud.
 */
export function filterCrossings(
  entries: readonly CrossingEntry[],
  filter: CrossingFilter,
): readonly CrossingEntry[] {
  if (isFilterEmpty(filter)) return entries;
  return entries.filter(
    (entry) =>
      (filter.role === "all" || entry.role === filter.role) &&
      (filter.lineId === null || entry.event.lineId === filter.lineId),
  );
}

/** Un onglet de filtre par ligne : son identité, sa couleur, et ce qu'elle porte. */
export interface LineFacet {
  lineId: string;
  lineName: string;
  lineColor: string | null;
  count: number;
}

/**
 * De quoi étiqueter les filtres : combien d'entrées, de sorties, et par ligne.
 *
 * **Ces comptes sont ceux du journal, pas de l'analyse**, et l'écran le dit. Ils ne
 * remplacent aucun total : `stats.byLine` reste la seule autorité (invariant 3).
 *
 * **Toutes les lignes du tracé y figurent, y compris à zéro** — la même règle que
 * `directionRows` côté tableau de bord. Un onglet absent se lirait « pas
 * d'information » alors qu'une ligne à zéro est une information : elle est posée là
 * où rien ne passe. Les lignes retirées du tracé mais présentes dans le journal
 * suivent, dans leur ordre d'apparition : leur franchissement a bien eu lieu.
 */
export function crossingFacets(
  entries: readonly CrossingEntry[],
  lines: readonly CountingLine[],
): { byRole: Readonly<Record<DirectionRole, number>>; byLine: readonly LineFacet[] } {
  const byRole: Record<DirectionRole, number> = { entry: 0, exit: 0, neutral: 0 };
  const counts = new Map<string, number>();

  for (const entry of entries) {
    byRole[entry.role] += 1;
    counts.set(entry.event.lineId, (counts.get(entry.event.lineId) ?? 0) + 1);
  }

  const byLine: LineFacet[] = lines.map((line) => ({
    lineId: line.id,
    lineName: line.name,
    lineColor: line.color,
    count: counts.get(line.id) ?? 0,
  }));

  const known = new Set(lines.map((line) => line.id));
  for (const entry of entries) {
    if (known.has(entry.event.lineId)) continue;
    known.add(entry.event.lineId);
    byLine.push({
      lineId: entry.event.lineId,
      lineName: entry.lineName,
      lineColor: null,
      count: counts.get(entry.event.lineId) ?? 0,
    });
  }

  return { byRole, byLine };
}

/* ═══════════════════════════════════════════════════════════════════════════
   Regroupement — les tranches de temps qui structurent la chronologie.
   ═══════════════════════════════════════════════════════════════════════════ */

/**
 * Les tailles de tranche possibles, de 5 s à 10 min.
 *
 * Une échelle et non une constante : à 10 s fixes, un journal étalé sur trente
 * minutes produirait jusqu'à 180 en-têtes pour 200 franchissements — un titre par
 * événement, donc l'inverse d'un regroupement.
 */
export const BUCKET_LADDER: readonly number[] = [5_000, 10_000, 30_000, 60_000, 300_000, 600_000];

/** Cible : une tranche pour quatre franchissements. Assez pour grouper, assez pour situer. */
export const BUCKET_TARGET_PER_GROUP = 4;

/**
 * Choisit la taille de tranche pour un journal donné.
 *
 * Prend le plus petit palier de l'échelle qui atteigne la cible, et le plus grand
 * palier quand même celui-là n'y suffit pas — plutôt qu'une valeur calculée au
 * millième, qui donnerait des bornes comme « 00:17 → 00:31 » impossibles à relier à
 * la barre de lecture.
 */
export function chooseBucketMs(
  spanMs: number,
  count: number,
  ladder: readonly number[] = BUCKET_LADDER,
): number {
  const first = ladder[0] ?? 10_000;
  const last = ladder[ladder.length - 1] ?? first;
  if (count <= 1 || spanMs <= 0) return first;

  const groups = Math.max(1, Math.ceil(count / BUCKET_TARGET_PER_GROUP));
  const ideal = spanMs / groups;
  return ladder.find((step) => step >= ideal) ?? last;
}

/** Une tranche de temps et les franchissements qui y tombent. */
export interface CrossingBucket {
  startMs: number;
  endMs: number;
  /** Le plus récent en tête, comme le journal entier. */
  entries: readonly CrossingEntry[];
}

/**
 * Découpe la chronologie en tranches alignées sur des bornes rondes.
 *
 * Alignées et non ancrées sur le premier événement : « 01:20 → 01:30 » se retrouve
 * sur la barre de lecture, « 01:17 → 01:27 » non. Seules les tranches **non vides**
 * sont rendues — un silence de trois minutes ne mérite pas dix-huit en-têtes vides,
 * et l'écart est déjà porté par le `gapMs` de l'événement qui le suit.
 */
export function bucketiseCrossings(
  entries: readonly CrossingEntry[],
  bucketMs: number,
): readonly CrossingBucket[] {
  if (entries.length === 0 || bucketMs <= 0) return [];

  const buckets: CrossingBucket[] = [];
  let current: { startMs: number; entries: CrossingEntry[] } | null = null;

  // L'ordre d'entrée est conservé — le plus récent en tête — donc les tranches
  // sortent de la plus récente à la plus ancienne, sans tri.
  for (const entry of entries) {
    const startMs = Math.floor(entry.event.timestampMs / bucketMs) * bucketMs;
    if (current === null || current.startMs !== startMs) {
      current = { startMs, entries: [] };
      buckets.push({ startMs, endMs: startMs + bucketMs, entries: current.entries });
    }
    current.entries.push(entry);
  }

  return buckets;
}

/* ═══════════════════════════════════════════════════════════════════════════
   Mise en mots — les durées et les relations, telles qu'elles s'affichent.
   ═══════════════════════════════════════════════════════════════════════════ */

/**
 * Une **durée** en français : « 0,4 s », « 12 s », « 2 min 05 s ».
 *
 * La virgule décimale et non le point, contrairement aux **instants** du journal
 * (`00:12.4`) : une durée se lit comme de la prose française, un horodatage comme un
 * repère de lecteur vidéo. Les deux se côtoient sur le même écran, et c'est
 * précisément parce qu'ils ne mesurent pas la même chose qu'ils ne se ponctuent pas
 * pareil.
 *
 * La décimale disparaît au-delà de dix secondes : « 14,3 s » suggère une précision
 * que la cadence d'échantillonnage ne porte pas.
 */
export function formatDuration(ms: number): string {
  const safe = Math.max(0, ms);
  if (safe < 10_000) return `${(safe / 1000).toFixed(1).replace(".", ",")} s`;
  if (safe < 60_000) return `${Math.round(safe / 1000)} s`;

  const totalSeconds = Math.round(safe / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes} min ${String(seconds).padStart(2, "0")} s`;
}

/**
 * Les bornes d'une tranche, en `mm:ss`.
 *
 * À la seconde et non au dixième : les bornes sont rondes par construction, et un
 * « 01:20.0 → 01:30.0 » n'ajouterait que du bruit là où le dixième sert, lui, à
 * distinguer deux franchissements de la même seconde.
 */
export function formatBucketRange(startMs: number, endMs: number): string {
  return `${formatClock(startMs)} → ${formatClock(endMs)}`;
}

function formatClock(ms: number): string {
  const totalSeconds = Math.floor(Math.max(0, ms) / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

/**
 * Ce que le passage précédent du même véhicule apprend sur celui-ci, ou `null`.
 *
 * Les deux premiers cas sont l'intérêt de tout le module : une entrée suivie d'une
 * sortie donne le **temps de traversée du carrefour**, et une sortie suivie d'une
 * entrée un retour. Le troisième couvre le reste — deux entrées, deux sorties, un
 * sens sans rôle — sans prétendre l'interpréter : il dit le rang et l'écart, ce qui
 * suffit à comprendre qu'on regarde le même véhicule et non un doublon d'affichage.
 *
 * « dans ce journal » est sous-entendu et assumé : au-delà de `LOG_LIMIT`, un
 * premier passage oublié rend `passageIndex` prudent. La phrase reste vraie — elle
 * relie deux franchissements tous deux visibles à l'écran.
 */
export function passageNote(entry: CrossingEntry): string | null {
  const previous = entry.previous;
  if (previous === null) return null;

  const delta = formatDuration(previous.deltaMs);
  if (previous.role === "entry" && entry.role === "exit") {
    return `Ressorti ${delta} après son entrée par « ${previous.lineName} »`;
  }
  if (previous.role === "exit" && entry.role === "entry") {
    return `Revenu ${delta} après sa sortie par « ${previous.lineName} »`;
  }
  return `${ordinal(entry.passageIndex)} passage — ${delta} après « ${previous.lineName} »`;
}

/** Ordinal français abrégé : « 2ᵉ », « 3ᵉ »… Le premier ne s'écrit jamais ici. */
function ordinal(rank: number): string {
  return rank <= 1 ? "1ᵉʳ" : `${rank}ᵉ`;
}
