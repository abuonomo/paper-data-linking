import React from 'react';
import { Link } from 'react-router-dom';

export default function PublicAbout() {
  const sectionStyle = {
    marginBottom: '2rem',
  };
  const headingStyle = {
    fontSize: 'var(--font-2xl)',
    fontWeight: '500',
    color: '#2c3e50',
    margin: '0 0 0.75rem 0',
  };
  const textStyle = {
    fontSize: 'var(--font-base)',
    color: '#444',
    lineHeight: '1.7',
    margin: '0 0 1rem 0',
    maxWidth: '720px',
  };

  return (
    <>
      <nav style={{ marginBottom: '1rem' }}>
        <Link to="/public/papers" style={{ color: '#666', textDecoration: 'none', fontSize: 'var(--font-base)', display: 'inline-flex', alignItems: 'center' }}>← Back to Papers</Link>
      </nav>
      <div style={{ maxWidth: '800px' }}>
        <div style={sectionStyle}>
          <h2 style={headingStyle}>What does this tool do?</h2>
          <p style={textStyle}>
            This application connects heliophysics research papers to the specific missions,
            instruments, and time ranges used in each study. Using a combination of natural
            language processing and expert review, we identify exactly which observations
            from missions like SDO, SOHO, STEREO, and others a paper relied on.
          </p>
          <p style={textStyle}>
            For each linked observation we provide ready-to-use SunPy/Fido search scripts,
            so researchers can quickly retrieve the exact data referenced in a paper.
          </p>
        </div>

        <div style={sectionStyle}>
          <h2 style={headingStyle}>How it works</h2>
          <ol style={{ ...textStyle, paddingLeft: '1.5rem' }}>
            <li style={{ marginBottom: '0.5rem' }}>
              Papers are ingested from the Astrophysics Data System (ADS) and analyzed to
              extract references to heliophysics instruments and time ranges.
            </li>
            <li style={{ marginBottom: '0.5rem' }}>
              Machine learning models identify candidate data-usage links between papers
              and instrument observations.
            </li>
            <li style={{ marginBottom: '0.5rem' }}>
              Domain experts review and validate these links to ensure accuracy.
            </li>
            <li style={{ marginBottom: '0.5rem' }}>
              Validated links are published here, along with metadata and download scripts.
            </li>
          </ol>
        </div>

        <div style={sectionStyle}>
          <h2 style={headingStyle}>Contact</h2>
          <p style={textStyle}>
            For questions, feedback, or collaboration inquiries, please
            contact <a href={`mailto:${import.meta.env.VITE_CONTACT_EMAIL}`} style={{ color: '#3182ce' }}>{import.meta.env.VITE_CONTACT_EMAIL}</a>.
          </p>
          <p style={textStyle}>
            This application is an alpha prototype in active development by the NASA
            Heliophysics Digital Resource Library.
          </p>
        </div>

        <div style={sectionStyle}>
          <h2 style={headingStyle}>Links</h2>
          <ul style={{ ...textStyle, paddingLeft: '1.5rem' }}>
            <li style={{ marginBottom: '0.4rem' }}>
              <a href="https://helio.data.nasa.gov/about" target="_blank" rel="noopener noreferrer" style={{ color: '#3182ce' }}>
                About HDRL
              </a>
            </li>
            <li style={{ marginBottom: '0.4rem' }}>
              <a href="https://helio.data.nasa.gov" target="_blank" rel="noopener noreferrer" style={{ color: '#3182ce' }}>
                Helio Data Portal
              </a>
            </li>
          </ul>
        </div>
      </div>
    </>
  );
}
