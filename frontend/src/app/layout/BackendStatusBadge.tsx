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
    // La raison distingue « aucun GPU sur cette machine » de « la détection a
    // échoué » — deux causes qui n'appellent pas le même geste. Le nom du GPU
    // n'apparaît que s'il y en a un à nommer.
    health.gpuName !== null
      ? `${health.device === "cpu" ? "CPU" : "GPU"} (${health.gpuName})`
      : health.deviceReason !== null
        ? `${health.device === "cpu" ? "CPU" : "GPU"} (${health.deviceReason})`
        : null,
    `Ultralytics ${health.ultralyticsVersion}`,
    health.loadedModels.length > 0
      ? `Résidents : ${health.loadedModels.join(", ")}`
      : "Aucun modèle en mémoire",
    // Quatre états et non deux. « Lecture de plaques disponible » décrivait déjà ce qui
    // n'était qu'une détection ; le corriger évite qu'un serveur sans OCR annonce une
    // lecture qu'il ne sait pas faire.
    //
    // Le quatrième — poids présents, auto-test en échec — est le seul qu'aucun autre
    // drapeau ne peut exprimer, et c'est celui qui trompe : `plateAvailable` est vrai,
    // l'option est cochable, et aucune plaque ne sortira jamais. Il passe donc en
    // premier dans la liste.
    health.plateAvailable && health.plateLoadable === false
      ? "Plaques : modèle présent mais ILLISIBLE — l'ANPR ne rendra rien"
      : !health.plateAvailable
        ? "Plaques : indisponibles"
        : health.plateOcrAvailable
          ? "Plaques : détection et lecture disponibles"
          : "Plaques : détection seule, sans lecture du texte",
  ]
    .filter((line): line is string => line !== null)
    .join(" · ");

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
