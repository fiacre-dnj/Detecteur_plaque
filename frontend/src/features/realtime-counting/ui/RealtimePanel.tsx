/**
 * Le panneau du comptage en direct : démarrer, arrêter, et **rendre la cadence lisible**.
 *
 * La colonne « abandonnées » est ici le choix d'interface qui compte. On pourrait la
 * cacher : c'est un chiffre technique, et il est souvent élevé. Mais c'est
 * précisément parce qu'il est élevé qu'il doit être visible — un utilisateur qui voit
 * « 12 envoyées / 340 abandonnées » comprend que son serveur est le facteur limitant,
 * là où un aperçu simplement saccadé se lit comme un logiciel de mauvaise qualité.
 * L'infobulle dit que c'est **normal**, ce qui est l'autre moitié du travail.
 */

import { Radio, Square } from "lucide-react";

import type { AnalysisStats } from "@/shared/api/contracts";
import { Button } from "@/shared/ui/Button";

import type { PacingStats, RealtimeStatus } from "../model";

interface RealtimePanelProps {
  status: RealtimeStatus;
  message: string | null;
  retryable: boolean;
  pacing: PacingStats;
  stats: AnalysisStats | null;
  /** Modèle et device **réellement** utilisés, tels que `ready` les a annoncés. */
  modelId: string | null;
  device: string | null;
  /** Facteur de réduction appliqué. 1 ⇒ la source est déjà sous la largeur cible. */
  factor: number;
  /** Dimensions réellement envoyées, à comparer avec celles de la scène. */
  sendWidth: number;
  sendHeight: number;
  /** Faux quand la source n'est pas une caméra, ou que le serveur est injoignable. */
  canStart: boolean;
  /** Explique le refus quand `canStart` est faux — un bouton grisé muet est un défaut. */
  blockedReason: string | null;
  onStart: () => void;
  onStop: () => void;
}

export function RealtimePanel(props: RealtimePanelProps) {
  const { status, pacing, stats } = props;
  const active = status === "connecting" || status === "counting";

  return (
    <section
      aria-labelledby="realtime-title"
      className="rounded-section bg-surface p-4 shadow-card"
    >
      <div className="flex items-center justify-between">
        <h3 id="realtime-title" className="label-micro">
          Comptage en direct
        </h3>
        {status === "counting" && (
          // L'accent vert **fonctionnel** : il encode un état actif, il ne décore pas
          // (ADR 0004). Le point pulse pour distinguer « en train de compter » d'un
          // simple libellé, ce qu'un texte statique ne dit pas.
          <span className="flex items-center gap-1.5 text-micro text-accent">
            <span
              aria-hidden="true"
              className="size-1.5 animate-pulse rounded-full bg-accent"
            />
            En direct
          </span>
        )}
      </div>

      {!active ? (
        <>
          <Button
            variant="primary"
            className="mt-3 w-full"
            disabled={!props.canStart}
            onClick={props.onStart}
            title={props.blockedReason ?? "Compter en direct sur le flux de la caméra"}
          >
            <Radio aria-hidden="true" className="size-4" />
            {status === "stopped" || status === "error"
              ? "Relancer le direct"
              : "Démarrer le direct"}
          </Button>

          {props.blockedReason !== null && (
            <p className="mt-2 text-caption text-ink-dim">{props.blockedReason}</p>
          )}
        </>
      ) : (
        <Button variant="ghost" className="mt-3 w-full" onClick={props.onStop}>
          <Square aria-hidden="true" className="size-4" />
          Arrêter le direct
        </Button>
      )}

      {status === "connecting" && (
        <p className="mt-2 text-caption text-ink-dim">Connexion au serveur…</p>
      )}

      {props.message !== null && (
        <p
          // `alert` uniquement pour une vraie erreur : un lecteur d'écran ne doit pas
          // interrompre l'utilisateur pour lui annoncer une fin de session normale.
          role={status === "error" ? "alert" : "status"}
          className={`mt-2 text-caption ${status === "error" ? "text-negative" : "text-ink-dim"}`}
        >
          {props.message}
          {status === "error" && !props.retryable && (
            // Le complément qui évite la boucle d'échecs : après un refus de
            // configuration, réessayer donnera exactement le même résultat.
            <span className="block text-ink-dim">
              Corrigez les réglages ou la géométrie avant de relancer.
            </span>
          )}
        </p>
      )}

      {active && (
        <dl className="mt-4 space-y-2 border-t border-line pt-3 text-caption">
          <Row
            term="Envoi"
            value={`${props.sendWidth}×${props.sendHeight} px`}
            // Le facteur affiché plutôt que déduit : c'est le nombre qui explique
            // pourquoi la géométrie envoyée diffère de celle qui est dessinée.
            hint={
              props.factor === 1
                ? "Résolution source, sans réduction"
                : `Réduit à ${Math.round(props.factor * 100)} % de la source`
            }
          />
          <Row
            term="Latence"
            value={pacing.latencyMs === null ? "—" : `${Math.round(pacing.latencyMs)} ms`}
            hint="Aller-retour de la dernière image analysée"
          />
          <Row
            term="Images"
            value={`${pacing.sent} envoyées · ${pacing.dropped} abandonnées`}
            hint={
              "Une seule image est en vol à la fois ; celles produites pendant l'attente " +
              "sont abandonnées. Un nombre élevé est normal et garde l'aperçu au présent."
            }
          />
          {props.modelId !== null && (
            <Row
              term="Modèle"
              value={props.modelId}
              hint={props.device === null ? undefined : `Calcul sur ${props.device}`}
            />
          )}
        </dl>
      )}

      {stats !== null && (
        <dl className="mt-3 space-y-2 border-t border-line pt-3 text-caption">
          <Row
            term="Véhicules détectés"
            value={String(stats.trackedVehicles)}
            hint="Un objet suivi = un véhicule, ligne franchie ou non"
          />
          <Row
            term="Franchissements"
            value={String(stats.crossings)}
            hint="Passages observés, tous sens — un aller-retour compte 2"
          />
        </dl>
      )}
    </section>
  );
}

/** Une ligne de mesure. Les chiffres sont en chasse tabulaire : ils ne dansent pas. */
function Row({
  term,
  value,
  hint,
}: {
  term: string;
  value: string;
  hint?: string | undefined;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <dt className="text-ink-muted">{term}</dt>
        <dd className="tabular text-ink" title={hint}>
          {value}
        </dd>
      </div>
      {hint !== undefined && <p className="mt-0.5 text-micro text-ink-dim">{hint}</p>}
    </div>
  );
}
