import { colors, buttonStyles } from '../styles';


const Modal = ({ isOpen, onClose, children }) => {
    if (!isOpen) return null;

    const modalStyle = {
        position: 'fixed',
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        backgroundColor: colors.primaryBackground,
        padding: '20px',
        zIndex: 1000,
        overflowY: 'auto',
        maxHeight: '80vh',
        width: '50%',
        borderRadius: '8px',
        boxShadow: '0 4px 6px rgba(0, 0, 0, 0.1)',
    };

    const overlayStyle = {
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.5)',
        zIndex: 1000,
    };

    return (
        <>
            <div style={overlayStyle} onClick={onClose} />
            <div style={modalStyle}>
                <button style={buttonStyles} onClick={onClose}>Close</button>
                {children}
            </div>
        </>
    );
};

export default Modal;