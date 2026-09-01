/**
 * État du backend, visible en permanence, **en bas du rail**.
 *
 * Quand le serveur est absent, l'interface **le dit** et désactive l'analyse :
 * ni page blanche, ni erreur console, ni bouton qui ne fait rien. C'est un
 * critère d'acceptation du projet, pas une amélioration.
 *
 * Les trois états tiennent dans une colonne de 56 px, ce qui a coûté deux
 * arbitrages :
 *
 * - **le mot « Serveur prêt » disparaît, le matériel reste.** Des deux, le matériel
 *   est le seul qu'on relise : il change la lecture de chaque chiffre de latence,
 *   alors que « prêt » est déjà dit par la pastille verte. Le nom accessible, lui,
 *   porte toujours la phrase entière ;
 * - **en erreur, le badge et « Réessayer » fusionnent en un seul bouton.** Ils
 *   étaient deux éléments côte à côte parce que l'entête avait la largeur de les
 *   porter ; dans un rail, il faudrait en sacrifier un. Fusionner vaut mieux que
 *   choisir : la surface qui *dit* le problème est celle qui le corrige, ce qui est
 *   une affordance plus forte que le mot posé à côté.
 *
 * **Perte assumée** : la phrase « Serveur injoignable » n'est plus lisible à l'œil,
 * seule la teinte `warning` signale l'anomalie. Ce n'est pas le seul canal — le
 * studio grise déjà « Lancer l'analyse » et affiche la cause à l'endroit exact où le
 * geste échoue. Si cela se révèle trop discret à l'usage, l'incrément suivant est une
 * étiquette dépliée au survol et au focus ; ne pas la construire d'avance.
 *
 * Deux règles d'accessibilité que ces trois états appliquent :
 *
 * - **`role="img"` sur les états non cliquables**, et pas un `<span>` nu : un
 *   `aria-label` posé sur un élément générique est ignoré par une partie des lecteurs
 *   d'écran, et l'état deviendrait alors muet au lieu d'être abrégé ;
 * - **`title` double le nom accessible, il n'en est jamais le seul porteur.** Il
 *   n'existe ni au clavier ni au toucher, et son annonce varie d'un lecteur à l'autre.
 */

import { CircleAlert, RefreshCw } from "lucide-react";

import { useHealth } from "./useHealth";

export function BackendStatusBadge() {
  const { data: health, isLoading, refetch, isFetching } = useHealth();

  if (isLoading) {
    return (
      <span
        role="img"
        aria-label="Connexion au serveur…"
        title="Connexion au serveur…"
        className="grid size-10 shrink-0 place-items-center"
      >
        <span
          aria-hidden="true"
          className="size-2 rounded-pill bg-ink-dim motion-safe:animate-pulse"
        />
      </span>
    );
  }

  if (!health) {
    return (
      <button
        type="button"
        onClick={() => void refetch()}
        disabled={isFetching}
        aria-label="Serveur injoignable — réessayer"
        title="Serveur injoignable — réessayer"
        className={[
          "grid size-10 shrink-0 place-items-center rounded-pill transition-colors",
          "bg-warning/12 text-warning hover:enabled:bg-warning/20 disabled:opacity-60",
        ].join(" ")}
      >
        {isFetching ? (
          <RefreshCw aria-hidden="true" className="size-4 motion-safe:animate-spin" />
        ) : (
          <CircleAlert aria-hidden="true" className="size-4" />
        )}
      </button>
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

  const device = health.device === "cpu" ? "CPU" : "CUDA";

  return (
    <span
      role="img"
      aria-label={`Serveur prêt, ${device}`}
      title={detail}
      className="flex w-10 shrink-0 flex-col items-center gap-1 rounded-pill bg-surface-2 py-1.5"
    >
      {/* Vert = fonctionnel : c'est exactement l'usage auquel l'accent est réservé. */}
      <span aria-hidden="true" className="size-1.5 rounded-pill bg-accent" />
      <span aria-hidden="true" className="label-micro leading-none text-ink">
        {device}
      </span>
    </span>
  );
}
