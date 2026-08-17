import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import UnifiedLayout from './components/UnifiedLayout';
import PaperAnalysisPage from './screens/PaperAnalysisPage';
import UsageExplorer from "./screens/UsageExplorer";
import { StreamlinedValidationInterface } from './components/StreamlinedValidationInterface';
import PaperValidationQueue from './components/PaperValidationQueue';
import PaperValidationOverview from './components/PaperValidationOverview';
import PaperValidationDetail from './components/PaperValidationDetail';
import MonitoringDashboard from './components/MonitoringDashboard';
import MonitorDashboard from './screens/MonitorDashboard';
import BatchDetailPage from './screens/BatchDetailPage';
import ProfilePage from './components/ProfilePage';
import PublicPaperUsages from './screens/PublicPaperUsages';
import PublicValidatedPapers from './screens/PublicValidatedPapers';
import PublicAbout from './screens/PublicAbout';
import PublicEvidenceView from './screens/PublicEvidenceView';
import PhenomenaValidationQueue from './components/PhenomenaValidationQueue';
import CampaignPage from './screens/CampaignPage';
import PaperPhenomenaValidation from './components/PaperPhenomenaValidation';
import PhenomenonValidationDetail from './components/PhenomenonValidationDetail';
import 'bootstrap/dist/css/bootstrap.min.css';
import 'bootstrap-icons/font/bootstrap-icons.css';
import './App.css';


const isAuthenticated = () => {
    return localStorage.getItem('access_token') !== null;
};


function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<UnifiedLayout />}>
          {/* Public routes — no auth required */}
          <Route path="/public/papers" element={<PublicValidatedPapers />} />
          <Route path="/public/p/:bibcode" element={<PublicPaperUsages />} />
          <Route path="/public/p/:bibcode/evidence/:usageId" element={<PublicEvidenceView />} />
          <Route path="/public/about" element={<PublicAbout />} />
          <Route path="/usage-explorer" element={<UsageExplorer />} />

          {/* Home redirects to public papers */}
          <Route path="/" element={<Navigate to="/public/papers" replace />} />

          {/* Auth-protected routes */}
          <Route path="/monitoring" element={<MonitoringDashboard />} />
          <Route path="/monitoring/batch" element={<RequireAuth><MonitorDashboard /></RequireAuth>} />
          <Route path="/monitoring/batch/:batchId" element={<RequireAuth><BatchDetailPage /></RequireAuth>} />
          <Route path="/profile" element={<RequireAuth><ProfilePage /></RequireAuth>} />
          <Route path="/papers/:paperId/analysis" element={<RequireAuth><PaperAnalysisPage /></RequireAuth>} />
          <Route path="/analyses/:analysisId" element={<RequireAuth><PaperAnalysisPage /></RequireAuth>} />
          <Route path="/validate" element={<RequireAuth><StreamlinedValidationInterface paperContext={undefined} /></RequireAuth>} />
          <Route path="/validate/:usageId" element={<RequireAuth><StreamlinedValidationInterface paperContext={undefined} /></RequireAuth>} />
          <Route path="/papers/validation-queue" element={<RequireAuth><PaperValidationQueue /></RequireAuth>} />
          <Route path="/papers/:paperId/validate" element={<RequireAuth><PaperValidationOverview /></RequireAuth>} />
          <Route path="/papers/:paperId/validate/phenomena/:mentionId" element={<RequireAuth><PhenomenonValidationDetail /></RequireAuth>} />
          <Route path="/papers/:paperId/validate/:usageId" element={<RequireAuth><PaperValidationDetail /></RequireAuth>} />
          <Route path="/papers/:paperId/validate/:analysisId/:usageId" element={<RequireAuth><PaperValidationDetail /></RequireAuth>} />
          <Route path="/phenomena-validation" element={<RequireAuth><PhenomenaValidationQueue /></RequireAuth>} />
          <Route path="/phenomena-validation/:paperId" element={<RequireAuth><PaperPhenomenaValidation /></RequireAuth>} />
          {/* Validation campaign: dashboard + direct claim route (bypasses the
              PaperValidationDetail wrapper so nothing config-related loads) */}
          <Route path="/campaign" element={<RequireAuth><CampaignPage /></RequireAuth>} />
          <Route path="/campaign/papers/:paperId/claims/:usageId" element={<RequireAuth><StreamlinedValidationInterface paperContext={undefined} /></RequireAuth>} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}


function RequireAuth({ children }: { children: React.ReactNode }) {
  return isAuthenticated() ? children : <Navigate to="/public/papers" replace />;
}


export default App;
