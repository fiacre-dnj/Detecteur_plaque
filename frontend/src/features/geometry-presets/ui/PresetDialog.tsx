/**
 * La modale des presets : enregistrer la géométrie courante, ou en charger une.
 *
 * `<dialog>` natif plutôt qu'une div en position fixe : il apporte gratuitement le
 * piégeage du focus, la fermeture par Échap et l'inertie du fond — trois
 * comportements qu'une réimplémentation rate presque toujours, et dont l'absence ne
 * se voit qu'au clavier ou au lecteur d'écran.
 *
 * **Chaque preset affiche s'il devra être adapté, avant qu'on clique.** C'est la
 * décision d'interface qui compte ici : prévenir après coup laisserait l'utilisateur
 * découvrir des lignes déplacées sans comprendre ce qui s'est passé.
 */

import { useEffect, useRef, useState } from "react";
import { Loader2, Save, Trash2 } from "lucide-react";

import type { CountingLine, Preset, Zone } from "@/shared/api/contracts";
import { Button } from "@/shared/ui/Button";

import { fetchPreset } from "../model/api";
import {
  aspectNotice,
  draftProblem,
  scalingNotice,
  toDraft,
} from "../model/notice";
import { useCreatePreset, useDeletePreset, usePresets } from "../model/usePresets";

interface PresetDialogProps {
  open: boolean;
  /** Dimensions de la vidéo courante. `null` tant que les métadonnées manquent. */
  scene: { width: number; height: number } | null;
  lines: readonly CountingLine[];
  zones: readonly Zone[];
  maskOutsideZones: boolean;
  onClose: () => void;
  /** Reçoit la géométrie **déjà mise à l'échelle** par le serveur. */
  onLoad: (preset: Preset) => void;
}

export function PresetDialog(props: PresetDialogProps) {
  const { open, scene, lines, zones } = props;
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);

  const presets = usePresets(open);
  const create = useCreatePreset();
  const remove = useDeletePreset();

  // `showModal()` et non l'attribut `open` : seul l'appel impératif active le
  // piégeage du focus et l'inertie du fond. L'attribut rend un dialogue non modal,
  // qu'on peut quitter au clavier sans le fermer.
  useEffect(() => {
    const element = dialog.current;
    if (element === null) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

  const width = scene?.width ?? 0;
  const height = scene?.height ?? 0;
  const problem = draftProblem(name, width, height, lines, zones);

  const save = async () => {
    if (problem !== null) return;
    setError(null);
    try {
      await create.mutateAsync(
        toDraft(name, description, width, height, props.maskOutsideZones, lines, zones),
      );
      setName("");
      setDescription("");
    } catch (cause) {
      // Le message du serveur, pas un texte générique : lui seul sait que le nom
      // est déjà pris, et c'est l'information qui permet d'agir.
      setError(cause instanceof Error ? cause.message : "L'enregistrement a échoué.");
    }
  };

  const load = async (preset: Preset) => {
    if (scene === null) return;
    setError(null);
    setLoadingId(preset.id);
    try {
      // **Relu du serveur avec les dimensions courantes**, jamais réutilisé depuis
      // la liste : celle-ci porte les coordonnées d'origine, et les charger telles
      // quelles placerait les lignes au mauvais endroit — sans aucune erreur.
      props.onLoad(await fetchPreset(preset.id, scene.width, scene.height));
      props.onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Le chargement a échoué.");
    } finally {
      setLoadingId(null);
    }
  };

  return (
    <dialog
      ref={dialog}
      aria-labelledby="presets-title"
      onClose={props.onClose}
      // Le clic sur le fond ferme, comme partout ailleurs. La cible est le
      // `<dialog>` lui-même : un clic dans le contenu a pour cible un enfant.
      onClick={(event) => {
        if (event.target === dialog.current) props.onClose();
      }}
      className="w-[min(34rem,92vw)] rounded-section bg-surface p-0 text-ink shadow-card backdrop:bg-base/70"
    >
      <div className="space-y-5 p-5">
        <h2 id="presets-title" className="text-body font-semibold">
          Presets de géométrie
        </h2>

        <section className="space-y-2">
          <h3 className="label-micro">Enregistrer la géométrie courante</h3>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={120}
            placeholder="Nom du preset"
            className="w-full rounded-input bg-elevated px-3 py-2 text-small text-ink placeholder:text-ink-dim"
          />
          <input
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={500}
            placeholder="Description (facultative)"
            className="w-full rounded-input bg-elevated px-3 py-2 text-small text-ink placeholder:text-ink-dim"
          />
          <div className="flex items-center gap-3">
            <Button
              variant="primary"
              disabled={problem !== null || create.isPending}
              onClick={() => void save()}
              // Le bouton grisé **dit pourquoi** : quatre causes, quatre actions.
              title={problem ?? "Enregistrer cette géométrie"}
            >
              <Save aria-hidden="true" className="size-4" />
              Enregistrer
            </Button>
            {scene !== null && (
              <span className="text-caption text-ink-dim tabular">
                {/* La résolution enregistrée, visible **avant** de valider : c'est
                    elle qui décidera de toute mise à l'échelle future. */}
                {width}×{height}
              </span>
            )}
          </div>
          {problem !== null && <p className="text-caption text-ink-dim">{problem}</p>}
        </section>

        <section className="space-y-2 border-t border-line pt-4">
          <h3 className="label-micro">Charger un preset</h3>

          {presets.isPending && <p className="text-caption text-ink-dim">Chargement…</p>}

          {presets.isError && (
            <p role="alert" className="text-caption text-negative">
              La liste des presets n'a pas pu être chargée.
            </p>
          )}

          {presets.data?.items.length === 0 && (
            // Un état vide qui dit quoi faire, pas un « aucun résultat » stérile.
            <p className="text-caption text-ink-dim">
              Aucun preset enregistré. Tracez une géométrie, puis enregistrez-la
              ci-dessus pour la réutiliser sur une autre vidéo.
            </p>
          )}

          <ul className="space-y-2">
            {presets.data?.items.map((preset) => {
              const notice = scene === null ? null : scalingNotice(preset, width, height);
              const aspect = scene === null ? null : aspectNotice(preset, width, height);
              return (
                <li
                  key={preset.id}
                  className="rounded-input bg-elevated p-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-small font-medium text-ink">{preset.name}</p>
                      <p className="text-micro text-ink-dim tabular">
                        {preset.lines.length} ligne{preset.lines.length > 1 ? "s" : ""} ·{" "}
                        {preset.zones.length} zone{preset.zones.length > 1 ? "s" : ""} ·{" "}
                        {preset.originalWidth}×{preset.originalHeight}
                      </p>
                      {preset.description !== "" && (
                        <p className="mt-1 text-micro text-ink-dim">{preset.description}</p>
                      )}
                    </div>
                    <div className="flex shrink-0 gap-1">
                      <Button
                        variant="ghost"
                        disabled={scene === null || loadingId !== null}
                        onClick={() => void load(preset)}
                        title={
                          scene === null
                            ? "Chargez d'abord une vidéo"
                            : "Charger cette géométrie"
                        }
                      >
                        {loadingId === preset.id ? (
                          <Loader2 aria-hidden="true" className="size-4 animate-spin" />
                        ) : (
                          "Charger"
                        )}
                      </Button>
                      <button
                        type="button"
                        onClick={() => remove.mutate(preset.id)}
                        title={`Supprimer « ${preset.name} »`}
                        className="rounded-input p-2 text-ink-dim transition-colors hover:bg-surface hover:text-negative"
                      >
                        <Trash2 aria-hidden="true" className="size-4" />
                        <span className="sr-only">Supprimer {preset.name}</span>
                      </button>
                    </div>
                  </div>

                  {/* Les avertissements **avant** le clic : prévenir après coup
                      laisserait découvrir des lignes déplacées sans comprendre. */}
                  {notice !== null && (
                    <p className="mt-2 text-micro text-ink-muted">{notice}</p>
                  )}
                  {aspect !== null && (
                    <p className="mt-1 text-micro text-warning">{aspect}</p>
                  )}
                </li>
              );
            })}
          </ul>
        </section>

        {error !== null && (
          <p role="alert" className="text-caption text-negative">
            {error}
          </p>
        )}

        <div className="flex justify-end border-t border-line pt-4">
          <Button variant="ghost" onClick={props.onClose}>
            Fermer
          </Button>
        </div>
      </div>
    </dialog>
  );
}
