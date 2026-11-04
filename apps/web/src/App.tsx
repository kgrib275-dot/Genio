import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "@/app/Layout";
import { RequireAuth } from "@/app/RequireAuth";
import { Loading } from "@/components/ErrorBox";
import { Toaster } from "@/components/ui/toast";
import LoginPage from "@/pages/auth/LoginPage";
import { ForgotPasswordPage, ResetPasswordPage, VerifyEmailPage } from "@/pages/auth/RecoveryPages";
import SignupPage from "@/pages/auth/SignupPage";

const InviteAcceptPage = lazy(() => import("@/pages/auth/InviteAcceptPage"));
const DashboardPage = lazy(() => import("@/pages/dashboard/DashboardPage"));
const BuilderPage = lazy(() => import("@/pages/apps/BuilderPage"));
const AppSettingsPage = lazy(() => import("@/pages/apps/AppSettingsPage"));
const AppRunsPage = lazy(() => import("@/pages/apps/AppRunsPage"));
const RunDetailPage = lazy(() => import("@/pages/apps/RunDetailPage"));
const KnowledgePage = lazy(() => import("@/pages/knowledge/KnowledgePage"));
const ConnectorsPage = lazy(() => import("@/pages/connectors/ConnectorsPage"));
const MarketPage = lazy(() => import("@/pages/market/MarketPage"));
const MarketDetailPage = lazy(() => import("@/pages/market/MarketDetailPage"));
const WorkspacePage = lazy(() => import("@/pages/workspace/WorkspacePage"));
const SharePage = lazy(() => import("@/pages/share/SharePage"));
const TaskLinkPage = lazy(() => import("@/pages/share/TaskLinkPage"));
const TasksPage = lazy(() => import("@/pages/tasks/TasksPage"));
const LearnPage = lazy(() => import("@/pages/learn/LearnPage"));
const AppFeaturesPage = lazy(() => import("@/pages/apps/AppFeaturesPage"));
const AppLogsPage = lazy(() => import("@/pages/apps/AppLogsPage"));
const AppMonitorPage = lazy(() => import("@/pages/apps/AppMonitorPage"));
const AppApiPage = lazy(() => import("@/pages/apps/AppApiPage"));
const AppTriggersPage = lazy(() => import("@/pages/apps/AppTriggersPage"));
const DataTablesPage = lazy(() => import("@/pages/data/DataTablesPage"));
const AdminPage = lazy(() => import("@/pages/admin/AdminPage"));
const HelpPage = lazy(() => import("@/pages/help/HelpPage"));
const SettingsPage = lazy(() => import("@/pages/settings/SettingsPage"));
const ProjectsBoardPage = lazy(() => import("@/pages/projects/ProjectsBoardPage"));

export default function App() {
  return (
    <>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignupPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/verify-email" element={<VerifyEmailPage />} />
          <Route path="/invite/:token" element={<InviteAcceptPage />} />
          <Route path="/share/:token" element={<SharePage />} />
          <Route path="/t/:token" element={<TaskLinkPage />} />
          <Route
            element={
              <RequireAuth>
                <Layout />
              </RequireAuth>
            }
          >
            <Route index element={<DashboardPage />} />
            <Route path="apps/:id" element={<Navigate to="builder" replace />} />
            <Route path="apps/:id/builder" element={<BuilderPage />} />
            <Route path="apps/:id/settings" element={<AppSettingsPage />} />
            <Route path="apps/:id/runs" element={<AppRunsPage />} />
            <Route path="apps/:id/features" element={<AppFeaturesPage />} />
            <Route path="apps/:id/logs" element={<AppLogsPage />} />
            <Route path="apps/:id/monitor" element={<AppMonitorPage />} />
            <Route path="apps/:id/api" element={<AppApiPage />} />
            <Route path="apps/:id/triggers" element={<AppTriggersPage />} />
            <Route path="runs/:id" element={<RunDetailPage />} />
            <Route path="knowledge" element={<KnowledgePage />} />
            <Route path="data" element={<DataTablesPage />} />
            <Route path="data/:tableId" element={<DataTablesPage />} />
            <Route path="connectors" element={<ConnectorsPage />} />
            <Route path="market" element={<MarketPage />} />
            <Route path="market/:key" element={<MarketDetailPage />} />
            <Route path="workspace" element={<WorkspacePage />} />
            <Route path="admin" element={<AdminPage />} />
            <Route path="help" element={<HelpPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="tasks" element={<TasksPage />} />
            <Route path="learn" element={<LearnPage />} />
            <Route path="projects" element={<ProjectsBoardPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
      <Toaster />
    </>
  );
}
