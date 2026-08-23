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
 * de flottaison.
 *
 * Ils s'ouvrent maintenant en **tiroir flottant**, posé *par-dessus* la page
 * plutôt que d'en pousser le contenu : un tiroir pleine largeur en flux normal a
 * été essayé d'abord, et décalait la vidéo et les résultats de plusieurs centaines
 * de pixels à chaque ouverture — la scène qu'on venait de tracer disparaissait de
 * l'écran pour un réglage qu'on touche une fois. `position: absolute`, ancré sous
 * la barre, rend la page inchangée sous le tiroir ; un clic en dehors ou `Échap`
 * le referme, comme n'importe quel menu.
 *
 * Un seul tiroir ouvert à la fois, et **fermé par défaut** : l'écran d'arrivée doit
 * montrer la vidéo, pas un formulaire.
 *
 * **La barre est collée sous l'entête** (`sticky`, décalée de `--app-header-h` que
 * `AppShell` mesure). Le bas de page s'est allongé — quatre sections de résultats
 * plus la chronologie — et les réglages, l'import et les compteurs techniques
 * partaient donc hors de l'écran dès qu'on lisait le registre. Elle porte son propre
 * fond opaque, débordé jusqu'aux gouttières de la page (`-mx-6 px-6`) : sans lui, la
 * vidéo défilerait visiblement *sous* les pilules.
 *
 * **Les tiroirs ne sont pas tous d'ici.** `panels` en accepte d'autres, fournis par
 * le studio — c'est ainsi que « Géométrie » rejoint la barre sans que cette feature
 * connaisse `geometry-editor`, même règle que `leading` et `trailing`.
 */

import { ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";

import { ModelPicker } from "@/features/model-picker";
import type {
  CountingLine,
  DetectableClass,
  Diagnostics,
  VehicleModel,
} from "@/shared/api/contracts";

import { plateCapability } from "../model/plateCapability";
import {
  ANALYSIS_FPS_CAPS,
  ANALYSIS_SPEEDS,
  BOUNDS,
  DEFAULT_CONFIDENCE,
  type AnalysisSettings,
} from "../model/settings";

/** Identifiants des tiroirs **de cette feature** — l'ordre est celui de la barre. */
const PANELS = [
  { id: "detection", label: "Détection" },
  { id: "comptage", label: "Comptage" },
  { id: "affichage", label: "Affichage & analyse" },
] as const;

type OwnPanelId = (typeof PANELS)[number]["id"];

/**
 * Un tiroir **fourni de l'extérieur**, rendu après les trois d'ici.
 *
 * « Géométrie » est le premier : c'était un panneau permanent de la colonne de
 * droite, alors qu'il se règle comme les autres — une fois, avant de lancer — et
 * qu'il volait la place des chiffres. Il ne peut pas être importé ici (une feature
 * n'importe jamais une autre feature), donc le studio le passe.
 */
export interface ExtraPanel {
  id: string;
  label: string;
  content: ReactNode;
}

/** L'identifiant du tiroir ouvert : l'un des trois d'ici, ou celui d'un `ExtraPanel`. */
type PanelId = string;

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
   * Le détecteur de plaques a-t-il passé l'auto-test du serveur ? `null` = non testé.
   *
   * Le troisième état de l'ANPR, et le seul qui trompe : poids **présents** et
   * chargement en échec. Sans ce drapeau, la case restait cochable, l'analyse payait
   * une inférence par véhicule et par image, et aucune plaque ne sortait jamais.
   * Voir `model/plateCapability.ts`, qui tranche les trois états en un endroit.
   */
  plateLoadable: boolean | null;
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
  /**
   * Le tracé courant, **pour nommer les lignes du diagnostic** — les
   * quasi-franchissements sont publiés par identifiant de ligne.
   *
   * Le type vient du contrat partagé, pas d'une autre feature : `analysis-settings`
   * ne connaît ni l'éditeur de géométrie ni le tableau de bord.
   */
  lines: readonly CountingLine[];
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
  /**
   * Contenu placé **après** les onglets, poussé à l'extrémité de la barre
   * (`ms-auto`) — le nom du fichier importé.
   *
   * Même raison d'emplacement que `leading` : le studio le fournit, cette feature
   * ne sait pas ce qu'est une source.
   */
  trailing?: ReactNode | undefined;
  /**
   * Une source est-elle chargée ?
   *
   * Sans elle, régler la détection, le comptage ou l'affichage n'a rien à quoi
   * s'appliquer : les trois tiroirs sont grisés, et un tiroir resté ouvert se
   * referme si la source disparaît pendant qu'il l'était.
   */
  hasSource: boolean;
  /**
   * Tiroirs supplémentaires, rendus **après** les trois d'ici — « Géométrie ».
   *
   * Une liste plutôt qu'un `ReactNode` : la barre doit dessiner leur pilule et
   * tenir l'exclusivité (un seul tiroir ouvert), ce qu'elle ne peut pas faire sur
   * du contenu déjà rendu.
   */
  panels?: readonly ExtraPanel[];
  /**
   * Le tiroir ouvert, `null` = tout fermé. **Piloté de l'extérieur.**
   *
   * L'état vivait ici, et c'était vrai tant que la barre était le seul endroit qui
   * ouvre un tiroir. Cliquer une ligne sur la vidéo doit maintenant déplier
   * « Géométrie » — le geste et le réglage sont le même acte, et l'utilisateur
   * cliquait un trait puis cherchait où le renommer. Le studio est le seul à voir
   * les deux, donc c'est lui qui tient l'état.
   */
  openPanel: PanelId | null;
  /** Demande d'ouverture ou de fermeture : re-clic, `Échap`, clic en dehors. */
  onOpenPanel: (id: PanelId | null) => void;
}

/**
 * Marqueur d'exemption du clic « en dehors », posé par l'appelant.
 *
 * Le tiroir flotte au-dessus de la page et se referme sur tout `pointerdown`
 * extérieur — sauf sur une surface qui, elle, **pilote** le tiroir. La scène de
 * tracé est ce cas : sans exemption, cliquer une ligne ouvrirait « Géométrie » puis
 * le refermerait dans le même événement, le gestionnaire de document s'exécutant
 * après celui de React.
 *
 * Un attribut plutôt qu'une liste de `ref` : cette feature n'a pas à connaître la
 * scène, ni le studio à lui passer une référence dont il ne fait rien d'autre.
 */
export const KEEP_PANELS_OPEN_ATTR = "data-keep-panels-open";

export function SettingsPanels({
  settings,
  models,
  detectableClasses,
  plateAvailable,
  plateLoadable,
  plateOcrAvailable,
  hasZones,
  lines,
  diagnostics,
  disabled,
  onChange,
  leading,
  trailing,
  hasSource,
  panels: extraPanels = [],
  openPanel: open,
  onOpenPanel: setOpen,
}: SettingsPanelsProps) {
  const base = useId();
  /** Racine du composant : borne le clic « en dehors » qui referme le tiroir. */
  const root = useRef<HTMLDivElement>(null);

  // Une source qui disparaît pendant qu'un tiroir est ouvert le referme : les
  // trois panneaux n'ont alors plus rien à régler, et un tiroir grisé resté
  // ouvert serait un formulaire qu'on ne peut plus toucher sans savoir pourquoi.
  useEffect(() => {
    // Inconditionnel, et non gardé par `open !== null` : l'état vit chez l'appelant
    // depuis que la scène ouvre « Géométrie », et un `setState` qui repose la même
    // valeur ne provoque aucun rendu. Le garde n'économiserait rien et ferait lire
    // `open` dans un effet qui ne dépend que de la source.
    if (!hasSource) setOpen(null);
  }, [hasSource, setOpen]);

  // Le tiroir flotte **par-dessus** la page (`position: absolute`) : il n'est
  // plus contenu par un parent qu'on pourrait cliquer pour le refermer, ni par
  // un lecteur d'écran qui saurait qu'un clic ailleurs y met fin. Un clic hors de
  // la racine, ou `Échap`, le referme donc explicitement — le geste attendu de
  // n'importe quel menu.
  useEffect(() => {
    if (open === null) return;

    const closeIfOutside = (event: PointerEvent): void => {
      const target = event.target as Node;
      if (root.current === null || root.current.contains(target)) return;
      // Une surface qui pilote elle-même le tiroir n'est pas un « en dehors » : la
      // scène de tracé ouvre « Géométrie » sur un clic de ligne, et ce
      // gestionnaire, qui s'exécute *après* celui de React, le refermerait aussitôt.
      if (
        target instanceof Element &&
        target.closest(`[${KEEP_PANELS_OPEN_ATTR}]`) !== null
      ) {
        return;
      }
      setOpen(null);
    };
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key === "Escape") setOpen(null);
    };

    document.addEventListener("pointerdown", closeIfOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeIfOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open, setOpen]);

  // Les trois états de l'ANPR tranchés **une fois**, en dehors du rendu : la case
  // de détection, celle de lecture et leurs deux phrases décrivent le même serveur,
  // et les faire décider séparément les laisserait se contredire.
  const plates = plateCapability({
    available: plateAvailable,
    loadable: plateLoadable,
    ocrAvailable: plateOcrAvailable,
  });

  const ownPanels: Record<OwnPanelId, ReactNode> = {
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
          // **Ce seuil ne filtre plus le détecteur.** Il décide ce qui *devient* une
          // piste ; les détections plus faibles continuent d'arriver au suivi, où
          // elles prolongent une piste dont la confiance plonge — sans jamais en
          // ouvrir une. Le dire ici est ce qui évite de le baisser pour « détecter
          // plus » : ce que cela change, c'est le nombre de pistes créées, donc de
          // véhicules comptés.
          hint={
            "Décide ce qui devient une piste, pas ce que le détecteur voit : une " +
            "détection plus faible prolonge encore une piste existante, elle n'en " +
            "crée jamais. " +
            (settings.confidenceThreshold === null
              ? "Suit le défaut du modèle sélectionné."
              : "Valeur explicite : conservée au changement de modèle.")
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

        <PanelGridFullRow>
          <ClassPicker
            classes={detectableClasses}
            selected={settings.classIds}
            disabled={disabled}
            onChange={(classIds) => onChange({ classIds })}
          />
        </PanelGridFullRow>

        {/* **Trois états, pas deux** : absent, présent mais illisible, disponible.
            Le deuxième est celui qui trompait — poids en place, chargement en échec,
            case cochable et aucune plaque en sortie. `plateCapability` le tranche, et
            l'ANPR reste indépendante de l'OCR : les rectangles seuls valident déjà un
            cadrage. */}
        <Toggle
          label="Repérer les plaques (ANPR)"
          checked={settings.detectPlates}
          disabled={disabled || !plates.canDetect}
          hint={plates.detectHint}
          onChange={(detectPlates) => onChange({ detectPlates })}
        />

        {settings.detectPlates && (
          <Slider
            label="Confiance plaques"
            value={settings.plateConfidence ?? 0.25}
            bounds={BOUNDS.plateConfidence}
            disabled={disabled}
            format={(value) => `${Math.round(value * 100)} %`}
            // Mesuré : sur 538 détections réelles, 112 étaient la boîte du véhicule
            // entier — dont certaines à 0,87 de confiance, donc **inatteignables par
            // un seuil**. C'est le filtre de forme qui les écarte, et le dire ici
            // évite de monter ce curseur en espérant gagner en justesse.
            hint="Seule la meilleure plaque de chaque véhicule est retenue : monter ce seuil en garde moins, pas de plus précises. Les boîtes de forme impossible sont écartées avant, quel que soit leur score."
            onChange={(plateConfidence) => onChange({ plateConfidence })}
          />
        )}

        {/* Une option **de** l'option : elle n'apparaît que si le repérage est actif,
            parce que lire sans détecter n'a pas de sens — il n'y aurait aucune boîte. */}
        {settings.detectPlates && (
          <Toggle
            label="Lire le texte des plaques (OCR)"
            checked={settings.readPlateText}
            disabled={disabled || !plates.canRead}
            hint={plates.readHint}
            onChange={(readPlateText) => onChange({ readPlateText })}
          />
        )}

        {/* **Déplacé depuis « Affichage & analyse »**, où il n'avait rien à faire :
            ce réglage ne change pas ce qu'on voit, il change ce que le détecteur
            reçoit — donc les chiffres. Sa place est ici, à côté du seuil de confiance
            et des classes, et le diagnostic de comptage compte d'ailleurs ce qu'il a
            retiré (« Masquées par une zone »). */}
        <Toggle
          label="Ignorer hors zone"
          checked={settings.maskOutsideZones}
          disabled={disabled || !hasZones}
          hint={
            hasZones
              ? "Le détecteur ne reçoit que l'intérieur des zones : ce qui passe dehors n'est ni détecté, ni suivi, ni compté."
              : "Tracez d'abord une zone : sans zone, il n'y aurait rien à garder."
          }
          onChange={(maskOutsideZones) => onChange({ maskOutsideZones })}
        />
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
          // Ce que « compté » veut dire précisément : entrer dans les véhicules
          // suivis et dans le registre. Une piste plus courte a bien existé — elle a
          // reçu un numéro dès sa première image, ce qui explique les trous dans la
          // suite des numéros — mais elle n'est pas un véhicule.
          hint="Nombre d'images qu'une piste doit vivre pour devenir un véhicule — compté dans les totaux et listé au registre. Plus haut = moins de faux positifs, mais les véhicules rapides peuvent être manqués."
          onChange={(minHits) => onChange({ minHits })}
        />

        <Slider
          label="Survie d'une piste perdue"
          value={settings.maxLostMs}
          bounds={BOUNDS.maxLostMs}
          disabled={disabled}
          format={(value) => `${(value / 1000).toFixed(1)} s`}
          // La contrepartie est dite parce qu'elle est **assumée** et verrouillée par
          // un test : un numéro ne revient jamais en arrière, donc une occlusion trop
          // longue donne un véhicule de plus. C'est le prix d'un comptage qui ne
          // fusionne jamais deux véhicules par erreur.
          hint="Silence au-delà duquel une piste est abandonnée. Un véhicule masqué plus longtemps repart comme un véhicule neuf — il compte alors pour deux, et c'est préférable à deux véhicules fusionnés en un."
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

        {/* **Ce qui n'est pas réglable, et pourquoi.** Ces deux mécanismes décident
            de franchissements que l'utilisateur voit à l'écran ; sans un mot ici, un
            passage compté une seule fois là où l'œil en voit trois, ou daté deux
            secondes trop tard, se lit comme un bug. Leurs valeurs sont mesurées et
            non devinées : c'est ce qui justifie de ne pas les exposer. */}
        <PanelGridFullRow>
          <p className="rounded-input bg-base p-2 text-micro text-ink-dim">
            <strong className="text-ink-muted">Décidé pour vous.</strong> Une bande
            morte entoure chaque trait — un quart de demi-boîte du véhicule — pour
            qu'un véhicule arrêté sur la ligne ne compte pas trois fois. Elle a un
            prix : l'instant publié est celui de la <em>sortie</em> de bande, jusqu'à
            deux secondes après le contact pour un gros véhicule qui aborde le trait
            presque parallèlement. Une piste qui naît dans la bande est rattrapée,
            donc un véhicule qui entre dans le champ juste au bord du trait est bien
            compté.
          </p>
        </PanelGridFullRow>

        {diagnostics !== null && (
          <PanelGridFullRow>
            <DiagnosticsPanel diagnostics={diagnostics} lines={lines} />
          </PanelGridFullRow>
        )}
      </PanelGrid>
    ),
    affichage: (
      <PanelGrid>
        <Toggle
          label="Trajectoires"
          checked={settings.showTrails}
          disabled={false}
          // Le seul réglage de ce panneau qui soit **purement** de l'affichage : il
          // ne part pas au serveur, ne touche aucun chiffre, et reste donc actif
          // pendant une analyse. « Ignorer hors zone » vivait ici et a rejoint
          // Détection, dont il modifie l'entrée.
          hint="Dessine le chemin parcouru par chaque véhicule. N'affecte que le canvas : aucun chiffre ne change."
          onChange={(showTrails) => onChange({ showTrails })}
        />

        <Slider
          label="Pas d'analyse"
          value={settings.frameStride}
          bounds={BOUNDS.frameStride}
          disabled={disabled}
          format={(value) => (value === 1 ? "toutes" : `1 sur ${value}`)}
          // Précision qui manquait : sauter des images ne décale **pas** les
          // horodatages — ils restent `index d'image / fps`, donc du temps de scène —
          // mais il raccourcit la trajectoire vue par le compteur, et c'est ainsi
          // qu'un franchissement se perd.
          hint="« Toutes » donne le comptage le plus fiable ; augmenter le pas accélère sur une machine sans GPU, au prix de véhicules rapides manqués. Les horodatages restent justes dans tous les cas."
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
          // Depuis que le registre et la statistique se remplissent pendant
          // l'analyse, borner la cadence ne sert plus seulement à regarder les
          // boîtes : c'est ce qui laisse le temps de lire une ligne du tableau au
          // moment où le véhicule correspondant passe à l'écran — la vérification que
          // le registre existe pour permettre.
          hint={
            settings.analysisSpeed === null
              ? "Sans borne, l'aperçu défile aussi vite que le serveur analyse — 1,7× la vitesse réelle sur cette machine. Bornez-la pour suivre l'analyse à l'œil, boîtes, compteurs et registre compris."
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

      </PanelGrid>
    ),
  };

  /**
   * Les tiroirs de la barre, les trois d'ici puis ceux qu'on lui donne.
   *
   * Une seule liste : la pilule, l'exclusivité et le contenu se lisent au même
   * endroit, et un tiroir venu du studio se comporte donc exactement comme les
   * autres — `Échap`, clic en dehors, re-clic qui referme.
   */
  const tabs: readonly ExtraPanel[] = [
    ...PANELS.map((panel) => ({
      id: panel.id,
      label: panel.label,
      content: ownPanels[panel.id],
    })),
    ...extraPanels,
  ];
  const current = tabs.find((tab) => tab.id === open) ?? null;

  return (
    /* `sticky` **et** un fond opaque débordé jusqu'aux gouttières : la barre reste
       atteignable quand on lit le bas de page, et la vidéo ne défile pas en
       transparence derrière ses pilules. `z-30` la pose sous l'entête de
       l'application (`z-40`) et au-dessus de tout le reste du studio. */
    <div
      ref={root}
      className={[
        "sticky top-[var(--app-header-h,0px)] z-30",
        "-mx-6 border-b border-line/40 bg-base/95 px-6 py-2 backdrop-blur",
      ].join(" ")}
    >
      <div className="flex flex-wrap items-center gap-2">
        {leading}
        {tabs.map((panel) => {
          const active = open === panel.id;
          return (
            <button
              key={panel.id}
              type="button"
              disabled={!hasSource}
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
                "transition-colors disabled:cursor-not-allowed disabled:opacity-45",
                active
                  ? "bg-elevated text-ink shadow-card"
                  : "bg-surface text-ink-muted hover:enabled:bg-surface-2 hover:enabled:text-ink",
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
        {trailing !== undefined && (
          <div className="ms-auto flex min-w-0 items-center">{trailing}</div>
        )}
      </div>

      {/* Flotte **par-dessus** la page : `absolute`, ancré sous la barre, jamais
          dans le flux. C'est ce qui évite qu'ouvrir un tiroir décale la vidéo et
          les résultats de plusieurs centaines de pixels — voir la docstring du
          fichier. Il hérite du `z-30` de la barre, donc il passe sous l'entête
          fixe de l'application (`z-40`, `AppShell`) et au-dessus du reste.

          `start-6` et non `start-0` : la barre déborde désormais de six unités de
          chaque côté pour peindre son fond jusqu'aux gouttières de la page, et un
          tiroir aligné sur ce débord commencerait hors de la colonne de contenu. */}
      {current !== null && (
        <section
          id={`${base}-${current.id}`}
          // `region` + le nom du panneau : le tiroir devient un point de repère
          // atteignable directement, au lieu d'un bloc anonyme.
          role="region"
          aria-label={current.label}
          className={[
            "absolute start-6 top-full mt-2 w-[min(36rem,calc(100%-3rem))] origin-top",
            "max-h-[70vh] overflow-y-auto rounded-panel bg-surface p-4 shadow-dialog",
          ].join(" ")}
        >
          {current.content}
        </section>
      )}
    </div>
  );
}

/**
 * La grille du tiroir : une colonne sur mobile, deux en largeur.
 *
 * Deux et non trois : le tiroir flotte dans une largeur bornée (36 rem) plutôt
 * que sur toute la barre — la troisième colonne n'aurait plus la place de
 * respirer.
 *
 * `items-start` est nécessaire : sans lui, les cellules d'une même rangée s'étirent
 * à la hauteur de la plus grande, et un curseur se retrouve centré dans le vide en
 * face du sélecteur de modèle.
 */
function PanelGrid({ children }: { children: ReactNode }) {
  return <div className="grid items-start gap-x-4 gap-y-3 sm:grid-cols-2">{children}</div>;
}

/** Une cellule qui prend toute la largeur de la grille — les listes, pas les curseurs. */
function PanelGridFullRow({ children }: { children: ReactNode }) {
  return <div className="sm:col-span-2">{children}</div>;
}

/**
 * Le diagnostic — quatre causes distinctes d'un véhicule manquant.
 *
 * L'ordre suit le chemin qu'une détection parcourt : détectée fortement, détectée
 * faiblement, confirmée en piste, ou écartée par une zone. Lire les quatre chiffres
 * dans cet ordre indique **où** la perte a lieu.
 */
function DiagnosticsPanel({
  diagnostics,
  lines,
}: {
  diagnostics: Diagnostics;
  lines: readonly CountingLine[];
}) {
  const rows: { label: string; value: number; hint: string }[] = [
    {
      label: "Détections retenues",
      value: diagnostics.highDetections,
      hint: "Au-dessus du seuil : elles associent et peuvent créer une piste.",
    },
    {
      label: "Détections faibles",
      value: diagnostics.rescuedByLowScore,
      // **Ce chiffre ne signale plus une perte.** Depuis ADR 0024, le détecteur
      // reçoit le plancher du tracker et non le seuil de l'utilisateur : ces
      // détections ne sont plus jetées, elles descendent jusqu'au suivi, où elles
      // prolongent une piste dont la confiance plonge sans jamais en ouvrir une —
      // le mécanisme qui était débranché, et qui coupait des pistes en deux (donc
      // perdait des franchissements *et* comptait des véhicules deux fois). Un
      // chiffre élevé ici n'est plus un problème : c'est ce mécanisme qui travaille.
      hint: "Sous le seuil : elles prolongent une piste existante sans jamais en ouvrir une — c'est le mécanisme qui évite qu'une piste se coupe en deux quand la confiance plonge un instant.",
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
    <div className="rounded-input bg-base p-2">
      <p className="label-micro mb-2">Diagnostic de la dernière analyse</p>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
        {rows.map((row) => (
          <div key={row.label} className="flex items-baseline justify-between gap-2" title={row.hint}>
            <dt className="text-micro text-ink-dim">{row.label}</dt>
            <dd className="text-micro font-bold text-ink-muted tabular">{row.value}</dd>
          </div>
        ))}
      </dl>
      {diagnostics.highDetections === 0 && diagnostics.rescuedByLowScore === 0 ? (
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

      <NearMisses nearMisses={diagnostics.nearMisses} lines={lines} />
    </div>
  );
}

/**
 * Les quasi-franchissements — **le seul chiffre qui juge le tracé**.
 *
 * Le serveur les publie depuis longtemps (`diagnostics.nearMisses`, par ligne) et
 * plus rien ne les affichait : ils vivaient sur les cartes de ligne du tableau de
 * bord, supprimées par la refonte du bas de page. Le diagnostic de comptage est
 * leur place naturelle — c'est déjà l'endroit où l'on vient comprendre un compteur
 * qui paraît faux.
 *
 * Ce qu'ils séparent, et que rien d'autre ne sépare : une ligne à zéro parce que
 * personne ne passe, et une ligne à zéro parce qu'elle est posée là où le suivi
 * s'arrête. Les deux affichent le même compteur et appellent des gestes opposés.
 *
 * **Ils ne s'ajoutent à aucun total** et n'affirment pas qu'un véhicule est passé :
 * il a pu faire demi-tour ou stationner. Ils disent que le tracé et le suivi se
 * sont manqués de peu — moins d'une demi-boîte.
 */
function NearMisses({
  nearMisses,
  lines,
}: {
  nearMisses: Record<string, number> | undefined;
  lines: readonly CountingLine[];
}) {
  // `undefined` vient d'un résultat archivé avant que le champ existe ; un objet
  // vide, d'une analyse qui n'en a relevé aucun. Les deux ne méritent rien à
  // l'écran, mais pour deux raisons différentes.
  const entries = Object.entries(nearMisses ?? {}).filter(([, count]) => count > 0);
  if (entries.length === 0) return null;

  return (
    <div className="mt-2 border-t border-line/40 pt-2">
      <p className="label-micro mb-1">Quasi-franchissements</p>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
        {entries.map(([lineId, count]) => (
          <div key={lineId} className="flex items-baseline justify-between gap-2">
            {/* Le nom si la ligne existe encore, l'identifiant sinon : un
                quasi-franchissement sur une ligne supprimée depuis reste un fait
                réel de l'analyse, et le masquer creuserait un écart inexpliqué. */}
            <dt className="truncate text-micro text-ink-dim">
              {lines.find((line) => line.id === lineId)?.name ?? lineId}
            </dt>
            <dd className="text-micro font-bold text-warning tabular">{count}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-1 text-micro text-ink-dim">
        Pistes éteintes à moins d'une demi-boîte d'un trait, sans l'avoir franchi.
        Elles ne comptent dans aucun total : elles disent que le tracé est posé là où
        le suivi s'arrête, pas qu'un véhicule a été manqué.
      </p>
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
