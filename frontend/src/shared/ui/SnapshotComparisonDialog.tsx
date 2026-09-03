/**
 * Deux véhicules côte à côte — « est-ce bien le même ? ».
 *
 * La contrepartie indispensable de la re-détection (ADR 0055) : l'écran affirme
 * « ce véhicule ressemble au #12 à 87 % », et cette modale est le seul endroit où
 * l'affirmation devient **vérifiable**. Sans elle, comparer deux captures demandait
 * d'ouvrir la première, la fermer, retrouver la seconde rangée, l'ouvrir — c'est-à-dire
 * de comparer deux images de mémoire, ce que l'œil fait très mal.
 *
 * **Séparée de `SnapshotDialog` et non un mode de plus.** Les deux dialogues n'ont
 * en commun que leur enveloppe : l'un montre une capture et sa plaque empilées,
 * l'autre deux véhicules en colonnes. Les fondre demanderait un drapeau qui
 * changerait la disposition entière, ce qui est la définition d'un second composant.
 * Ce qui *est* partagé — le cadre d'image et son repli « purgée » — l'est pour de
 * vrai, par `SnapshotFrame`.
 *
 * Le patron du dialogue reste celui de `SnapshotDialog`, `LaunchDialog` et
 * `PresetDialog`, recopié sans rien inventer : un `<dialog>` natif ouvert par
 * `showModal()`, qui fournit gratuitement le piégeage du focus, l'inertie du fond et
 * Échap.
 */

import { X } from "lucide-react";
import { useEffect, useRef } from "react";

import { Button } from "@/shared/ui/Button";
import { SnapshotFrame } from "@/shared/ui/SnapshotFrame";

/** Un des deux véhicules comparés, réduit à ce que la modale montre. */
export interface ComparisonSide {
  /** « Voiture #12 ». Sert aussi d'`alt` aux images. */
  title: string;
  /** L'instant de la capture, en une ligne. */
  subtitle?: string | undefined;
  vehicleSrc: string;
  /**
   * La vignette de plaque, ou rien — il n'y avait aucune plaque à recadrer.
   *
   * Rien plutôt qu'une phrase d'explication, contrairement à `SnapshotDialog` : ici
   * elle apparaîtrait **deux fois**, dans deux colonnes étroites, pour dire une
   * absence que le vide dit déjà. La modale de capture, elle, n'a que ce texte à
   * mettre à cet endroit.
   */
  plateSrc?: string | null | undefined;
  /** Le texte lu. Deux plaques différentes tranchent la question à elles seules. */
  plateText?: string | null | undefined;
}

interface SnapshotComparisonDialogProps {
  open: boolean;
  onClose: () => void;
  /** Ce que la modale demande, en une phrase. */
  title: string;
  /**
   * Le véhicule vu **en premier**, à gauche.
   *
   * L'ordre est chronologique et non « celui qu'on a cliqué » : on lit de gauche à
   * droite, et « le même véhicule est repassé » se raconte dans ce sens. L'inverser
   * selon la rangée cliquée ferait changer la disposition d'une comparaison à
   * l'autre, alors que c'est précisément la stabilité qui permet de comparer.
   */
  earlier: ComparisonSide;
  /** Le véhicule courant, à droite. */
  later: ComparisonSide;
  /** La ressemblance mesurée, déjà formatée — « 87 % ». */
  score?: string | undefined;
}

export function SnapshotComparisonDialog(props: SnapshotComparisonDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null);

  // `showModal()` et non l'attribut `open` : seul l'appel impératif active le
  // piégeage du focus et l'inertie du fond.
  useEffect(() => {
    const element = dialog.current;
    if (element === null) return;
    if (props.open && !element.open) element.showModal();
    if (!props.open && element.open) element.close();
  }, [props.open]);

  return (
    <dialog
      ref={dialog}
      aria-labelledby="comparison-title"
      onClose={props.onClose}
      onClick={(event) => {
        if (event.target === dialog.current) props.onClose();
      }}
      // Plus large que `SnapshotDialog` : deux colonnes de véhicules à 40 rem
      // donneraient deux vignettes trop petites pour ce qu'on vient y chercher.
      className="w-[min(52rem,94vw)] rounded-section bg-surface p-0 text-ink shadow-dialog backdrop:bg-base/70"
    >
      <div className="space-y-3 p-5">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 id="comparison-title" className="text-body font-semibold">
              {props.title}
            </h2>
            {/* **Le doute est écrit, pas sous-entendu.** Les distributions de
                ressemblance se recouvrent largement (ADR 0048) : deux vues du même
                véhicule descendent à 0,387, deux véhicules différents montent à
                0,891. Un pourcentage seul, en gros, se lirait comme un verdict. */}
            <p className="text-small text-ink-dim">
              {props.score === undefined
                ? "Ressemblance mesurée sur l'apparence — c'est à vous de trancher."
                : `Ressemblance ${props.score} — une hypothèse, à confirmer sur les deux photos.`}
            </p>
          </div>
          <button
            type="button"
            onClick={props.onClose}
            aria-label="Fermer"
            className="grid size-7 shrink-0 place-items-center rounded-input text-ink-dim transition-colors hover:bg-elevated hover:text-ink"
          >
            <X aria-hidden="true" className="size-4" />
          </button>
        </div>

        {/* Côte à côte dès `sm`, empilées en dessous. Deux colonnes sur un écran
            étroit rendraient chaque véhicule plus petit que la vignette du tableau,
            ce qui retirerait à cette modale sa seule raison d'être. */}
        <div className="grid gap-3 sm:grid-cols-2">
          <Side side={props.earlier} />
          <Side side={props.later} />
        </div>

        <div className="flex items-center justify-end border-t border-line pt-4">
          <Button variant="ghost" size="sm" onClick={props.onClose}>
            Fermer
          </Button>
        </div>
      </div>
    </dialog>
  );
}

/**
 * Une colonne : le véhicule, sa plaque, son texte.
 *
 * L'en-tête est **au-dessus** de l'image et non en dessous : les deux colonnes n'ont
 * pas la même hauteur — une camionnette et une berline n'ont pas le même format, et
 * une plaque peut manquer d'un côté — donc un libellé posé sous l'image flotterait à
 * deux hauteurs différentes et ne se rattacherait plus à rien.
 */
function Side({ side }: { side: ComparisonSide }) {
  return (
    <div className="space-y-2">
      <div className="min-h-8">
        <p className="text-small font-semibold text-ink">{side.title}</p>
        {side.subtitle !== undefined && (
          <p className="text-micro text-ink-dim">{side.subtitle}</p>
        )}
      </div>
      <SnapshotFrame src={side.vehicleSrc} alt={`Photo du véhicule — ${side.title}`} tall />
      {side.plateSrc != null && (
        <SnapshotFrame src={side.plateSrc} alt={`Plaque du véhicule — ${side.title}`} />
      )}
      {/* La plaque lue tranche à elle seule quand les deux côtés en ont une : deux
          textes différents réfutent la ressemblance mieux que n'importe quel score. */}
      {side.plateText != null && (
        <p className="rounded-card bg-surface-2 p-2 text-center text-body font-bold text-ink tabular">
          {side.plateText}
        </p>
      )}
    </div>
  );
}
