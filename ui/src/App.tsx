import { useEffect } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { startHistory } from "./api/history";
import { startLive } from "./api/live";
import { AbortConfirm, CountdownOverlay, SaveDialog } from "./components/Dialogs";
import { ConnectionBanner, FaultBanner, NavRail, TopBar } from "./components/Shell";
import { AppDataProvider } from "./state/appdata";
import { ControllerProvider } from "./state/controller";
import { ToastProvider } from "./state/toasts";
import { OperatePage } from "./pages/Operate";
import { CalibrationPage } from "./pages/Calibration";
import { HardwarePage } from "./pages/Hardware";
import { EpisodesPage } from "./pages/Episodes";
import { OrganizationPage } from "./pages/Organization";
import { SettingsPage } from "./pages/Settings";
import { NotFound } from "./pages/NotFound";

export function App() {
  useEffect(() => {
    startLive();
    startHistory();
  }, []);
  return (
    <BrowserRouter>
      <ToastProvider>
        <AppDataProvider>
          <ControllerProvider>
            <div className="app">
              <NavRail />
              <div className="app-main">
                <TopBar />
                <ConnectionBanner />
                <FaultBanner />
                <main className="app-content">
                  <Routes>
                    <Route path="/" element={<OperatePage />} />
                    <Route path="/calibration" element={<CalibrationPage />} />
                    <Route path="/hardware" element={<HardwarePage />} />
                    <Route path="/episodes" element={<EpisodesPage />} />
                    <Route path="/organization" element={<OrganizationPage />} />
                    <Route path="/settings" element={<SettingsPage />} />
                    <Route path="*" element={<NotFound />} />
                  </Routes>
                </main>
              </div>
            </div>
            <SaveDialog />
            <AbortConfirm />
            <CountdownOverlay />
          </ControllerProvider>
        </AppDataProvider>
      </ToastProvider>
    </BrowserRouter>
  );
}
