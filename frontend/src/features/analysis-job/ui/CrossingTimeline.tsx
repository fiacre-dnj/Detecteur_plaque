/**
 * La chronologie des franchissements, au fil de l'analyse.
 *
 * **Pourquoi ce panneau existe** : un total se croit, une liste se vérifie. Pouvoir
 * dire « à 00:12.4, cette voiture-là est entrée par cette ligne-là » et le confronter
 * à l'image qu'on a sous les yeux est ce qui sépare une analyse qu'on livre d'une
 * analyse qu'on valide.
 *
 * **Pourquoi une chronologie et non un tableau** : la version en tableau posait un
 * fait par ligne, sans rien dire de ce qui se lit *entre* deux faits. Quatre passages
 * en une seconde et demie et quatre passages en deux minutes s'y affichaient
 * identiquement ; l'entrée et la sortie d'un même véhicule étaient deux lignes que
 * rien ne reliait ; et un aller-retour se lisait comme un doublon d'affichage. Ces
 * relations sont calculées par `model/crossingTimeline.ts` et rendues ici : une
 * colonne vertébrale, des tranches de temps, l'écart avec le passage précédent, et le
 * temps de traversée du carrefour quand une sortie suit une entrée.
 *
 * Quatre règles d'affichage, chacune payée par un défaut de la version précédente :
 *
 * - **le plus récent en tête, et la liste ne défile pas toute seule.** Un défilement
 *   automatique arracherait la ligne qu'on est en train de lire — celle qu'on
 *   regardait justement la vidéo pour voir ;
 * - **les compteurs de cette section sont ceux du journal, pas de l'analyse.** Le
 *   journal est borné à `LOG_LIMIT` ; l'ancienne version affichait `events.length`
 *   comme un total, qui plafonnait donc à 200 en silence sous un tableau de bord qui
 *   continuait de monter. La borne est désormais annoncée dès qu'elle est atteinte, et
 *   les totaux restent ceux du serveur (invariant 3) ;
 * - **le rôle du sens est l'information de tête**, pas le signe. « sens + » ne dit
 *   rien à qui regarde un carrefour ; « Entrée » répond à la question posée. Le rôle
 *   est lu sur le **tracé courant**, donc basculer un sens entrée ↔ sortie réétiquette
 *   la chronologie sans réanalyser — même mécanique que le registre ;
 * - **aucune région `aria-live`.** Annoncer chaque franchissement transformerait un
 *   lecteur d'écran en métronome sur un carrefour chargé. La chronologie se consulte,
 *   elle n'interpelle pas.
 *
 * Ce panneau **ne sert pas à se déplacer dans le temps** : c'est le rôle de la barre
 * de lecture, et c'est le double emploi qui avait fait retirer l'ancienne chronologie
 * cliquable. Aucun clic ici ne déplace la tête de lecture.
 */

import { ArrowUp, CornerDownRight, Filter } from "lucide-react";
import { useMemo, useState } from "react";

import type { CountingLine, CrossingEvent, DirectionRole } from "@/shared/api/contracts";
import { classColor } from "@/shared/config/palettes";
import { classLabel } from "@/shared/lib/classes";
import { plateCell, plateTitle } from "@/shared/lib/plate";

import {
  NO_CROSSING_FILTER,
  bucketiseCrossings,
  chooseBucketMs,
  crossingFacets,
  describeCrossings,
  filterCrossings,
  formatBucketRange,
  formatDuration,
  isFilterEmpty,
  passageNote,
  type CrossingBucket,
  type CrossingEntry,
  type CrossingFilter,
  type RoleFilter,
} from "../model/crossingTimeline";
import { LOG_LIMIT, formatSceneTime } from "../model/previewLog";

interface CrossingTimelineProps {
  /** Le journal tel que le suivi le tient : le plus récent en tête, borné. */
  events: readonly CrossingEvent[];
  /**
   * La géométrie **courante**, et non une table de noms.
   *
   * Les lignes entières parce que la chronologie nomme le *rôle* du sens — « Entrée »,
   * « Sortie » — que seule la ligne complète permet de lire. Un nom de ligne seul
   * obligeait à afficher « sens + », le contrat machine.
   */
  lines: readonly CountingLine[];
  /**
   * L'analyse tourne-t-elle encore ?
   *
   * Ne change que deux détails, tous deux honnêtes : la pastille de battement et le
   * halo sur le franchissement le plus récent. Marquer « le dernier compté » sur un
   * journal figé serait une fausse indication de vie.
   */
  live?: boolean;
  title?: string;
}

/** Hauteur du défilement : assez pour une dizaine de passages sans manger la page. */
const VIEWPORT_CLASS = "max-h-[26rem]";

export function CrossingTimeline({
  events,
  lines,
  live = false,
  title = "Franchissements",
}: CrossingTimelineProps) {
  const [filter, setFilter] = useState<CrossingFilter>(NO_CROSSING_FILTER);

  const entries = useMemo(() => describeCrossings(events, lines), [events, lines]);
  const facets = useMemo(() => crossingFacets(entries, lines), [entries, lines]);
  const visible = useMemo(() => filterCrossings(entries, filter), [entries, filter]);

  const buckets = useMemo(() => {
    if (visible.length === 0) return [];
    // L'étendue se mesure sur ce qui est **affiché** : filtrer sur une seule ligne
    // resserre le journal, et garder la taille de tranche de l'ensemble donnerait
    // une seule tranche pour tout.
    const newest = visible[0]?.event.timestampMs ?? 0;
    const oldest = visible[visible.length - 1]?.event.timestampMs ?? 0;
    return bucketiseCrossings(visible, chooseBucketMs(newest - oldest, visible.length));
  }, [visible]);

  const busiestBucket = buckets.reduce((max, bucket) => Math.max(max, bucket.entries.length), 0);
  const filtered = !isFilterEmpty(filter);
  const truncated = events.length >= LOG_LIMIT;

  return (
    <section aria-labelledby="crossings-title" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-1">
        <div className="min-w-0">
          <h2 id="crossings-title" className="label-micro">
            {title}
          </h2>
          <p className="mt-0.5 text-micro text-ink-dim">
            Chronologie du plus récent au plus ancien — elle ne défile pas toute seule.
          </p>
        </div>

        <p className="flex shrink-0 items-baseline gap-1.5">
          {live && (
            // La seule couleur d'accent de la section, et elle est fonctionnelle :
            // « le journal reçoit encore des événements » (ADR 0004).
            <span aria-hidden="true" className="size-1.5 animate-pulse self-center rounded-pill bg-accent" />
          )}
          <output className="text-caption font-bold text-ink tabular">{visible.length}</output>
          {/* Jamais « sur 47 franchissements » tout court : ce 47 est le contenu du
              journal, pas le total de l'analyse, et les deux divergent dès la 201ᵉ. */}
          <span className="text-micro text-ink-dim">
            {filtered ? `sur ${entries.length} au journal` : "au journal"}
          </span>
        </p>
      </div>

      {events.length === 0 ? (
        <p className="rounded-card bg-surface p-4 text-caption text-ink-dim shadow-card">
          Aucun franchissement pour l'instant. Chaque passage compté par le serveur
          apparaît ici, avec l'instant, la ligne, le sens et le véhicule — de quoi le
          retrouver sur la vidéo et le vérifier.
        </p>
      ) : (
        <div className="overflow-hidden rounded-card bg-surface shadow-card">
          <FilterBar facets={facets} filter={filter} onChange={setFilter} />

          {visible.length === 0 ? (
            <p className="p-4 text-caption text-ink-dim">
              Aucun franchissement ne correspond à ce filtre.{" "}
              <button
                type="button"
                onClick={() => setFilter(NO_CROSSING_FILTER)}
                className="underline transition-colors hover:text-ink"
              >
                Tout afficher
              </button>
            </p>
          ) : (
            <div className={`${VIEWPORT_CLASS} overflow-y-auto`}>
              {buckets.map((bucket, index) => (
                <Bucket
                  key={bucket.startMs}
                  bucket={bucket}
                  bordered={index > 0}
                  busiest={busiestBucket}
                  // Le tout premier de la toute première tranche : le dernier compté.
                  latestId={live && index === 0 ? entryKey(bucket.entries[0]) : null}
                />
              ))}
            </div>
          )}

          {truncated && (
            // La borne, dite plutôt que subie. Sans cette phrase, un compteur de
            // journal figé à 200 sous un tableau de bord qui monte se lit comme une
            // panne de comptage.
            <p className="border-t border-line/40 px-3 py-2 text-micro text-ink-dim">
              La chronologie garde les {LOG_LIMIT} derniers franchissements ; les plus
              anciens sont oubliés. Les totaux du tableau de bord, eux, portent sur
              toute l'analyse.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Le filtre — lire la chronologie par rôle et par ligne.
   ═══════════════════════════════════════════════════════════════════════════ */

/**
 * Les onglets de filtre.
 *
 * Ce n'est pas un moyen de navigation mais de lecture : « montre-moi seulement les
 * sorties par la voie sud » est la question qu'on pose devant un carrefour chargé, et
 * la barre de lecture n'y répond pas.
 *
 * **Les compteurs sont ceux du journal**, et l'infobulle le dit. Une ligne à zéro
 * garde son onglet — désactivé — parce qu'un zéro est une information : la ligne est
 * posée là où rien ne passe. La faire disparaître laisserait croire à un oubli.
 */
function FilterBar({
  facets,
  filter,
  onChange,
}: {
  facets: ReturnType<typeof crossingFacets>;
  filter: CrossingFilter;
  onChange: (filter: CrossingFilter) => void;
}) {
  const roles: { role: RoleFilter; label: string; count: number | null }[] = [
    { role: "all", label: "Tout", count: null },
    { role: "entry", label: "Entrées", count: facets.byRole.entry },
    { role: "exit", label: "Sorties", count: facets.byRole.exit },
  ];
  // Mêmes règles d'apparition que « Sans rôle » ci-dessous : un onglet permanent à
  // zéro sur un tracé qui ne déclare aucune de ces deux natures serait un choix de
  // plus à lire pour rien.
  if (facets.byRole.forbidden > 0) {
    roles.push({ role: "forbidden", label: "Interdits", count: facets.byRole.forbidden });
  }
  if (facets.byRole.transit > 0) {
    roles.push({ role: "transit", label: "Passages", count: facets.byRole.transit });
  }
  // « Sans rôle » n'apparaît que s'il y en a : sur un tracé conforme à ADR 0021, cet
  // onglet serait un troisième choix permanent à zéro.
  if (facets.byRole.neutral > 0) {
    roles.push({ role: "neutral", label: "Sans rôle", count: facets.byRole.neutral });
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5 border-b border-line/40 p-2.5">
      <Filter aria-hidden="true" size={12} className="me-0.5 shrink-0 text-ink-dim" />

      {roles.map(({ role, label, count }) => (
        <Chip
          key={role}
          active={filter.role === role}
          disabled={count === 0}
          onClick={() => onChange({ ...filter, role })}
          title={count === null ? undefined : `${count} au journal`}
        >
          {label}
          {count !== null && <Count value={count} />}
        </Chip>
      ))}

      {facets.byLine.length > 1 && (
        <>
          <span aria-hidden="true" className="mx-1 h-4 w-px bg-line/60" />
          <Chip
            active={filter.lineId === null}
            onClick={() => onChange({ ...filter, lineId: null })}
          >
            Toutes les lignes
          </Chip>
          {facets.byLine.map((facet) => (
            <Chip
              key={facet.lineId}
              active={filter.lineId === facet.lineId}
              disabled={facet.count === 0}
              onClick={() => onChange({ ...filter, lineId: facet.lineId })}
              title={`${facet.count} au journal`}
            >
              <span
                aria-hidden="true"
                className={`size-2 shrink-0 rounded-badge ${facet.lineColor === null ? "bg-ink-dim" : ""}`}
                style={facet.lineColor === null ? undefined : { backgroundColor: facet.lineColor }}
              />
              <span className="max-w-28 truncate">{facet.lineName}</span>
              <Count value={facet.count} />
            </Chip>
          ))}
        </>
      )}
    </div>
  );
}

function Chip({
  active,
  disabled = false,
  onClick,
  title,
  children,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  /** `| undefined` explicite : `exactOptionalPropertyTypes` refuse sinon l'onglet « Tout », qui n'a pas de compte à annoncer. */
  title?: string | undefined;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      title={title}
      className={[
        "inline-flex items-center gap-1.5 rounded-pill px-2.5 py-1 text-micro font-semibold tracking-wide",
        "ring-1 transition-colors",
        active
          ? "bg-ink/15 text-ink ring-ink/30"
          : "bg-elevated text-ink-muted ring-transparent hover:text-ink",
        // Un onglet désactivé reste lisible : l'estomper jusqu'à l'illisibilité
        // empêche de comprendre ce qui est indisponible (même règle que `Button`).
        "disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:text-ink-muted",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

function Count({ value }: { value: number }) {
  return <span className="tabular text-ink-dim">{value}</span>;
}

/* ═══════════════════════════════════════════════════════════════════════════
   Une tranche de temps et ses franchissements.
   ═══════════════════════════════════════════════════════════════════════════ */

/**
 * Une tranche de temps : son en-tête collant, sa barre de densité, ses passages.
 *
 * L'en-tête est `sticky` parce que la chronologie défile : sans lui, on perd de vue
 * *quand* on est en descendant, et chaque instant redevient un nombre isolé.
 *
 * La barre de densité remplace l'ancien rail d'histogramme sans en reprendre le
 * défaut : elle ne prétend pas être un axe temporel — les tranches vides ne sont pas
 * rendues — mais compare les tranches entre elles d'un coup d'œil.
 */
function Bucket({
  bucket,
  bordered,
  busiest,
  latestId,
}: {
  bucket: CrossingBucket;
  bordered: boolean;
  busiest: number;
  latestId: string | null;
}) {
  const count = bucket.entries.length;
  const share = busiest === 0 ? 0 : (count / busiest) * 100;

  return (
    <div>
      <h3
        className={`sticky top-0 z-10 flex items-center gap-2 bg-surface-2 px-3 py-1.5 ${
          bordered ? "border-t border-line/40" : ""
        }`}
      >
        <span className="shrink-0 text-micro font-bold text-ink-muted tabular">
          {formatBucketRange(bucket.startMs, bucket.endMs)}
        </span>
        <span aria-hidden="true" className="h-1 w-16 overflow-hidden rounded-pill bg-elevated">
          <span className="block h-full rounded-pill bg-ink-dim" style={{ width: `${share}%` }} />
        </span>
        <span className="ms-auto shrink-0 text-micro text-ink-dim tabular">
          {count} {count > 1 ? "passages" : "passage"}
        </span>
      </h3>

      <ol>
        {bucket.entries.map((entry) => (
          <Passage key={entryKey(entry)} entry={entry} latest={entryKey(entry) === latestId} />
        ))}
      </ol>
    </div>
  );
}

/**
 * Un franchissement, sur la colonne vertébrale.
 *
 * Deux étages : ce qui s'est passé, puis — seulement quand il y a quelque chose à en
 * dire — ce que le passage précédent du même véhicule apprend. Le second étage est
 * absent la plupart du temps, et c'est voulu : une ligne « — » par franchissement sans
 * antécédent ferait passer l'exception pour la règle.
 */
function Passage({ entry, latest }: { entry: CrossingEntry; latest: boolean }) {
  const { event } = entry;
  const note = passageNote(entry);

  return (
    <li className="relative flex gap-3 px-3 py-2 transition-colors hover:bg-elevated/40">
      {/* La gouttière : un trait continu et un nœud coloré par la ligne franchie.
          Continu d'une tranche à l'autre — c'est ce qui fait lire l'ensemble comme
          une chronologie et non comme des listes empilées. */}
      <span aria-hidden="true" className="relative w-3 shrink-0">
        <span className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-line/40" />
        {latest && (
          <span className="absolute left-1/2 top-1.5 size-2.5 -translate-x-1/2 animate-ping rounded-pill bg-accent/60" />
        )}
        <span
          className={`absolute left-1/2 top-1.5 size-2.5 -translate-x-1/2 rounded-pill ring-2 ring-surface ${
            entry.lineColor === null ? "bg-ink-dim" : ""
          }`}
          style={entry.lineColor === null ? undefined : { backgroundColor: entry.lineColor }}
        />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="shrink-0 text-caption font-bold text-ink tabular">
            {formatSceneTime(event.timestampMs)}
          </span>

          <RolePill
            role={entry.role}
            label={entry.directionName}
            headingDeg={entry.headingDeg}
          />

          {/* Le seul texte de longueur arbitraire de la rangée — l'utilisateur nomme
              ses lignes — donc c'est lui qui cède quand la place manque. */}
          <span className="min-w-0 flex-1 truncate text-small text-ink-muted">
            {entry.lineName}
          </span>

          <span className="flex shrink-0 items-center gap-1.5 text-small">
            <span
              aria-hidden="true"
              className="size-2 shrink-0 rounded-badge"
              style={{ backgroundColor: classColor(event.label) }}
            />
            <span className="text-ink">{classLabel(event.label)}</span>
            <span className="text-ink-dim tabular">#{event.globalId}</span>
          </span>

          {/* La plaque **seulement quand elle est lue**. La plupart des
              franchissements n'en ont pas — le serveur les émet avant la passe OCR de
              la même image — et un « — » par rangée créerait une colonne de tirets qui
              ferait passer l'exception pour la règle. L'autorité reste le registre
              (ADR 0007), qui agrège toute la vie du véhicule. */}
          {event.plateText !== null && (
            <span
              className="shrink-0 rounded-badge bg-elevated px-1.5 text-micro tabular tracking-wide text-ink"
              title={plateTitle(event.plateText, event.plateTextScore, null)}
            >
              {plateCell(event.plateText, null)}
            </span>
          )}

          {/* Le rythme : l'écart avec le franchissement précédent, toutes lignes
              confondues. Absent sur le plus ancien du journal, où ce qui précède a pu
              être oublié — un « +0,0 s » s'y lirait comme une simultanéité. */}
          {entry.gapMs !== null && (
            <span
              className="shrink-0 text-micro text-ink-dim tabular"
              title="Écart avec le franchissement précédent"
            >
              +{formatDuration(entry.gapMs)}
            </span>
          )}
        </div>

        {note !== null && (
          <p className="mt-0.5 flex items-start gap-1.5 text-micro text-ink-dim">
            <CornerDownRight aria-hidden="true" size={11} className="mt-px shrink-0" />
            <span className="min-w-0">{note}</span>
          </p>
        )}
      </div>
    </li>
  );
}

/**
 * Le rôle du sens, en tête de rangée.
 *
 * Entrée et sortie se distinguent par **le poids et l'angle de la flèche**, jamais par
 * une couleur de teinte : la couleur encode déjà deux données sur cette rangée — la
 * ligne au nœud, la classe au véhicule — et une troisième teinte les rendrait toutes
 * trois muettes. Le poids suit la convention de la barre entrées/sorties de la
 * Statistique, où l'entrée est pleine et la sortie atténuée.
 */
const ROLE_STYLE: Readonly<Record<DirectionRole, string>> = {
  entry: "bg-ink/15 text-ink ring-ink/25",
  exit: "bg-ink/5 text-ink-muted ring-line/60",
  // La seule exception à la règle ci-dessus, et elle la confirme : le rouge n'encode
  // pas *quel* sens, il encode qu'il ne fallait pas passer. C'est une gravité, pas
  // une catégorie — la ligne et la classe gardent leurs teintes intactes à côté.
  forbidden: "bg-negative/15 text-negative ring-negative/40",
  transit: "bg-ink/5 text-ink-muted ring-line/60",
  neutral: "bg-elevated text-ink-dim ring-transparent",
};

/**
 * La flèche est **pivotée à l'angle réel du tracé**, pas un pictogramme d'entrée ou de
 * sortie.
 *
 * Deux pictogrammes (`LogIn` / `LogOut`) tenaient cette place, et ils redisaient en
 * image ce que le mot à côté disait déjà. Une flèche à l'angle du trait dit autre
 * chose, que le mot ne dit pas : **par où**. C'est la même flèche, au même angle, que
 * celle du panneau de géométrie et du canvas pour ce sens-là — le regard fait donc le
 * lien entre la rangée et le trait à l'écran, sans avoir à retrouver quelle ligne est
 * « Voie sud ».
 *
 * `ArrowUp` et une rotation CSS, jamais un glyphe unicode (`→ ↘ ↓ …`) : un glyphe ne
 * pivote qu'à 45° près, donc il rendrait la flèche *presque* perpendiculaire au trait,
 * jamais exactement — et « presque » est ce qui fait douter du sens affiché.
 *
 * Sans angle — ligne retirée du tracé, segment dégénéré — **aucune flèche**. Une
 * `ArrowUp` non pivotée affirmerait « vers le haut », un angle que personne n'a
 * mesuré ; `directionName` porte alors le glyphe brut de la convention serveur
 * (« sens ↑ »), qui ne prétend décrire aucune géométrie.
 */
function RolePill({
  role,
  label,
  headingDeg,
}: {
  role: DirectionRole;
  label: string;
  headingDeg: number | null;
}) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-pill px-1.5 py-0.5 text-micro font-bold uppercase tracking-wider ring-1 ${ROLE_STYLE[role]}`}
    >
      {headingDeg !== null && (
        <ArrowUp
          aria-hidden="true"
          size={11}
          className="shrink-0"
          // La flèche hérite de la couleur de la pastille — vive en entrée, atténuée
          // en sortie : elle porte l'angle, le poids reste au rôle. La colorer à la
          // ligne (ce que fait `GeometryPanel`, faute d'autre repère) redirait ici la
          // couleur du nœud, à deux centimètres de là.
          style={{ transform: `rotate(${headingDeg}deg)` }}
        />
      )}
      {label}
    </span>
  );
}

/**
 * Clé stable d'un franchissement.
 *
 * Les quatre champs, et pas seulement l'horodatage : deux véhicules franchissent
 * régulièrement la même image, et un même véhicule peut franchir deux lignes sur la
 * même image. Une clé plus courte ferait réutiliser une rangée pour un autre
 * événement, ce qui garderait à l'écran une plaque appartenant au précédent.
 */
function entryKey(entry: CrossingEntry | undefined): string {
  if (entry === undefined) return "";
  const { event } = entry;
  return `${event.lineId}-${event.globalId}-${event.frameIndex}-${event.direction}`;
}
