/**
 * Le vocabulaire des classes de véhicule : leur ordre d'affichage et leur nom français.
 *
 * **Dans `shared/` et non dans une feature**, pour la même raison que
 * `shared/lib/directions.ts` : quatre features nomment une classe — la répartition
 * par type, son camembert, le registre et le journal des franchissements. Une
 * feature n'importe jamais une autre feature, et sans ce module le journal écrivait
 * `car #12` là où le registre écrivait `Voiture` pour le même véhicule. C'est
 * l'invariant 12 qui tranche : le code parle français à l'utilisateur.
 *
 * Le backend renvoie les libellés COCO en anglais (`car`, `truck`…) : c'est son
 * contrat, et le traduire côté serveur mélangerait la langue des données et celle de
 * l'interface. La traduction se fait donc ici, une seule fois.
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

/**
 * Les classes que la définition d'analyse punit — **par nom COCO, jamais par
 * libellé**.
 *
 * Ce sont les plus petits gabarits de COCO : leur boîte fait couramment 60 px de
 * large sur une vue de circulation, donc une vingtaine dans une entrée de réseau à
 * 640 (ADR 0037). Une voiture au même endroit en fait trois fois plus.
 *
 * Un ensemble nommé ici plutôt qu'un test dans l'écran qui en a besoin : deux
 * surfaces s'en servent déjà — l'avertissement d'avant-analyse et, demain, tout ce
 * qui voudra dire « ce type-là demande de la définition ». Deux listes finiraient par
 * diverger, et la panne serait un avertissement qui ne se déclenche plus sur la
 * classe dont l'utilisateur se plaint.
 */
export const SMALL_CLASSES: ReadonlySet<string> = new Set(["motorcycle", "bicycle", "person"]);

/**
 * Le nom COCO de la seule classe qui ne soit pas un véhicule.
 *
 * Nommé plutôt qu'écrit en clair là où on en a besoin : `"person"` en littéral dans
 * un composant est une chaîne magique qu'un renommage du catalogue laisserait
 * silencieusement fausse — la carte disparaîtrait sans que rien ne le dise.
 */
export const PERSON_CLASS = "person";
