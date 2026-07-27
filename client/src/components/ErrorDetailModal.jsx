import React from 'react';
import { Modal, Button } from 'react-bootstrap';

/**
 * Error Detail Modal Component
 *
 * Displays detailed error information including error type, message, and traceback
 *
 * @param {boolean} show - Controls modal visibility
 * @param {function} handleClose - Function to close the modal
 * @param {object} error - Error details object containing type, message, and traceback
 */
const ErrorDetailModal = ({ show, handleClose, error }) => {
  if (!error) {
    return null;
  }

  const { type, message, traceback } = error;

  return (
    <Modal show={show} onHide={handleClose} size="lg">
      <Modal.Header closeButton>
        <Modal.Title>{type || 'Error Details'}</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        <h5>Error Message:</h5>
        <div className="alert alert-danger">{message || 'No error message available'}</div>

        {traceback && (
          <>
            <h5>Full Traceback:</h5>
            <pre className="bg-dark text-light p-3" style={{ maxHeight: '300px', overflow: 'auto' }}>
              {traceback}
            </pre>
          </>
        )}
      </Modal.Body>
      <Modal.Footer>
        <Button variant="secondary" onClick={handleClose}>
          Close
        </Button>
      </Modal.Footer>
    </Modal>
  );
};

export default ErrorDetailModal;