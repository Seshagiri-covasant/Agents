// File: src/ChatMessage.js
// Updated to better handle htmlContent

import React from 'react';

const ChatMessage = ({ msg }) => {
  const hasHtmlContent = msg.htmlContent && msg.htmlContent.trim() !== '';

  return (
    <div
      data-message-id={`message-${msg.id}`}
      className={`message ${msg.sender} ${msg.type || ''} ${msg.isStreamingDone ? 'streaming-done' : ''}`}
    >
      {/* Render text content first */}
      {msg.text && <span className="message-content">{msg.text}</span>}
      {hasHtmlContent && (
        <div 
          className="html-content-wrapper" 
          dangerouslySetInnerHTML={{ __html: msg.htmlContent }} 
        />
      )}
      
      {/* Streaming cursor for assistant messages that are not yet done */}
      {msg.sender === 'assistant' && !msg.isStreamingDone &&(
        <span className="cursor" />
      )}
    </div>
  );
};

export default ChatMessage;
