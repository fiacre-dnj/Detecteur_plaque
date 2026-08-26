/**
 * Le journal des franchissements observés pendant une analyse.
 *
 * Pourquoi un journal en plus des compteurs : un total ne se vérifie pas. « 47
 * franchissements » est un chiffre qu'on croit ou qu'on ne croit pas. « 00:12.4 —
 * car #7 · Voie nord · sens + », lu au moment où la voiture passe la ligne à
 * l'écran, est un chiffre qu'on **vérifie**. C'est toute la différence entre une
 * analyse qu'on livre et une analyse qu'on valide.
 *
 * Le journal est borné. Une analyse d'une heure produit des milliers d'entrées, et
 * personne ne défile jusqu'à la première : garder tout ferait grossir la mémoire du
 * navigateur pour une information que l'interface n'affiche jamais.
 *
 * **Le journal et le registre peuvent afficher deux plaques différentes pour le même
 * véhicule, et c'est légitime.** Côté serveur, un franchissement est émis *avant* la
 * passe OCR de la même image : il porte donc ce que le serveur savait au moment de
 * compter, souvent rien. Le registre, lui, agrège toute la vie du véhicule.
 * **L'autorité est le registre** (ADR 0007).
 */

import type { CrossingEvent } from "@/shared/api/contracts";

/** Entrées conservées. Au-delà, les plus anciennes sont oubliées. */
export const LOG_LIMIT = 200;

/**
 * Ajoute des franchissements au journal, **le plus récent en tête**.
 *
 * L'ordre d'affichage est celui du journal : ce qui vient de se passer doit être
 * en haut, sinon il faut défiler pour voir l'événement qu'on attendait — et c'est
 * précisément l'événement qu'on regardait la vidéo pour voir.
 *
 * **Insertion triée, plus empilement**, depuis qu'un franchissement porte la date
 * de son intersection avec le trait (ADR 0038). La bande morte a une épaisseur
 * proportionnelle à la boîte du véhicule : un poids lourd la traverse bien plus
 * lentement qu'une moto, donc deux passages peuvent arriver dans **deux trames SSE
 * différentes** en ordre inverse de leurs dates. Le serveur trie à l'intérieur
 * d'une trame ; le désordre entre trames se referme ici, et nulle part ailleurs.
 *
 * Ce n'est pas une question de présentation : `describeCrossings` en dérive
 * `gapMs`, le numéro de passage, et surtout `previous` — qui relie une sortie à
 * l'entrée du **même** véhicule pour donner le temps de traversée du carrefour.
 * Sur un journal désordonné, cette durée devient négative.
 *
 * Le coût est borné par `limit` (200 entrées) : au pire 200 comparaisons par
 * trame, soit une insertion linéaire sur une liste que l'écran affiche déjà en
 * entier. Un tri complet serait plus lisible et plus cher pour rien.
 */
export function appendCrossings(
  log: readonly CrossingEvent[],
  incoming: readonly CrossingEvent[],
  limit: number = LOG_LIMIT,
): readonly CrossingEvent[] {
  if (incoming.length === 0) return log;
  const merged = [...log];
  for (const event of incoming) {
    // Première position dont l'instant n'est **pas plus récent** : à date égale
    // l'entrant passe devant, ce qui reproduit exactement l'empilement d'avant
    // (`[...incoming].reverse()`) et garde le dernier arrivé en tête.
    let at = merged.findIndex((seen) => seen.timestampMs <= event.timestampMs);
    if (at < 0) at = merged.length;
    merged.splice(at, 0, event);
  }
  return merged.slice(0, limit);
}

/**
 * Horodatage de **scène** au format `mm:ss.d`.
 *
 * Dixièmes de seconde et non centièmes : à 25 images par seconde, le dixième
 * suffit à situer l'événement sur la vidéo, et deux décimales donneraient une
 * fausse impression de précision.
 */
export function formatSceneTime(timestampMs: number): string {
  const total = Math.max(0, timestampMs) / 1000;
  const minutes = Math.floor(total / 60);
  const seconds = Math.floor(total % 60);
  const tenths = Math.floor((total * 10) % 10);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${tenths}`;
}

/*
 * `directionLabel` (« sens + » / « sens − ») et `lineLabel` vivaient ici et sont
 * **supprimés**, pas masqués.
 *
 * Le premier affichait le contrat machine à un humain qui regarde un carrefour : la
 * chronologie nomme désormais le **rôle** du sens — « Entrée », « Sortie » — que
 * `shared/lib/directions.ts` lit sur le tracé courant. Le second dupliquait le repli
 * « nom, sinon identifiant » de `lineName` du même module, et obligeait l'appelant à
 * bâtir une table de noms qui perdait la couleur et les rôles de la ligne.
 */
