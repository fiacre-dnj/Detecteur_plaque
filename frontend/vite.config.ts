import babel from "@rolldown/plugin-babel";
import tailwindcss from "@tailwindcss/vite";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const src = fileURLToPath(new URL("./src", import.meta.url));

const VENDOR = ["react", "react-dom", "react-router", "@tanstack/react-query"];

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // Le React Compiler mémoïse : c'est lui qui rend `useMemo` et `useCallback`
    // inutiles pour la performance dans tout le reste du code.
    babel({ presets: [reactCompilerPreset()] }),
  ],

  // L'alias `@/*` doit rester d'accord dans TROIS fichiers : ici pour le
  // bundler, `tsconfig.app.json` pour `tsc -b`, et `tsconfig.json` racine —
  // le seul que `bun test` lit (piège 51 de prompt/13).
  resolve: { alias: { "@": src } },

  server: {
    // Lu depuis l'environnement : un outillage qui assigne un port doit obtenir
    // le serveur qu'il attend, pas celui que Vite a choisi.
    port: Number(process.env.PORT) || 5173,
    proxy: {
      // On passe par le proxy plutôt qu'en cross-origin pour rester
      // **same-origin** en développement : ni CORS ni CORP à négocier, et le
      // flux SSE traverse sans réglage.
      "/api": {
        target: process.env.BACKEND_URL || "http://127.0.0.1:8000",
        changeOrigin: true,
        // Indispensable pour le WebSocket du comptage en direct.
        ws: true,
      },
    },
  },

  build: {
    rollupOptions: {
      output: {
        // Isoler les dépendances stables dans un chunk `vendor` : elles changent
        // rarement, donc il reste en cache du navigateur entre deux
        // déploiements, alors que le code du projet, lui, change à chaque fois.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          return VENDOR.some((name) => id.includes(`node_modules/${name}`))
            ? "vendor"
            : undefined;
        },
      },
    },
    // `chunkSizeWarningLimit` est laissé au défaut : un dépassement est un
    // signal à examiner, pas une nuisance à museler.
  },
});
