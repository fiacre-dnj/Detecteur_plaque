/**
 * Le test de la cadence — il prouve que les frames sont **abandonnées** et non mises
 * en file.
 *
 * Aucun test ici ne dort ni ne mesure une durée réelle : le temps est un paramètre.
 * C'est délibéré, et c'est la seule façon d'avoir une assertion exacte sur la
 * latence. Un test qui attendrait `setTimeout` puis vérifierait « environ 30 ms »
 * passerait ou échouerait selon la charge de la machine, et un test dont le verdict
 * dépend de la vitesse de la machine ne prouve rien.
 */

import { describe, expect, test } from "bun:test";

import { EMPTY_PACING, FramePacer, sceneTimeMs } from "./pacing";

describe("FramePacer — une seule frame en vol", () => {
  test("accorde le premier créneau", () => {
    const pacer = new FramePacer();
    expect(pacer.tryClaim(0)).toBe(true);
    expect(pacer.busy).toBe(true);
  });

  test("refuse le second tant que le premier n'est pas revenu", () => {
    const pacer = new FramePacer();
    pacer.tryClaim(0);
    expect(pacer.tryClaim(16)).toBe(false);
    expect(pacer.tryClaim(33)).toBe(false);
  });

  test("rend le créneau après le résultat", () => {
    const pacer = new FramePacer();
    pacer.tryClaim(0);
    pacer.complete(120);
    expect(pacer.busy).toBe(false);
    expect(pacer.tryClaim(130)).toBe(true);
  });

  test("les frames refusées sont comptées, pas oubliées", () => {
    // Un taux d'abandon invisible est un taux d'abandon qu'on ne peut pas
    // expliquer à l'utilisateur qui trouve le direct « lent ».
    const pacer = new FramePacer();
    pacer.tryClaim(0);
    pacer.tryClaim(16);
    pacer.tryClaim(33);
    pacer.tryClaim(50);
    expect(pacer.snapshot().dropped).toBe(3);
    expect(pacer.snapshot().sent).toBe(0);
  });

  test("les frames refusées ne sont **pas** rejouées ensuite", () => {
    // Le cœur de la règle. Après trois abandons et un résultat, le tour suivant
    // envoie **une** frame — la courante. S'il en partait quatre, c'est qu'une
    // file existerait quelque part, et la latence dériverait sans se rattraper.
    const pacer = new FramePacer();
    pacer.tryClaim(0);
    pacer.tryClaim(16);
    pacer.tryClaim(33);
    pacer.complete(100);

    expect(pacer.tryClaim(116)).toBe(true);
    expect(pacer.tryClaim(133)).toBe(false);
    expect(pacer.snapshot().sent).toBe(1);
  });

  test("un serveur trois fois plus lent que la caméra abandonne deux frames sur trois", () => {
    // Simulation d'un cas réel : caméra à 30 images/s (33 ms), serveur à 10 (100 ms).
    //
    // La réponse arrive **de façon asynchrone**, pas dans le même tour : c'est tout
    // le point. `dueAt` retient l'instant où le résultat reviendra, et chaque tour
    // le complète seulement s'il est échu — reproduire l'ordonnancement réel est
    // indispensable, un `complete()` dans le même tour rendrait le créneau
    // immédiatement et le test conclurait qu'aucune frame n'est jamais abandonnée.
    const pacer = new FramePacer();
    let dueAt: number | null = null;

    for (let frame = 0; frame < 9; frame += 1) {
      const now = frame * 33;
      if (dueAt !== null && now >= dueAt) {
        pacer.complete(dueAt);
        dueAt = null;
      }
      if (pacer.tryClaim(now)) dueAt = now + 100;
    }

    // 9 frames produites aux instants 0…264 ms. Envoyées : 0, 132, 264. Le rapport
    // suit le débit du serveur, ce qui est exactement l'autorégulation cherchée.
    expect(pacer.snapshot().sent).toBe(2); // la troisième est encore en vol
    expect(pacer.snapshot().dropped).toBe(6);
  });
});

describe("FramePacer — latence", () => {
  test("mesure l'aller-retour de la frame envoyée", () => {
    const pacer = new FramePacer();
    pacer.tryClaim(1000);
    pacer.complete(1085);
    expect(pacer.snapshot().latencyMs).toBe(85);
  });

  test("garde la latence de la **dernière** frame, non une moyenne", () => {
    // Une moyenne lisserait la dégradation qu'on veut voir apparaître : c'est
    // l'instantané qui dit à l'utilisateur que le serveur vient de saturer.
    const pacer = new FramePacer();
    pacer.tryClaim(0);
    pacer.complete(500);
    pacer.tryClaim(600);
    pacer.complete(640);
    expect(pacer.snapshot().latencyMs).toBe(40);
  });

  test("n'est jamais négative même si l'horloge recule", () => {
    // `performance.now()` est monotone, mais le pacer ne dépend pas de cette
    // garantie : une latence négative affichée serait un défaut visible.
    const pacer = new FramePacer();
    pacer.tryClaim(1000);
    pacer.complete(900);
    expect(pacer.snapshot().latencyMs).toBe(0);
  });

  test("est nulle avant toute frame", () => {
    // `null` et non 0 : « 0 ms » se lirait comme une réponse instantanée.
    expect(new FramePacer().snapshot().latencyMs).toBeNull();
  });
});

describe("FramePacer — abandon d'une frame en vol", () => {
  test("libère le créneau sans compter un envoi", () => {
    const pacer = new FramePacer();
    pacer.tryClaim(0);
    pacer.abandon();
    expect(pacer.busy).toBe(false);
    expect(pacer.snapshot().sent).toBe(0);
  });

  test("un échec ne fige pas le direct pour toujours", () => {
    // La panne que `abandon()` existe pour empêcher : sans lui, une frame refusée
    // par un message `error` laisserait `inFlight` à `true` définitivement — le
    // direct se figerait avec une connexion ouverte et aucun message d'erreur.
    const pacer = new FramePacer();
    pacer.tryClaim(0);
    pacer.abandon();
    expect(pacer.tryClaim(33)).toBe(true);
  });

  test("ne compte pas d'abandon de cadence : ce n'est pas un manque de créneau", () => {
    // La colonne « abandonnées » mesure la saturation. Y mêler les erreurs
    // serveur ferait diagnostiquer « serveur lent » là où le problème est autre.
    const pacer = new FramePacer();
    pacer.tryClaim(0);
    pacer.abandon();
    expect(pacer.snapshot().dropped).toBe(0);
  });
});

describe("FramePacer — remise à zéro", () => {
  test("rend l'état d'une session neuve", () => {
    const pacer = new FramePacer();
    pacer.tryClaim(0);
    pacer.tryClaim(16);
    pacer.complete(100);
    pacer.reset();
    expect(pacer.snapshot()).toEqual(EMPTY_PACING);
    expect(pacer.busy).toBe(false);
  });
});

describe("sceneTimeMs", () => {
  test("compte depuis le début de la session, pas depuis l'époque", () => {
    // Un horodatage absolu de 1,7 × 10¹² ferait perdre la précision utile dans
    // les flottants dès le premier calcul de delta côté serveur.
    expect(sceneTimeMs(5000, 5250)).toBe(250);
  });

  test("commence à zéro", () => {
    expect(sceneTimeMs(5000, 5000)).toBe(0);
  });

  test("ne rend jamais un temps négatif — le serveur refuse `ge=0`", () => {
    // `timestampMs` est borné `ge=0` dans `FrameMessage` : une valeur négative
    // ferait répondre un message `error` au lieu d'un résultat.
    expect(sceneTimeMs(5000, 4900)).toBe(0);
  });
});
