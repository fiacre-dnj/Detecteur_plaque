/**
 * Le sélecteur de modèles : groupes à entêtes **collantes**, clavier **à plat**.
 *
 * Le patron d'accessibilité est `listbox` / `option`, avec une seule case tabulable
 * (`tabIndex` 0 sur l'option active, -1 sur les autres). C'est le patron ARIA des
 * listes de sélection : sans lui, la tabulation traverse vingt éléments avant de
 * sortir du composant, et l'utilisateur au clavier abandonne.
 *
 * Les entêtes sont `aria-hidden` : elles servent l'œil, pas le lecteur d'écran, qui
 * reçoit le palier dans le texte de chaque option. Les annoncer deux fois
 * alourdirait la lecture sans rien ajouter.
 */

import { Check, Download, HardDrive } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { preloadModel } from "@/entities/model";
import type { VehicleModel } from "@/shared/api/contracts";

import {
  flatOrder,
  groupByTier,
  modelSizeLabel,
  modelStateLabel,
  nextIndex,
  shouldPreload,
} from "../model/grouping";

interface ModelPickerProps {
  models: readonly VehicleModel[];
  selectedId: string;
  disabled?: boolean;
  /**
   * Peut-on précharger un modèle absent au moment où on le choisit ?
   *
   * Faux pendant qu'un job tourne : le préchargement prend un bail sur le modèle,
   * et il attendrait donc la fin de l'analyse en cours — une attente que rien à
   * l'écran n'expliquerait.
   */
  canPreload?: boolean;
  onSelect: (modelId: string) => void;
}

export function ModelPicker({
  models,
  selectedId,
  disabled = false,
  canPreload = false,
  onSelect,
}: ModelPickerProps) {
  const groups = useMemo(() => groupByTier(models), [models]);
  const flat = useMemo(() => flatOrder(groups), [groups]);

  /**
   * Option **active** au clavier, distincte de l'option **sélectionnée**.
   *
   * La distinction est celle du patron ARIA : on peut parcourir la liste sans
   * changer la sélection, et ne valider qu'avec Entrée ou Espace. Les confondre
   * lancerait un préchargement à chaque flèche.
   */
  const [activeIndex, setActiveIndex] = useState(() =>
    Math.max(0, flat.findIndex((entry) => entry.id === selectedId)),
  );

  const listRef = useRef<HTMLDivElement>(null);

  // La sélection peut changer de l'extérieur (chargement d'un preset, relance d'un
  // job de l'historique) : l'option active doit suivre, sinon le clavier repart
  // d'un endroit qui n'a plus de rapport avec ce qui est coché.
  useEffect(() => {
    const index = flat.findIndex((entry) => entry.id === selectedId);
    if (index >= 0) setActiveIndex(index);
  }, [selectedId, flat]);

  /**
   * Choisit un modèle, **et déclenche son téléchargement s'il manque**.
   *
   * Appelé depuis le clic et depuis Entrée/Espace — c'est-à-dire depuis les deux
   * gestes qui *choisissent*, et **jamais** depuis la navigation aux flèches. La
   * distinction est celle que la docstring de l'option active pose déjà : les
   * confondre lancerait un préchargement à chaque flèche, donc vingt
   * téléchargements pour un parcours de la liste.
   *
   * Le résultat n'est pas attendu et l'échec est **ignoré** : ce préchargement est
   * une avance de confort, pas une condition de la sélection. S'il échoue, le
   * serveur refusera proprement au lancement, avec le message et le bouton de
   * reprise que porte le Studio — le dire deux fois n'aiderait personne.
   */
  const select = useCallback(
    (model: VehicleModel) => {
      onSelect(model.id);
      if (shouldPreload(model, canPreload)) {
        void preloadModel(model.id).catch(() => undefined);
      }
    },
    [onSelect, canPreload],
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (disabled) return;

      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        const target = flat[activeIndex];
        if (target !== undefined) select(target);
        return;
      }

      // **La navigation est à plat** : `flat` ignore les frontières de groupe, qui
      // sont purement visuelles.
      // **La navigation ne choisit pas** : elle déplace l'option active, et rien
      // d'autre. Aucun `select` ici — donc aucun préchargement à la flèche.
      const next = nextIndex(event.key, activeIndex, flat.length);
      if (next === null) return;
      event.preventDefault();
      setActiveIndex(next);

      // Le défilement suit l'option active, sinon la navigation clavier sort de la
      // zone visible et l'utilisateur ne voit plus où il en est.
      const option = listRef.current?.querySelector(`[data-index="${next}"]`);
      option?.scrollIntoView({ block: "nearest" });
    },
    [disabled, flat, activeIndex, select],
  );

  if (models.length === 0) {
    return (
      <p className="text-small text-ink-dim">
        Le catalogue est indisponible : le serveur ne répond pas.
      </p>
    );
  }

  return (
    <div
      ref={listRef}
      role="listbox"
      aria-label="Modèle de détection"
      aria-disabled={disabled || undefined}
      onKeyDown={handleKeyDown}
      className="max-h-64 overflow-y-auto rounded-input bg-base"
    >
      {groups.map((group) => (
        <div key={group.tier}>
          {/* Entête **collante** : dans une liste de vingt modèles, savoir dans
              quel palier on se trouve sans remonter est ce qui rend le défilement
              utilisable. `aria-hidden` car le palier est déjà dans chaque option. */}
          <p
            aria-hidden="true"
            className="sticky top-0 z-10 bg-base/95 px-2 py-1 text-micro font-semibold uppercase tracking-wider text-ink-dim backdrop-blur"
          >
            {group.label}
          </p>

          {group.models.map((entry) => {
            const index = flat.indexOf(entry);
            const selected = entry.id === selectedId;
            const active = index === activeIndex;

            return (
              <div
                key={entry.id}
                role="option"
                data-index={index}
                aria-selected={selected}
                // Une seule case tabulable : sans cela, la tabulation traverse les
                // vingt options avant de sortir du composant.
                tabIndex={active ? 0 : -1}
                onClick={() => !disabled && select(entry)}
                onFocus={() => setActiveIndex(index)}
                className={[
                  "flex cursor-pointer items-start gap-2 px-2 py-1.5 transition-colors",
                  selected ? "bg-elevated" : "hover:bg-surface-2",
                  active ? "ring-1 ring-inset ring-accent/60" : "",
                  disabled ? "cursor-not-allowed opacity-60" : "",
                ].join(" ")}
              >
                <span className="mt-0.5 size-3.5 shrink-0">
                  {selected && <Check aria-hidden="true" className="size-3.5 text-accent" />}
                </span>

                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5">
                    <span className="text-small font-bold text-ink">{entry.label}</span>
                    <span className="text-micro text-ink-dim tabular">
                      {modelSizeLabel(entry)}
                    </span>
                    {/* L'état passe par une **icône plus un texte** : la couleur
                        seule ne suffit pas (daltonisme, et l'accent est réservé).
                        Le `title` va sur le `span` — les icônes lucide ne le
                        prennent pas, et un `<title>` SVG serait de toute façon
                        annoncé alors que l'état est déjà dans le texte. */}
                    {entry.loaded ? (
                      <span title="Résident en mémoire">
                        <HardDrive aria-hidden="true" className="size-3 text-ink-muted" />
                      </span>
                    ) : entry.downloaded ? (
                      <span title="Téléchargé sur le serveur">
                        <Download aria-hidden="true" className="size-3 text-ink-dim" />
                      </span>
                    ) : null}
                  </span>
                  {entry.note !== "" && (
                    <span className="block text-micro text-ink-muted">{entry.note}</span>
                  )}
                  <span className="block text-micro text-ink-dim">{modelStateLabel(entry)}</span>
                </span>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
