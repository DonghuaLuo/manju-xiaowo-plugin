import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { viteSingleFile } from "vite-plugin-singlefile";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
    base: "./",
    plugins: [react(), tailwindcss(), viteSingleFile()],
    resolve: {
        alias: { "@": path.resolve(__dirname, "src") },
        extensions: [".mjs", ".mts", ".ts", ".tsx", ".js", ".jsx", ".json"],
    },
    build: {
        outDir: "dist",
        emptyOutDir: true,
        assetsInlineLimit: 100000000,
        cssCodeSplit: false,
    },
    test: {
        environment: "jsdom",
        setupFiles: ["src/test/setup.ts"],
    },
});
