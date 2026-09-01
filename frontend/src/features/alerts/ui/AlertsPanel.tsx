/**
 * Le centre de notifications — ce que l'analyse signale, replié derrière une
 * cloche.
 *
 * Il a été trois choses en une journée, et chacune est morte de la même cause : la
 * place qu'elle prenait n'était pas proportionnelle à ce qu'on venait y chercher.
 *
 * - **la pile flottante posée sur la vidéo.** Des cartes sur du bitume ne se lisent
 *   pas, et sur un carrefour chargé elles masquaient l'image qu'elles servaient à
 *   faire regarder ;
 * - **la section en bas de page.** Sous la vidéo, sous la Statistique, sous le
 *   Registre : pendant l'analyse, personne n'y était ;
 * - **la colonne de 18 rem à côté de la scène.** Elle réglait les deux premiers
 *   défauts et en créait un troisième : elle coûtait sa largeur à la vidéo **en
 *   permanence** pour une liste qu'on consulte par à-coups. La vidéo est ce qu'on
 *   regarde ; les alertes sont ce qu'on va chercher.
 *
 * Un tiroir répond aux trois : rien sur la scène, à hauteur d'œil dans la barre,
 * et zéro pixel quand il est fermé. La cloche, elle, ne coûte rien et dit
 * l'essentiel — combien, et est-ce grave.
 *
 * **Trois étages, et le premier n'est pas la liste.** C'est le changement de fond :
 * une liste dit ce qui s'est passé un par un, elle ne dit jamais *ce qu'il faut en
 * penser*. Sur cinquante infractions, la question est « lesquelles, et faites par
 * quels véhicules » — pas « quelle est la trente-septième ».
 *
 * 1. **le résumé**, dérivé de `stats` : exact, sans plafond ;
 * 2. **les filtres**, sur trois axes qui se composent — nature, type de véhicule,
 *    ligne ;
 * 3. **le flux**, borné à `ALERT_LIMIT`, et **la borne est annoncée**.
 *
 * **Les deux sources de chiffres ne se mélangent jamais.** Le résumé vient de
 * `violationCounts`, dérivé de `stats.byLine` et sans plafond ; le flux vient du
 * journal, borné à 200 entrées. Afficher `alerts.length` comme un total ferait
 * plafonner un compteur en silence — invariant 3, le défaut que l'ancienne
 * chronologie a déjà payé une fois. C'est pourquoi le résumé n'est pas calculé
 * ici : il arrive en prop, du même juge que le KPI des Résultats.
 *
 * **Une seule région vivante, et elle ne porte qu'un nombre.** La pile flottante
 * annonçait chaque carte ; sur un carrefour chargé, cela faisait d'un lecteur
 * d'écran un métronome.
 */

import { Filter, X } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import type { CountingLine } from "@/shared/api/contracts";
import { vehicleSnapshotUrl } from "@/shared/api/jobUrls";
import { classLabel } from "@/shared/lib/classes";
import type { ViolationCounts } from "@/shared/lib/violationTally";
import { PanelHeading } from "@/shared/ui/PanelHeading";

import { ALERT_LIMIT, alertScore, type Alert, type VehicleScores } from "../model/alerts";
import { NO_FILTER, alertFacets, filterAlerts, isFiltering } from "../model/alertFilters";
import { AlertCard } from "./AlertCard";
import { ALERT_LOOK } from "./alertLook";

/** Les entrées visibles avant d'avoir à demander la suite. */
const INITIAL_SHOWN = 8;

interface AlertsPanelProps {
  alerts: readonly Alert[];
  lines: readonly CountingLine[];
  /** Une règle est-elle déclarée, ou une plaque recherchée ? Sinon rien à dire. */
  armed: boolean;
  /**
   * Les totaux d'infraction du tracé courant, **dérivés de `stats`**.
   *
   * En prop et non calculés ici, pour deux raisons qui vont dans le même sens :
   * une feature n'importe jamais une autre feature, et surtout ce doivent être
   * **exactement** les chiffres du KPI « Franchissements interdits » des
   * Résultats. Deux calculs du même total finiraient par diverger, sur deux
   * surfaces que l'utilisateur lit à quelques secondes d'intervalle.
   *
   * `null` quand il n'y a pas encore de statistiques : le résumé se tait, et seul
   * le flux s'affiche.
   */
  violations: ViolationCounts | null;
  /**
   * L'analyse tourne-t-elle ? Décide du repère « en direct » et de la région
   * vivante — après coup, le panneau se relit et n'a plus rien à annoncer.
   */
  live?: boolean;
  onSeek?: ((timestampMs: number) => void) | undefined;
  /**
   * Le job dont on peut demander les captures — **en cours ou terminé**.
   *
   * `null` avant toute analyse. Depuis ADR 0046 les JPEG sont écrits au fil de
   * l'eau, donc une vignette demandée pendant l'analyse arrive : la restreindre au
   * job terminé priverait de preuve les alertes au moment précis où elles tombent.
   */
  jobId?: string | null | undefined;
  /**
   * L'instant de la capture de chaque véhicule, pour **versionner** son adresse.
   *
   * Le serveur sert ces images en `immutable`, et une capture est remplacée dès
   * qu'une meilleure vue arrive — jusqu'à une dizaine de fois par piste sur une
   * capture par ressemblance (ADR 0051). Sans version, la vignette resterait figée
   * pour un an sur la vue la plus lointaine, dans le panneau qui sert justement à
   * vérifier.
   *
   * **En prop et non dans l'`Alert`**, et c'est le piège à connaître : `mergeAlerts`
   * garde la **première** occurrence d'une clé, donc un instant porté par l'alerte
   * serait gelé à sa première publication — exactement ce qu'on cherche à éviter.
   */
  capturedMs?: ReadonlyMap<number, number | null> | undefined;
  /**
   * Les scores **vivants** de chaque véhicule — confiance de lecture, ressemblance.
   *
   * En prop et pour la raison exacte de `capturedMs`, qui est le piège de ce
   * panneau : `mergeAlerts` garde la première occurrence d'une clé, donc un score
   * porté par l'alerte serait gelé à sa première publication alors que les deux
   * s'améliorent en cours d'analyse. Absent, la carte retombe sur ce que l'alerte a
   * figé — le seul recours pour une plaque recherchée dont le véhicule n'a encore
   * franchi aucune ligne, le registre de l'aperçu étant restreint aux franchisseurs.
   */
  scores?: ReadonlyMap<number, VehicleScores> | undefined;
  /** Ouvre la capture en grand. Absent = la vignette n'est pas cliquable. */
  onOpenSnapshot?: ((globalId: number) => void) | undefined;
}

export function AlertsPanel({
  alerts,
  lines,
  armed,
  violations,
  live = false,
  onSeek,
  jobId = null,
  capturedMs,
  scores,
  onOpenSnapshot,
}: AlertsPanelProps) {
  const [filter, setFilter] = useState(NO_FILTER);
  const [expanded, setExpanded] = useState(false);

  const facets = useMemo(() => alertFacets(alerts), [alerts]);
  const filtered = useMemo(() => filterAlerts(alerts, filter), [alerts, filter]);

  // Masqué tant qu'aucune règle n'est posée et qu'aucune plaque n'est recherchée :
  // un panneau vide intitulé « Alertes » se lit comme « rien à signaler », alors
  // que la vérité est « on n'a rien demandé de signaler ».
  if (!armed) return null;

  const shown = expanded ? filtered : filtered.slice(0, INITIAL_SHOWN);
  const remaining = filtered.length - shown.length;
  const filtering = isFiltering(filter);

  return (
    <section aria-labelledby="alerts-title" className="flex min-w-0 flex-col gap-3">
      <PanelHeading
        id="alerts-title"
        title="Alertes"
        live={live}
        trailing={
          /* La seule région vivante du panneau, et elle ne porte qu'un nombre. */
          <output aria-live={live ? "polite" : "off"} className="text-micro text-ink-dim tabular">
            {alerts.length === 0
              ? "aucune"
              : `${alerts.length} alerte${alerts.length > 1 ? "s" : ""}`}
          </output>
        }
      />

      {/* ── 1. Le résumé — exact, et il ne vient pas du journal ─────────────── */}
      {violations !== null && violations.declared && (
        <ViolationSummary counts={violations} />
      )}

      {alerts.length === 0 ? (
        <p className="rounded-card bg-base p-3 text-small text-ink-dim">
          Rien à signaler pour l'instant. Les règles posées sur le tracé et les plaques
          recherchées sont surveillées pendant toute l'analyse.
        </p>
      ) : (
        <>
          {/* ── 2. Les filtres ───────────────────────────────────────────────
              Trois axes qui se composent, parce que la question réelle est
              « les camions qui remontent la voie de bus » et non « les
              infractions ». Ce sont des outils de **lecture** : aucun ne
              déplace la vidéo, c'est le clic sur une carte qui le fait. */}
          <div className="rounded-card bg-base p-2">
            <div className="mb-1.5 flex items-center gap-1.5">
              <Filter aria-hidden="true" className="size-3 shrink-0 text-ink-dim" />
              <span className="label-micro">Filtrer</span>
              {filtering && (
                <button
                  type="button"
                  onClick={() => setFilter(NO_FILTER)}
                  className="ms-auto inline-flex items-center gap-1 rounded-pill px-1.5 py-0.5 text-micro text-ink-muted transition-colors hover:bg-elevated hover:text-ink"
                >
                  <X aria-hidden="true" className="size-3" />
                  Tout effacer
                </button>
              )}
            </div>

            <FacetRow label="Nature" count={facets.kinds.length}>
              {facets.kinds.map((facet) => (
                <Chip
                  key={facet.value}
                  label={ALERT_LOOK[facet.value].title}
                  count={facet.count}
                  active={filter.kind === facet.value}
                  onClick={() =>
                    setFilter((current) => ({
                      ...current,
                      kind: current.kind === facet.value ? null : facet.value,
                    }))
                  }
                />
              ))}
            </FacetRow>

            {/* **L'axe demandé** : « voir les types d'infraction selon les
                véhicules ». La classe est celle **votée** sur la vie du véhicule
                (invariant 4), donc la même que celle des cartes de Résultats. */}
            <FacetRow label="Type de véhicule" count={facets.labels.length}>
              {facets.labels.map((facet) => (
                <Chip
                  key={facet.value}
                  label={classLabel(facet.value)}
                  count={facet.count}
                  active={filter.label === facet.value}
                  onClick={() =>
                    setFilter((current) => ({
                      ...current,
                      label: current.label === facet.value ? null : facet.value,
                    }))
                  }
                />
              ))}
            </FacetRow>

            {/* Les lignes seulement s'il y en a plus d'une à distinguer — un
                filtre à une seule option est un bouton qui ne change rien. Même
                règle que le filtre par ligne du registre. */}
            {facets.lines.length > 1 && (
              <FacetRow label="Ligne" count={facets.lines.length}>
                {facets.lines.map((facet) => (
                  <Chip
                    key={facet.value.id}
                    label={facet.value.name}
                    count={facet.count}
                    color={facet.value.color}
                    active={filter.lineId === facet.value.id}
                    onClick={() =>
                      setFilter((current) => ({
                        ...current,
                        lineId: current.lineId === facet.value.id ? null : facet.value.id,
                      }))
                    }
                  />
                ))}
              </FacetRow>
            )}
          </div>

          {/* ── 3. Le flux ───────────────────────────────────────────────────
              Une colonne, et non une grille en `auto-fill` : le tiroir a une
              largeur fixe et bornée, il n'a plus à deviner s'il est en colonne
              étroite ou en pleine largeur. */}
          {filtered.length === 0 ? (
            <p className="rounded-card bg-base p-3 text-small text-ink-dim">
              Aucune alerte ne correspond à ces filtres. Les{" "}
              <strong className="text-ink-muted">{alerts.length}</strong> du journal sont
              toujours là.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {shown.map((alert) => (
                <li key={alert.key} className="flex items-start gap-2">
                  {/* La vignette **à côté** de la carte, pas dedans : la carte est
                      déjà un bouton qui déplace la lecture, et un bouton dans un
                      bouton est du HTML invalide. Les deux gestes sont d'ailleurs
                      distincts — l'un montre le fait, l'autre le prouve. */}
                  {jobId !== null && (
                    <AlertSnapshot
                      jobId={jobId}
                      globalId={alert.globalId}
                      capturedMs={capturedMs?.get(alert.globalId) ?? null}
                      live={live}
                      onOpen={() => onOpenSnapshot?.(alert.globalId)}
                    />
                  )}
                  <span className="min-w-0 flex-1">
                    <AlertCard
                      alert={alert}
                      score={alertScore(alert, scores?.get(alert.globalId))}
                      lines={lines}
                      onSeek={onSeek}
                    />
                  </span>
                </li>
              ))}
            </ul>
          )}

          {remaining > 0 && (
            <button
              type="button"
              onClick={() => setExpanded(true)}
              className="self-start rounded-input px-2 py-1 text-small text-ink-muted transition-colors hover:bg-elevated hover:text-ink"
            >
              Afficher les {remaining} restantes
            </button>
          )}

          {/* La borne, dite dès qu'elle est atteinte — jamais un total silencieux.
              Le résumé ci-dessus et les KPI des Résultats, eux, viennent de `stats`
              et ne plafonnent pas. */}
          {alerts.length >= ALERT_LIMIT && (
            <p className="text-micro text-ink-dim">
              Les {ALERT_LIMIT} alertes les plus récentes sont conservées. Le résumé et les
              Résultats, eux, portent sur toute l'analyse.
            </p>
          )}
        </>
      )}
    </section>
  );
}

/**
 * Le résumé chiffré — « combien, et de quelle nature ».
 *
 * **Il ne compte rien.** Tout vient de `violationCounts`, le même juge que le KPI
 * des Résultats : deux calculs du même total finiraient par en donner deux, sur
 * deux surfaces lues à quelques secondes d'intervalle.
 *
 * Les natures **à zéro ne sont pas rendues**. « 0 voie réservée » sur un tracé qui
 * n'en déclare aucune se lit « surveillé, rien à signaler », alors que la vérité
 * est « il n'y avait rien à surveiller de ce côté ». C'est le même raisonnement,
 * un cran plus bas, que le `declared` qui décide de tout ce bloc.
 */
function ViolationSummary({ counts }: { counts: ViolationCounts }) {
  const kinds = (["wrong-way", "closed-line", "reserved-lane"] as const).filter(
    (kind) => counts.byKind[kind] > 0,
  );

  return (
    <div
      className={[
        "rounded-card p-3 ring-1",
        counts.total > 0 ? "bg-negative/10 ring-negative/40" : "bg-base ring-transparent",
      ].join(" ")}
    >
      <div className="flex items-baseline gap-2">
        <span
          className={[
            "text-[1.75rem] font-bold leading-none tabular",
            counts.total > 0 ? "text-negative" : "text-ink",
          ].join(" ")}
        >
          {counts.total}
        </span>
        <span className="label-micro">
          franchissement{counts.total > 1 ? "s" : ""} interdit{counts.total > 1 ? "s" : ""}
        </span>
      </div>

      {/* Le détail par nature : « à contresens » et « ligne infranchissable » sont
          deux faits différents, et ils appellent deux gestes différents. Le KPI des
          Résultats les additionne ; c'est ici qu'on les sépare. */}
      {kinds.length > 0 && (
        <dl className="mt-2 space-y-1">
          {kinds.map((kind) => {
            const look = ALERT_LOOK[kind];
            return (
              <div key={kind} className="flex items-baseline justify-between gap-2">
                <dt className="flex min-w-0 items-center gap-1.5 text-micro text-ink-muted">
                  <look.Icon aria-hidden="true" className="size-3 shrink-0" />
                  <span className="truncate">{look.title}</span>
                </dt>
                <dd className="shrink-0 text-micro font-bold text-ink tabular">
                  {counts.byKind[kind]}
                </dd>
              </div>
            );
          })}
        </dl>
      )}

      {/* **Le rappel d'unité, et il n'est pas décoratif.** Ce sont des passages, là
          où le chiffre de tête des Résultats compte des véhicules depuis ADR 0045 :
          un aller-retour interdit vaut 2 ici et 1 là-bas. Sans cette phrase, les
          deux se lisent comme un désaccord. */}
      <p className="mt-2 text-micro text-ink-dim">
        Des passages, pas des véhicules : un aller-retour interdit en compte deux. Le
        passage reste compté — une infraction est un passage qualifié.
      </p>
    </div>
  );
}

/**
 * Une rangée de facettes, avec son intitulé. Rien si l'axe n'a aucune option.
 *
 * `count` est passé plutôt que déduit des enfants : inspecter `children` marche
 * tant que l'appelant rend un `map`, et casse silencieusement le jour où il rend
 * un fragment. Un axe vide rendrait alors un intitulé sans puce.
 */
function FacetRow({
  label,
  count,
  children,
}: {
  label: string;
  count: number;
  children: ReactNode;
}) {
  if (count === 0) return null;

  return (
    <div className="mt-1 flex flex-wrap items-baseline gap-1">
      <span className="me-1 shrink-0 text-micro text-ink-dim">{label}</span>
      {children}
    </div>
  );
}

function Chip({
  label,
  count,
  active,
  color,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  /** La pastille de la ligne, pour relier la puce au trait sur la vidéo. */
  color?: string | undefined;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      // `aria-pressed` et non `aria-selected` : ce sont des bascules indépendantes
      // qui se composent, pas les onglets d'un même groupe.
      aria-pressed={active}
      className={[
        "inline-flex items-center gap-1 rounded-pill px-2 py-0.5 text-micro transition-colors",
        active ? "bg-ink font-bold text-base" : "bg-surface-2 text-ink-muted hover:bg-elevated",
      ].join(" ")}
    >
      {color !== undefined && (
        <span
          aria-hidden="true"
          className="size-1.5 shrink-0 rounded-badge"
          style={{ backgroundColor: color }}
        />
      )}
      <span className="max-w-32 truncate">{label}</span>
      <span className="tabular">{count}</span>
    </button>
  );
}

/**
 * La preuve, à côté de l'alerte : la photo du véhicule signalé.
 *
 * C'est elle qui répond à la question qu'une alerte de plaque pose forcément —
 * « est-ce bien celle-là ? ». L'OCR perd régulièrement un caractère (ADR 0029), donc
 * une correspondance annoncée « probable » ne se tranche qu'en regardant.
 *
 * **Silencieuse quand il n'y a rien.** La plupart des véhicules n'ont pas de capture,
 * et la moitié des alertes sont des infractions, où aucune plaque n'a forcément été
 * lue. Un cadre vide à côté de chaque carte serait du bruit ; `onError` fait
 * simplement disparaître la vignette.
 *
 * **Un seul réessai, et seulement pendant l'analyse** (ADR 0046) : le JPEG est écrit
 * au fil de l'eau, quelques centaines de millisecondes pouvant séparer la capture de
 * son arrivée sur disque. Après l'analyse, une image absente est absente pour de bon
 * — c'est le cas normal après le TTL de la vidéo — et réessayer ne ferait que
 * doubler des requêtes vouées à échouer.
 */
function AlertSnapshot({
  jobId,
  globalId,
  capturedMs,
  live,
  onOpen,
}: {
  jobId: string;
  globalId: number;
  capturedMs: number | null;
  live: boolean;
  onOpen: () => void;
}) {
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);

  if (failed) return null;

  return (
    <button
      type="button"
      onClick={onOpen}
      title={`Voir la capture du véhicule #${globalId}`}
      className="shrink-0 overflow-hidden rounded-input ring-1 ring-line/40 transition-transform hover:scale-105"
    >
      <img
        // `attempt` fait partie de la clé de cache du navigateur : sans lui, un
        // second chargement de la même adresse ressusciterait la réponse en échec.
        src={vehicleSnapshotUrl(jobId, globalId, capturedMs, attempt)}
        alt={`Capture du véhicule #${globalId}`}
        width={40}
        height={40}
        loading="lazy"
        decoding="async"
        className="size-10 bg-base object-cover"
        onError={() => {
          if (live && attempt === 0) setAttempt(1);
          else setFailed(true);
        }}
      />
    </button>
  );
}
