import React from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { materialLight } from 'react-syntax-highlighter/dist/esm/styles/prism';

const CodeBlock = ({ script }) => {
  // Remove the leading and trailing ```python and ``` from the script string
  const cleanScript = script.replace(/^```python\s+|\s+```$/g, '');
//   const cleanScript = script

  // Function to copy text
    const copyToClipboard = () => {
        navigator.clipboard.writeText(cleanScript).then(() => {
            alert('Script copied to clipboard!');
        }, (err) => {
            console.error('Failed to copy: ', err);
        });
    };

    // Styles for the copy button
    const copyButtonStyle = {
        top: '5px',
        right: '5px',
        padding: '5px 10px',
        cursor: 'pointer',
        background: 'grey',
        color: "white",
        border: 'none',
        borderRadius: '5px',
    };

  // Define custom styles for SyntaxHighlighter
const customStyle = {
  ...materialLight, // Spread the existing theme styles
  'code[class*="language-"]': {
    fontSize: '14px', // Decrease font size
    whiteSpace: 'pre-wrap', // Enable wrapping
  },
  'pre[class*="language-"]': {
    margin: '0px',
    borderRadius: '5px',
    whiteSpace: 'pre-wrap', // Ensure the container allows wrapping
  },
};


  // Define styles for the scrollable container
  const containerStyle = {
    maxHeight: '400px', // Set a fixed maximum height
    overflow: 'auto', // Add scroll if content exceeds the container's height
    marginBottom: '20px', // Add some space below the container
    marginLeft: '20px', // Center the container
    border: '1px solid #ddd', // Add a border to the container
    borderRadius: '5px', // Round the corners
    boxShadow: '0 2px 4px rgba(0,0,0,0.1)', // Optional: add a subtle shadow
  };

  return (
    <div style={containerStyle}>
      <button onClick={copyToClipboard} style={copyButtonStyle} type="button">Copy</button>
      <SyntaxHighlighter language="python" style={customStyle}>
        {cleanScript}
      </SyntaxHighlighter>
    </div>
  );
};

export default CodeBlock;
