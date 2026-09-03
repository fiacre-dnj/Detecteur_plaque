/**
 * La capture d'un véhicule, en grand : lui au-dessus, sa plaque en dessous.
 *
 * **Dans `shared/ui/` parce que deux features l'ouvrent** — le registre depuis sa
 * colonne, les alertes depuis une plaque recherchée — et qu'une feature n'importe
 * jamais une autre feature.
 *
 * Le patron du dialogue est celui de `LaunchDialog` et `PresetDialog`, recopié sans
 * rien inventer : un `<dialog>` natif ouvert par `showModal()`, qui fournit
 * gratuitement le piégeage du focus, l'inertie du fond et Échap. Aucun code de
 * gestion du focus ici, et c'est voulu.
 *
 * **Deux images et non une composée.** La mise en page vit ici, en CSS ; le serveur
 * stocke deux fichiers. C'est ce qui permet de montrer la plaque seule ailleurs, et
 * d'éviter que la table charge une image dont elle n'afficherait qu'un tiers.
 */

import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

import { Button } from "@/shared/ui/Button";
import { SnapshotFrame } from "@/shared/ui/SnapshotFrame";

interface SnapshotDialogProps {
  open: boolean;
  onClose: () => void;
  /** Ce qu'on regarde : « Voiture #34 ». Sert aussi de nom au dialogue. */
  title: string;
  /** Sous le titre : l'instant de la capture, la confiance de lecture. */
  subtitle?: string | undefined;
  vehicleSrc: string;
  /**
   * La vignette de plaque, ou rien — **il n'y avait aucune plaque à recadrer**.
   *
   * C'est le cas d'une photo retenue pour la ressemblance du véhicule (ADR 0051).
   * Absente, la modale l'explique au lieu d'afficher le repère d'échec : ici rien ne
   * manque, et un pictogramme d'erreur pour un état normal est exactement ce que le
   * repère muet existe pour éviter.
   */
  plateSrc?: string | null | undefined;
  /** Le texte lu, affiché sous la plaque — c'est ce qu'on vient vérifier. */
  plateText?: string | null | undefined;
  /**
   * Le texte **recherché**, quand la modale est ouverte depuis une alerte.
   *
   * Affiché sous le texte lu, et c'est là que l'opérateur tranche : la vignette de
   * plaque est la seule chose capable de départager une correspondance probable
   * d'une erreur de lecture.
   */
  watched?: string | null | undefined;
  onPrevious?: (() => void) | undefined;
  onNext?: (() => void) | undefined;
}

export function SnapshotDialog(props: SnapshotDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null);

  // `showModal()` et non l'attribut `open` : seul l'appel impératif active le
  // piégeage du focus et l'inertie du fond.
  useEffect(() => {
    const element = dialog.current;
    if (element === null) return;
    if (props.open && !element.open) element.showModal();
    if (!props.open && element.open) element.close();
  }, [props.open]);

  const { onPrevious, onNext } = props;
  // Les flèches naviguent, parce que comparer deux captures est le geste que cette
  // modale existe pour permettre — et rouvrir le tableau entre chacune le tuerait.
  // Sur le `<dialog>` et non sur le document : un écouteur global survivrait à sa
  // fermeture, et la modale est de toute façon la seule chose interactive à l'écran.
  useEffect(() => {
    const element = dialog.current;
    if (element === null || !props.open) return undefined;
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "ArrowLeft") onPrevious?.();
      if (event.key === "ArrowRight") onNext?.();
    };
    element.addEventListener("keydown", onKey);
    return () => element.removeEventListener("keydown", onKey);
  }, [props.open, onPrevious, onNext]);

  return (
    <dialog
      ref={dialog}
      aria-labelledby="snapshot-title"
      onClose={props.onClose}
      // Le clic sur le fond ferme, comme partout ailleurs. La cible est le
      // `<dialog>` lui-même : un clic dans le contenu a pour cible un enfant.
      onClick={(event) => {
        if (event.target === dialog.current) props.onClose();
      }}
      className="w-[min(40rem,92vw)] rounded-section bg-surface p-0 text-ink shadow-dialog backdrop:bg-base/70"
    >
      <div className="space-y-3 p-5">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 id="snapshot-title" className="text-body font-semibold">
              {props.title}
            </h2>
            {props.subtitle !== undefined && (
              <p className="text-small text-ink-dim">{props.subtitle}</p>
            )}
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

        {/* Le véhicule d'abord : c'est lui qu'on identifie. Une hauteur **maximale**
            plutôt que fixe — une camionnette et une berline n'ont pas le même format,
            et le même cadre rognerait l'une ou étirerait l'autre. */}
        <SnapshotFrame src={props.vehicleSrc} alt={`Photo du véhicule — ${props.title}`} tall />

        {/* La plaque en dessous, plus basse et pleine largeur : c'est sa forme. */}
        {props.plateSrc != null ? (
          <SnapshotFrame src={props.plateSrc} alt={`Plaque du véhicule — ${props.title}`} />
        ) : (
          <p className="rounded-card bg-surface-2 p-3 text-center text-micro text-ink-dim">
            Aucune vignette de plaque — cette photo a été retenue pour la ressemblance du
            véhicule.
          </p>
        )}

        {(props.plateText != null || props.watched != null) && (
          <div className="rounded-card bg-surface-2 p-3">
            {props.plateText != null && (
              <p className="text-body font-bold text-ink tabular">{props.plateText}</p>
            )}
            {props.watched != null && (
              <p className="text-small text-ink-dim">
                Recherchée : <span className="text-ink-muted tabular">{props.watched}</span>
              </p>
            )}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-line pt-4">
          {(onPrevious !== undefined || onNext !== undefined) && (
            <div className="me-auto flex items-center gap-1">
              <NavButton label="Capture précédente" onClick={onPrevious}>
                <ChevronLeft aria-hidden="true" className="size-4" />
              </NavButton>
              <NavButton label="Capture suivante" onClick={onNext}>
                <ChevronRight aria-hidden="true" className="size-4" />
              </NavButton>
            </div>
          )}
          <Button variant="ghost" size="sm" onClick={props.onClose}>
            Fermer
          </Button>
        </div>
      </div>
    </dialog>
  );
}

function NavButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: (() => void) | undefined;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={onClick === undefined}
      aria-label={label}
      title={label}
      className="grid size-8 place-items-center rounded-input bg-surface-2 text-ink-muted transition-colors hover:bg-elevated hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}
