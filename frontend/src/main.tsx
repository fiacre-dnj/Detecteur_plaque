import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { applyTheme, loadTheme } from "./shared/lib/theme";
import "./index.css";

/**
 * Le thème est posé **avant** le premier rendu.
 *
 * L'usage courant serait un petit script en ligne dans `index.html`, qui
 * s'exécute avant même le bundle. La CSP du service (`default-src 'self'`)
 * l'interdit, et l'assouplir pour une préférence de couleur serait un mauvais
 * échange. Ici, l'attribut est posé à l'import du module, donc avant que React
 * ne peigne quoi que ce soit : l'écran ne clignote pas.
 */
applyTheme(loadTheme());

const container = document.getElementById("root");
if (!container) {
  // Impossible en pratique — mais échouer avec un message clair vaut mieux
  // qu'un `!` non justifié qui produirait un « null is not an object ».
  throw new Error("L'élément racine #root est absent de index.html.");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
