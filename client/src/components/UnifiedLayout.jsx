import React, { useState, useRef, useEffect } from 'react';
import { Outlet, Link, useNavigate, useLocation } from 'react-router-dom';
import { Navbar, Nav, NavDropdown, Container } from 'react-bootstrap';
import { useAuth } from '../hooks/useAuth';
import { PageTitleProvider, usePageTitleValue } from '../hooks/usePageTitle';
import { logoutUser } from '../services/apiServices';
import LoginModal from './LoginModal';
import logo from '../assets/logo.png';
import '../styles/unified-layout.css';

export default function UnifiedLayout() {
  return (
    <PageTitleProvider>
      <LayoutShell />
    </PageTitleProvider>
  );
}

function LayoutShell() {
  const { isAuthenticated, username } = useAuth();
  const { title, subtitle } = usePageTitleValue();
  const navigate = useNavigate();
  const location = useLocation();
  const navRef = useRef(null);
  const [showLogin, setShowLogin] = useState(false);

  // Routes that need full viewport height (no footer, no main padding)
  const fullBleed = location.pathname.startsWith('/validate') ||
    location.pathname.match(/^\/papers\/[^/]+\/validate/) ||
    location.pathname.match(/^\/public\/p\/[^/]+\/evidence\/[^/]+$/);

  // Set --navbar-height CSS variable so full-bleed pages can calc against it
  useEffect(() => {
    if (navRef.current) {
      const h = navRef.current.offsetHeight;
      document.documentElement.style.setProperty('--navbar-height', `${h}px`);
    }
  });

  // Auto-open login modal when redirected here after a 401 (?login=1)
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get('login') === '1') {
      setShowLogin(true);
      // Remove the query param without adding a history entry
      params.delete('login');
      const newUrl = location.pathname + (params.toString() ? `?${params}` : '');
      window.history.replaceState(null, '', newUrl);
    }
  }, []);

  const handleLogout = () => {
    logoutUser();
    window.location.reload();
  };

  const handleLoginSuccess = (redirectTo) => {
    if (redirectTo) {
      window.location.href = redirectTo;
    } else {
      window.location.reload();
    }
  };

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    }}>
      {/* Header */}
      <Navbar ref={navRef} expand="lg" variant="dark" className="unified-navbar" sticky="top">
        <Container fluid style={{ maxWidth: '1400px' }}>
          <Navbar.Brand as={Link} to="/public/papers">
            <img src={logo} alt="" style={{ height: '24px', width: 'auto', marginRight: '0.5rem', verticalAlign: 'middle' }} />
            {title || 'Paper Data Linking'}
          </Navbar.Brand>

          <Navbar.Toggle aria-controls="unified-nav" />

          <Navbar.Collapse id="unified-nav">
            {/* Public links — always visible, left side */}
            <Nav className="me-auto">
              <Nav.Link as={Link} to="/public/papers">Papers</Nav.Link>
              <Nav.Link as={Link} to="/public/about">About</Nav.Link>
            </Nav>

            {/* Right side — monitor menu for all users, internal tools/auth extras when logged in */}
            <Nav>
              <NavDropdown title="Monitor" id="nav-monitor" align="end">
                <NavDropdown.Item as={Link} to="/monitoring">System</NavDropdown.Item>
                {isAuthenticated && (
                  <NavDropdown.Item as={Link} to="/monitoring/batch">Batch Jobs</NavDropdown.Item>
                )}
              </NavDropdown>

              {isAuthenticated && (
                <>
                  <NavDropdown title="Validate" id="nav-validate" align="end">
                    <NavDropdown.Item as={Link} to="/papers/validation-queue">Instruments</NavDropdown.Item>
                    <NavDropdown.Item as={Link} to="/phenomena-validation">Phenomena</NavDropdown.Item>
                  </NavDropdown>

                  <NavDropdown title={username || 'Account'} id="nav-user" align="end">
                    <NavDropdown.Item as={Link} to="/profile">Profile</NavDropdown.Item>
                    <NavDropdown.Divider />
                    <NavDropdown.Item onClick={handleLogout}>Logout</NavDropdown.Item>
                  </NavDropdown>
                </>
              )}
              {!isAuthenticated && (
                <Nav.Link onClick={() => setShowLogin(true)} className="btn-login" role="button">
                  Log In
                </Nav.Link>
              )}
            </Nav>
          </Navbar.Collapse>
        </Container>
      </Navbar>

      {/* Login modal */}
      <LoginModal
        show={showLogin}
        onHide={() => setShowLogin(false)}
        onSuccess={handleLoginSuccess}
      />

      {/* Main content */}
      <main className={`unified-main${fullBleed ? ' full-bleed' : ''}`}>
        <div className="unified-main-inner">
          <Outlet />
        </div>
      </main>

      {/* Footer — hidden on full-bleed pages */}
      {!fullBleed && <footer className="unified-footer">
        <div className="unified-footer-inner">
          <div>
            <div style={{ marginBottom: '0.4rem' }}>
              <span style={{
                fontWeight: '700',
                color: '#e74c3c',
                fontSize: 'var(--font-2xl, 1.575rem)',
                letterSpacing: '1px',
              }}>HDRL</span>
            </div>
            <div style={{
              fontSize: 'var(--font-sm, 0.84rem)',
              color: 'rgba(255,255,255,0.6)',
              lineHeight: '1.5',
            }}>
              NASA Heliophysics Digital Resource Library
            </div>
            <div style={{
              fontSize: 'var(--font-xs, 0.7875rem)',
              color: 'rgba(255,255,255,0.4)',
              marginTop: '0.3rem',
            }}>
              Linking research papers with heliophysics observations
            </div>
          </div>

          <div style={{ display: 'flex', gap: '2rem', fontSize: 'var(--font-sm, 0.84rem)' }}>
            <a href="https://helio.data.nasa.gov/about" target="_blank" rel="noopener noreferrer">
              About HDRL
            </a>
            <a href="https://helio.data.nasa.gov" target="_blank" rel="noopener noreferrer">
              Helio Data Portal
            </a>
          </div>
        </div>
      </footer>}
    </div>
  );
}
