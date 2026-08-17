/**
 * Libellés et formatage des mesures.
 *
 * Le cas qui compte : **une vitesse sans échelle px/m ne doit jamais s'afficher en
 * km/h**. Un véhicule à « 360 km/h » sur une image mal calibrée discrédite tout le
 * tableau, et l'utilisateur ne saura pas si c'est la vitesse ou le comptage qui est
 * faux.
 */

import { describe, expect, it } from "bun:test";

import {
  VEHICLE_CLASSES,
  classLabel,
  crossingRate,
  crossroadFlowSentence,
  directionArrow,
  directionLabel,
  formatCrossingRate,
  formatFrameLatency,
  formatSceneTime,
  formatSceneTimePrecise,
  formatScore,
  formatSpeed,
  plural,
} from "./labels";

describe("classes de véhicule", () => {
  it("ne liste que les quatre classes que le modèle peut émettre", () => {
    // Pas les 80 de COCO : 76 tuiles toujours vides transformeraient la
    // répartition par type en mur de zéros.
    expect([...VEHICLE_CLASSES]).toEqual(["car", "motorcycle", "bus", "truck"]);
  });

  it("traduit les libellés du backend en français", () => {
    expect(classLabel("car")).toBe("Voiture");
    expect(classLabel("truck")).toBe("Camion");
    expect(classLabel("motorcycle")).toBe("Moto");
    expect(classLabel("bus")).toBe("Bus");
  });

  it("couvre les sept classes que le serveur sait détecter", () => {
    // Les trois dernières sont arrivées avec ADR 0014 — l'utilisateur peut cocher
    // vélo, personne et train. Sans leur libellé, la répartition par type afficherait
    // « person » au milieu de « Voiture » et « Camion », ce qui se lit comme une
    // colonne mal branchée plutôt que comme une traduction manquante.
    expect(classLabel("bicycle")).toBe("Vélo");
    expect(classLabel("person")).toBe("Personne");
    expect(classLabel("train")).toBe("Train");
  });

  it("laisse passer une classe inconnue au lieu de la masquer", () => {
    // Si le serveur commence à renvoyer une classe que l'interface ignore, il faut
    // la **voir** pour décider quoi en faire — un « Autre » fourre-tout cacherait le
    // changement.
    expect(classLabel("boat")).toBe("boat");
  });
});

describe("formatSpeed — trois cas distincts, jamais confondus", () => {
  it("affiche des km/h quand l'échelle est fournie", () => {
    expect(formatSpeed(48.6, 1250)).toBe("49 km/h");
  });

  it("**retombe sur px/s sans échelle**, plutôt que d'inventer des km/h", () => {
    // Le cas central : afficher des km/h sans px/m produirait des chiffres
    // inventés que l'utilisateur prendrait au sérieux.
    expect(formatSpeed(null, 1250)).toBe("1250 px/s");
  });

  it("affiche un tiret quand la vitesse est inconnue", () => {
    // Un `0` voudrait dire « à l'arrêt », ce qui est une affirmation différente.
    expect(formatSpeed(null, null)).toBe("—");
  });
});

describe("formatFrameLatency — la cadence lue dans l'autre sens", () => {
  it("convertit une cadence en temps par image", () => {
    expect(formatFrameLatency(5)).toBe("200 ms");
    expect(formatFrameLatency(2.5)).toBe("400 ms");
  });

  it("garde une décimale sous 10 ms, pas au-delà", () => {
    // Sur GPU, l'entier écraserait la différence entre 2 et 9 ms ; sur CPU, la
    // décimale de « 213,4 ms » est du bruit que personne ne lit.
    expect(formatFrameLatency(400)).toBe("2.5 ms");
    expect(formatFrameLatency(4.69)).toBe("213 ms");
  });

  it("rend un tiret plutôt qu'un infini quand rien n'a été mesuré", () => {
    // Une cadence nulle est le cas normal avant la première image publiée.
    expect(formatFrameLatency(0)).toBe("—");
    expect(formatFrameLatency(Number.NaN)).toBe("—");
    expect(formatFrameLatency(-1)).toBe("—");
  });
});

describe("crossingRate — le chiffre qui juge le tracé", () => {
  it("rapporte les véhicules ayant franchi aux véhicules détectés", () => {
    // 48 véhicules vus, 5 d'entre eux ont franchi : la ligne n'est pas sur le
    // passage du trafic. Ni « 48 » ni « 5 » ne le disent seuls.
    expect(formatCrossingRate(crossingRate(48, 5))).toBe("10 %");
    expect(formatCrossingRate(crossingRate(20, 20))).toBe("100 %");
  });

  it("reste borné à 100 % sur un aller-retour — le cas qui cassait le taux", () => {
    // **Le test qui a changé de sens avec ADR 0014.** Il affirmait l'inverse :
    // « n'écrête pas au-dessus de 100 % », et vérifiait que 25 franchissements pour
    // 10 véhicules donnaient 250 %.
    //
    // C'était vrai du calcul et faux de la question posée. Depuis qu'on compte des
    // passages, un aller-retour en vaut 2 pour 1 véhicule : le numérateur et le
    // dénominateur n'avaient plus la même unité, et « 250 % des véhicules ont
    // franchi » ne veut rien dire.
    //
    // Le numérateur est désormais un nombre de véhicules **distincts** ayant
    // franchi — un sous-ensemble des véhicules vus. Le même trafic qu'avant, celui
    // qui produisait 25 passages, donne donc au plus 100 %.
    expect(formatCrossingRate(crossingRate(10, 10))).toBe("100 %");
    // Et l'aller-retour d'un seul véhicule parmi dix : 2 passages, 1 véhicule.
    expect(formatCrossingRate(crossingRate(10, 1))).toBe("10 %");
  });

  it("rend un tiret sans véhicule, jamais « 0 % »", () => {
    // Au démarrage d'une analyse, « 0 % » se lirait comme un comptage en échec.
    expect(crossingRate(0, 0)).toBeNull();
    expect(formatCrossingRate(null)).toBe("—");
  });

  it("dit bien 0 % quand des véhicules passent sans jamais franchir", () => {
    // Là, en revanche, le zéro est l'information : la ligne ne compte rien.
    expect(formatCrossingRate(crossingRate(12, 0))).toBe("0 %");
  });
});

describe("formatSceneTime — millisecondes de scène", () => {
  it("formate en mm:ss", () => {
    expect(formatSceneTime(0)).toBe("00:00");
    expect(formatSceneTime(75_000)).toBe("01:15");
    expect(formatSceneTime(440)).toBe("00:00");
  });

  it("rend --:-- pour une valeur non exploitable", () => {
    expect(formatSceneTime(Number.NaN)).toBe("--:--");
    expect(formatSceneTime(-1)).toBe("--:--");
  });

  it("prend bien des millisecondes et non des secondes", () => {
    // La confusion d'un facteur 1000 est exactement le genre d'erreur invisible
    // que ce test rend impossible : 60 000 ms = une minute.
    expect(formatSceneTime(60_000)).toBe("01:00");
  });
});

describe("formatSceneTimePrecise — l'instant d'un franchissement", () => {
  it("formate au dixième de seconde, virgule décimale française", () => {
    expect(formatSceneTimePrecise(0)).toBe("00:00,0");
    expect(formatSceneTimePrecise(75_400)).toBe("01:15,4");
    expect(formatSceneTimePrecise(440)).toBe("00:00,4");
  });

  it("distingue deux franchissements de la même seconde", () => {
    // La raison d'être de cette fonction : deux passages du même véhicule sur
    // deux lignes voisines tombent dans la même seconde, et `formatSceneTime`
    // les afficherait à la même heure — donc indistinguables.
    expect(formatSceneTimePrecise(3_200)).not.toBe(formatSceneTimePrecise(3_700));
  });

  it("tronque au lieu d'arrondir, comme formatSceneTime", () => {
    // Sinon un franchissement à 59 950 ms paraîtrait tomber après une fenêtre de
    // présence qui, elle, se termine à 00:59.
    expect(formatSceneTimePrecise(59_950)).toBe("00:59,9");
    expect(formatSceneTime(59_950)).toBe("00:59");
  });

  it("rend --:-- pour une valeur non exploitable", () => {
    expect(formatSceneTimePrecise(Number.NaN)).toBe("--:--");
    expect(formatSceneTimePrecise(-1)).toBe("--:--");
  });
});

describe("sens d'un franchissement", () => {
  it("nomme les sens par les poignées visibles sur le canvas", () => {
    // « + » et « − » sont le contrat machine ; « A→B » renvoie à ce que
    // l'utilisateur voit tracé à l'écran.
    expect(directionLabel(1)).toBe("A→B");
    expect(directionLabel(-1)).toBe("B→A");
  });

  it("donne une flèche pour les puces compactes", () => {
    expect(directionArrow(1)).toBe("↑");
    expect(directionArrow(-1)).toBe("↓");
  });
});

describe("formatScore", () => {
  it("affiche un pourcentage entier", () => {
    expect(formatScore(0.71)).toBe("71 %");
  });

  it("affiche un tiret pour une plaque absente", () => {
    expect(formatScore(null)).toBe("—");
  });
});

describe("plural", () => {
  it("accorde le nom au compte", () => {
    expect(plural(1, "véhicule", "véhicules")).toBe("1 véhicule");
    expect(plural(2, "véhicule", "véhicules")).toBe("2 véhicules");
    expect(plural(0, "véhicule", "véhicules")).toBe("0 véhicules");
  });
});

describe("crossroadFlowSentence — le bilan d'une ligne, du point de vue du carrefour", () => {
  it("dit explicitement qu'on entre *dans le carrefour*, pas dans la rue", () => {
    const sentence = crossroadFlowSentence("Ligne Nord", 12, 8);

    expect(sentence).toBe(
      "12 véhicules sont entrés dans le carrefour par « Ligne Nord », 8 en sont ressortis.",
    );
  });

  it("accorde le singulier à un seul véhicule de chaque côté", () => {
    expect(crossroadFlowSentence("Ligne Nord", 1, 1)).toBe(
      "1 véhicule est entré dans le carrefour par « Ligne Nord », 1 en est ressorti.",
    );
  });

  it("omet la sortie quand ce sens est resté neutre", () => {
    // Ligne héritée d'avant ADR 0021 : le rôle de sortie n'a jamais été
    // déclaré. Inventer un chiffre serait pire qu'une phrase incomplète.
    expect(crossroadFlowSentence("Ligne Nord", 12, null)).toBe(
      "12 véhicules sont entrés dans le carrefour par « Ligne Nord ».",
    );
  });

  it("omet l'entrée quand ce sens est resté neutre", () => {
    expect(crossroadFlowSentence("Ligne Nord", null, 8)).toBe(
      "8 véhicules sont ressortis du carrefour par « Ligne Nord ».",
    );
  });

  it("dit que le rôle n'est pas déclaré quand les deux sens sont neutres", () => {
    expect(crossroadFlowSentence("Ligne Nord", null, null)).toBe(
      "Le rôle des sens de « Ligne Nord » n'est pas déclaré.",
    );
  });

  it("lit naturellement un compte à zéro, sans se lire comme une erreur", () => {
    expect(crossroadFlowSentence("Ligne Nord", 0, 0)).toBe(
      "0 véhicules sont entrés dans le carrefour par « Ligne Nord », 0 en sont ressortis.",
    );
  });
});
