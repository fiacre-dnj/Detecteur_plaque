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

/**
 * Libellés français des classes détectables, dans les mêmes termes que le serveur
 * (`DETECTABLE_CLASSES`).
 *
 * Recopiés et non lus depuis `GET /models/classes`, et c'est un compromis assumé :
 * la répartition doit s'afficher sur un résultat archivé, y compris hors ligne ou
 * lorsque le catalogue n'a pas encore répondu. Le repli sur le libellé brut
 * ci-dessous fait que l'oubli d'une classe se voit — « bicycle » au lieu de
 * « Vélo » — au lieu de faire disparaître une ligne.
 */
const LABELS: Readonly<Record<string, string>> = {
  car: "Voiture",
  motorcycle: "Moto",
  bus: "Bus",
  truck: "Camion",
  bicycle: "Vélo",
  person: "Personne",
  train: "Train",
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
 * Formate un **instant** de scène en `mm:ss,d` — au dixième de seconde.
 *
 * Distinct de `formatSceneTime`, et les deux cohabitent pour une raison précise :
 * une **fenêtre de présence** (« vu de 00:55 à 01:02 ») se lit à la seconde, mais
 * un **franchissement** est un événement ponctuel, et deux passages du même
 * véhicule sur deux lignes voisines tombent régulièrement dans la même seconde.
 * Arrondir les afficherait à la même heure, donc indistinguables, alors que le
 * dixième dit lequel a eu lieu d'abord — la seule information qui permette de
 * retrouver le passage dans la vidéo.
 *
 * Le point et non la virgule décimale française, **par alignement** : le journal
 * des franchissements (`analysis-job/model/previewLog.ts`) écrit `00:12.4` depuis
 * l'origine, et les deux se lisent sur le même écran. Deux ponctuations pour le
 * même instant se remarquent bien plus qu'un séparateur non francisé.
 *
 * **Ce n'est pas une heure d'horloge.** C'est du temps de scène (invariant 1) :
 * `frame_index / fps`, compté depuis le début de la vidéo.
 */
export function formatSceneTimePrecise(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "--:--";
  // Tronqué et non arrondi, pour rester cohérent avec `formatSceneTime` : un
  // franchissement à 59 950 ms doit s'afficher 00:59,9 et non 01:00,0, sinon il
  // paraît tomber après une fenêtre de présence qui, elle, se termine à 00:59.
  const tenths = Math.floor(ms / 100);
  const minutes = Math.floor(tenths / 600);
  const seconds = Math.floor(tenths / 10) % 60;
  return `${minutes.toString().padStart(2, "0")}:${seconds
    .toString()
    .padStart(2, "0")}.${tenths % 10}`;
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
