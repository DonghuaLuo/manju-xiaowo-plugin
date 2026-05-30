import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Trash2 } from "lucide-react";
import { API, type DesignResourceType } from "@/api";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import { errMsg } from "@/utils/async";

interface DeleteDesignButtonProps {
  projectName: string;
  resourceType: DesignResourceType;
  resourceId: string;
  onDeleted?: () => void | Promise<void>;
}

export function DeleteDesignButton({
  projectName,
  resourceType,
  resourceId,
  onDeleted,
}: DeleteDesignButtonProps) {
  const { t } = useTranslation("dashboard");
  const [checking, setChecking] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const handleRequestDelete = async () => {
    if (checking || deleting) return;
    setChecking(true);
    try {
      const usage = await API.getDesignResourceUsage(projectName, resourceType, resourceId);
      if (usage.in_use) {
        useAppStore.getState().pushToast(t("design_delete_in_use"), "warning");
        return;
      }
      setConfirmOpen(true);
    } catch (err) {
      const message = errMsg(err);
      useAppStore
        .getState()
        .pushToast(
          message.includes("已应用")
            ? t("design_delete_in_use")
            : t("design_delete_failed", { message }),
          message.includes("已应用") ? "warning" : "error",
        );
    } finally {
      setChecking(false);
    }
  };

  const handleConfirmDelete = async () => {
    setDeleting(true);
    try {
      const result = await API.deleteDesignResource(projectName, resourceType, resourceId);
      if (result.asset_fingerprints) {
        useProjectsStore.getState().updateAssetFingerprints(result.asset_fingerprints);
      }
      const failedFileCount = Math.max(
        result.failed_files?.length ?? 0,
        result.file_delete_errors?.length ?? 0,
      );
      setConfirmOpen(false);
      if (failedFileCount > 0) {
        useAppStore
          .getState()
          .pushToast(t("delete_files_partial_failed", { count: failedFileCount }), "warning");
      } else {
        useAppStore.getState().pushToast(t("design_deleted", { name: resourceId }), "success");
      }
    } catch (err) {
      const message = errMsg(err);
      useAppStore
        .getState()
        .pushToast(
          message.includes("已应用")
            ? t("design_delete_in_use")
            : t("design_delete_failed", { message }),
          message.includes("已应用") ? "warning" : "error",
        );
      setDeleting(false);
      return;
    }

    try {
      await onDeleted?.();
    } catch (err) {
      useAppStore
        .getState()
        .pushToast(t("load_failed", { message: errMsg(err) }), "error");
    } finally {
      setDeleting(false);
    }
  };

  const busy = checking || deleting;

  return (
    <>
      <button
        type="button"
        onClick={() => void handleRequestDelete()}
        disabled={busy}
        title={t("delete_design")}
        aria-label={t("delete_design")}
        className="focus-ring inline-flex h-7 w-7 items-center justify-center rounded-md text-[var(--color-text-3)] transition-colors hover:bg-[oklch(0.70_0.18_25_/_0.13)] hover:text-[oklch(0.74_0.17_25)] disabled:opacity-40"
      >
        {busy ? (
          <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin" />
        ) : (
          <Trash2 className="h-3.5 w-3.5" />
        )}
      </button>

      <ConfirmDialog
        open={confirmOpen}
        title={t("confirm_delete_design_title")}
        description={t("confirm_delete_design_desc", { name: resourceId })}
        confirmLabel={t("delete_design")}
        loadingLabel={t("deleting_design")}
        tone="danger"
        loading={deleting}
        onConfirm={handleConfirmDelete}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}
