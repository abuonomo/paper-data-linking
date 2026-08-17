// src/screens/CampaignPage.jsx
//
// Validation-campaign dashboard: the reviewer's single entry point into a
// blinded claim-level review campaign. Shows per-user progress (never
// consensus or the co-reviewer's activity), gates the bulk/overlap sections
// behind calibration, and offers one-click resume at the first unjudged claim.
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchCampaignOverview } from '../services/apiServices';
import './CampaignPage.css';

const CAMPAIGN_SLUG = 'val2026';

const claimUrl = (paperId, usageId) =>
  `/campaign/papers/${paperId}/claims/${usageId}?campaign=${CAMPAIGN_SLUG}`;

const ProgressBar = ({ done, total }) => (
  <div className="campaign-progress-bar" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
    <div
      className="campaign-progress-fill"
      style={{ width: total > 0 ? `${(100 * done) / total}%` : '0%' }}
    />
  </div>
);

const PaperRow = ({ paper, locked, navigate }) => {
  const done = paper.my_judged_claims >= paper.total_claims && paper.total_claims > 0;
  const targetUsageId = paper.resume_usage_id;
  return (
    <div
      className={`campaign-paper-row ${done ? 'is-done' : ''} ${locked ? 'is-locked' : ''}`}
      onClick={() => {
        if (locked || !targetUsageId) return;
        navigate(claimUrl(paper.id, targetUsageId));
      }}
      title={locked ? 'Complete calibration first' : (done ? 'All claims judged' : 'Open at your next unjudged claim')}
    >
      <div className="campaign-paper-main">
        <span className="campaign-paper-bibcode">{paper.bibcode}</span>
        <span className="campaign-paper-title">{paper.title}</span>
      </div>
      <div className="campaign-paper-progress">
        <span className="campaign-paper-count">{paper.my_judged_claims}/{paper.total_claims} claims</span>
        <ProgressBar done={paper.my_judged_claims} total={paper.total_claims} />
      </div>
    </div>
  );
};

const PaperGroup = ({ heading, papers, locked, navigate, collapsed: defaultCollapsed = false }) => {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  if (!papers.length) return null;
  return (
    <div className="campaign-paper-group">
      <button className="campaign-group-heading" onClick={() => setCollapsed(c => !c)}>
        {collapsed ? '▸' : '▾'} {heading} ({papers.length})
      </button>
      {!collapsed && papers.map(p => (
        <PaperRow key={p.id} paper={p} locked={locked} navigate={navigate} />
      ))}
    </div>
  );
};

const CampaignPage = () => {
  const navigate = useNavigate();
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchCampaignOverview(CAMPAIGN_SLUG)
      .then(data => { if (!cancelled) setOverview(data); })
      .catch(err => {
        if (cancelled) return;
        if (err?.response?.status === 403) {
          setError('You are not a reviewer on this campaign.');
        } else if (err?.response?.status === 404) {
          setError('Campaign not found.');
        } else {
          setError('Failed to load campaign overview.');
        }
      })
      .finally(() => { if (!cancelled) setIsLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (isLoading) {
    return <div className="campaign-page"><p className="campaign-muted">Loading campaign…</p></div>;
  }
  if (error) {
    return <div className="campaign-page"><p className="campaign-error">{error}</p></div>;
  }

  const { campaign, calibration, papers, stats, resume } = overview;
  const calibrationDone = campaign.calibration_complete;
  const hasCalibration = calibration.total > 0;

  const sortPapers = (list) => {
    const inProgress = list.filter(p => p.my_judged_claims > 0 && p.my_judged_claims < p.total_claims);
    const notStarted = list.filter(p => p.my_judged_claims === 0);
    const done = list.filter(p => p.total_claims > 0 && p.my_judged_claims >= p.total_claims);
    return { inProgress, notStarted, done };
  };
  const bulk = sortPapers(papers.filter(p => p.section === 'bulk'));
  const overlap = sortPapers(papers.filter(p => p.section === 'overlap'));

  const nextCalibration = calibration.claims.find(c => !c.judged);

  return (
    <div className="campaign-page">
      <div className="campaign-header">
        <div>
          <h2>Validation campaign · {campaign.slug}</h2>
          <p className="campaign-muted">
            Blind claim review — your progress: {stats.judged_claims}/{stats.total_claims} claims
            {hasCalibration && ` · calibration ${stats.calibration_judged}/${stats.calibration_total}`}
          </p>
        </div>
        {resume && (
          <button
            className="campaign-resume-btn"
            onClick={() => navigate(claimUrl(resume.paper_id, resume.usage_id))}
          >
            Resume ▸
          </button>
        )}
      </div>

      {hasCalibration && (
        <div className={`campaign-section campaign-calibration ${calibrationDone ? 'is-done' : ''}`}>
          <h3>
            Calibration {calibrationDone ? '· complete ✓' : `· ${calibration.judged}/${calibration.total}`}
          </h3>
          <p className="campaign-muted">
            Both reviewers judge the same {calibration.total} claims first, then meet to freeze the rubric.
            {!calibrationDone && ' Bulk and overlap papers unlock when calibration is complete.'}
          </p>
          <ProgressBar done={calibration.judged} total={calibration.total} />
          {!calibrationDone && nextCalibration && (
            <button
              className="campaign-resume-btn campaign-resume-secondary"
              onClick={() => navigate(claimUrl(nextCalibration.paper_id, nextCalibration.usage_id))}
            >
              Continue calibration ▸
            </button>
          )}
        </div>
      )}

      <div className="campaign-section">
        <h3>Your papers</h3>
        {hasCalibration && !calibrationDone && (
          <p className="campaign-locked-note">Locked until calibration is complete.</p>
        )}
        <PaperGroup heading="In progress" papers={bulk.inProgress} locked={hasCalibration && !calibrationDone} navigate={navigate} />
        <PaperGroup heading="Not started" papers={bulk.notStarted} locked={hasCalibration && !calibrationDone} navigate={navigate} />
        <PaperGroup heading="Done" papers={bulk.done} locked={false} navigate={navigate} collapsed />
      </div>

      <div className="campaign-section">
        <h3>Overlap papers</h3>
        <p className="campaign-muted">
          Reviewed independently by both reviewers — please don't discuss these until the campaign's
          agreement analysis is done.
        </p>
        {hasCalibration && !calibrationDone && (
          <p className="campaign-locked-note">Locked until calibration is complete.</p>
        )}
        <PaperGroup heading="In progress" papers={overlap.inProgress} locked={hasCalibration && !calibrationDone} navigate={navigate} />
        <PaperGroup heading="Not started" papers={overlap.notStarted} locked={hasCalibration && !calibrationDone} navigate={navigate} />
        <PaperGroup heading="Done" papers={overlap.done} locked={false} navigate={navigate} collapsed />
      </div>
    </div>
  );
};

export default CampaignPage;
