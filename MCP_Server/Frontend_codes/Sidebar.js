    // File: src/Sidebar.js
    // Updated with Clear File Context button logic

    import React from 'react';
    import './Sidebar.css'; // Make sure you have some basic styling for .sidebar-delete-button

    function Sidebar({
        history,
        loadConversation,
        startNewChat,
        activeConversationId,
        // File Upload Props
        handleFileChange,
        isStreaming,
        fileInputRef,
        selectedFile, // The currently selected file object from input
        handleFileUpload,
        uploadStatus,
        // New Props for File Context Management
        handleDeleteFileContext, // Function to call when "Clear File Context" is clicked
        isFileContextActive      // Boolean: true if a file has been successfully uploaded and is "active"
    }) {
        // console.log("--- [SIDEBAR] Received props:", { history, activeConversationId, selectedFile, isFileContextActive, uploadStatus });

        return (
            <div className="sidebar">
                <div className="sidebar-header">
                    <button onClick={startNewChat} className="new-chat-button" disabled={isStreaming}>
                        + New Chat
                    </button>
                </div>

                <div className="sidebar-content">
                    {history && history.length > 0 ? (
                        <ul className="history-list">
                            {history.map(conv => (
                                <li
                                    key={conv.id}
                                    className={`history-item ${conv.id === activeConversationId ? 'active' : ''}`}
                                    onClick={() => !isStreaming && loadConversation(conv.id, conv.title)}
                                    title={conv.title}
                                    style={{ cursor: isStreaming ? 'not-allowed' : 'pointer' }}
                                >
                                    {conv.title}
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <div className="no-history">No chat history.</div>
                    )}
                </div>

                <div className="sidebar-upload-section">
                    <input
                        type="file"
                        onChange={handleFileChange}
                        disabled={isStreaming || isFileContextActive} // Disable if streaming or a file is already active
                        ref={fileInputRef}
                        id="sidebarFileUploadInput"
                        style={{ display: 'none' }}
                    />
                    <label 
                        htmlFor="sidebarFileUploadInput" 
                        className={`sidebar-upload-label ${isStreaming || isFileContextActive ? 'disabled' : ''}`}
                        title={isFileContextActive ? "Clear current file context to upload a new file" : "Upload a file for analysis"}
                    >
                        📜 Upload File
                    </label>

                    {selectedFile && !isFileContextActive && ( // Show selected file name only if context isn't active yet
                        <span className="sidebar-selected-file" title={selectedFile.name}>
                            {selectedFile.name.length > 25 
                                ? `${selectedFile.name.substring(0, 22)}...` 
                                : selectedFile.name
                            }
                        </span>
                    )}
                    {isFileContextActive && uploadStatus && uploadStatus.includes("Success") && (
                        <span className="sidebar-selected-file" title={uploadStatus}>
                            {/* Optionally display a generic "File Active" or part of the success message */}
                            Context: {uploadStatus.split('(')[1]?.split(')')[0] || "Active File"}
                        </span>
                    )}


                    {/* Conditional rendering for Process or Clear button */}
                    {!isFileContextActive && selectedFile && (
                        <button
                            onClick={handleFileUpload}
                            disabled={isStreaming || !selectedFile} // Disable if no file or streaming
                            className="sidebar-upload-button"
                        >
                            Process File
                        </button>
                    )}

                    {isFileContextActive && (
                        <button
                            onClick={handleDeleteFileContext}
                            disabled={isStreaming} // Only disable if actively streaming a response
                            className="sidebar-delete-button" // Add styling for this button
                            title="Clear the currently active file context"
                        >
                            Delete
                        </button>
                    )}

                    {uploadStatus && (
                        <div className={`sidebar-upload-status ${
                            uploadStatus.toLowerCase().includes('fail') || uploadStatus.toLowerCase().includes('error') 
                            ? 'error' 
                            : (uploadStatus.toLowerCase().includes('success') ? 'success' : '')
                        }`}>
                            {uploadStatus}
                        </div>
                    )}
                </div>
            </div>
        );
    }

    export default Sidebar;
