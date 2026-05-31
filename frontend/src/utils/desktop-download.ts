import { PluginSDK } from "xiaowo-sdk";

type DialogFilter = { name: string; extensions: string[] };

export interface SaveBlobDialogOptions {
  title?: string;
  defaultFileName: string;
  filters?: DialogFilter[];
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

export async function saveBlobWithDialog(
  blob: Blob,
  options: SaveBlobDialogOptions,
): Promise<string | null> {
  const savePath = await PluginSDK.dialog.save({
    title: options.title,
    defaultPath: options.defaultFileName,
    filters: options.filters,
  });
  if (!savePath) return null;

  await writeBlobToPath(blob, savePath);
  return savePath;
}

export async function writeBlobToPath(blob: Blob, path: string): Promise<void> {
  if (blob.type.startsWith("text/")) {
    await PluginSDK.fs.writeTextFile(path, await blob.text(), false);
    return;
  }

  const bytes = new Uint8Array(await blob.arrayBuffer());
  await PluginSDK.fs.writeBase64File(path, bytesToBase64(bytes), false);
}

export async function offerOpenSavedFile(
  path: string,
  options: { title: string; message: string },
): Promise<void> {
  const shouldOpen = await PluginSDK.dialog.ask(options.message, {
    title: options.title,
    type: "info",
  });
  if (shouldOpen) {
    await PluginSDK.shell.open(path);
  }
}
