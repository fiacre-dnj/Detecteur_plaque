/**
 * La colonne « Alertes » — ce que l'analyse signale, à côté de la scène.
 *
 * Elle remplace deux surfaces d'un coup, et c'est le même défaut qui les
 * condamnait toutes les deux :
 *
 * - **la pile flottante posée sur la vidéo** (`AlertToasts`, supprimée). Des cartes
 *   posées sur du bitume ne se lisent pas — et sur un carrefour chargé elles
 *   masquaient précisément l'image qu'elles servaient à faire regarder. Une alerte
 *   doit être visible *sans* couvrir la preuve ;
 * - **la section en bas de page.** Elle était sous la vidéo, sous la Statistique et
 *   sous le Registre : pendant l'analyse, personne n'y était.
 *
 * La colonne règle les deux : elle est à hauteur d'œil, à côté de la scène, et ne
 * recouvre rien. Cinq points qui ne se devinent pas :
 *
 * - **une seule source, un seul rendu.** Le journal vivant pendant l'analyse, le
 *   résultat relu après — c'est l'appelant qui choisit (`alerts`), et ce composant
 *   ne connaît pas la différence. Deux surfaces d'alerte, c'était deux jeux de
 *   règles d'affichage à garder d'accord ;
 * - **la grille est en `auto-fill`, pas en points de rupture.** Le panneau vit dans
 *   une colonne étroite sur grand écran et sur toute la largeur en dessous, où il
 *   passe sous la scène ; `minmax` lui fait rendre une carte par rangée dans le
 *   premier cas et quatre dans le second, sans qu'aucune classe `lg:` ait à deviner
 *   dans lequel il se trouve ;
 * - **la borne du journal est annoncée** dès qu'elle est atteinte. Un compte
 *   plafonné affiché comme un total est un défaut que ce dépôt a déjà payé
 *   (invariant 3) ; les vrais totaux sont les KPI des Résultats, dérivés de `stats` ;
 * - **les filtres sont un outil de lecture**, pas de navigation. Ils ne touchent pas
 *   la vidéo : c'est le clic sur une carte qui déplace la lecture, et lui seul ;
 * - **une seule région vivante, et elle ne porte qu'un nombre.** L'ancienne pile
 *   flottante annonçait chaque carte ; sur un carrefour chargé, cela faisait d'un
 *   lecteur d'écran un métronome. Le compteur, lui, dit « il se passe quelque
 *   chose » en une phrase courte, et le détail reste lisible à la demande.
 */

import { useMemo, useState } from "react";

import type { CountingLine } from "@/shared/api/contracts";
import { vehicleSnapshotUrl } from "@/shared/api/jobUrls";
import { PanelHeading } from "@/shared/ui/PanelHeading";

import { ALERT_LIMIT, isViolation, type Alert } from "../model/alerts";
import { AlertCard } from "./AlertCard";

/** Les entrées visibles avant d'avoir à demander la suite. */
const INITIAL_SHOWN = 8;

type Facet = "all" | "violations" | "plates";

interface AlertsPanelProps {
  alerts: readonly Alert[];
  lines: readonly CountingLine[];
  /** Une règle est-elle déclarée, ou une plaque recherchée ? Sinon rien à dire. */
  armed: boolean;
  /**
   * L'analyse tourne-t-elle ? Décide du repère « en direct » et de la région
   * vivante — après coup, le panneau se relit et n'a plus rien à annoncer.
   */
  live?: boolean;
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

export function AlertsPanel({
  alerts,
  lines,
  armed,
  live = false,
  onSeek,
  jobId = null,
  onOpenSnapshot,
}: AlertsPanelProps) {
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

  // Masqué tant qu'aucune règle n'est posée et qu'aucune plaque n'est recherchée :
  // un panneau vide intitulé « Alertes » se lit comme « rien à signaler », alors
  // que la vérité est « on n'a rien demandé de signaler ».
  if (!armed) return null;

  const shown = expanded ? filtered : filtered.slice(0, INITIAL_SHOWN);
  const remaining = filtered.length - shown.length;

  return (
    <section aria-labelledby="alerts-title" className="flex min-w-0 flex-col gap-2">
      {/* L'entête reste visible quand la colonne défile sous elle : les filtres
          sont ce qu'on reprend en main après avoir lu quinze cartes. Son fond est
          opaque pour la même raison que celui de la barre du studio. */}
      <div className="sticky -top-px z-10 flex flex-col gap-2 bg-base/95 pb-2 pt-px backdrop-blur">
        {/* La **même** entête que la colonne des résultats, au même composant : les
            deux colonnes sont côte à côte à la même hauteur, et deux titres qui ne
            s'alignent pas se lisent comme deux niveaux d'information. */}
        <PanelHeading
          id="alerts-title"
          title="Alertes"
          live={live}
          trailing={
            /* La seule région vivante du panneau, et elle ne porte qu'un nombre. */
            <output
              aria-live={live ? "polite" : "off"}
              className="text-micro text-ink-dim tabular"
            >
              {counts.all === 0 ? "aucune" : `${counts.all} alerte${counts.all > 1 ? "s" : ""}`}
            </output>
          }
        />

        {alerts.length > 0 && (
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
        )}
      </div>

      {alerts.length === 0 ? (
        <p className="rounded-card bg-surface p-3 text-small text-ink-dim shadow-card">
          Rien à signaler pour l'instant. Les règles posées sur le tracé et les plaques
          recherchées sont surveillées pendant toute l'analyse.
        </p>
      ) : (
        <>
          {/* `auto-fill` et non des points de rupture : le panneau ne sait pas s'il
              est en colonne ou en pleine largeur, et n'a pas à le savoir. */}
          <ul className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(15rem,1fr))]">
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
              className="self-start rounded-input px-2 py-1 text-small text-ink-muted transition-colors hover:bg-elevated hover:text-ink"
            >
              Afficher les {remaining} restantes
            </button>
          )}

          {/* La borne, dite dès qu'elle est atteinte — jamais un total silencieux.
              Les compteurs des Résultats et de la Statistique, eux, viennent de
              `stats` et ne plafonnent pas. */}
          {alerts.length >= ALERT_LIMIT && (
            <p className="text-micro text-ink-dim">
              Les {ALERT_LIMIT} alertes les plus récentes sont conservées. Les totaux des
              Résultats, eux, portent sur toute l'analyse.
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
