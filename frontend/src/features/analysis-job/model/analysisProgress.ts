/**
 * Où en est l'analyse — une phase, un pourcentage, une phrase.
 *
 * Deux surfaces décrivent le même job : l'anneau de la barre du studio et le bloc sous
 * la vidéo. Elles ne peuvent pas le calculer chacune de leur côté — deux pourcentages
 * du même job sur le même écran est le genre d'écart qu'on ne remarque qu'une fois
 * qu'il a fait douter de tout le reste. La règle du dépôt s'applique en plus : sans
 * test de composant, **ce qui doit être vérifié doit être une fonction pure**.
 *
 * Cette fonction porte les quatre distinctions que la barre de progression a payées :
 *
 * - **l'envoi et l'analyse sont deux phases**, jamais une barre unique. Sur une vidéo
 *   de 800 Mo, l'envoi prend des minutes ; une barre commune retomberait ensuite à
 *   zéro, et une barre qui retombe à zéro se lit comme un échec — on recommence ;
 * - **aucune phase sans image lue n'affiche de compteur.** « 0 / 0 images · 0.0 img/s »
 *   se lit exactement comme une analyse plantée, et il y a **deux** moments où ce
 *   serait faux : le chargement du modèle, et l'attente d'une place sur le serveur.
 *   Le second n'avait pas été prévu et s'est vu à l'usage — un job suspendu garde sa
 *   place, donc le suivant peut rester en file un long moment, à « 0 / 0 » ;
 * - **la cadence n'est plus donnée ici du tout.** Elle y a figuré, libellée
 *   « (serveur) » pour la distinguer de la cadence de *lecture* de la vidéo — deux
 *   cadences sans étiquette sur le même écran se confondent immanquablement. Mais la
 *   rangée de chiffres qui suit l'anneau porte déjà « Cadence serveur », avec son
 *   libellé : la répéter dans le détail était un doublon, et le doublon le plus cher
 *   qui soit puisqu'il occupait la largeur d'une barre qui doit tenir sur une ligne.
 *   Le détail ne garde donc que ce que rien d'autre ne dit : **où en est le compte
 *   d'images** ;
 * - **un job terminal ne rend plus de progression.** Une analyse finie, annulée ou en
 *   échec n'a pas de « 100 % » à afficher : elle a un résultat, ou une erreur.
 */

import type { Job } from "@/shared/api/contracts";
import { isTerminal } from "@/shared/api/contracts";

import { formatBytes, type UploadProgress } from "./uploadJob";

export type AnalysisPhase =
  /** Rien en cours : avant un lancement, ou après un statut terminal. */
  | "idle"
  /** Le fichier monte vers le serveur. Le job n'existe pas encore. */
  | "upload"
  /** Le serveur charge le modèle — souvent en le téléchargeant. */
  | "preparing"
  /** Le job existe côté serveur mais attend son tour : rien n'est encore analysé. */
  | "queued"
  /** Des images sont analysées. */
  | "running"
  /** Suspendue à la demande : elle garde sa place et son bail de modèle. */
  | "paused";

export interface AnalysisProgress {
  phase: AnalysisPhase;
  /** De 0 à 1. Vaut `0` sur `idle`, où il ne doit pas être affiché. */
  ratio: number;
  /** Le nom de la phase, tel qu'il s'affiche — « Analyse en cours », « Envoi »… */
  label: string;
  /**
   * La ligne de détail, ou `null` quand il n'y a rien d'honnête à dire.
   *
   * `null` en `preparing` **pour le compteur d'images** : c'est `hint` qui porte alors
   * la cause de l'attente.
   */
  detail: string | null;
  /** Une phrase d'explication, quand la phase en demande une. */
  hint: string | null;
  /** `true` dès qu'il y a quelque chose à montrer — c'est-à-dire hors `idle`. */
  active: boolean;
}

const IDLE: AnalysisProgress = {
  phase: "idle",
  ratio: 0,
  label: "",
  detail: null,
  hint: null,
  active: false,
};

/**
 * @param upload progression de l'envoi, `null` dès qu'il est fini ou qu'il n'a pas lieu
 * @param job le job suivi, `null` tant que le serveur n'en a pas rendu
 * @param modelLabel nom lisible du modèle, pour nommer ce qui se charge
 */
export function analysisProgress(
  upload: UploadProgress | null,
  job: Job | null,
  modelLabel?: string | undefined,
): AnalysisProgress {
  // **L'envoi d'abord, et seulement tant qu'aucun job n'existe.** Le `job === null`
  // n'est pas redondant avec `ratio < 1` : le serveur peut rendre le job avant que le
  // dernier morceau soit acquitté, et on afficherait alors « Envoi 99 % » au-dessus
  // d'une analyse qui a déjà commencé.
  if (upload !== null && upload.ratio < 1 && job === null) {
    return {
      phase: "upload",
      ratio: upload.ratio,
      label: "Envoi de la vidéo",
      detail: `${formatBytes(upload.loaded)} sur ${formatBytes(upload.total)}`,
      hint: null,
      active: true,
    };
  }

  if (job === null) {
    // Le fichier est parti, le serveur n'a pas encore rendu de job. Ce n'est pas
    // `idle` : quelque chose est en cours, et une barre qui disparaîtrait ici se
    // lirait comme un abandon.
    return upload === null
      ? IDLE
      : {
          phase: "preparing",
          ratio: 0,
          label: "Préparation",
          detail: null,
          hint: "En attente du serveur…",
          active: true,
        };
  }

  if (isTerminal(job.status)) return IDLE;

  if (job.preparing === true) {
    return {
      phase: "preparing",
      ratio: job.progress,
      label: "Préparation",
      detail: null,
      hint: `Chargement du modèle ${modelLabel ?? job.modelId} — premier usage, téléchargement possible.`,
      active: true,
    };
  }

  // **La file d'attente est une phase, pas une variante d'« en cours ».** Elle l'a
  // été, et deux choses en dépendaient sans qu'on le voie : « Suspendre » était
  // proposé sur un job qui n'a pas encore de thread à arrêter, et le bloc explicatif
  // sous la vidéo restait masqué au moment précis où il aurait servi. Un serveur qui
  // n'exécute qu'une analyse à la fois rend ce cas fréquent — une analyse **suspendue**
  // garde sa place, donc la suivante peut attendre longtemps.
  if (job.status === "queued") {
    return {
      phase: "queued",
      ratio: job.progress,
      label: "En file d'attente",
      detail: null,
      hint: "En attente d'une place sur le serveur — une analyse déjà lancée, ou suspendue, en occupe une.",
      active: true,
    };
  }

  // **Aucun compteur tant qu'aucune image n'a été lue.** `totalFrames` vaut zéro
  // jusqu'à ce que le serveur ait sondé la vidéo, ce qui couvre les tout premiers
  // instants d'une analyse : « 0 / 0 images · 0.0 img/s » s'y lirait comme une analyse
  // plantée.
  if (job.totalFrames === 0) {
    return {
      phase: "running",
      ratio: job.progress,
      label: "Analyse en cours",
      detail: null,
      hint: "Le serveur ouvre la vidéo…",
      active: true,
    };
  }

  const frames = `${job.processedFrames} / ${job.totalFrames} images`;

  if (job.status === "paused") {
    return {
      phase: "paused",
      ratio: job.progress,
      label: "Analyse suspendue",
      detail: `suspendue à ${frames}`,
      hint: "L'analyse reprendra à cette image, avec les mêmes identités. Elle garde sa place sur le serveur pendant ce temps.",
      active: true,
    };
  }

  return {
    phase: "running",
    ratio: job.progress,
    label: "Analyse en cours",
    detail: frames,
    hint: null,
    active: true,
  };
}
