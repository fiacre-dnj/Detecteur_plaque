/**
 * Libellés français des classes de véhicule, et formatage des mesures.
 *
 * Le backend renvoie les libellés COCO en anglais (`car`, `truck`…) : c'est son
 * contrat, et le traduire côté serveur mélangerait la langue des données et celle
 * de l'interface. La traduction se fait donc ici, une seule fois.
 *
 * **Seules les classes que le modèle peut réellement émettre** sont listées — les
 * quatre de `VEHICLE_CLASS_IDS`, pas les 80 de COCO. Afficher 80 tuiles dont 76
 * toujours vides transformerait la répartition par type en mur de zéros.
 */

/** Les quatre classes de véhicule, dans l'ordre d'affichage souhaité. */
export const VEHICLE_CLASSES = ["car", "motorcycle", "bus", "truck"] as const;

export type VehicleClass = (typeof VEHICLE_CLASSES)[number];

const LABELS: Readonly<Record<string, string>> = {
  car: "Voiture",
  motorcycle: "Moto",
  bus: "Bus",
  truck: "Camion",
};

/**
 * Libellé français d'une classe.
 *
 * Rend le libellé brut du serveur pour une classe inconnue, plutôt qu'un « Autre »
 * fourre-tout : si le serveur commence à renvoyer `train`, il faut le **voir** pour
 * pouvoir décider quoi en faire, pas le masquer.
 */
export function classLabel(raw: string): string {
  return LABELS[raw] ?? raw;
}

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
 * Formate une vitesse selon l'échelle disponible.
 *
 * Trois cas distincts, et les confondre serait mentir : `km/h` quand l'échelle
 * px/m est fournie, `px/s` sinon, et `—` quand la vitesse est inconnue. Afficher
 * des km/h sans échelle produirait des chiffres inventés — un véhicule à
 * « 360 km/h » sur une image mal calibrée, ce qui discrédite tout le tableau.
 */
export function formatSpeed(kmh: number | null, pxPerSecond: number | null): string {
  if (kmh !== null) return `${Math.round(kmh)} km/h`;
  if (pxPerSecond !== null) return `${Math.round(pxPerSecond)} px/s`;
  return "—";
}

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
 * véhicules uniques et les franchissements ne dit rien de la détection : il dit
 * que la ligne n'est pas sur le passage du trafic, ou qu'elle ne couvre qu'une
 * voie. C'est l'information que ni « 48 uniques » ni « 5 franchissements » ne
 * donnent séparément, et qu'on ne calcule jamais de tête devant un écran.
 *
 * Le chiffre se lit littéralement depuis l'ADR 0009 : un véhicule compte une
 * fois, toutes lignes confondues, donc le rapport est vraiment « combien des
 * véhicules vus sont passés par la ligne ». Avec l'ancien garde par ligne et par
 * sens, un second tracé suffisait à faire doubler le taux sans qu'un véhicule de
 * plus soit passé.
 *
 * Rendu `null` sans véhicule : afficher « 0 % » quand rien n'a encore été détecté
 * se lirait comme un comptage en échec, alors que l'analyse commence à peine.
 */
export function crossingRate(uniqueVehicles: number, crossings: number): number | null {
  if (uniqueVehicles <= 0) return null;
  return crossings / uniqueVehicles;
}

/**
 * Le taux, en pourcentage.
 *
 * Non borné à 100 %, et pour une seule raison depuis l'ADR 0009 : un véhicule
 * disparu puis reconnu à son retour recompte. Une caméra qui voit passer la même
 * navette plusieurs fois dépasse donc légitimement 100 %, et écrêter masquerait
 * précisément ce cas.
 */
export function formatCrossingRate(rate: number | null): string {
  return rate === null ? "—" : `${Math.round(rate * 100)} %`;
}

/** Formate un score de plaque en pourcentage. */
export function formatScore(score: number | null): string {
  return score === null ? "—" : `${Math.round(score * 100)} %`;
}

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
