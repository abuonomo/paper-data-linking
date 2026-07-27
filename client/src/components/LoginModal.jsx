import React, { useState } from 'react';
import { Modal, Form, Button, Alert } from 'react-bootstrap';
import { FaEye, FaEyeSlash } from 'react-icons/fa';
import { loginUser } from '../services/apiServices';

export default function LoginModal({ show, onHide, onSuccess }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const response = await loginUser(username, password);
      const { access, refresh } = response.data;
      localStorage.setItem('access_token', access);
      localStorage.setItem('refresh_token', refresh);
      localStorage.setItem('username', username);
      setUsername('');
      setPassword('');
      onHide();
      onSuccess('/papers/validation-queue');
    } catch (err) {
      setError('Invalid username or password.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal show={show} onHide={onHide} centered size="sm" className="login-modal">
      <Modal.Header closeButton closeVariant="white" style={{
        background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)',
        borderBottom: '2px solid #e74c3c',
        color: 'white',
      }}>
        <Modal.Title style={{ fontSize: 'var(--font-lg, 1.1rem)', fontWeight: 600 }}>
          Log In
        </Modal.Title>
      </Modal.Header>
      <Modal.Body style={{ padding: '1.5rem' }}>
        {error && <Alert variant="danger" style={{ fontSize: 'var(--font-sm)' }}>{error}</Alert>}
        <Form onSubmit={handleSubmit}>
          <Form.Group className="mb-3">
            <Form.Label style={{ fontSize: 'var(--font-sm)', fontWeight: 500 }}>Username</Form.Label>
            <Form.Control
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              size="sm"
            />
          </Form.Group>
          <Form.Group className="mb-3">
            <Form.Label style={{ fontSize: 'var(--font-sm)', fontWeight: 500 }}>Password</Form.Label>
            <div style={{ position: 'relative' }}>
              <Form.Control
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                size="sm"
                style={{ paddingRight: '2.5rem' }}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                style={{
                  position: 'absolute',
                  right: '8px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  color: '#666',
                  padding: '2px',
                }}
              >
                {showPassword ? <FaEyeSlash size={14} /> : <FaEye size={14} />}
              </button>
            </div>
          </Form.Group>
          <Button
            type="submit"
            disabled={loading}
            style={{
              width: '100%',
              backgroundColor: '#e74c3c',
              border: 'none',
              fontSize: 'var(--font-sm)',
              fontWeight: 600,
            }}
          >
            {loading ? 'Logging in...' : 'Log In'}
          </Button>
        </Form>
      </Modal.Body>
    </Modal>
  );
}
