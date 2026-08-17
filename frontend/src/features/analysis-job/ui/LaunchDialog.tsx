/**
 * La modale de lancement : **sur quelle portion de la vidéo ?**
 *
 * Elle existe parce que « Lancer l'analyse serveur » posait une question à laquelle
 * il répondait tout seul — toujours depuis le début. Or on vient rarement de nulle
 * part : on a fait défiler la vidéo jusqu'à l'endroit qui pose problème, et c'est
 * *là* qu'on veut compter. Repartir de zéro coûtait alors les minutes qui précèdent,
 * en calcul comme en attente.
 *
 * **Un `<dialog>` natif**, comme la modale des presets et pour les mêmes raisons :
 * piégeage du focus, fermeture par Échap et inertie du fond, trois comportements
 * qu'une `div` en `position: fixed` rate presque toujours — et dont l'absence ne se
 * voit qu'au clavier ou au lecteur d'écran.
 *
 * **L'intervalle est publié en direct, pas à la validation.** Le rail du lecteur se
 * met donc à jour pendant qu'on tape ou qu'on choisit, ce qui est tout l'intérêt de
 * l'avoir dessiné là : on voit *où* tombent ses bornes au lieu de les imaginer.
 * `Annuler` remet ce qui était en place à l'ouverture — sans cette restauration,
 * fermer la modale laisserait un intervalle qu'on venait justement de renoncer à
 * poser, et l'analyse suivante partirait dessus.
 */

import { useEffect, useRef, useState } from "react";
import { Clapperboard, Crosshair, Scissors } from "lucide-react";

import {
  FULL_RANGE,
  MIN_RANGE_MS,
  clampRange,
  formatTimecode,
  parseTimecode,
  rangeDurationMs,
  type AnalysisRange,
} from "@/entities/analysis-range";
import { Button } from "@/shared/ui/Button";

/**
 * Les trois façons de répondre à la question, et **pourquoi pas une de plus**.
 *
 * « Depuis le début » et « à partir d'ici » sont deux cas particuliers d'un
 * intervalle : on pourrait n'offrir que le troisième. Ils restent séparés parce
 * qu'ils répondent en un clic à ce qu'on veut faire neuf fois sur dix, là où le
 * troisième demande de lire, saisir et vérifier deux valeurs. Un écran qui fait
 * payer le cas courant au prix du cas rare est un écran mal réglé.
 */
type LaunchMode = "full" | "fromHere" | "custom";

interface LaunchDialogProps {
  open: boolean;
  /** Durée de la vidéo, en millisecondes. `0` tant que les métadonnées manquent. */
  durationMs: number;
  /** Tête de lecture au moment de l'ouverture, en millisecondes. */
  currentTimeMs: number;
  range: AnalysisRange;
  /** Publié à chaque modification : c'est ce qui fait vivre le rail du lecteur. */
  onRangeChange: (range: AnalysisRange) => void;
  /** Lance l'analyse sur l'intervalle courant. */
  onLaunch: () => void;
  onCancel: () => void;
}

export function LaunchDialog({
  open,
  durationMs,
  currentTimeMs,
  range,
  onRangeChange,
  onLaunch,
  onCancel,
}: LaunchDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null);

  /**
   * L'intervalle tel qu'il était **à l'ouverture**, pour pouvoir y revenir.
   *
   * Un `ref` et non un state : le restaurer ne doit rien re-rendre, et le lire
   * pendant le rendu donnerait la valeur d'un rendu ultérieur.
   */
  const initial = useRef<AnalysisRange>(range);

  const [mode, setMode] = useState<LaunchMode>("full");
  /**
   * Les deux champs de saisie, gardés en **texte**.
   *
   * Reformater à chaque frappe rendrait le champ inutilisable : taper « 1:3 » pour
   * arriver à « 1:30 » verrait le premier état corrigé en « 01:03 », et le curseur
   * sauterait. Le texte reste donc tel qu'il est tapé, et c'est `parseTimecode` qui
   * décide s'il veut dire quelque chose.
   */
  const [startText, setStartText] = useState("");
  const [endText, setEndText] = useState("");

  /**
   * L'intervalle et la durée **du dernier rendu**, lisibles depuis un effet qui ne
   * doit pas s'y abonner.
   *
   * L'amorçage ci-dessous veut *photographier* l'état à l'ouverture, pas le suivre :
   * `range` change à chaque frappe, et une dépendance dessus réécrirait les champs
   * sous les doigts de l'utilisateur. Un `ref` mis à jour à chaque rendu exprime
   * cela sans mentir à la règle des dépendances — la désactiver dirait « je sais ce
   * que je fais » à un endroit où la prochaine lecture aurait à le vérifier.
   */
  const latest = useRef({ range, durationMs });
  latest.current = { range, durationMs };

  // `showModal()` et non l'attribut `open` : seul l'appel impératif active le
  // piégeage du focus et l'inertie du fond.
  useEffect(() => {
    const element = dialog.current;
    if (element === null) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

  /**
   * Réamorce la modale **à chaque ouverture**, jamais entre deux.
   *
   * Sans le garde sur `open`, la position de lecture qui bouge derrière la modale
   * réécrirait les champs pendant qu'on les remplit. Avec, on repart de ce que
   * l'écran montre au moment où l'on pose la question — et l'intervalle déjà
   * dessiné sur le lecteur est **conservé**, sinon rouvrir la modale pour vérifier
   * ses bornes les effacerait.
   */
  useEffect(() => {
    if (!open) return;
    const { range: opened, durationMs: total } = latest.current;
    initial.current = opened;
    setMode(opened.startMs > 0 || opened.endMs !== null ? "custom" : "full");
    setStartText(formatTimecode(opened.startMs));
    setEndText(formatTimecode(opened.endMs ?? total));
  }, [open]);

  const hasDuration = Number.isFinite(durationMs) && durationMs > 0;
  /**
   * « À partir d'ici » n'a de sens qu'ailleurs qu'au début — et qu'à plus d'une
   * seconde de la fin, faute de quoi la fenêtre serait trop courte pour confirmer
   * la moindre piste. Le bouton grisé **dit laquelle des deux raisons s'applique**.
   */
  const fromHereProblem = !hasDuration
    ? "La durée de la vidéo n'est pas encore connue."
    : currentTimeMs <= 0
      ? "La lecture est déjà au début : c'est le premier choix."
      : currentTimeMs > durationMs - MIN_RANGE_MS
        ? "Il ne reste pas assez de vidéo après cette position pour compter quoi que ce soit."
        : null;

  const startMs = parseTimecode(startText);
  const endMs = parseTimecode(endText);
  const customProblem =
    startMs === null
      ? "Début illisible. Écrivez par exemple 34, 0:34 ou 1:02:03."
      : endMs === null
        ? "Fin illisible. Écrivez par exemple 5:00 ou 1:02:03."
        : endMs - startMs < MIN_RANGE_MS
          ? "La fin doit précéder le début d'au moins une seconde."
          : hasDuration && startMs >= durationMs
            ? `Le début tombe après la fin de la vidéo (${formatTimecode(durationMs)}).`
            : null;

  /** Applique un mode, et publie aussitôt l'intervalle qu'il décrit. */
  const choose = (next: LaunchMode): void => {
    setMode(next);
    if (next === "full") {
      onRangeChange(FULL_RANGE);
      return;
    }
    if (next === "fromHere") {
      onRangeChange(clampRange({ startMs: currentTimeMs, endMs: null }, durationMs));
      return;
    }
    // Passage en saisie libre : on part de ce que le rail montre déjà, pour que le
    // basculement ne déplace rien sous les yeux de l'utilisateur.
    setStartText(formatTimecode(range.startMs));
    setEndText(formatTimecode(range.endMs ?? durationMs));
  };

  /** Republie l'intervalle dès qu'une saisie devient lisible. */
  const editCustom = (start: string, end: string): void => {
    setStartText(start);
    setEndText(end);
    const from = parseTimecode(start);
    const to = parseTimecode(end);
    if (from === null || to === null || to - from < MIN_RANGE_MS) return;
    onRangeChange(clampRange({ startMs: from, endMs: to }, durationMs));
  };

  const problem = mode === "custom" ? customProblem : mode === "fromHere" ? fromHereProblem : null;

  const cancel = (): void => {
    // La restauration **avant** la fermeture : l'ordre inverse laisserait un rendu
    // afficher l'intervalle abandonné le temps d'une frame.
    onRangeChange(initial.current);
    onCancel();
  };

  return (
    <dialog
      ref={dialog}
      aria-labelledby="launch-title"
      // `onClose` couvre Échap **et** la fermeture programmée : les deux doivent
      // rendre l'intervalle d'origine, sinon échapper la modale vaudrait valider.
      onClose={cancel}
      onClick={(event) => {
        if (event.target === dialog.current) cancel();
      }}
      className="w-[min(32rem,92vw)] rounded-section bg-surface p-0 text-ink shadow-card backdrop:bg-base/70"
    >
      <div className="space-y-4 p-5">
        <header className="space-y-1">
          <h2 id="launch-title" className="text-body font-semibold">
            Lancer l'analyse
          </h2>
          <p className="text-caption text-ink-dim">
            Choisissez la portion de vidéo à analyser. Une portion plus courte est
            analysée d'autant plus vite.
          </p>
        </header>

        <div role="radiogroup" aria-labelledby="launch-title" className="space-y-2">
          <ModeCard
            icon={<Clapperboard aria-hidden="true" className="size-4" />}
            title="Toute la vidéo"
            detail={
              hasDuration
                ? `00:00 → ${formatTimecode(durationMs)} · ${formatTimecode(durationMs)} à analyser`
                : "Du début à la fin"
            }
            selected={mode === "full"}
            disabled={false}
            problem={null}
            onSelect={() => choose("full")}
          />

          <ModeCard
            icon={<Crosshair aria-hidden="true" className="size-4" />}
            title="À partir d'où j'en suis"
            detail={
              fromHereProblem === null
                ? `${formatTimecode(currentTimeMs)} → ${formatTimecode(durationMs)} · ${formatTimecode(
                    durationMs - currentTimeMs,
                  )} à analyser`
                : "Reprend l'analyse à la position de lecture"
            }
            selected={mode === "fromHere"}
            disabled={fromHereProblem !== null}
            problem={fromHereProblem}
            onSelect={() => choose("fromHere")}
          />

          <ModeCard
            icon={<Scissors aria-hidden="true" className="size-4" />}
            title="Entre deux moments précis"
            detail="Par exemple de 00:34 à 05:00"
            selected={mode === "custom"}
            disabled={!hasDuration}
            problem={hasDuration ? null : "La durée de la vidéo n'est pas encore connue."}
            onSelect={() => choose("custom")}
          >
            {/* Les champs **dans** la carte choisie, pas dans un bloc à part : ils
                n'existent que pour ce mode, et les poser ailleurs obligerait à
                faire le lien des yeux entre un choix et sa suite. */}
            <div className="mt-3 space-y-2 border-t border-line pt-3">
              <div className="grid grid-cols-2 gap-2">
                <TimeField
                  label="Début"
                  value={startText}
                  onChange={(value) => editCustom(value, endText)}
                  onUseCurrent={() => editCustom(formatTimecode(currentTimeMs), endText)}
                  currentLabel={formatTimecode(currentTimeMs)}
                />
                <TimeField
                  label="Fin"
                  value={endText}
                  onChange={(value) => editCustom(startText, value)}
                  onUseCurrent={() => editCustom(startText, formatTimecode(currentTimeMs))}
                  currentLabel={formatTimecode(currentTimeMs)}
                />
              </div>
              <p className="text-micro text-ink-dim">
                Formats acceptés : <span className="tabular">34</span> (secondes),{" "}
                <span className="tabular">0:34</span>, <span className="tabular">1:02:03</span>. Les
                bornes se déplacent aussi à la souris, sur le rail du lecteur.
              </p>
            </div>
          </ModeCard>
        </div>

        {/* Le récapitulatif, **toujours à la même place**, juste au-dessus du
            bouton : c'est la dernière chose lue avant de cliquer, et elle dit ce
            qui va réellement partir — pas ce qui a été coché. */}
        {problem === null && hasDuration && (
          <p className="rounded-input bg-elevated px-3 py-2 text-caption text-ink-muted">
            Sera analysé :{" "}
            <span className="font-medium text-ink tabular">
              {formatTimecode(range.startMs)} → {formatTimecode(range.endMs ?? durationMs)}
            </span>{" "}
            <span className="text-ink-dim tabular">
              ({formatTimecode(rangeDurationMs(range, durationMs))})
            </span>
          </p>
        )}

        {problem !== null && (
          <p role="alert" className="text-caption text-negative">
            {problem}
          </p>
        )}

        <div className="flex justify-end gap-2 border-t border-line pt-4">
          <Button variant="ghost" onClick={cancel}>
            Annuler
          </Button>
          <Button
            variant="primary"
            disabled={problem !== null}
            onClick={onLaunch}
            title={problem ?? "Envoyer la vidéo et lancer le comptage"}
          >
            Lancer l'analyse
          </Button>
        </div>
      </div>
    </dialog>
  );
}

interface ModeCardProps {
  icon: React.ReactNode;
  title: string;
  detail: string;
  selected: boolean;
  disabled: boolean;
  /** Pourquoi ce choix est indisponible — affiché **dans** la carte, pas ailleurs. */
  problem: string | null;
  onSelect: () => void;
  children?: React.ReactNode;
}

/**
 * Une des trois réponses, en carte cliquable.
 *
 * `role="radio"` sur un `<button>` et non un vrai `<input type="radio">` : la carte
 * contient des champs de saisie, et un `<label>` enveloppant en ferait un piège au
 * clic — taper dans le champ « Début » rebasculerait le choix, en boucle. Le rôle et
 * `aria-checked` rendent l'équivalent aux lecteurs d'écran.
 */
function ModeCard({
  icon,
  title,
  detail,
  selected,
  disabled,
  problem,
  onSelect,
  children,
}: ModeCardProps) {
  return (
    <div
      className={[
        "rounded-input border transition-colors",
        selected ? "border-accent bg-elevated" : "border-line bg-elevated/40",
        disabled ? "opacity-50" : "",
      ].join(" ")}
    >
      <button
        type="button"
        role="radio"
        aria-checked={selected}
        disabled={disabled}
        onClick={onSelect}
        title={problem ?? title}
        className="flex w-full items-start gap-3 p-3 text-start disabled:cursor-not-allowed"
      >
        <span
          className={[
            "mt-0.5 shrink-0",
            selected ? "text-accent" : "text-ink-dim",
          ].join(" ")}
        >
          {icon}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-small font-medium text-ink">{title}</span>
          <span className="block text-caption text-ink-dim tabular">{detail}</span>
          {problem !== null && (
            <span className="mt-1 block text-micro text-warning">{problem}</span>
          )}
        </span>
      </button>

      {/* Le contenu du mode n'est monté **que** s'il est choisi : des champs
          visibles sous une carte non cochée invitent à les remplir, puis à
          découvrir qu'ils n'ont servi à rien. */}
      {selected && children !== undefined && <div className="px-3 pb-3">{children}</div>}
    </div>
  );
}

interface TimeFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onUseCurrent: () => void;
  currentLabel: string;
}

function TimeField({ label, value, onChange, onUseCurrent, currentLabel }: TimeFieldProps) {
  return (
    <label className="block space-y-1">
      <span className="label-micro">{label}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        inputMode="numeric"
        placeholder="00:00"
        className="w-full rounded-input bg-surface px-2 py-1.5 text-small text-ink tabular placeholder:text-ink-dim"
      />
      {/* Le raccourci qui évite de recopier à la main un temps déjà affiché sous
          la vidéo — la faute de frappe la plus probable de cet écran. */}
      <button
        type="button"
        onClick={onUseCurrent}
        className="text-micro text-ink-dim underline-offset-2 hover:text-ink hover:underline"
      >
        Utiliser la position actuelle ({currentLabel})
      </button>
    </label>
  );
}
