// styles.js — Unified design language (matches public pages)

export const colors = {
  // Primary
  primaryBackground: '#fafafa',
  primaryText: '#333333',

  // Accent (navy/red from public header)
  secondaryBackground: '#16213e',
  secondaryText: '#FFFFFF',
  accent: '#e74c3c',

  // Table rows
  alternateRowBackground: '#f5f5f5',

  // Header
  headerText: '#333333',

  // Buttons
  buttonBackground: '#e74c3c',
  buttonText: '#FFFFFF',
  buttonHover: '#c0392b',

  // Links
  linkText: '#1976D2',
  linkHover: '#1565C0',

  // Borders
  border: '#dee2e6',
};

export const contentInnerStyles = {
  maxWidth: '1200px',
  margin: '0 auto',
  padding: '2rem',
};

export const headerStyles = {
  color: colors.headerText,
  fontSize: 'var(--font-4xl, 2.5rem)',
  fontWeight: '400',
  marginBottom: '1rem',
};

export const primaryText = {
  color: colors.primaryText,
  fontSize: 'var(--font-lg, 1.1rem)',
  marginBottom: '1.5rem',
};

export const buttonStyles = {
  backgroundColor: colors.buttonBackground,
  color: colors.buttonText,
  border: 'none',
  padding: '0.5rem 1rem',
  borderRadius: '4px',
  cursor: 'pointer',
  fontWeight: '600',
  fontSize: 'var(--font-base, 1rem)',
  transition: 'background-color 0.2s ease',
  textDecoration: 'none',
  display: 'inline-block',
};
