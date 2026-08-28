/**
 * La cloche de la barre du studio — ce qui reste des alertes quand elles sont
 * repliées.
 *
 * Elle remplace une colonne de 18 rem qui vivait à côté de la scène. Le calcul est
 * simple à énoncer : cette colonne coûtait sa largeur à la vidéo **en permanence**
 * pour une liste qu'on consulte par à-coups — la vidéo est ce qu'on regarde, la
 * liste est ce qu'on va chercher. Une cloche coûte quarante pixels et dit la même
 * chose de l'essentiel : combien, et est-ce grave.
 *
 * Deux éléments, et **aucun mot** :
 *
 * - **l'icône bascule** à `BellRing` dès qu'il y a quelque chose, `Bell` sinon. Une
 *   cloche muette et une cloche qui sonne se distinguent d'un coup d'œil, là où
 *   « 0 » et « 3 » demandent de lire un chiffre ;
 * - **la pastille porte le compte et la gravité.** Rouge dès qu'une alerte
 *   `critical` existe, orange si toutes sont `warning`. C'est la règle de tout ce
 *   module : la couleur encode la gravité, jamais la famille.
 *
 * **Elle n'est pas une région vivante.** L'annonce `aria-live` est portée par le
 * compteur du tiroir, une seule fois : deux régions vivantes pour le même nombre
 * feraient répéter chaque alerte à un lecteur d'écran. Le nom accessible de la
 * pilule — posé par `SettingsPanels` — porte le libellé, et la pastille son
 * `aria-label` chiffré.
 */

import { Bell, BellRing } from "lucide-react";

import type { Alert } from "../model/alerts";

/**
 * Au-delà, la pastille dirait « 137 » sur une pilule de quarante pixels.
 *
 * Le nombre exact reste dans le `aria-label` et dans le compteur du tiroir : c'est
 * l'encombrement qu'on borne, pas l'information.
 */
const BADGE_CEILING = 99;

export function AlertBellIcon({ alerts }: { alerts: readonly Alert[] }) {
  const Icon = alerts.length === 0 ? Bell : BellRing;
  return <Icon aria-hidden="true" className="size-4" />;
}

export function AlertBellBadge({
  alerts,
  live = false,
}: {
  alerts: readonly Alert[];
  /** L'analyse tourne-t-elle ? Décide de la seule animation de la pilule. */
  live?: boolean;
}) {
  if (alerts.length === 0) return null;

  const critical = alerts.some((alert) => alert.severity === "critical");
  const shown = alerts.length > BADGE_CEILING ? `${BADGE_CEILING}+` : String(alerts.length);

  return (
    <span
      // Un `aria-label` chiffré et non le texte tronqué : « 99+ » lu à voix haute
      // est moins clair que le nombre, et il n'y a ici aucune contrainte de place.
      aria-label={`${alerts.length} alerte${alerts.length > 1 ? "s" : ""}`}
      className={[
        "inline-flex min-w-4 items-center justify-center rounded-pill px-1",
        "text-micro font-bold leading-4 text-base tabular",
        critical ? "bg-negative" : "bg-warning",
        // La pulsation dit « il en arrive encore », et s'arrête avec l'analyse :
        // une pastille qui pulse sur un résultat figé annoncerait un mouvement qui
        // n'existe plus. `motion-safe` la retire pour qui a demandé moins
        // d'animation.
        live ? "motion-safe:animate-pulse" : "",
      ].join(" ")}
    >
      {shown}
    </span>
  );
}
