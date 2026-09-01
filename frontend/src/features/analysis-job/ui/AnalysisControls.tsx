/**
 * Lancer, suspendre, reprendre, annuler — dans la barre, à côté de l'import.
 *
 * Ces commandes vivaient à **deux** endroits qu'on ne voit pas d'un même coup d'œil :
 * « Lancer l'analyse » tout en bas du lecteur, « Suspendre » et « Annuler » dans un
 * bloc sous la vidéo qui n'apparaît qu'une fois l'analyse partie. Piloter une analyse
 * demandait donc de chercher le bouton suivant ailleurs que là où on venait de
 * cliquer. Elles sont désormais **une seule pilule ou deux**, toujours au même endroit,
 * juste après le bouton d'import.
 *
 * Trois points qui ne se devinent pas :
 *
 * - **la phase vient de `analysisProgress`, jamais d'une lecture directe du job.** Le
 *   bloc sous la vidéo lit la même fonction : deux surfaces qui décideraient
 *   séparément de ce qu'est « en cours » finiraient par proposer « Suspendre » sur une
 *   analyse déjà finie ;
 * - **« Annuler » n'apparaît pas pendant l'envoi** — le bouton d'import redevient
 *   disponible et refaire un choix de fichier est le geste naturel — mais il apparaît
 *   dès la préparation, où il y a un job côté serveur à arrêter ;
 * - **« Suspendre » n'existe que sur une analyse qui tourne.** En file d'attente il n'y
 *   a pas encore de thread à arrêter, et pendant la préparation le modèle est en train
 *   de se charger : suspendre ne rendrait pas la main plus tôt.
 *
 * **Ces quatre pilules ne se déplient pas au survol**, contrairement à toutes les
 * autres de la barre (`expandOnHover={false}`). Deux raisons, et la première suffit :
 * elles sont en **tête** de rangée, donc leur expansion pousserait tout ce qui suit —
 * y compris l'anneau de progression et les chiffres, qu'on est justement en train de
 * lire au moment où l'on hésite à suspendre. Et elles changent de nature en cours de
 * route : une pilule qui s'ouvre sous le curseur à l'instant où « Lancer » devient
 * « Suspendre » se lit comme un déplacement, pas comme une information.
 *
 * La teinte porte donc seule la nature de chaque commande : **bleu** pour lancer et
 * reprendre, `warning` pour suspendre — réversible, mais elle arrête quelque chose —,
 * `negative` pour annuler, qui perd les images déjà analysées.
 *
 * **Le bleu n'est pas un caprice** : le vert est déjà celui du bouton d'import, à
 * gauche immédiate. Deux pastilles vertes voisines se lisaient comme un seul groupe, et
 * « Lancer » passait pour une variante de « Changer de vidéo ». La source est verte, le
 * job est bleu.
 */

import { Pause, Play, X } from "lucide-react";

import { ToolbarButton } from "@/shared/ui/ToolbarButton";

import type { AnalysisProgress } from "../model/analysisProgress";

interface AnalysisControlsProps {
  progress: AnalysisProgress;
  /** Ouvre la modale de lancement — le choix de la portion à analyser. */
  onLaunch: () => void;
  /** `false` : pas de serveur, pas de source, ou pas de ligne tracée. */
  canLaunch: boolean;
  /** Pourquoi le lancement est impossible, ou ce qu'il fera. */
  launchHint: string;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
}

export function AnalysisControls({
  progress,
  onLaunch,
  canLaunch,
  launchHint,
  onPause,
  onResume,
  onCancel,
}: AnalysisControlsProps) {
  const { phase } = progress;

  // Rien ne tourne : une seule pilule, l'action principale de l'écran.
  if (phase === "idle") {
    return (
      <ToolbarButton
        label="Lancer l'analyse"
        icon={<Play className="size-4" />}
        expandOnHover={false}
        tone="primary"
        disabled={!canLaunch}
        // Le `title` de `ToolbarButton` porte le libellé ; ici il porte la **cause**
        // de l'indisponibilité, qui est la seule chose utile quand le bouton est
        // grisé. C'est la seule pilule de la barre dans ce cas.
        title={launchHint}
        onClick={onLaunch}
      />
    );
  }

  return (
    <>
      {phase === "running" && (
        <ToolbarButton
          label="Suspendre"
          icon={<Pause className="size-4" />}
          expandOnHover={false}
          tone="warning"
          title="Suspendre l'analyse — elle reprendra à cette image"
          onClick={onPause}
        />
      )}
      {phase === "paused" && (
        <ToolbarButton
          label="Reprendre"
          icon={<Play className="size-4" />}
          expandOnHover={false}
          tone="primary"
          title="Reprendre l'analyse là où elle s'est arrêtée"
          onClick={onResume}
        />
      )}
      {phase !== "upload" && (
        <ToolbarButton
          label="Annuler"
          icon={<X className="size-4" />}
          expandOnHover={false}
          tone="danger"
          title="Annuler l'analyse — les images déjà analysées sont perdues"
          onClick={onCancel}
        />
      )}
    </>
  );
}
