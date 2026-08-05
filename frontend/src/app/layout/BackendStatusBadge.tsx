/**
 * État du backend, visible en permanence.
 *
 * Quand le serveur est absent, l'interface **le dit** et désactive l'analyse :
 * ni page blanche, ni erreur console, ni bouton qui ne fait rien. C'est un
 * critère d'acceptation du projet, pas une amélioration.
 */

import { CircleAlert, RefreshCw } from "lucide-react";

import { useHealth } from "./useHealth";

export function BackendStatusBadge() {
  const { data: health, isLoading, refetch, isFetching } = useHealth();

  if (isLoading) {
    return (
      <span className="label-micro rounded-pill bg-surface-2 px-3 py-1.5">
        Connexion…
      </span>
    );
  }

  if (!health) {
    return (
      <div className="flex items-center gap-2">
        <span className="label-micro flex items-center gap-1.5 rounded-pill bg-warning/12 px-3 py-1.5 text-warning">
          <CircleAlert aria-hidden="true" className="size-3.5" />
          Serveur injoignable
        </span>
        <button
          type="button"
          onClick={() => void refetch()}
          disabled={isFetching}
          className="label-micro flex items-center gap-1.5 rounded-pill px-2 py-1.5 text-ink-dim transition-colors hover:text-ink disabled:opacity-50"
        >
          <RefreshCw aria-hidden="true" className="size-3.5" />
          Réessayer
        </button>
      </div>
    );
  }

  // Le détail matériel est dans l'infobulle plutôt qu'à l'écran : il compte
  // quand on interprète un chiffre de latence, pas en permanence.
  const detail = [
    `Ultralytics ${health.ultralyticsVersion}`,
    health.loadedModels.length > 0
      ? `Résidents : ${health.loadedModels.join(", ")}`
      : "Aucun modèle en mémoire",
    health.plateAvailable ? "Lecture de plaques disponible" : "Lecture de plaques indisponible",
  ].join(" · ");

  return (
    <span
      title={detail}
      className="label-micro flex items-center gap-2 rounded-pill bg-surface-2 px-3 py-1.5 text-ink-muted"
    >
      {/* Vert = fonctionnel : c'est exactement l'usage auquel l'accent est réservé. */}
      <span aria-hidden="true" className="size-1.5 rounded-pill bg-accent" />
      Serveur prêt
      <span className="text-ink-dim">·</span>
      <span className="text-ink">{health.device === "cpu" ? "CPU" : "CUDA"}</span>
    </span>
  );
}
