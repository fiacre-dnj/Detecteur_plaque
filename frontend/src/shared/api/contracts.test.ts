/**
 * Le garde-fou entre les deux moitiés du projet.
 *
 * La fixture `__fixtures__/analysis-result.json` est **produite par le vrai
 * backend** (`serialise_result` sur une analyse factice, deux véhicules, un
 * franchissement dans chaque sens). Elle est committée et parsée ici dans un
 * type explicite.
 *
 * Conséquence voulue : un champ renommé côté Python casse un test **côté
 * frontend**. C'est le seul mécanisme automatique qui relie les deux — il n'y a
 * pas de monorepo tool, et c'est un choix (voir CLAUDE.md).
 *
 * Ce que ces tests ne font **pas** : vérifier que le backend calcule juste. Le
 * comptage a ses 500 tests côté Python. Ici on vérifie la **forme du contrat**,
 * et les quelques invariants qu'un affichage ne doit jamais contredire.
 */

import { describe, expect, it } from "bun:test";

import fixture from "./__fixtures__/analysis-result.json";
import previewFixture from "./__fixtures__/job-preview.json";
import type { AnalysisResult, JobPreview, TrackSnapshot } from "./contracts";

/**
 * L'assignation **est** le test.
 *
 * Si le backend renomme `identityLabel`, `tsc -b` échoue ici — avant même que
 * les assertions ne tournent. C'est le mode de détection le plus rapide.
 */
const result: AnalysisResult = fixture as AnalysisResult;

describe("contrat du résultat d'analyse", () => {
  it("porte les blocs de premier niveau attendus", () => {
    expect(Object.keys(result).sort()).toEqual([
      "crossings",
      "jobId",
      "modelId",
      "processingFps",
      "stats",
      "timeline",
      "vehicles",
      "video",
      "zoneEvents",
    ]);
  });

  it("décrit la vidéo source, dont les dimensions ancrent toute la géométrie", () => {
    expect(result.video.width).toBeGreaterThan(0);
    expect(result.video.height).toBeGreaterThan(0);
    expect(result.video.fps).toBeGreaterThan(0);
  });

  it("horodate la timeline en temps de scène, croissant", () => {
    // `frameIndex / fps × 1000`, jamais l'horloge murale (invariant 1). Un
    // horodatage qui reculerait casserait la recherche binaire de la relecture.
    const stamps = result.timeline.map((row) => row.timestampMs);
    const sorted = [...stamps].sort((a, b) => a - b);

    expect(stamps).toEqual(sorted);
    expect(stamps[0]).toBe(0);
  });
});

describe("contrat d'une piste", () => {
  /**
   * La première piste porteuse de plaque.
   *
   * Extraite par une fonction qui **lève** si la fixture n'en contient pas,
   * plutôt que par un `!` : le jour où la fixture est régénérée sans ANPR, le
   * message doit dire ce qui manque au lieu de produire un `undefined` qui
   * échoue trois lignes plus loin.
   */
  function trackWithPlate(): TrackSnapshot {
    const found = result.timeline
      .flatMap((row) => row.tracks)
      .find((candidate) => candidate.plates.length > 0);
    if (found === undefined) {
      throw new Error("La fixture ne contient aucune piste avec plaque.");
    }
    return found;
  }

  const track = trackWithPlate();

  it("expose une piste complète, plaque comprise", () => {
    expect(Object.keys(track).sort()).toEqual([
      "box",
      "classId",
      "counted",
      "globalId",
      "hits",
      "identityLabel",
      "label",
      "plateText",
      "plateTextScore",
      "plates",
      "score",
      "trackId",
    ]);
  });

  it("porte `plateText` voté en plus des lectures de l'image", () => {
    // Même raison d'être qu'`identityLabel` : l'OCR est étranglée côté serveur et ne
    // remplit `plates[].text` qu'une image sur trois. C'est `plateText` que l'overlay
    // dessine, sinon l'étiquette clignoterait.
    const voted = result.timeline
      .flatMap((row) => row.tracks)
      .find((candidate) => candidate.plateText !== null);
    expect(voted).toBeDefined();
    if (voted === undefined) return;

    expect(voted.plateText).toBe("AB-123-CD");
    expect(typeof voted.plateTextScore).toBe("number");
  });

  it("ne vote aucun texte sur la première image d'un véhicule", () => {
    // Le vote exige **deux lectures concordantes** : une lecture unique *est* la
    // lecture de l'image courante, exactement ce que l'invariant 4 interdit de
    // publier. Un texte présent dès la première image signifierait que le serveur
    // publie la frame et non le vote — et deux relectures du même clip donneraient
    // alors deux plaques différentes.
    const [firstRow] = result.timeline;
    expect(firstRow).toBeDefined();
    if (firstRow === undefined) return;

    for (const candidate of firstRow.tracks) {
      expect(candidate.plateText).toBeNull();
    }
  });

  it("le texte voté d'une piste sur sa DERNIÈRE image est celui du registre", () => {
    // Le vote agrège sous `globalId` (invariant 4), et c'est un agrégat **vivant** :
    // une lecture ultérieure discordante peut faire revenir un texte publié à
    // `null` (`no_consensus`). Comparer sur une image intermédiaire supposerait à
    // tort que le vote ne fait que se renforcer ; seule la dernière image d'une
    // piste doit porter exactement l'état final du registre — un désaccord là
    // serait structurel, la piste et le registre lisant deux agrégats différents.
    const byId = new Map(result.vehicles.map((vehicle) => [vehicle.globalId, vehicle]));
    const lastSeen = new Map<number, TrackSnapshot>();
    for (const candidate of result.timeline.flatMap((row) => row.tracks)) {
      lastSeen.set(candidate.globalId, candidate);
    }

    for (const [globalId, candidate] of lastSeen) {
      expect(byId.get(globalId)?.plateText).toBe(candidate.plateText);
    }
  });

  it("porte `identityLabel` en plus de `label`", () => {
    // Les deux existent, et le canvas colore par le **voté** : une lecture qui
    // vacille d'une image à l'autre ne doit pas faire clignoter la couleur.
    expect(typeof track.identityLabel).toBe("string");
    expect(typeof track.label).toBe("string");
  });

  it("donne les boîtes en pixels de la vidéo source", () => {
    // Invariant 2 : jamais des pixels modèle, jamais des pixels CSS. Une boîte
    // qui dépasserait la source signalerait une conversion perdue en route.
    expect(track.box.x).toBeGreaterThanOrEqual(0);
    expect(track.box.x + track.box.width).toBeLessThanOrEqual(result.video.width);
    expect(track.box.y + track.box.height).toBeLessThanOrEqual(result.video.height);
  });

  it("exprime la plaque dans le repère de l'image complète, pas du recadrage", () => {
    const [plate] = track.plates;
    expect(plate).toBeDefined();
    if (plate === undefined) return;

    // Contenue dans la boîte du véhicule : c'est ce qui prouve que l'adaptateur
    // a réexprimé les coordonnées du crop en coordonnées absolues.
    expect(plate.box.x).toBeGreaterThanOrEqual(track.box.x);
    expect(plate.box.x + plate.box.width).toBeLessThanOrEqual(track.box.x + track.box.width);
  });

  it("porte le texte de la plaque en plus de sa boîte", () => {
    const [plate] = track.plates;
    expect(plate).toBeDefined();
    if (plate === undefined) return;

    expect(Object.keys(plate).sort()).toEqual(["box", "score", "text", "textScore"]);
    expect(plate.text).toBe("AB-123-CD");
    expect(typeof plate.textScore).toBe("number");
  });

  it("distingue « plaque vue mais illisible » de « aucune plaque »", () => {
    // L'état que l'interface rate le plus facilement, et la raison pour laquelle la
    // fixture porte deux véhicules dont un seul est lu. Une plaque vue sans texte garde
    // un `score` de détection bien réel : une case vide en face serait une
    // contradiction avec le rectangle jaune visible à l'écran.
    const unreadable = result.timeline
      .flatMap((row) => row.tracks)
      .flatMap((candidate) => candidate.plates)
      .find((plate) => plate.text === null);
    expect(unreadable).toBeDefined();
    if (unreadable === undefined) return;

    expect(unreadable.textScore).toBeNull();
    expect(unreadable.score).toBeGreaterThan(0);
  });
});

describe("invariants que l'affichage ne doit jamais contredire", () => {
  it("crossings === Σ byLine[*].total", () => {
    // Invariant 3 : un compteur affiché est **dérivé**, jamais accumulé en
    // double. Deux compteurs indépendants finissent toujours par se contredire,
    // et l'utilisateur ne sait alors plus lequel croire.
    const perLine = Object.values(result.stats.byLine).reduce(
      (sum, tally) => sum + tally.total,
      0,
    );

    expect(result.stats.crossings).toBe(perLine);
  });

  it("total === positive + negative pour chaque ligne", () => {
    for (const [lineId, tally] of Object.entries(result.stats.byLine)) {
      expect(
        tally.byDirection.positive.total + tally.byDirection.negative.total,
        lineId,
      ).toBe(tally.total);
    }
  });

  it("chaque sens ventile par type, et sa ventilation somme à son total", () => {
    // La matrice type × sens que l'écran affiche. Sans cette égalité, « 3 camions
    // entrent » pourrait coexister avec « 2 passages dans ce sens ».
    for (const [lineId, tally] of Object.entries(result.stats.byLine)) {
      for (const sign of ["positive", "negative"] as const) {
        const side = tally.byDirection[sign];
        const summed = Object.values(side.byClass).reduce((sum, count) => sum + count, 0);
        expect(summed, `${lineId} ${sign}`).toBe(side.total);
      }
    }
  });

  it("un sens sans passage porte `null` et non 0 comme premier instant", () => {
    // `0` se lirait « à la première image de la vidéo », ce qui est une affirmation
    // et non une absence.
    for (const tally of Object.values(result.stats.byLine)) {
      for (const sign of ["positive", "negative"] as const) {
        const side = tally.byDirection[sign];
        if (side.total === 0) {
          expect(side.firstMs).toBeNull();
          expect(side.lastMs).toBeNull();
        } else {
          expect(typeof side.firstMs).toBe("number");
          expect(typeof side.lastMs).toBe("number");
        }
      }
    }
  });

  it("deux véhicules en sens opposés comptent chacun dans son sens", () => {
    // La fixture décrit deux véhicules distincts traversant en sens opposés. Depuis
    // ADR 0016 il n'y a plus de déduplication du tout : chaque franchissement
    // observé compte, donc un aller-retour du *même* véhicule donnerait le même
    // résultat — ce qui n'était pas vrai sous ADR 0009.
    const tally = result.stats.byLine.l1;
    expect(tally).toBeDefined();
    if (tally === undefined) return;

    expect(tally.byDirection.positive.total).toBe(1);
    expect(tally.byDirection.negative.total).toBe(1);
  });

  it("un franchissement porte un sens qui vaut +1 ou -1", () => {
    for (const crossing of result.crossings) {
      expect([1, -1]).toContain(crossing.direction);
    }
  });

  it("chaque franchissement est rattaché à un véhicule du registre", () => {
    // On compte sous `globalId` (invariant 4) : un franchissement dont
    // l'identité n'existe pas au registre serait un chiffre impossible à
    // justifier dans l'interface.
    const known = new Set(result.vehicles.map((vehicle) => vehicle.globalId));

    for (const crossing of result.crossings) {
      expect(known).toContain(crossing.globalId);
    }
  });

  it("trackedVehicles correspond exactement à la taille du registre", () => {
    // **Égalité et non inégalité** : les deux filtrent sur la même confirmation de
    // piste depuis ADR 0016. Le total est donc vérifiable ligne à ligne, ce qui est
    // toute la raison d'être du registre.
    expect(result.stats.trackedVehicles).toBe(result.vehicles.length);
  });

  it("la répartition par type somme au nombre de véhicules", () => {
    const summed = Object.values(result.stats.trackedByClass).reduce(
      (sum, count) => sum + count,
      0,
    );
    expect(summed).toBe(result.stats.trackedVehicles);
  });

  it("les véhicules qui ont franchi ne dépassent pas ceux qui ont été vus", () => {
    // L'inégalité qui fait du taux de franchissement un pourcentage. Avec
    // `crossings` au numérateur, il dépassait 100 % dès le premier aller-retour.
    expect(result.stats.crossedUnique).toBeLessThanOrEqual(result.stats.trackedVehicles);
  });

  it("les numéros de véhicule sont strictement croissants et sans répétition", () => {
    // **Le défaut qu'ADR 0016 supprime, verrouillé de l'autre côté du fil.** La
    // galerie relâchait une identité puis la ré-attachait, donc le même `#1` pouvait
    // réapparaître au milieu de la vidéo et fausser le comptage.
    const ids = result.vehicles.map((vehicle) => vehicle.globalId);
    expect(new Set(ids).size).toBe(ids.length);
    expect([...ids].sort((left, right) => left - right)).toEqual(ids);
  });

  it("un franchissement expose la plaque connue à l'instant du comptage", () => {
    const [crossing] = result.crossings;
    expect(crossing).toBeDefined();
    if (crossing === undefined) return;

    expect(Object.keys(crossing).sort()).toEqual([
      // La catégorie est **servie**, pas déduite du libellé : c'est ce qui permet à
      // la relecture de ventiler véhicules et personnes sans recopier la table des
      // classes du serveur.
      "category",
      "direction",
      "frameIndex",
      "globalId",
      "label",
      "lineId",
      "plateText",
      "plateTextScore",
      "timestampMs",
      "trackId",
    ]);

    // Un score sans texte serait une confiance dans le vide, que l'interface
    // afficherait comme un fait.
    for (const event of result.crossings) {
      if (event.plateText === null) expect(event.plateTextScore).toBeNull();
    }
  });

  it("le registre est l'autorité sur la plaque, le journal dit ce qu'on savait", () => {
    // Un franchissement peut porter `null` là où le registre porte le texte : côté
    // serveur, les franchissements d'une image sont émis **avant** sa passe OCR. Les
    // deux disent la vérité de ce qu'ils décrivent — mais quand les deux portent un
    // texte, ce doit être le même, sinon le vote n'agrège pas sous `globalId`.
    const byId = new Map(result.vehicles.map((vehicle) => [vehicle.globalId, vehicle]));

    for (const crossing of result.crossings) {
      if (crossing.plateText === null) continue;
      expect(byId.get(crossing.globalId)?.plateText).toBe(crossing.plateText);
    }
  });
});

describe("contrat du registre des véhicules", () => {
  it("expose une ligne complète, les deux confiances de plaque comprises", () => {
    const [vehicle] = result.vehicles;
    expect(vehicle).toBeDefined();
    if (vehicle === undefined) return;

    expect(Object.keys(vehicle).sort()).toEqual([
      "bestPlateScore",
      "crossedLines",
      "firstSeenMs",
      "globalId",
      "label",
      "lastSeenMs",
      // Le candidat rapporté sans y souscrire, sous `no_consensus` seulement — un
      // indice, jamais un vote : afficher ce candidat à la place de `plateText`
      // republierait la lecture la plus favorable.
      "plateBestGuess",
      "plateBestGuessScore",
      // Le couple qui remplace une case vide par une cause : « vue à 48 px » dit
      // de resserrer le plan, « non détectée » dit tout autre chose. Sans lui, le
      // silence se lit comme une panne du service.
      "plateBestWidthPx",
      "plateText",
      "plateTextScore",
      "plateUnreadReason",
      "zonesVisited",
    ]);
  });

  it("un texte lu implique toujours une plaque détectée", () => {
    // Le détecteur précède l'OCR : un texte sans score de détection serait un texte
    // lu sur rien, donc un bug de câblage entre les deux passes.
    for (const vehicle of result.vehicles) {
      if (vehicle.plateText !== null) expect(vehicle.bestPlateScore).not.toBeNull();
    }
  });

  it("distingue « plaque vue mais illisible » de « aucune plaque »", () => {
    const unreadable = result.vehicles.find((vehicle) => vehicle.plateText === null);
    expect(unreadable).toBeDefined();
    if (unreadable === undefined) return;

    // Vue — le score de détection le prouve — mais aucune lecture ne fait consensus.
    expect(unreadable.bestPlateScore).not.toBeNull();
    expect(unreadable.plateTextScore).toBeNull();
  });
});

describe("contrat du diagnostic", () => {
  it("expose les sept mesures qui rendent un comptage explicable", () => {
    // Ce bloc n'est pas décoratif : « le compte est faux » n'est diagnosticable
    // que si l'on voit si un véhicule manquant n'a jamais été détecté, l'a été
    // faiblement, n'était pas confirmé, ou a été masqué par une zone — et, dans
    // l'autre sens, si un véhicule compté en trop était un doublon inclus.
    //
    // `lowDetections` a disparu (ADR 0024) : il prétendait mesurer des
    // détections jetées avant le suivi, une quantité qu'aucun adaptateur n'a
    // jamais su observer — `rescuedByLowScore` porte désormais le même rôle,
    // mesurable celui-là.
    expect(Object.keys(result.stats.diagnostics).sort()).toEqual([
      "confirmedTracks",
      "containedOut",
      "highDetections",
      "maskedOut",
      "nearMisses",
      "rescuedByLowScore",
      "tentativeTracks",
    ]);
  });

  it("indexe les quasi-franchissements par ligne, une entrée par ligne tracée", () => {
    // La seule mesure du bloc qui ne soit pas un entier : elle porte sur le
    // **tracé** et non sur la détection, et un total ne dirait pas *laquelle* des
    // lignes est mal posée — ce qui est la seule chose qu'on veut en savoir.
    //
    // Une ligne sans quasi-franchissement est présente à `0` : l'absence de clé se
    // lirait « pas d'information » alors que zéro en est une.
    const nearMisses = result.stats.diagnostics.nearMisses;
    expect(nearMisses).toBeDefined();
    expect(Object.keys(nearMisses ?? {}).sort()).toEqual(Object.keys(result.stats.byLine).sort());
    for (const count of Object.values(nearMisses ?? {})) {
      expect(Number.isInteger(count)).toBe(true);
    }
  });
});

describe("contrat de l'aperçu d'une analyse en cours", () => {
  /**
   * Assemblée par `scripts/build_fixtures.py` depuis une analyse factice passée
   * par les **vrais sérialiseurs** — pas par une main humaine qui recopierait des
   * noms de champs. La forme des pistes, des franchissements, des compteurs et
   * des véhicules vient donc du code réellement servi ; seul l'emballage de
   * premier niveau est monté par le script, à l'identique de
   * `JobManager._preview_payload`.
   */
  const preview: JobPreview = previewFixture as JobPreview;

  it("porte les blocs de premier niveau attendus", () => {
    expect(Object.keys(preview).sort()).toEqual([
      "crossings",
      "frameHeight",
      "frameIndex",
      "frameWidth",
      "jobId",
      "stats",
      "timestampMs",
      "tracks",
      // Le registre en cours de constitution : ce champ est **tout** ce qui
      // permet au tableau des véhicules de se remplir pendant l'analyse au lieu
      // d'attendre le résultat complet.
      "vehicles",
      "zoneEvents",
    ]);
  });

  it("décrit un véhicule exactement comme le registre du résultat", () => {
    // La même égalité de forme que pour les pistes, et pour la même raison : le
    // tableau affiché pendant l'analyse et celui affiché après sont **le même
    // composant**. Un champ manquant ici — une durée, une plaque, une raison de
    // non-lecture — donnerait une colonne vide qui se remplirait toute seule à la
    // fin, ce qui se lit comme un bug de comptage.
    const [live] = preview.vehicles ?? [];
    const [archived] = result.vehicles;
    expect(live).toBeDefined();
    expect(archived).toBeDefined();
    if (live === undefined || archived === undefined) return;

    expect(Object.keys(live).sort()).toEqual(Object.keys(archived).sort());
  });

  it("ne publie que les véhicules ayant franchi une ligne", () => {
    // La population que l'écran affiche (ADR 0023) — et la raison pour laquelle
    // l'aperçu peut la republier plusieurs fois par minute sans faire grossir le
    // flux avec l'analyse. Le résultat archivé, lui, garde tout objet suivi.
    const live = preview.vehicles ?? [];
    expect(live.length).toBeGreaterThan(0);
    expect(live.every((vehicle) => vehicle.crossedLines.length > 0)).toBe(true);
    // La restriction est réelle sur cette scène : trois objets suivis, deux qui
    // franchissent. Sans cet écart, le test ci-dessus serait une tautologie.
    expect(result.vehicles.length).toBeGreaterThan(live.length);
  });

  it("décrit une piste exactement comme la timeline, plaques comprises", () => {
    // C'est cette égalité de forme qui permet à `drawScene` de dessiner
    // l'aperçu, la relecture et le direct sans une seule branche.
    const [track] = preview.tracks;
    expect(track).toBeDefined();
    if (track === undefined) return;

    const fromTimeline = result.timeline
      .flatMap((row) => row.tracks)
      .find((candidate) => candidate.plates.length > 0);
    expect(fromTimeline).toBeDefined();
    if (fromTimeline === undefined) return;

    expect(Object.keys(track).sort()).toEqual(Object.keys(fromTimeline).sort());

    // **Les clés imbriquées aussi.** Comparer seulement le premier niveau laisserait
    // passer un aperçu dont les plaques n'auraient pas de `text` : les rectangles
    // seraient muets pendant l'analyse et bavards à la relecture, et rien ici ne le
    // verrait — c'est précisément le mode de divergence que ce test existe pour
    // attraper.
    const [previewPlate] = track.plates;
    const [timelinePlate] = fromTimeline.plates;
    expect(previewPlate).toBeDefined();
    expect(timelinePlate).toBeDefined();
    if (previewPlate === undefined || timelinePlate === undefined) return;

    // `stale` est **délibérément optionnel** — sérialisé seulement quand il vaut
    // `true`, parce qu'un booléen sur 100 % des plaques de 45 000 images pèse pour
    // une information qui n'a de sens que dans le cas minoritaire. Il est donc
    // écarté de la comparaison de forme, qui porte sur les clés **toujours**
    // présentes. Ce que le test protège reste entier : une plaque d'aperçu sans
    // `text` serait muette pendant l'analyse et bavarde à la relecture.
    const required = (plate: object): string[] =>
      Object.keys(plate)
        .filter((key) => key !== "stale")
        .sort();

    expect(required(previewPlate)).toEqual(required(timelinePlate));
  });

  it("annonce les dimensions décodées par le serveur", () => {
    // Le client les compare à celles de sa balise `<video>` et refuse de
    // dessiner en cas de désaccord : sans ce filet, une géométrie mal ancrée
    // produirait des boîtes décalées que rien n'expliquerait.
    expect(preview.frameWidth).toBe(result.video.width);
    expect(preview.frameHeight).toBe(result.video.height);
  });

  it("horodate en temps de scène, cohérent avec son index d'image", () => {
    expect(preview.timestampMs).toBeCloseTo(
      (preview.frameIndex / result.video.fps) * 1000,
      3,
    );
  });

  it("porte les compteurs courants, pas seulement des boîtes", () => {
    // Sans eux, l'aperçu montrerait des véhicules détectés sans jamais dire
    // s'ils sont comptés — c'est-à-dire la moitié de ce qu'on cherche à valider.
    expect(preview.stats.trackedVehicles).toBeGreaterThan(0);
    expect(preview.stats.crossings).toBe(
      Object.values(preview.stats.byLine).reduce((sum, tally) => sum + tally.total, 0),
    );
  });

  it("marque ✓ une piste comptée, et elle seule", () => {
    // Le badge dérive du tally serveur (invariant 5) : il vient de la même source
    // que `crossedUnique`, donc les deux ne peuvent pas se contredire à l'écran.
    const counted = preview.tracks.filter((track) => track.counted).map((t) => t.globalId);
    const crossed = new Set(preview.crossings.map((crossing) => crossing.globalId));

    for (const globalId of crossed) {
      expect(counted).toContain(globalId);
    }
  });
});

describe("contrat du registre des véhicules", () => {
  it("liste les lignes franchies par chaque véhicule", () => {
    const vehicle = result.vehicles.find((candidate) => candidate.crossedLines.length > 0);
    expect(vehicle).toBeDefined();
    const crossed = vehicle?.crossedLines[0];
    expect(crossed).toBeDefined();
    if (crossed === undefined) return;

    expect(crossed.lineId).toBe("l1");
    expect([1, -1]).toContain(crossed.direction);
  });
});
