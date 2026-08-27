/**
 * L'instant d'un fait, tel qu'il s'écrit — **du temps de scène, jamais une heure**.
 *
 * Dans `shared/` parce que trois features datent des faits ponctuels : le registre,
 * la chronologie des franchissements et les alertes. Une feature n'importe jamais
 * une autre feature ; sans ce module, la troisième aurait recopié la fonction, et
 * le dépôt porte déjà deux `formatSceneTime` de sorties différentes — l'un rend
 * `mm:ss`, l'autre `mm:ss.d`. Une troisième copie aurait fini par en rendre une
 * quatrième.
 *
 * `results-dashboard/model/labels.ts` réexporte celle-ci pour ne rien changer à
 * son API publique, dont le registre dépend.
 */

/**
 * Un **instant** de scène en `mm:ss.d` — au dixième de seconde.
 *
 * Distinct du `mm:ss` d'une fenêtre de présence, et les deux cohabitent pour une
 * raison précise : « vu de 00:55 à 01:02 » se lit à la seconde, mais un
 * franchissement est ponctuel, et deux passages du même véhicule sur deux lignes
 * voisines tombent régulièrement dans la même seconde. Arrondir les afficherait à
 * la même heure, donc indistinguables, alors que le dixième dit lequel a eu lieu
 * d'abord — la seule information qui permette de retrouver le passage dans la
 * vidéo.
 *
 * Le point et non la virgule décimale française, **par alignement** : le journal
 * des franchissements écrit `00:12.4` depuis l'origine, et les deux se lisent sur
 * le même écran. Deux ponctuations pour le même instant se remarquent bien plus
 * qu'un séparateur non francisé.
 *
 * **Ce n'est pas une heure d'horloge.** C'est du temps de scène (invariant 1) :
 * `frame_index / fps`, compté depuis le début de la vidéo.
 */
export function formatSceneTimePrecise(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "--:--";
  // Tronqué et non arrondi, pour rester cohérent avec le `mm:ss` d'une fenêtre de
  // présence : un franchissement à 59 950 ms doit s'afficher 00:59.9 et non
  // 01:00.0, sinon il paraît tomber après une fenêtre qui se termine à 00:59.
  const tenths = Math.floor(ms / 100);
  const minutes = Math.floor(tenths / 600);
  const seconds = Math.floor(tenths / 10) % 60;
  return `${minutes.toString().padStart(2, "0")}:${seconds
    .toString()
    .padStart(2, "0")}.${tenths % 10}`;
}
