// router.tsx — Route definitions for the studio layout

import { useEffect } from "react";
import { Route, Switch, Redirect, useParams } from "wouter";
import { PluginSDK } from "xiaowo-sdk";
import { StudioLayout } from "@/components/layout";
import { StudioCanvasRouter } from "@/components/canvas/StudioCanvasRouter";
import { ProjectsPage } from "@/components/pages/ProjectsPage";
import { SystemConfigPage } from "@/components/pages/SystemConfigPage";
import { ProjectSettingsPage } from "@/components/pages/ProjectSettingsPage";
import { AssetLibraryPage } from "@/components/pages/AssetLibraryPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { ToastOverlay } from "@/components/layout/ToastOverlay";
import { API } from "@/api";
import { useProjectsStore } from "@/stores/projects-store";
import { useAssistantStore } from "@/stores/assistant-store";
import { useConfigStatusStore } from "@/stores/config-status-store";

let workspaceMaximizeState: "idle" | "pending" | "done" = "idle";

function maximizeWorkspaceWindowOnce() {
  if (workspaceMaximizeState !== "idle") return;
  workspaceMaximizeState = "pending";
  void PluginSDK.maximize()
    .then(() => {
      workspaceMaximizeState = "done";
    })
    .catch((error) => {
      workspaceMaximizeState = "idle";
      console.error("Failed to maximize plugin window on first project entry", error);
    });
}

// ---------------------------------------------------------------------------
// StudioWorkspace — loads project data and renders three-column layout
// ---------------------------------------------------------------------------

function StudioWorkspace() {
  const params = useParams<{ projectName: string }>();
  const projectName = params.projectName ?? null;
  const { setCurrentProject, setProjectDetailLoading } = useProjectsStore();

  useEffect(() => {
    if (!projectName) return;
    let cancelled = false;

    maximizeWorkspaceWindowOnce();

    // 清空上一个项目的 assistant 状态，确保会话隔离
    const assistantState = useAssistantStore.getState();
    assistantState.setSessions([]);
    assistantState.setCurrentSessionId(null);
    assistantState.setTurns([]);
    assistantState.setDraftTurn(null);
    assistantState.setSessionStatus(null);
    assistantState.setIsDraftSession(false);

    setProjectDetailLoading(true);
    API.getProject(projectName)
      .then((res) => {
        if (!cancelled) {
          setCurrentProject(projectName, res.project, res.scripts ?? {}, res.asset_fingerprints);
        }
      })
      .catch(() => {
        // Still set the project name so the UI shows something
        if (!cancelled) {
          setCurrentProject(projectName, null);
        }
      })
      .finally(() => {
        if (!cancelled) setProjectDetailLoading(false);
      });

    return () => {
      cancelled = true;
      setCurrentProject(null, null);
    };
  }, [projectName, setCurrentProject, setProjectDetailLoading]);

  return (
    <StudioLayout>
      <StudioCanvasRouter />
    </StudioLayout>
  );
}

// ---------------------------------------------------------------------------
// Top-level route tree
// ---------------------------------------------------------------------------

function ConfigStatusLoader() {
  const fetchConfigStatus = useConfigStatusStore((s) => s.fetch);
  const initialized = useConfigStatusStore((s) => s.initialized);

  useEffect(() => {
    if (initialized) return;
    let cancelled = false;
    let attempts = 0;

    const run = () => {
      if (cancelled || useConfigStatusStore.getState().initialized) return;
      attempts += 1;
      void fetchConfigStatus().finally(() => {
        if (cancelled || useConfigStatusStore.getState().initialized || attempts >= 5) return;
        window.setTimeout(run, 300);
      });
    };

    run();
    return () => {
      cancelled = true;
    };
  }, [fetchConfigStatus, initialized]);

  return null;
}

export function AppRoutes() {
  return (
    <>
      <ConfigStatusLoader />
      <Switch>
        {/* Root redirects to projects list */}
        <Route path="/">
          <Redirect to="/app/projects" />
        </Route>

        {/* /app and /app/ also redirect to projects list */}
        <Route path="/app">
          <Redirect to="/app/projects" />
        </Route>

        {/* Projects list */}
        <Route path="/app/projects">
          <ProjectsPage />
        </Route>

        {/* System settings */}
        <Route path="/app/settings">
          <SystemConfigPage />
        </Route>

        {/* Asset library */}
        <Route path="/app/assets">
          <AssetLibraryPage />
        </Route>

        {/* Project settings — full-screen, must be before the nested workspace route */}
        <Route path="/app/projects/:projectName/settings">
          <ProjectSettingsPage />
        </Route>

        {/* Studio workspace (three-column layout) */}
        <Route path="/app/projects/:projectName" nest>
          <StudioWorkspace />
        </Route>

        {/* 404 */}
        <Route>
          <NotFoundPage />
        </Route>
      </Switch>
      <ToastOverlay />
    </>
  );
}
