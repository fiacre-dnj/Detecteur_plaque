import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import "./index.css";

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
