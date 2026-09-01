/**
 * Formatage des mesures affichées par le tableau de bord.
 *
 * **Les libellés de classe vivent dans `shared/lib/classes.ts`**, plus ici : le
 * journal des franchissements en a besoin lui aussi, et une feature n'importe jamais
 * une autre feature. Tant qu'ils étaient rangés dans ce module, le journal écrivait
 * `car #12` là où le registre écrivait `Voiture` pour le même véhicule.
 */

/** Pluriel français d'un compte, avec son mot. */
export function plural(count: number, singular: string, plural_: string): string {
  return `${count} ${count === 1 ? singular : plural_}`;
}

/**
 * Formate une position temporelle de scène en `mm:ss`.
 *
 * Distinct de `formatTime` du transport, qui prend des **secondes** : ici l'entrée
 * est en millisecondes de temps de scène, l'unité de tout le résultat. Convertir à
 * l'appel serait une source d'erreur de facteur 1000 exactement là où elle est
 * invisible.
 */
export function formatSceneTime(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "--:--";
  const total = Math.floor(ms / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
}

/**
 * L'instant précis d'un fait, au dixième de seconde.
 *
 * **Déménagé dans `shared/lib/sceneTime.ts`** et seulement réexporté ici : les
 * alertes en ont besoin elles aussi, et une feature n'importe jamais une autre
 * feature. Réexporter plutôt que déplacer l'appel garde intacte l'API publique de
 * `results-dashboard`, dont le registre dépend (`formatSceneTimePrecise` y date les
 * colonnes « Entrée par » et « Sortie par »).
 */
export { formatSceneTimePrecise } from "@/shared/lib/sceneTime";

/**
 * Temps moyen de traitement d'une image, en millisecondes.
 *
 * C'est la cadence lue dans l'autre sens, et c'est délibéré : « 5 img/s » répond
 * à « combien d'images par seconde », « 200 ms » répond à « combien de temps pour
 * une image » — la question qu'on se pose devant une analyse qui n'avance pas.
 * Les deux chiffres cohabitent déjà dans le tableau de benchmark, pour la même
 * raison.
 *
 * Ce n'est **pas** une latence de bout en bout côté client : en différé, aucun
 * aller-retour réseau n'intervient par image. Le libellé doit donc parler du
 * traitement, pas d'un ping.
 */
export function formatFrameLatency(processingFps: number): string {
  if (!Number.isFinite(processingFps) || processingFps <= 0) return "—";
  const ms = 1000 / processingFps;
  // En dessous de 10 ms, l'entier écraserait la différence entre 2 et 9 ms ;
  // au-delà, la décimale est du bruit — personne ne lit « 213,4 ms ».
  return ms < 10 ? `${ms.toFixed(1)} ms` : `${Math.round(ms)} ms`;
}

/**
 * Part des véhicules détectés qui ont franchi au moins une ligne.
 *
 * **Le chiffre qui juge le tracé, pas le modèle.** Un écart franc entre les
 * véhicules détectés et ceux qui franchissent ne dit rien de la détection : il dit
 * que la ligne n'est pas sur le passage du trafic, ou qu'elle ne couvre qu'une
 * voie. C'est l'information que ni « 48 uniques » ni « 5 franchissements » ne
 * donnent séparément, et qu'on ne calcule jamais de tête devant un écran.
 *
 * **Le numérateur est un nombre de véhicules, pas de franchissements**, et cette
 * précision est tout ce qui sépare la version d'aujourd'hui d'un chiffre faux.
 * Jusqu'à ADR 0014 les deux étaient interchangeables — un véhicule comptait une
 * fois, toutes lignes confondues. Depuis, on compte des **passages** : un
 * aller-retour en vaut 2, deux lignes en travers de la même voie en valent 2. Le
 * rapport `crossings / trackedVehicles` mélangerait donc deux unités, dépasserait
 * 100 % sans rien signaler, et ne répondrait plus à la question écrite ci-dessus.
 *
 * D'où `crossedUnique` : le nombre de `globalId` **distincts** apparaissant dans
 * les franchissements. Il reste **dérivé** des événements (invariant 3), jamais
 * accumulé à côté, et il est borné par `trackedVehicles` par construction.
 *
 * Rendu `null` sans véhicule : afficher « 0 % » quand rien n'a encore été détecté
 * se lirait comme un comptage en échec, alors que l'analyse commence à peine.
 */
export function crossingRate(trackedVehicles: number, crossedUnique: number): number | null {
  if (trackedVehicles <= 0) return null;
  return crossedUnique / trackedVehicles;
}

/**
 * Le taux, en pourcentage.
 *
 * **Borné à 100 % par construction, plus par écrêtage** : le numérateur est un
 * sous-ensemble du dénominateur — des véhicules qui ont franchi, parmi les
 * véhicules vus. Il n'y a donc plus rien à écrêter, et c'est le signe que le
 * calcul est le bon. La version d'avant ADR 0014 documentait explicitement
 * qu'elle ne bornait pas, et c'est ce commentaire qui trahissait le mélange
 * d'unités.
 */
export function formatCrossingRate(rate: number | null): string {
  return rate === null ? "—" : `${Math.round(rate * 100)} %`;
}

/**
 * Formate un score de plaque en pourcentage.
 *
 * **Réexporté et non défini ici** : trois features l'affichent — les Résultats, le
 * registre et le tiroir d'alertes — et une feature n'importe jamais une autre. Le
 * juge unique vit dans `shared/lib/score.ts` ; ce réexport garde l'API publique de
 * la feature intacte pour ses lecteurs d'origine.
 */
export { formatScore } from "@/shared/lib/score";

/**
 * Libellé du sens d'un franchissement.
 *
 * « A→B » et « B→A » plutôt que « + » et « − » : le signe est le contrat machine,
 * mais il ne dit rien à un humain qui regarde une ligne tracée à l'écran. Les
 * lettres renvoient aux poignées visibles sur le canvas.
 */
export function directionLabel(direction: number): string {
  return direction > 0 ? "A→B" : "B→A";
}

/** Flèche du sens, pour les puces compactes du registre. */
export function directionArrow(direction: number): string {
  return direction > 0 ? "↑" : "↓";
}

/**
 * La phrase-bilan d'une ligne, dans la section Statistique.
 *
 * **« Entrée » veut dire entrer dans le carrefour**, pas dans la rue — la phrase
 * le dit explicitement (« dans le carrefour par... ») plutôt que de se limiter à
 * un « X en entrée » qui laisserait deviner le sens du mot.
 *
 * `null` signifie qu'un sens est resté `neutral` — une ligne tracée avant ADR
 * 0021, où le rôle est devenu obligatoire. Omettre cette moitié de la phrase
 * plutôt qu'inventer un chiffre : la logique déjà pratiquée par
 * `flowBalance.declared` dans `directions.ts`.
 */
export function crossroadFlowSentence(
  lineName: string,
  entries: number | null,
  exits: number | null,
): string {
  if (entries === null && exits === null) {
    return `Le rôle des sens de « ${lineName} » n'est pas déclaré.`;
  }
  if (exits === null) {
    return `${plural(entries ?? 0, "véhicule est entré", "véhicules sont entrés")} dans le carrefour par « ${lineName} ».`;
  }
  if (entries === null) {
    return `${plural(exits, "véhicule est ressorti", "véhicules sont ressortis")} du carrefour par « ${lineName} ».`;
  }
  return (
    `${plural(entries, "véhicule est entré", "véhicules sont entrés")} dans le carrefour ` +
    `par « ${lineName} », ${plural(exits, "en est ressorti", "en sont ressortis")}.`
  );
}
