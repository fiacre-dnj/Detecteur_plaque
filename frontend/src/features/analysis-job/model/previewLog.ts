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
 */
export function appendCrossings(
  log: readonly CrossingEvent[],
  incoming: readonly CrossingEvent[],
  limit: number = LOG_LIMIT,
): readonly CrossingEvent[] {
  if (incoming.length === 0) return log;
  // Les entrants sont eux-mêmes dans l'ordre chronologique : les renverser avant
  // de les empiler garde le plus récent tout en haut, y compris à l'intérieur
  // d'un même aperçu qui en porte plusieurs.
  return [...[...incoming].reverse(), ...log].slice(0, limit);
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
