import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { viteSingleFile } from "vite-plugin-singlefile";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import type { Plugin } from "vite";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const styleThumbnailDir = path.resolve(__dirname, "../backend/public/style-thumbnails");

function styleThumbnailDevServer(): Plugin {
    return {
        name: "manju-style-thumbnails-dev-server",
        apply: "serve",
        configureServer(server) {
            server.middlewares.use("/style-thumbnails", (req, res, next) => {
                const rawUrl = req.url?.split("?")[0] ?? "";
                let fileName: string;
                try {
                    fileName = decodeURIComponent(rawUrl).replace(/^\/+/, "");
                } catch {
                    next();
                    return;
                }

                if (!fileName || fileName.includes("/") || fileName.includes("\\") || fileName.includes("..")) {
                    next();
                    return;
                }

                const filePath = path.resolve(styleThumbnailDir, fileName);
                if (!filePath.startsWith(`${styleThumbnailDir}${path.sep}`)) {
                    next();
                    return;
                }

                fs.stat(filePath, (statError, stat) => {
                    if (statError || !stat.isFile()) {
                        next();
                        return;
                    }
                    res.setHeader("Content-Type", "image/png");
                    res.setHeader("Content-Length", String(stat.size));
                    fs.createReadStream(filePath).pipe(res);
                });
            });
        },
    };
}

export default defineConfig({
    base: "./",
    plugins: [react(), tailwindcss(), styleThumbnailDevServer(), viteSingleFile()],
    server: {
        port: 5174,
    },
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
