/**
 * Regroupement du catalogue par palier, et **navigation clavier à plat**.
 *
 * La subtilité de ce module tient en une phrase : **les groupes sont purement
 * visuels**. Les entêtes de palier aident l'œil à se repérer dans vingt modèles,
 * mais les flèches du clavier doivent parcourir la liste **comme si elle était
 * plate**. Un utilisateur au clavier qui doit « sortir » d'un groupe pour entrer
 * dans le suivant se retrouve bloqué sans comprendre pourquoi — et c'est le défaut
 * classique des listes groupées.
 *
 * D'où la séparation : `groupByTier` sert au rendu, `flatOrder` sert au clavier, et
 * les deux dérivent de la même source dans le même ordre.
 */

import type { ModelTier, VehicleModel } from "@/shared/api/contracts";

/** Ordre d'affichage des paliers, du plus léger au plus lourd. */
export const TIER_ORDER: readonly ModelTier[] = ["nano", "small", "medium", "large", "xlarge"];

export interface TierGroup {
  tier: ModelTier;
  label: string;
  models: VehicleModel[];
}

/**
 * Regroupe les modèles par palier, dans l'ordre des paliers.
 *
 * Les paliers **vides sont omis** : un entête « xlarge » suivi de rien serait un
 * cul-de-sac visuel. Le libellé vient du serveur (`tierLabel`) plutôt que d'être
 * codé ici, pour qu'ajouter un palier au catalogue ne demande qu'une ligne côté
 * Python.
 */
export function groupByTier(models: readonly VehicleModel[]): TierGroup[] {
  const groups: TierGroup[] = [];

  for (const tier of TIER_ORDER) {
    const inTier = models.filter((model) => model.tier === tier);
    if (inTier.length === 0) continue;
    groups.push({
      tier,
      label: inTier[0]?.tierLabel ?? tier,
      models: inTier,
    });
  }

  // Un modèle dont le palier n'est pas dans `TIER_ORDER` ne doit **pas**
  // disparaître : il serait invisible dans l'interface tout en étant analysable
  // par l'API, ce qui est le pire des deux mondes.
  const known = new Set(TIER_ORDER);
  const orphans = models.filter((model) => !known.has(model.tier));
  if (orphans.length > 0) {
    groups.push({ tier: orphans[0]?.tier ?? "nano", label: "Autres", models: orphans });
  }
  return groups;
}

/**
 * L'ordre plat, celui que suivent les flèches du clavier.
 *
 * Identique à l'ordre visuel, groupes aplatis. C'est ce qui garantit que la
 * navigation clavier et l'œil sont d'accord : `flatOrder` doit toujours dériver de
 * `groupByTier`, jamais du tableau d'origine — sinon les deux divergent dès qu'un
 * palier est vide.
 */
export function flatOrder(groups: readonly TierGroup[]): VehicleModel[] {
  return groups.flatMap((group) => group.models);
}

/**
 * Index suivant pour une touche de navigation.
 *
 * Rend `null` quand la touche ne navigue pas, pour que l'appelant n'ait pas à
 * décider s'il consomme l'événement.
 *
 * **Pas de bouclage** : arrivé en bas, `ArrowDown` ne repart pas en haut. Le
 * bouclage désoriente dans une liste longue — on croit avoir tout parcouru alors
 * qu'on est revenu au début sans le voir passer.
 */
export function nextIndex(key: string, current: number, count: number): number | null {
  if (count === 0) return null;

  switch (key) {
    case "ArrowDown":
      return Math.min(count - 1, current + 1);
    case "ArrowUp":
      return Math.max(0, current - 1);
    case "Home":
      return 0;
    case "End":
      return count - 1;
    case "PageDown":
      return Math.min(count - 1, current + 5);
    case "PageUp":
      return Math.max(0, current - 5);
    default:
      return null;
  }
}

/**
 * Ce qu'il faut dire d'un modèle avant que l'utilisateur ne le choisisse.
 *
 * Le cas qui compte : un modèle **non téléchargé** coûte un téléchargement au
 * premier usage. L'annoncer ici évite le « pourquoi ma première analyse a mis 90
 * secondes » — la question que cette distinction en trois états existe pour
 * supprimer.
 */
export function modelStateLabel(model: VehicleModel): string {
  if (model.loaded) return "résident en mémoire";
  if (model.downloaded) return "téléchargé";
  return `premier usage : téléchargement ~${model.sizeMb} Mo`;
}

/**
 * Faut-il précharger ce modèle au moment où on le choisit ?
 *
 * Extrait du composant pour être **testable** : la règle a trois conditions dont
 * deux ont un coût réel si on les oublie, et aucune n'est vérifiable en lisant du
 * JSX.
 *
 * - `downloaded` ⇒ non. Le poids est là ; l'appel ne ferait que prendre un bail
 *   pour rien.
 * - `canPreload` faux ⇒ non. Le préchargement prend un bail, donc le lancer
 *   pendant une analyse le ferait attendre la fin de celle-ci, sans que rien à
 *   l'écran ne l'explique.
 *
 * **Ce prédicat ne dit rien du geste.** Le composant ne l'appelle que depuis un
 * *choix* — clic, Entrée, Espace — et jamais depuis la navigation aux flèches :
 * les confondre lancerait vingt téléchargements pour un parcours de la liste.
 */
export function shouldPreload(model: VehicleModel, canPreload: boolean): boolean {
  return canPreload && !model.downloaded;
}

/** Taille réelle sur disque si connue, sinon l'estimation du catalogue. */
export function modelSizeLabel(model: VehicleModel): string {
  if (model.sizeBytes !== null) {
    return `${(model.sizeBytes / (1024 * 1024)).toFixed(1)} Mo`;
  }
  return `~${model.sizeMb} Mo`;
}
