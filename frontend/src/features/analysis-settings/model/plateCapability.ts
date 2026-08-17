/**
 * Ce que le serveur sait **réellement** faire des plaques, et ce que l'écran en dit.
 *
 * Trois artefacts, trois états, et l'interface les confondait en deux. Le
 * détecteur (`license-plate.pt`) et le lecteur (`license-plate-ocr.onnx` + son
 * dictionnaire) sont récupérés par deux scripts distincts : « détection sans
 * lecture » est l'état de tout déploiement neuf, pas une anomalie.
 *
 * **Le troisième état est celui qui trompe** : poids présents, chargement en
 * échec. `plateAvailable` ne peut pas le voir — c'est un test de présence de
 * fichier, délibérément, parce que l'interface interroge `/health` en permanence
 * — donc la case était cochable, l'analyse ralentissait, et aucune plaque ne
 * sortait jamais. Le suffixe du fichier suffit à produire ce cas : Ultralytics
 * choisit son backend d'après le *nom*, donc un `.pt` déposé sous un nom en
 * `.onnx` s'annonce disponible et ne détecte rien. `plateLoadable` est le verdict
 * d'un vrai chargement suivi d'une inférence à vide, et `null` veut dire « pas
 * encore testé » (préchauffage désactivé) — jamais « en échec ».
 *
 * Des fonctions **pures** qui rendent des phrases, comme `launchNotice` : la copie
 * se corrige et se teste sans monter l'écran.
 */

export interface PlateHealth {
  /** Le modèle de **détection** est présent sur le disque du serveur. */
  available: boolean;
  /** Il a passé son auto-test au démarrage. `null` = pas encore testé. */
  loadable: boolean | null;
  /** Le modèle de **lecture** et son dictionnaire sont présents. */
  ocrAvailable: boolean;
}

export interface PlateCapability {
  /** La case « Repérer les plaques » est-elle actionnable ? */
  canDetect: boolean;
  detectHint: string;
  /** La case « Lire le texte » est-elle actionnable ? */
  canRead: boolean;
  readHint: string;
}

export function plateCapability({ available, loadable, ocrAvailable }: PlateHealth): PlateCapability {
  return {
    // **Décochable dans l'état « présent mais illisible »**, et c'est un choix :
    // laisser cocher promettrait un travail qui ne rend rien, tout en ralentissant
    // l'analyse d'une inférence par véhicule et par image. Le verdict est solide —
    // le serveur a vraiment tenté un chargement — donc l'interface peut trancher.
    canDetect: available && loadable !== false,
    detectHint: detectHint({ available, loadable, ocrAvailable }),
    // Subordonnée à la détection, comme côté serveur : lire sans détecter n'a pas
    // de sens, il n'y aurait aucune boîte à lire.
    canRead: available && loadable !== false && ocrAvailable,
    readHint: readHint(ocrAvailable),
  };
}

function detectHint({ available, loadable }: PlateHealth): string {
  if (!available) {
    return "Le modèle de plaques n'est pas installé sur ce serveur.";
  }
  if (loadable === false) {
    return (
      "Les poids sont présents mais ne se chargent pas : l'ANPR ne rendrait aucune " +
      "plaque tout en ralentissant l'analyse. Vérifiez le fichier de plaques du " +
      "serveur — son suffixe fait partie du contrat, un .pt renommé en .onnx " +
      "s'annonce disponible et ne détecte jamais rien."
    );
  }
  // Ce que coûte l'option, et ce qui la rend supportable — les deux, parce que
  // « plus lent » sans ordre de grandeur ni contrepartie ne se décide pas.
  return (
    "Une inférence de plus par véhicule suivi, une image sur trois seulement : les " +
    "images sautées portent la dernière plaque mesurée, reprojetée sur la boîte du " +
    "véhicule, donc les rectangles ne clignotent pas. Les boîtes manifestement " +
    "impossibles — celle du véhicule entier, par exemple — sont écartées par un " +
    "filtre de forme, pas par ce seuil."
  );
}

function readHint(ocrAvailable: boolean): string {
  if (!ocrAvailable) {
    return (
      "Le modèle de lecture ou son dictionnaire manque : les plaques sont " +
      "encadrées, leur texte n'est pas lu."
    );
  }
  return (
    "Le texte publié est un vote sur toute la vie du véhicule, jamais la lecture " +
    "d'une seule image — deux relectures du même clip donnent donc la même plaque. " +
    "Une plaque trop petite n'est pas lue du tout : le registre dit alors pourquoi, " +
    "avec la largeur mesurée."
  );
}
