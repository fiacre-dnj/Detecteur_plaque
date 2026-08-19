/**
 * Routeur — **une seule route, et les pages vivent dessous**.
 *
 * Les trois pages étaient des routes enfants rendues par `<Outlet />`, donc
 * démontées à chaque changement d'onglet : quitter le Studio pour l'historique
 * suffisait à perdre la vidéo importée, le tracé et le résultat en cours. Elles
 * sont désormais montées ensemble et masquées une à une par `KeepAlivePages`, qui
 * porte aussi leur chargement paresseux — le Studio pèse son canvas d'édition et sa
 * relecture de timeline, le benchmark son tableau, l'historique sa pagination, et
 * personne ne doit payer les trois pour n'en ouvrir qu'une.
 *
 * `path: "*"` : la coquille répond à toute URL, y compris inconnue, et c'est
 * `KeepAlivePages` qui rend alors la page d'erreur — sans démonter les pages déjà
 * ouvertes, qui attendent derrière.
 */

import { createBrowserRouter } from "react-router";

import { AppShell } from "./layout/AppShell";
import { RouteError } from "./layout/RouteError";

export const router = createBrowserRouter([
  {
    path: "*",
    element: <AppShell />,
    // La frontière d'erreur de l'application : un panneau qui casse au rendu
    // n'efface pas tout l'écran sans un mot.
    errorElement: <RouteError />,
  },
]);
