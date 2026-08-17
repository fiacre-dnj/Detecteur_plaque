/**
 * Les trois états de l'ANPR, et celui qui trompe.
 *
 * Le cas qui a motivé ce module : `plateAvailable: true` avec
 * `plateLoadable: false` — poids présents, chargement en échec. L'interface le
 * lisait comme « disponible », donc l'option était cochable, l'analyse payait une
 * inférence par véhicule et par image, et aucune plaque ne sortait. Tout paraissait
 * vert.
 */

import { describe, expect, it } from "bun:test";

import { plateCapability } from "./plateCapability";

const ABSENT = { available: false, loadable: null, ocrAvailable: false };
const DETECTION_SEULE = { available: true, loadable: true, ocrAvailable: false };
const COMPLET = { available: true, loadable: true, ocrAvailable: true };
/** Poids présents, auto-test en échec — l'état à surveiller. */
const ILLISIBLE = { available: true, loadable: false, ocrAvailable: true };
/** Préchauffage désactivé : rien n'a été testé, ce n'est pas un échec. */
const NON_TESTE = { available: true, loadable: null, ocrAvailable: true };

describe("plateCapability", () => {
  it("interdit tout quand le modèle de détection est absent", () => {
    const capability = plateCapability(ABSENT);

    expect(capability.canDetect).toBe(false);
    expect(capability.canRead).toBe(false);
    expect(capability.detectHint).toContain("n'est pas installé");
  });

  it("autorise la détection sans la lecture — l'état d'un déploiement neuf", () => {
    // Deux artefacts, deux scripts de récupération : « détection sans lecture »
    // n'est pas une anomalie, et proposer une case qui ne fait rien en serait une.
    const capability = plateCapability(DETECTION_SEULE);

    expect(capability.canDetect).toBe(true);
    expect(capability.canRead).toBe(false);
    expect(capability.readHint).toContain("dictionnaire");
  });

  it("autorise les deux quand les deux modèles sont là", () => {
    const capability = plateCapability(COMPLET);

    expect(capability.canDetect).toBe(true);
    expect(capability.canRead).toBe(true);
  });

  it("refuse la détection quand les poids sont présents mais illisibles", () => {
    // **Le cas central.** Cocher promettrait un travail qui ne rend rien, tout en
    // ralentissant l'analyse. Le verdict est solide : le serveur a tenté un vrai
    // chargement suivi d'une inférence à vide.
    const capability = plateCapability(ILLISIBLE);

    expect(capability.canDetect).toBe(false);
    expect(capability.canRead).toBe(false);
    // Et il dit **quoi vérifier**, pas seulement que ça ne marche pas : le suffixe
    // du fichier est la cause déjà rencontrée sur ce projet.
    expect(capability.detectHint).toContain("suffixe");
  });

  it("ne lit pas « pas encore testé » comme un échec", () => {
    // `null` arrive quand le préchauffage est désactivé. Bloquer l'option sur cette
    // base priverait d'ANPR un serveur parfaitement capable.
    const capability = plateCapability(NON_TESTE);

    expect(capability.canDetect).toBe(true);
    expect(capability.canRead).toBe(true);
  });

  it("dit le coût de la détection et ce qui l'amortit", () => {
    // « Plus lent » sans ordre de grandeur ni contrepartie ne se décide pas.
    const hint = plateCapability(COMPLET).detectHint;

    expect(hint).toContain("une image sur trois");
    expect(hint).toContain("reprojetée");
  });

  it("dit que le texte est voté, pas lu sur une image", () => {
    // C'est l'invariant 4 : sans lui, deux relectures du même clip donneraient deux
    // plaques, et l'utilisateur ne saurait pas laquelle croire.
    expect(plateCapability(COMPLET).readHint).toContain("vote sur toute la vie");
  });
});
