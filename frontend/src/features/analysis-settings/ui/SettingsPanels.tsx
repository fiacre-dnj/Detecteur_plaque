/**
 * La barre de réglages du studio, et le **diagnostic live**.
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
 *
 * **Une barre au-dessus de la vidéo, plus une colonne à côté.** Les trois panneaux
 * étaient trois accordéons empilés dans un `<aside>` de 20 rem : ils occupaient en
 * permanence le quart de l'écran pour des réglages qu'on touche une fois avant de
 * lancer, et repoussaient les résultats — ce qu'on regarde vraiment — sous la ligne
 * de flottaison. Ils s'ouvrent maintenant en **tiroir pleine largeur**, ce qui leur
 * donne trois colonnes au lieu d'une, et rend la place à la scène et aux compteurs.
 *
 * Un seul tiroir ouvert à la fois, et **fermé par défaut** : l'écran d'arrivée doit
 * montrer la vidéo, pas un formulaire.
 */

import { ChevronDown } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { ModelPicker } from "@/features/model-picker";
import type { DetectableClass, Diagnostics, VehicleModel } from "@/shared/api/contracts";

import {
  ANALYSIS_FPS_CAPS,
  ANALYSIS_SPEEDS,
  BOUNDS,
  DEFAULT_CONFIDENCE,
  type AnalysisSettings,
} from "../model/settings";

/** Identifiants des tiroirs — l'ordre est celui de la barre. */
const PANELS = [
  { id: "detection", label: "Détection" },
  { id: "comptage", label: "Comptage" },
  { id: "affichage", label: "Affichage & analyse" },
] as const;

type PanelId = (typeof PANELS)[number]["id"];

interface SettingsPanelsProps {
  settings: AnalysisSettings;
  models: readonly VehicleModel[];
  /**
   * Le catalogue **du serveur** (`GET /api/v1/models/classes`), jamais une liste
   * écrite ici. Vide tant que la requête n'a pas répondu : le groupe de cases
   * n'est alors pas affiché, plutôt que d'afficher des cases devinées.
   */
  detectableClasses: readonly DetectableClass[];
  /** Faux quand le serveur signale le modèle de **détection** de plaques absent. */
  plateAvailable: boolean;
  /**
   * Faux quand le modèle de **lecture** ou son dictionnaire manque.
   *
   * Distinct de `plateAvailable` : ce sont deux artefacts, et « détection sans lecture »
   * est l'état de tout déploiement neuf. Sans ce drapeau, l'interface proposerait une
   * case qui ne fait rien.
   */
  plateOcrAvailable: boolean;
  /** Vrai s'il existe au moins une zone : « ignorer hors zone » en dépend. */
  hasZones: boolean;
  /** Diagnostic de la dernière analyse, `null` avant. */
  diagnostics: Diagnostics | null;
  disabled: boolean;
  onChange: (patch: Partial<AnalysisSettings>) => void;
  /**
   * Contenu placé **avant** les onglets, sur la même ligne.
   *
   * C'est là que le studio pose le bouton d'import. Un emplacement plutôt qu'un
   * import direct : `analysis-settings` n'a pas à connaître `media-source`, et le
   * câblage entre deux features passe par `StudioPage` — la même règle qui donne à
   * `GeometryPanel` un `onOpenPresets` plutôt que la modale elle-même.
   */
  leading?: ReactNode | undefined;
}

export function SettingsPanels({
  settings,
  models,
  detectableClasses,
  plateAvailable,
  plateOcrAvailable,
  hasZones,
  diagnostics,
  disabled,
  onChange,
  leading,
}: SettingsPanelsProps) {
  /** `null` = tout fermé, l'état d'arrivée. */
  const [open, setOpen] = useState<PanelId | null>(null);
  const base = useId();

  const panels: Record<PanelId, ReactNode> = {
    detection: (
      <PanelGrid>
        {/* `canPreload={!disabled}` : le préchargement prend un bail sur le
            modèle, donc le lancer pendant une analyse ferait attendre la fin de
            celle-ci sans que rien à l'écran ne l'explique. `disabled` vaut
            exactement « une analyse ou un direct occupe le serveur ». */}
        <ModelPicker
          models={models}
          selectedId={settings.modelId}
          disabled={disabled}
          canPreload={!disabled}
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

        <ClassPicker
          classes={detectableClasses}
          selected={settings.classIds}
          disabled={disabled}
          onChange={(classIds) => onChange({ classIds })}
        />

        {/* Piloté par `plateAvailable` **seul** : la détection reste utile sans OCR,
            les rectangles jaunes valident déjà un cadrage. */}
        <Toggle
          label="Repérer les plaques (ANPR)"
          checked={settings.detectPlates}
          disabled={disabled || !plateAvailable}
          hint={
            plateAvailable
              ? "Recadre chaque véhicule suivi et y localise sa plaque — plus lent, mais les recadrages d'une même image partent groupés."
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
            hint="Seule la meilleure plaque de chaque véhicule est retenue : monter ce seuil en garde moins, pas de plus précises."
            onChange={(plateConfidence) => onChange({ plateConfidence })}
          />
        )}

        {/* Une option **de** l'option : elle n'apparaît que si le repérage est actif,
            parce que lire sans détecter n'a pas de sens — il n'y aurait aucune boîte. */}
        {settings.detectPlates && (
          <Toggle
            label="Lire le texte des plaques (OCR)"
            checked={settings.readPlateText}
            disabled={disabled || !plateOcrAvailable}
            hint={
              plateOcrAvailable
                ? "Le texte affiché est voté sur toute la vie du véhicule, pas lu sur une seule image — et il est conservé en base avec le résultat."
                : "Le modèle de lecture n'est pas installé sur ce serveur : les plaques sont encadrées, leur texte n'est pas lu."
            }
            onChange={(readPlateText) => onChange({ readPlateText })}
          />
        )}
      </PanelGrid>
    ),
    comptage: (
      <PanelGrid>
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
          hint="Silence au-delà duquel une piste est abandonnée. Un véhicule masqué plus longtemps recommence en tant que nouveau véhicule."
          onChange={(maxLostMs) => onChange({ maxLostMs })}
        />

        {/* Le curseur « Similarité de ré-identification » n'existe plus, et le
            réglage non plus : ADR 0016 a supprimé la galerie d'apparence, donc il n'y
            a plus de seuil à régler. ADR 0014 l'avait déjà retiré de l'écran en le
            laissant dans le contrat ; le laisser plus longtemps aurait été garder un
            réglage annoncé et sans effet, le pire état d'un réglage. */}

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
      </PanelGrid>
    ),
    affichage: (
      <PanelGrid>
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

        {/* Placé juste après « Pas d'analyse », dont il est l'exact opposé : l'un
            accélère l'analyse en sautant des images, l'autre la ralentit pour qu'on
            puisse la regarder. Les voir côte à côte évite de chercher le second
            dans les réglages de lecture, où il n'est pas — c'est le serveur qui
            attend, pas le lecteur. */}
        <Choice
          label="Cadence d'analyse"
          options={ANALYSIS_SPEEDS}
          value={settings.analysisSpeed}
          disabled={disabled}
          hint={
            settings.analysisSpeed === null
              ? "Sans borne, l'aperçu défile aussi vite que le serveur analyse — 1,7× la vitesse réelle sur cette machine. Bornez-la pour suivre l'analyse à l'œil."
              : "Une cadence maximale : l'analyse attend entre deux images, sans jamais dépasser cette vitesse — ni l'atteindre si la machine ne suit pas. Les compteurs sont identiques."
          }
          onChange={(analysisSpeed) => onChange({ analysisSpeed })}
        />

        {/* Distinct de la cadence ci-dessus : celle-ci borne une vitesse
            relative à la scène, celle-ci borne le débit absolu du serveur —
            utile pour partager la machine entre plusieurs sources sans se
            soucier de la vitesse de lecture de chacune. */}
        <Choice
          label="Cadence serveur maximale"
          options={ANALYSIS_FPS_CAPS}
          value={settings.maxAnalysisFps}
          disabled={disabled}
          hint={
            settings.maxAnalysisFps === null
              ? "Aucun plafond : le serveur analyse aussi vite qu'il peut, dans la limite de la cadence ci-dessus."
              : "Le serveur n'analyse jamais plus vite que cette cadence, quelle que soit celle de la vidéo — combiné au réglage précédent, le plus restrictif des deux s'applique."
          }
          onChange={(maxAnalysisFps) => onChange({ maxAnalysisFps })}
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
      </PanelGrid>
    ),
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {leading}
        {PANELS.map((panel) => {
          const active = open === panel.id;
          return (
            <button
              key={panel.id}
              type="button"
              // `aria-expanded` + `aria-controls` : l'accordéon d'origine n'avait ni
              // l'un ni l'autre, donc un lecteur d'écran annonçait un bouton sans
              // dire qu'il ouvre quelque chose, ni quoi.
              aria-expanded={active}
              aria-controls={`${base}-${panel.id}`}
              // Re-cliquer referme : c'est le geste attendu d'un tiroir, et cela
              // évite d'avoir à chercher une croix de fermeture.
              onClick={() => setOpen(active ? null : panel.id)}
              className={[
                "label-caps inline-flex h-10 items-center gap-2 rounded-pill px-4",
                "transition-colors",
                active
                  ? "bg-elevated text-ink shadow-card"
                  : "bg-surface text-ink-muted hover:bg-surface-2 hover:text-ink",
              ].join(" ")}
            >
              {panel.label}
              <ChevronDown
                aria-hidden="true"
                className={`size-4 text-ink-dim transition-transform ${active ? "rotate-180" : ""}`}
              />
            </button>
          );
        })}
      </div>

      {open !== null && (
        <section
          id={`${base}-${open}`}
          // `region` + le nom du panneau : le tiroir devient un point de repère
          // atteignable directement, au lieu d'un bloc anonyme.
          role="region"
          aria-label={PANELS.find((panel) => panel.id === open)?.label}
          className="rounded-section bg-surface p-4 shadow-card"
        >
          {panels[open]}
        </section>
      )}
    </div>
  );
}

/**
 * La grille du tiroir : une colonne sur mobile, deux puis trois en largeur.
 *
 * `items-start` est nécessaire : sans lui, les cellules d'une même rangée s'étirent
 * à la hauteur de la plus grande, et un curseur se retrouve centré dans le vide en
 * face du sélecteur de modèle.
 */
function PanelGrid({ children }: { children: ReactNode }) {
  return (
    <div className="grid items-start gap-x-6 gap-y-4 md:grid-cols-2 xl:grid-cols-3">{children}</div>
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

interface ChoiceProps<T> {
  label: string;
  options: readonly { value: T; label: string }[];
  value: T;
  disabled: boolean;
  hint?: string | undefined;
  onChange: (value: T) => void;
}

/**
 * Un choix parmi trois ou quatre — des **vrais boutons radio**, habillés en pilules.
 *
 * Pas un `<select>` : les options sont courtes et se comparent d'un regard, et un
 * menu déroulant les cacherait derrière un clic. Pas des `<button>` non plus, qui
 * n'auraient ni le groupe annoncé par le lecteur d'écran, ni la navigation aux
 * flèches — un groupe de radios les donne tous les deux gratuitement. L'input est
 * masqué visuellement (`sr-only`) mais reste dans l'arbre d'accessibilité et garde
 * le focus clavier, que `peer-focus-visible` rend visible sur la pilule.
 */
function Choice<T extends string | number | null>({
  label,
  options,
  value,
  disabled,
  hint,
  onChange,
}: ChoiceProps<T>) {
  const name = useId();

  return (
    <fieldset className="min-w-0">
      <legend className="text-small text-ink-muted">{label}</legend>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {options.map((option) => {
          const active = option.value === value;
          return (
            <label
              key={String(option.value)}
              className={[
                "inline-flex cursor-pointer items-center rounded-pill px-3 py-1 text-small",
                // `has-[:focus-visible]` et non `peer-focus-visible` : l'input est
                // un **enfant** du label, pas son frère, donc `peer-*` ne
                // l'atteindrait pas et l'anneau de focus ne s'afficherait jamais.
                "transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-accent",
                active ? "bg-elevated text-ink shadow-card" : "bg-base text-ink-dim hover:text-ink",
                disabled ? "cursor-not-allowed opacity-50" : "",
              ].join(" ")}
            >
              <input
                type="radio"
                name={name}
                checked={active}
                disabled={disabled}
                onChange={() => onChange(option.value)}
                className="sr-only"
              />
              {option.label}
            </label>
          );
        })}
      </div>
      {hint !== undefined && <p className="mt-1 text-micro text-ink-dim">{hint}</p>}
    </fieldset>
  );
}

interface ClassPickerProps {
  classes: readonly DetectableClass[];
  selected: readonly number[];
  disabled: boolean;
  onChange: (classIds: number[]) => void;
}

/**
 * Les classes à détecter et à compter.
 *
 * **La liste vient du serveur.** Une case écrite en dur ici pourrait être refusée
 * à l'envoi — ou, pire, une classe détectable ne serait cochable par personne.
 * Tant que le catalogue n'a pas répondu, on n'affiche rien plutôt que des cases
 * devinées.
 *
 * **Tout décocher n'est pas interdit à l'écran**, mais le serveur refuse une
 * sélection vide (elle compterait les 80 classes de COCO). L'avertissement dit ce
 * qui se passera, et `toRequest` retombe sur les véhicules : l'utilisateur n'est
 * jamais bloqué par un 422 sur un écran qui paraissait valide.
 */
function ClassPicker({ classes, selected, disabled, onChange }: ClassPickerProps) {
  if (classes.length === 0) return null;

  const chosen = new Set(selected);
  const toggle = (id: number, next: boolean) => {
    // L'ordre du catalogue est conservé plutôt que l'ordre des clics : c'est celui
    // de l'affichage, et une liste qui se réordonne à chaque clic rendrait deux
    // configurations identiques visuellement différentes à la relecture.
    const wanted = new Set(chosen);
    if (next) wanted.add(id);
    else wanted.delete(id);
    onChange(classes.filter((entry) => wanted.has(entry.id)).map((entry) => entry.id));
  };

  const people = classes.filter((entry) => entry.category === "person");

  return (
    <fieldset className="min-w-0">
      <legend className="label-micro mb-2">Objets à compter</legend>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1">
        {classes.map((entry) => (
          <label
            key={entry.id}
            className="flex items-center gap-2 text-small text-ink-muted"
            title={`Classe COCO « ${entry.cocoName} »`}
          >
            <input
              type="checkbox"
              checked={chosen.has(entry.id)}
              disabled={disabled}
              onChange={(event) => toggle(entry.id, event.target.checked)}
              className="accent-accent disabled:opacity-50"
            />
            {entry.label}
          </label>
        ))}
      </div>
      {chosen.size === 0 ? (
        <p className="mt-1 text-micro text-ink-dim">
          Aucune classe cochée : l'analyse repartira sur les véhicules.
        </p>
      ) : (
        people.some((entry) => chosen.has(entry.id)) && (
          <p className="mt-1 text-micro text-ink-dim">
            Les personnes sont comptées <strong>à part</strong> des véhicules.
          </p>
        )
      )}
    </fieldset>
  );
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
