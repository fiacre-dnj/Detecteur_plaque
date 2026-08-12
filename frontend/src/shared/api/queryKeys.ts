/**
 * Fabrique de clés React Query — **centralisée**.
 *
 * Une clé écrite à la main dans deux composants finit par diverger d'un
 * caractère, et l'invalidation rate silencieusement sa cible : l'écran affiche
 * alors des données périmées sans que rien ne le signale.
 */

export const queryKeys = {
  health: ["health"] as const,
  models: ["models"] as const,
  // Distincte de `models` : le catalogue de modèles se réinterroge toutes les 15 s
  // pour suivre l'état de résidence, alors que la liste des classes ne change
  // qu'avec une version du serveur. Les fusionner ferait payer la seconde la
  // cadence de la première.
  detectableClasses: ["models", "classes"] as const,
  // `offset` fait partie de la clé : sans lui, changer de page rendrait la page
  // précédente depuis le cache, et l'utilisateur croirait à un bug d'affichage.
  jobs: (filters?: { status?: string; modelId?: string; offset?: string }) =>
    ["jobs", filters ?? {}] as const,
  job: (jobId: string) => ["jobs", jobId] as const,
  jobVehicles: (jobId: string) => ["jobs", jobId, "vehicles"] as const,
  jobCrossings: (jobId: string) => ["jobs", jobId, "crossings"] as const,
  presets: ["presets"] as const,
} as const;
