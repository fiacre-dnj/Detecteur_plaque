/**
 * L'entête d'une colonne du studio — « Résultats », « Alertes ».
 *
 * Elle vit dans `shared` et non dans l'une des deux features parce que c'est
 * exactement le genre de chose qui dérive : les deux colonnes sont côte à côte, à
 * la même hauteur, et un demi-pixel d'écart de graisse ou d'interligne entre leurs
 * titres se voit immédiatement — alors qu'aucune des deux features n'a le droit
 * d'importer l'autre.
 *
 * Trois points qui ne se devinent pas :
 *
 * - **elle est collante, et c'est le titre qui sert de repère.** Chaque colonne a
 *   son propre défilement borné à la hauteur de la fenêtre ; sans entête collée, on
 *   se retrouve à lire des cartes sans savoir de quelle colonne elles viennent ;
 * - **le repère « en cours » est un point, sans un mot.** L'accent du projet est
 *   réservé à ce qui vit (lecture, serveur prêt, action primaire) : ici il dit que
 *   les chiffres et les cartes en dessous arrivent du serveur **à cet instant**, ce
 *   qui distingue une lecture en cours d'un résultat relu. Il a porté le texte « en
 *   direct » pendant quelques heures : deux mots par colonne, sur deux colonnes
 *   côte à côte, pour une information que le point suffit à donner — et ils
 *   volaient la place du compteur dans une entête de 20 rem. Le mot survit en
 *   `sr-only`, parce qu'un point n'existe pas pour un lecteur d'écran ;
 * - **aucune région `aria-live` ici.** Le repère pulse pour l'œil ; ce qui est
 *   annoncé, c'est le compteur que l'appelant pose en `trailing`, et lui seul — une
 *   entête qui parle à chaque changement ferait d'un lecteur d'écran un métronome.
 */

import type { ReactNode } from "react";

interface PanelHeadingProps {
  /** Cible de l'`aria-labelledby` de la section. */
  id: string;
  title: string;
  /** L'analyse tourne-t-elle ? Affiche le point d'activité (sans texte). */
  live?: boolean;
  /** Posé à l'extrémité de la rangée : un compteur, un filtre. */
  trailing?: ReactNode;
}

export function PanelHeading({ id, title, live = false, trailing }: PanelHeadingProps) {
  return (
    <div className="flex min-h-6 items-center gap-2">
      <h3 id={id} className="label-micro">
        {title}
      </h3>
      {live && (
        <span
          title="Analyse en cours"
          className="inline-flex shrink-0 items-center text-micro text-accent"
        >
          <span
            aria-hidden="true"
            className="size-1.5 rounded-pill bg-accent motion-safe:animate-pulse"
          />
          <span className="sr-only">analyse en cours</span>
        </span>
      )}
      {trailing !== undefined && (
        <div className="ms-auto flex min-w-0 items-center">{trailing}</div>
      )}
    </div>
  );
}
