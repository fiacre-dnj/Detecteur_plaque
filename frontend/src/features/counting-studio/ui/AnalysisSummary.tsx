/**
 * « Configuration système » — ce que la colonne de droite montre tant qu'aucune
 * analyse n'a produit de chiffre.
 *
 * Cette colonne était **vide** entre l'import d'une vidéo et le premier résultat :
 * une bande de 24 rem sur toute la hauteur de la scène, à côté de l'écran où l'on
 * règle tout. Le squelette du chiffre de tête vivait, lui, tout en bas de la
 * page, sous la vidéo, là où personne ne le voyait avant d'avoir défilé.
 *
 * Ce qui remplit le vide n'est pas un décor : c'est le récapitulatif des réglages
 * qui partiront au serveur au clic sur « Lancer l'analyse ». Ils vivent dans quatre
 * tiroirs différents de la barre, et les vérifier demandait d'ouvrir les quatre —
 * pendant que la place pour les lire tous d'un coup restait inoccupée juste à côté.
 *
 * Les phrases d'avertissement disent une **conséquence**, jamais un interdit :
 * lancer reste possible sans ligne tracée, et c'est `canAnalyse` — pas cet écran —
 * qui décide ce qui est permis.
 */

import type { AnalysisSummaryRow } from "../model/analysisSummary";

export function AnalysisSummary({ rows }: { rows: readonly AnalysisSummaryRow[] }) {
  return (
    <section aria-labelledby="summary-title">
      <h3 id="summary-title" className="label-micro mb-3">
        Configuration système
      </h3>
      <dl className="overflow-hidden rounded-card bg-surface shadow-card">
        {rows.map((row, index) => (
          <div
            key={row.label}
            className={`p-3 ${index > 0 ? "border-t border-line/40" : ""}`}
          >
            {/* Libellé et valeur sur la **même** rangée tant qu'ils tiennent, la
                valeur repassant dessous en fenêtre étroite (`flex-wrap`) : la
                colonne fait 24 rem et « Repérage et lecture du texte » ne tient
                pas à côté de son libellé. `min-w-0` sur la valeur, sinon un nom de
                modèle long pousse le libellé hors de la carte. */}
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <dt className="label-micro">{row.label}</dt>
              <dd
                className={`min-w-0 text-caption font-semibold ${
                  row.warning === undefined ? "text-ink" : "text-warning"
                }`}
              >
                {row.value}
              </dd>
            </div>
            {row.warning !== undefined && (
              // Pas de `role="alert"` : rien ne vient de se produire, et ces
              // phrases sont présentes dès l'arrivée sur l'écran. Une alerte
              // annoncée à l'ouverture d'une page se lit comme une panne.
              <p className="mt-1 text-micro text-ink-dim">{row.warning}</p>
            )}
          </div>
        ))}
      </dl>
    </section>
  );
}
