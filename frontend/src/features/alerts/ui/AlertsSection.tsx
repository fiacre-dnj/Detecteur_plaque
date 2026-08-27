/**
 * La section « Alertes » du bas de page — ce que l'analyse a signalé, en entier.
 *
 * Elle prend la place libérée par la chronologie des franchissements, et ce n'est
 * pas un hasard : celle-ci posait un fait par rangée sans dire lequel méritait
 * qu'on aille voir. Une alerte, elle, ne dit que cela.
 *
 * Trois règles qui viennent de l'ancienne section et qu'il ne faut pas défaire :
 *
 * - **la borne est annoncée** dès qu'elle est atteinte. Le journal plafonne à
 *   `ALERT_LIMIT`, et un compte plafonné affiché comme un total est le défaut qu'on
 *   a déjà payé une fois. Les vrais totaux, eux, sont dans les KPI — dérivés de
 *   `stats`, donc exacts ;
 * - **les filtres sont un outil de lecture**, pas de navigation. Ils n'ont aucun
 *   effet sur la vidéo ; c'est le clic sur une carte qui déplace la lecture, et lui
 *   seul ;
 * - **aucune région `aria-live`.** Le direct de la pile flottante en porte une,
 *   parce qu'elle annonce ce qui arrive ; cette section-ci se relit, et la faire
 *   parler à chaque ajout ferait d'un lecteur d'écran un métronome.
 */

import { useMemo, useState } from "react";

import type { CountingLine } from "@/shared/api/contracts";
import { vehicleSnapshotUrl } from "@/shared/api/jobUrls";

import { ALERT_LIMIT, isViolation, type Alert } from "../model/alerts";
import { AlertCard } from "./AlertCard";

/** Les entrées visibles avant d'avoir à demander la suite. */
const INITIAL_SHOWN = 6;

type Facet = "all" | "violations" | "plates";

interface AlertsSectionProps {
  alerts: readonly Alert[];
  lines: readonly CountingLine[];
  /** Une règle est-elle déclarée, ou une plaque recherchée ? Sinon rien à dire. */
  armed: boolean;
  onSeek?: ((timestampMs: number) => void) | undefined;
  /**
   * Le job **terminé**, pour construire les adresses des captures.
   *
   * `null` pendant l'analyse : les fichiers sont écrits à la fin, et une vignette
   * demandée trop tôt afficherait une image cassée sur chaque alerte.
   */
  jobId?: string | null | undefined;
  /** Ouvre la capture en grand. Absent = la vignette n'est pas cliquable. */
  onOpenSnapshot?: ((globalId: number) => void) | undefined;
}

export function AlertsSection({
  alerts,
  lines,
  armed,
  onSeek,
  jobId = null,
  onOpenSnapshot,
}: AlertsSectionProps) {
  const [facet, setFacet] = useState<Facet>("all");
  const [expanded, setExpanded] = useState(false);

  const counts = useMemo(() => {
    const violations = alerts.filter(isViolation).length;
    return { all: alerts.length, violations, plates: alerts.length - violations };
  }, [alerts]);

  const filtered = useMemo(() => {
    if (facet === "all") return alerts;
    if (facet === "violations") return alerts.filter(isViolation);
    return alerts.filter((alert) => !isViolation(alert));
  }, [alerts, facet]);

  // Masquée tant qu'aucune règle n'est posée et qu'aucune plaque n'est recherchée :
  // une section vide intitulée « Alertes » se lit comme « rien à signaler », alors
  // que la vérité est « on n'a rien demandé de signaler ».
  if (!armed) return null;

  const shown = expanded ? filtered : filtered.slice(0, INITIAL_SHOWN);
  const remaining = filtered.length - shown.length;

  return (
    <section aria-labelledby="alerts-title" className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="alerts-title" className="label-micro">
          Alertes
        </h2>
        <div className="flex flex-wrap gap-1">
          <FacetChip
            label="Tout"
            count={counts.all}
            active={facet === "all"}
            onClick={() => setFacet("all")}
          />
          <FacetChip
            label="Infractions"
            count={counts.violations}
            active={facet === "violations"}
            onClick={() => setFacet("violations")}
          />
          <FacetChip
            label="Plaques"
            count={counts.plates}
            active={facet === "plates"}
            onClick={() => setFacet("plates")}
          />
        </div>
      </div>

      {alerts.length === 0 ? (
        <p className="rounded-card bg-surface p-4 text-caption text-ink-dim shadow-card">
          Aucune alerte pour l'instant. Les règles posées sur le tracé et les plaques
          recherchées sont surveillées pendant toute l'analyse.
        </p>
      ) : (
        <>
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
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
                    onOpen={() => onOpenSnapshot?.(alert.globalId)}
                  />
                )}
                <span className="min-w-0 flex-1">
                  <AlertCard alert={alert} lines={lines} onSeek={onSeek} />
                </span>
              </li>
            ))}
          </ul>

          {remaining > 0 && (
            <button
              type="button"
              onClick={() => setExpanded(true)}
              className="rounded-input px-2 py-1 text-small text-ink-muted transition-colors hover:bg-elevated hover:text-ink"
            >
              Afficher les {remaining} alertes restantes
            </button>
          )}

          {/* La borne, dite dès qu'elle est atteinte — jamais un total silencieux.
              Les compteurs des Résultats et de la Statistique, eux, viennent de
              `stats` et ne plafonnent pas. */}
          {alerts.length >= ALERT_LIMIT && (
            <p className="text-micro text-ink-dim">
              Les {ALERT_LIMIT} alertes les plus récentes sont conservées. Les totaux
              affichés dans les Résultats, eux, portent sur toute l'analyse.
            </p>
          )}
        </>
      )}
    </section>
  );
}

function FacetChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={count === 0}
      aria-pressed={active}
      className={[
        "rounded-pill px-2 py-0.5 text-micro transition-colors",
        active ? "bg-ink text-base font-bold" : "bg-surface-2 text-ink-muted hover:bg-elevated",
        "disabled:cursor-not-allowed disabled:opacity-40",
      ].join(" ")}
    >
      {label}
      <span className="ms-1 tabular">{count}</span>
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
 */
function AlertSnapshot({
  jobId,
  globalId,
  onOpen,
}: {
  jobId: string;
  globalId: number;
  onOpen: () => void;
}) {
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
        src={vehicleSnapshotUrl(jobId, globalId)}
        alt={`Capture du véhicule #${globalId}`}
        width={40}
        height={40}
        loading="lazy"
        decoding="async"
        className="size-10 bg-base object-cover"
        onError={() => setFailed(true)}
      />
    </button>
  );
}
