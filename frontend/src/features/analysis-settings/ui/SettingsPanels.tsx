/**
 * Les trois panneaux de réglages, et le **diagnostic live**.
 *
 * Le diagnostic n'est pas décoratif, et c'est la raison d'être de ce fichier :
 * « le compte est faux » n'est diagnosticable que si l'on peut voir **laquelle** des
 * quatre causes est en jeu — un véhicule manquant n'a jamais été détecté, l'a été
 * faiblement, n'était pas confirmé, ou a été masqué par une zone. Sans ces chiffres,
 * l'utilisateur ne peut que constater l'écart et perdre confiance ; avec eux, il sait
 * quel curseur bouger.
 *
 * Chaque réglage porte l'énoncé de son compromis. Un curseur sans explication est un
 * curseur qu'on ne touche pas — ou qu'on tourne à fond, ce qui est pire.
 */

import { ChevronDown } from "lucide-react";
import { useId, useState } from "react";

import { ModelPicker } from "@/features/model-picker";
import type { Diagnostics, VehicleModel } from "@/shared/api/contracts";

import { BOUNDS, DEFAULT_CONFIDENCE, type AnalysisSettings } from "../model/settings";

interface SettingsPanelsProps {
  settings: AnalysisSettings;
  models: readonly VehicleModel[];
  /** Faux quand le serveur signale le modèle de plaques absent. */
  plateAvailable: boolean;
  /** Vrai s'il existe au moins une zone : « ignorer hors zone » en dépend. */
  hasZones: boolean;
  /** Diagnostic de la dernière analyse, `null` avant. */
  diagnostics: Diagnostics | null;
  disabled: boolean;
  onChange: (patch: Partial<AnalysisSettings>) => void;
}

export function SettingsPanels({
  settings,
  models,
  plateAvailable,
  hasZones,
  diagnostics,
  disabled,
  onChange,
}: SettingsPanelsProps) {
  return (
    <>
      <Section title="Détection" defaultOpen>
        <ModelPicker
          models={models}
          selectedId={settings.modelId}
          disabled={disabled}
          onSelect={(modelId) => onChange({ modelId })}
        />

        <Slider
          label="Confiance véhicules"
          value={settings.confidenceThreshold ?? DEFAULT_CONFIDENCE}
          bounds={BOUNDS.confidenceThreshold}
          disabled={disabled}
          format={(value) => `${Math.round(value * 100)} %`}
          hint={
            settings.confidenceThreshold === null
              ? "Suit le défaut du modèle sélectionné."
              : "Valeur explicite : conservée au changement de modèle."
          }
          onChange={(confidenceThreshold) => onChange({ confidenceThreshold })}
          // **Le bouton « Défaut » est le chemin de retour.** Avant lui, c'était le
          // seul réglage sans réinitialisation : une fois touché, impossible de
          // revenir à « suivre le modèle ».
          onReset={
            settings.confidenceThreshold === null
              ? undefined
              : () => onChange({ confidenceThreshold: null })
          }
        />

        <Toggle
          label="Lire les plaques (ANPR)"
          checked={settings.detectPlates}
          disabled={disabled || !plateAvailable}
          hint={
            plateAvailable
              ? "Recadre chaque véhicule suivi et y cherche une plaque — nettement plus lent."
              : "Le modèle de plaques n'est pas installé sur ce serveur."
          }
          onChange={(detectPlates) => onChange({ detectPlates })}
        />

        {settings.detectPlates && (
          <Slider
            label="Confiance plaques"
            value={settings.plateConfidence ?? 0.25}
            bounds={BOUNDS.plateConfidence}
            disabled={disabled}
            format={(value) => `${Math.round(value * 100)} %`}
            onChange={(plateConfidence) => onChange({ plateConfidence })}
          />
        )}
      </Section>

      <Section title="Comptage">
        <Slider
          label="Images avant comptage"
          value={settings.minHits}
          bounds={BOUNDS.minHits}
          disabled={disabled}
          format={(value) => `${value} image${value > 1 ? "s" : ""}`}
          hint="Plus haut = moins de faux positifs, mais les véhicules rapides peuvent être manqués."
          onChange={(minHits) => onChange({ minHits })}
        />

        <Slider
          label="Survie d'une piste perdue"
          value={settings.maxLostMs}
          bounds={BOUNDS.maxLostMs}
          disabled={disabled}
          format={(value) => `${(value / 1000).toFixed(1)} s`}
          hint="Durée pendant laquelle une piste sans détection reste candidate à la ré-identification."
          onChange={(maxLostMs) => onChange({ maxLostMs })}
        />

        <Slider
          label="Similarité de ré-identification"
          value={settings.reidMinSimilarity}
          bounds={BOUNDS.reidMinSimilarity}
          disabled={disabled}
          format={(value) => `${Math.round(value * 100)} %`}
          hint="Plus haut = moins de fusions abusives, mais des véhicules réapparus comptés deux fois."
          onChange={(reidMinSimilarity) => onChange({ reidMinSimilarity })}
        />

        <Slider
          label="Seuil IoU"
          value={settings.iouThreshold}
          bounds={BOUNDS.iouThreshold}
          disabled={disabled}
          format={(value) => value.toFixed(2)}
          hint="Recouvrement au-delà duquel deux détections sont considérées comme le même objet."
          onChange={(iouThreshold) => onChange({ iouThreshold })}
        />

        {diagnostics !== null && <DiagnosticsPanel diagnostics={diagnostics} />}
      </Section>

      <Section title="Affichage & analyse">
        <Toggle
          label="Trajectoires"
          checked={settings.showTrails}
          disabled={false}
          onChange={(showTrails) => onChange({ showTrails })}
        />

        <Toggle
          label="Ignorer hors zone"
          checked={settings.maskOutsideZones}
          disabled={disabled || !hasZones}
          hint={
            hasZones
              ? "Le détecteur ne reçoit que l'intérieur des zones."
              : "Tracez d'abord une zone : sans zone, il n'y aurait rien à garder."
          }
          onChange={(maskOutsideZones) => onChange({ maskOutsideZones })}
        />

        <Slider
          label="Pas d'analyse"
          value={settings.frameStride}
          bounds={BOUNDS.frameStride}
          disabled={disabled}
          format={(value) => (value === 1 ? "toutes" : `1 sur ${value}`)}
          hint="« Toutes » donne le comptage le plus fiable ; augmenter le pas accélère sur une machine sans GPU, au prix de véhicules rapides manqués."
          onChange={(frameStride) => onChange({ frameStride })}
        />

        <Slider
          label="Échelle (px/m)"
          value={settings.pixelsPerMeter ?? 0}
          bounds={BOUNDS.pixelsPerMeter}
          disabled={disabled}
          format={(value) => (value === 0 ? "non définie" : `${value} px/m`)}
          // Sans échelle, les vitesses restent en px/s **plutôt que d'être
          // converties à tort** en km/h : un chiffre en km/h sans calibration est
          // une invention que l'utilisateur prendrait au sérieux.
          hint="Sans échelle, les vitesses restent en pixels par seconde au lieu d'être converties en km/h."
          onChange={(value) => onChange({ pixelsPerMeter: value === 0 ? null : value })}
        />
      </Section>
    </>
  );
}

/**
 * Le diagnostic — quatre causes distinctes d'un véhicule manquant.
 *
 * L'ordre suit le chemin qu'une détection parcourt : détectée fortement, détectée
 * faiblement, confirmée en piste, ou écartée par une zone. Lire les quatre chiffres
 * dans cet ordre indique **où** la perte a lieu.
 */
function DiagnosticsPanel({ diagnostics }: { diagnostics: Diagnostics }) {
  const rows: { label: string; value: number; hint: string }[] = [
    {
      label: "Détections retenues",
      value: diagnostics.highDetections,
      hint: "Au-dessus du seuil de confiance.",
    },
    {
      label: "Détections faibles",
      value: diagnostics.lowDetections,
      hint: "Sous le seuil : baisser « Confiance véhicules » les récupérerait.",
    },
    {
      label: "Récupérées de justesse",
      value: diagnostics.rescuedByLowScore,
      hint: "Rattachées à une piste existante malgré un score faible.",
    },
    {
      label: "Pistes confirmées",
      value: diagnostics.confirmedTracks,
      hint: "Ont atteint le seuil d'images avant comptage.",
    },
    {
      label: "Pistes provisoires",
      value: diagnostics.tentativeTracks,
      hint: "Pas encore confirmées : baisser « Images avant comptage » les compterait.",
    },
    {
      label: "Masquées par une zone",
      value: diagnostics.maskedOut,
      hint: "Écartées parce qu'elles étaient hors des zones.",
    },
    {
      label: "Doublons inclus",
      value: diagnostics.containedOut,
      hint:
        "Boîtes entièrement contenues dans une autre — la cabine d'un semi-remorque " +
        "dans la boîte du véhicule entier. Sans cette suppression, elles compteraient deux fois.",
    },
  ];

  return (
    <div className="mt-3 rounded-input bg-base p-2">
      <p className="label-micro mb-2">Diagnostic de la dernière analyse</p>
      <dl className="space-y-1">
        {rows.map((row) => (
          <div key={row.label} className="flex items-baseline justify-between gap-2" title={row.hint}>
            <dt className="text-micro text-ink-dim">{row.label}</dt>
            <dd className="text-micro font-bold text-ink-muted tabular">{row.value}</dd>
          </div>
        ))}
      </dl>
      {diagnostics.highDetections === 0 && diagnostics.lowDetections === 0 ? (
        // **Le cinquième cas**, et le seul que les quatre chiffres n'expliquent
        // pas : zéro détection à *tous* les seuils. Ce n'est alors pas un réglage
        // trop strict — baisser la confiance n'y changera rien, et c'est
        // exactement ce que l'utilisateur va essayer pendant vingt minutes.
        //
        // La cause habituelle est l'imagerie : les détecteurs COCO sont entraînés
        // sur des photographies, et s'effondrent sur une scène dessinée, un rendu
        // 3D stylisé ou une vue de jeu vidéo. Le dire ici évite de conclure à une
        // panne du service (piège 54 de prompt/13).
        <p role="status" className="mt-2 text-micro text-warning">
          <strong>Aucune détection, à aucun seuil.</strong> Baisser la confiance n'y
          changera rien. Les détecteurs sont entraînés sur des photographies : une
          scène dessinée, un rendu 3D ou une capture de jeu vidéo ne produit souvent
          aucune détection. Vérifiez avec une vidéo de trafic réelle avant de
          conclure à un problème du service.
        </p>
      ) : (
        <p className="mt-2 text-micro text-ink-dim">
          Un véhicule manquant est soit jamais détecté, soit détecté faiblement, soit
          non confirmé, soit masqué par une zone. Ces chiffres disent lequel.
        </p>
      )}
    </div>
  );
}

/* ── Primitives ─────────────────────────────────────────────────────────── */

function Section({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-section bg-surface shadow-card">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center justify-between p-4 text-start"
      >
        <span className="label-micro">{title}</span>
        <ChevronDown
          aria-hidden="true"
          className={`size-4 text-ink-dim transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && <div className="space-y-4 px-4 pb-4">{children}</div>}
    </div>
  );
}

interface SliderProps {
  label: string;
  value: number;
  bounds: { min: number; max: number; step: number };
  disabled: boolean;
  format: (value: number) => string;
  // `| undefined` explicite : sous `exactOptionalPropertyTypes`, un `?` seul
  // interdit de **passer** `undefined`, alors que c'est exactement ce qu'un appelant
  // fait pour dire « pas de bouton Défaut ici ».
  hint?: string | undefined;
  onChange: (value: number) => void;
  onReset?: (() => void) | undefined;
}

function Slider({
  label,
  value,
  bounds,
  disabled,
  format,
  hint,
  onChange,
  onReset,
}: SliderProps) {
  const id = useId();

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="text-small text-ink-muted">
          {label}
        </label>
        <span className="flex items-baseline gap-2">
          <output htmlFor={id} className="text-small font-bold text-ink tabular">
            {format(value)}
          </output>
          {onReset !== undefined && (
            <button
              type="button"
              onClick={onReset}
              disabled={disabled}
              className="text-micro text-ink-dim underline transition-colors hover:text-ink disabled:cursor-not-allowed"
            >
              Défaut
            </button>
          )}
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={bounds.min}
        max={bounds.max}
        step={bounds.step}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        className="mt-1.5 h-1 w-full cursor-pointer appearance-none rounded-pill bg-line accent-accent disabled:cursor-not-allowed disabled:opacity-50"
      />
      {hint !== undefined && <p className="mt-1 text-micro text-ink-dim">{hint}</p>}
    </div>
  );
}

interface ToggleProps {
  label: string;
  checked: boolean;
  disabled: boolean;
  hint?: string | undefined;
  onChange: (checked: boolean) => void;
}

function Toggle({ label, checked, disabled, hint, onChange }: ToggleProps) {
  return (
    <div>
      <label className="flex items-center gap-2 text-small text-ink-muted">
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
          className="accent-accent disabled:opacity-50"
        />
        {label}
      </label>
      {hint !== undefined && <p className="mt-1 ps-6 text-micro text-ink-dim">{hint}</p>}
    </div>
  );
}
