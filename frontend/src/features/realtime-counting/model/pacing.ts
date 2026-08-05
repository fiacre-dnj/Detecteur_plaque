/**
 * La cadence d'envoi — **une frame en vol à la fois, les autres abandonnées**.
 *
 * La règle tient en une phrase et l'alternative naturelle est un piège. Mettre en
 * file les frames produites pendant qu'on attend une réponse paraît plus soigneux :
 * aucune image perdue. En réalité, si le serveur traite à 8 images/s ce que la caméra
 * produit à 30, la file grandit de 22 éléments par seconde **indéfiniment**. La
 * latence dérive sans jamais se rattraper : au bout d'une minute, l'aperçu commente
 * une scène vieille de vingt secondes, et l'utilisateur voit des boîtes sur des
 * véhicules partis depuis longtemps. Une file n'absorbe une pointe que si le débit
 * moyen le permet ; ici, il ne le permet par construction jamais.
 *
 * Abandonner, au contraire, autorégule : on envoie exactement au rythme où le serveur
 * répond, et l'aperçu reste au présent. Les comptages n'en souffrent pas — le serveur
 * horodate en temps de scène ce qu'il reçoit (invariant 1), et une frame sautée est
 * exactement ce que fait déjà `frameStride` en mode différé.
 *
 * Ce module est pur : pas de `WebSocket`, pas de `canvas`, pas de `requestAnimationFrame`.
 * C'est ce qui permet de tester la règle d'abandon par des assertions sur des nombres
 * plutôt que par un test qui dort et croise les doigts.
 */

/** Compteurs d'une session, tels que l'interface les affiche. */
export interface PacingStats {
  /** Frames dont le résultat est revenu. */
  sent: number;
  /** Frames abandonnées faute de créneau. Élevé ⇒ serveur saturé, et **c'est normal**. */
  dropped: number;
  /** Dernière latence aller-retour observée, en millisecondes. */
  latencyMs: number | null;
}

export const EMPTY_PACING: PacingStats = { sent: 0, dropped: 0, latencyMs: null };

/**
 * Le régulateur de cadence.
 *
 * Un objet mutable et non un état React : il est consulté et modifié à chaque
 * animation frame, et faire passer chaque décision par un `setState` provoquerait un
 * rendu par frame en plus de donner des valeurs périmées aux closures.
 */
export class FramePacer {
  private inFlight = false;
  private sentAt: number | null = null;
  private stats: PacingStats = EMPTY_PACING;

  /**
   * Réclame le créneau d'envoi.
   *
   * Rend `false` si une frame est déjà en vol — et **compte l'abandon**, parce
   * qu'un taux d'abandon invisible est un taux d'abandon qu'on n'explique pas quand
   * l'utilisateur trouve le direct « lent ».
   *
   * `now` est passé en paramètre et non lu de `performance.now()` : c'est la seule
   * façon de tester la latence sans dépendre de la vitesse de la machine — un test
   * dont le verdict dépend de l'horloge ne prouve rien.
   */
  tryClaim(now: number): boolean {
    if (this.inFlight) {
      this.stats = { ...this.stats, dropped: this.stats.dropped + 1 };
      return false;
    }
    this.inFlight = true;
    this.sentAt = now;
    return true;
  }

  /**
   * Le résultat est revenu : le créneau se libère et la latence est mesurée.
   *
   * **Ici l'horloge murale est légitime** : c'est une mesure de performance, pas un
   * horodatage métier. Le temps de scène des frames, lui, ne vient jamais d'ici.
   */
  complete(now: number): void {
    this.inFlight = false;
    const latency = this.sentAt === null ? null : Math.max(0, now - this.sentAt);
    this.sentAt = null;
    this.stats = {
      sent: this.stats.sent + 1,
      dropped: this.stats.dropped,
      latencyMs: latency,
    };
  }

  /**
   * Libère le créneau **sans** compter un envoi réussi.
   *
   * Pour la frame que le serveur a refusée par un message `error` non fatal, et pour
   * l'encodage qui a rendu `null`. Sans cette sortie, un seul échec laisserait
   * `inFlight` à `true` pour toujours : le direct se figerait définitivement, avec
   * une connexion ouverte et aucun message d'erreur — la panne la plus difficile à
   * diagnostiquer de ce module.
   */
  abandon(): void {
    this.inFlight = false;
    this.sentAt = null;
  }

  /** Une frame attend-elle sa réponse ? */
  get busy(): boolean {
    return this.inFlight;
  }

  snapshot(): PacingStats {
    return this.stats;
  }

  reset(): void {
    this.inFlight = false;
    this.sentAt = null;
    this.stats = EMPTY_PACING;
  }
}

/**
 * Temps de **scène** d'une frame du direct.
 *
 * Compté depuis le début de la session et non depuis l'époque Unix : le serveur
 * l'utilise pour des durées et des vitesses, et un horodatage absolu de 1,7 × 10¹²
 * ferait perdre la précision utile dans les flottants au premier calcul de delta.
 *
 * `startedAt` et `now` viennent tous deux de `performance.now()` — le seul usage
 * d'horloge murale que l'invariant 1 autorise pour du temps de scène, parce qu'un
 * flux caméra **n'a pas** d'index de frame : il n'y a pas de fichier à indexer, et
 * le temps écoulé est la seule origine disponible. Le serveur, lui, dérive son
 * `frameIndex` de ce que le client lui donne.
 */
export function sceneTimeMs(startedAt: number, now: number): number {
  return Math.max(0, now - startedAt);
}
