/**
 * MM Madam Chat Widget - Embeddable Version
 * 
 * Usage:
 * 1. Include this script in your website
 * 2. Set window.MM_CHAT_API_URL if using custom API endpoint
 * 3. Call MMChatWidget.init() to initialize
 */
if (window.location.origin === 'https://dev.macromicro.me') {
    window.MM_CHAT_API_URL = 'https://bop24wysqopcnedomvrl4jm3je0itxaa.lambda-url.ap-northeast-1.on.aws';
}
if (window.location.origin === 'https://bop24wysqopcnedomvrl4jm3je0itxaa.lambda-url.ap-northeast-1.on.aws') {
    window.MM_DISABLE_SYSTEM_PROMPT_TOGGLE = false;
    window.MM_DISABLE_CONFIG_TOGGLE = false;
    
    // Fetch config from backend API
    fetch('/config')
        .then(response => response.json())
        .then(config => {
            console.log('Frontend config loaded:', config);
            window.MM_HIDE_CHAT_BUBBLE = config.MM_HIDE_CHAT_BUBBLE === 'true';
            console.log('MM_HIDE_CHAT_BUBBLE value:', window.MM_HIDE_CHAT_BUBBLE);
            
            // Re-initialize widget with new config if already initialized
            if (window.MMChatWidget.instance) {
                window.MMChatWidget.instance.updateBubbleVisibility();
            }
        })
        .catch(error => {
            console.error('Failed to load frontend config:', error);
            // Fallback to default
            window.MM_HIDE_CHAT_BUBBLE = true;
            console.log('MM_HIDE_CHAT_BUBBLE fallback value:', window.MM_HIDE_CHAT_BUBBLE);
        });
}
(function() {
    'use strict';

    // CSS Styles
    const CSS_STYLES = `
        .mm-chat-widget {
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 10000;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }

        .mm-chat-bubble {
            width: 60px;
            height: 60px;
            background: transparent;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
            transition: all 0.3s ease;
            position: relative;
        }

        .mm-chat-bubble:hover {
            transform: scale(1.1);
            box-shadow: 0 6px 25px rgba(0, 0, 0, 0.4);
        }

        .mm-chat-bubble.hidden {
            display: none !important;
        }

        .mm-chat-bubble::before {
            content: '';
            background-image: url('static/chat-bubble-icon.png');
            background-size: contain;
            background-repeat: no-repeat;
            background-position: center;
            width: 60px;
            height: 60px;
            display: block;
            border: 2px solid white;
            border-radius: 50%;
        }

        .mm-chat-panel {
            position: absolute;
            bottom: 80px;
            right: 0;
            width: 600px;
            height: 600px;
            background: white;
            border-radius: 12px;
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.3);
            display: none;
            flex-direction: column;
            overflow: hidden;
            border: 1px solid #e0e0e0;
        }

        .mm-chat-panel.open {
            display: flex;
            animation: mm-slideUp 0.3s ease-out;
        }

        @keyframes mm-slideUp {
            from {
                opacity: 0;
                transform: translateY(20px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        .mm-chat-header {
            background: linear-gradient(135deg, #4260C4 0%, #4DD1BD 100%);
            color: white;
            padding: 20px 25px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .mm-chat-header > div:last-child {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .mm-chat-header h3 {
            margin: 0;
            font-size: 18px;
            font-weight: 600;
        }

        .mm-config-toggle, .mm-system-prompt-toggle {
            background: none;
            border: none;
            color: white;
            cursor: pointer;
            font-size: 20px;
            padding: 0;
            width: 30px;
            height: 30px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background 0.2s ease;
        }

        .mm-config-toggle:hover, .mm-system-prompt-toggle:hover {
            background: rgba(255, 255, 255, 0.2);
        }

        .mm-mode-switch-btn {
            background: white;
            border: 1px solid rgba(255, 255, 255, 0.3);
            color: #333;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            padding: 8px 16px;
            border-radius: 20px;
            transition: all 0.2s ease;
        }

        .mm-mode-switch-btn:hover {
            background: rgba(255, 255, 255, 0.9);
            transform: translateY(-1px);
        }

        .mm-chat-messages {
            flex: 1;
            padding: 25px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 18px;
            background: #f8f9fa;
        }

        .mm-message {
            max-width: 80%;
            padding: 16px 20px;
            border-radius: 15px;
            font-size: 15px;
            line-height: 1.5;
            position: relative;
        }

        .mm-message.user {
            background: #007bff;
            color: white;
            align-self: flex-end;
            border-bottom-right-radius: 0px;
        }

        .mm-message.assistant {
            background: white;
            color: #333;
            align-self: flex-start;
            border-bottom-left-radius: 6px;
            border: 1px solid #e0e0e0;
            margin-left: 20px;
        }

        .mm-message.assistant::before {
            content: '';
            background-image: url('static/mm-ai-icon.png');
            background-size: contain;
            background-repeat: no-repeat;
            background-position: center;
            position: absolute;
            left: -32px;
            top: -4px;
            width: 28px;
            height: 28px;
            display: block;
            border: 2px solid white;
            border-radius: 50%;
        }

        .mm-copy-button {
            position: absolute;
            top: 8px;
            right: 8px;
            background: #f0f0f0;
            border: 1px solid #ddd;
            border-radius: 6px;
            padding: 6px 10px;
            cursor: pointer;
            font-size: 12px;
            color: #666;
            display: flex;
            align-items: center;
            gap: 4px;
            transition: all 0.2s ease;
            opacity: 0;
        }

        .mm-message.assistant:hover .mm-copy-button {
            opacity: 1;
        }

        .mm-copy-button:hover {
            background: #e0e0e0;
            border-color: #ccc;
            color: #333;
        }

        .mm-copy-button.copied {
            background: #4caf50;
            border-color: #4caf50;
            color: white;
        }

        .mm-copy-button svg {
            width: 14px;
            height: 14px;
            fill: currentColor;
        }

        .mm-message-footnote {
            font-size: 11px;
            color: #888;
            margin-top: 6px;
            padding-top: 6px;
            border-top: 1px solid #f0f0f0;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .mm-token-info {
            display: flex;
            gap: 8px;
            font-family: Monaco, Consolas, monospace;
        }

        .mm-time-info {
            font-weight: 500;
            color: #667eea;
        }

        .mm-chat-input-area {
            padding: 20px 25px;
            border-top: 1px solid #e0e0e0;
            background: white;
        }

        .mm-chat-input-container {
            display: flex;
            gap: 10px;
            align-items: flex-end;
        }

        .mm-input-wrapper {
            flex: 1;
            position: relative;
            display: flex;
            align-items: center;
        }

        .mm-chat-input {
            width: 100%;
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 10px 90px 10px 15px;
            font-size: 16px;
            resize: none;
            min-height: 40px;
            max-height: 100px;
            outline: none;
            transition: border-color 0.2s ease;
            font-family: inherit;
            box-sizing: border-box;
        }

        .mm-chat-input:focus {
            border-color: #667eea;
        }

        .mm-chat-send {
            background: #667eea;
            color: white;
            border: none;
            border-radius: 10%;
            width: 40px;
            height: 40px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background 0.2s ease;
            flex-shrink: 0;
        }

        .mm-chat-send:hover:not(:disabled) {
            background: #5a6fd8;
        }

        .mm-chat-send:disabled, .mm-chat-send.disabled {
            background: #ccc;
            cursor: not-allowed;
        }

        .mm-chat-stop {
            background: #dc3545;
            color: white;
            border: none;
            border-radius: 10%;
            width: 40px;
            height: 40px;
            cursor: pointer;
            display: none;
            align-items: center;
            justify-content: center;
            transition: background 0.2s ease;
            flex-shrink: 0;
            margin-left: 10px;
        }

        .mm-chat-stop:hover {
            background: #c82333;
        }

        .mm-chat-stop.show {
            display: flex;
        }

        .mm-typing-indicator {
            display: flex;
            align-items: center;
            gap: 8px;
            color: #666;
            font-size: 14px;
            padding: 10px 16px;
            margin-left: 20px;
        }

        .mm-typing-dots {
            display: flex;
            gap: 3px;
        }

        .mm-typing-dot {
            width: 6px;
            height: 6px;
            background: #666;
            border-radius: 50%;
            animation: mm-typing 1.5s infinite;
        }

        .mm-typing-dot:nth-child(2) {
            animation-delay: 0.2s;
        }

        .mm-typing-dot:nth-child(3) {
            animation-delay: 0.4s;
        }

        @keyframes mm-typing {
            0%, 60%, 100% {
                transform: scale(1);
                opacity: 0.5;
            }
            30% {
                transform: scale(1.2);
                opacity: 1;
            }
        }

        .mm-error-message {
            background: #fee;
            color: #c53030;
            padding: 10px;
            border-radius: 8px;
            font-size: 13px;
            margin-bottom: 10px;
            border: 1px solid #fed7d7;
        }

        .mm-config-panel {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: white;
            padding: 20px;
            overflow-y: auto;
            display: none;
        }

        .mm-config-panel.open {
            display: block;
        }

        .mm-config-item {
            margin-bottom: 15px;
        }

        .mm-config-item label {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 14px;
            cursor: pointer;
        }

        .mm-config-item input[type="checkbox"] {
            width: 16px;
            height: 16px;
        }

        .mm-config-back {
            background: #667eea;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            margin-bottom: 20px;
        }


        .mm-system-prompt-modal {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background: rgba(0, 0, 0, 0.5);
            z-index: 20000;
            display: none;
            align-items: center;
            justify-content: flex-start;
            padding-left: 50px;
        }

        .mm-system-prompt-modal.open {
            display: flex;
        }

        .mm-system-prompt-content {
            background: white;
            width: 600px;
            max-width: 90vw;
            height: 80vh;
            border-radius: 12px;
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.3);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .mm-system-prompt-header {
            background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
            color: white;
            padding: 20px 25px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .mm-system-prompt-header h3 {
            margin: 0;
            font-size: 18px;
            font-weight: 600;
        }

        .mm-system-prompt-close {
            background: none;
            border: none;
            color: white;
            cursor: pointer;
            font-size: 20px;
            padding: 0;
            width: 30px;
            height: 30px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background 0.2s ease;
        }

        .mm-system-prompt-close:hover {
            background: rgba(255, 255, 255, 0.2);
        }

        .mm-system-prompt-body {
            flex: 1;
            padding: 25px;
            overflow-y: auto;
            background: #f8f9fa;
        }

        .mm-system-prompt-text {
            background: white;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 20px;
            font-family: Monaco, Consolas, monospace;
            font-size: 12px;
            line-height: 1.5;
            white-space: pre-wrap;
            word-wrap: break-word;
            color: #333;
            max-height: 100%;
            overflow-y: auto;
        }

        .mm-system-prompt-toggle {
            background: none;
            border: none;
            color: white;
            cursor: pointer;
            font-size: 16px;
            padding: 5px;
            margin-left: 5px;
            border-radius: 4px;
            transition: background 0.2s ease;
        }

        .mm-system-prompt-toggle:hover {
            background: rgba(255, 255, 255, 0.2);
        }

        .mm-welcome-popup {
            position: absolute;
            bottom: 80px;
            right: 0;
            width: 410px;
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            border-radius: 20px;
            padding: 15px;
            color: #333;
            display: none;
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.3);
            animation: mm-slideUp 0.3s ease-out;
        }

        .mm-welcome-content {
            background: rgba(255, 255, 255, 0.95);
            border: 2px #7eb3ff;
            border-radius: 15px;
            padding: 20px;
        }

        .mm-welcome-popup.open {
            display: block;
        }

        .mm-welcome-popup h3 {
            margin: 0 0 15px 0;
            font-size: 18px;
            font-weight: 600;
        }

        .mm-welcome-popup p {
            margin: 0 0 20px 0;
            font-size: 14px;
            line-height: 1.5;
            opacity: 0.9;
        }

        .mm-welcome-question {
            text-align: center;
            margin: 20px 0 15px 0;
            font-size: 16px;
            font-weight: 500;
        }

        .mm-welcome-buttons {
            display: flex;
            gap: 15px;
            justify-content: center;
        }

        .mm-welcome-btn {
            background: #5b73e8;
            border: 2px solid white;
            color: white;
            padding: 12px 24px;
            border-radius: 25px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.3s ease;
        }

        .mm-welcome-btn:hover {
            background: #4a61d1;
            border-color: white;
            transform: translateY(-2px);
        }

        @media (max-width: 768px) {
            .mm-welcome-popup {
                width: calc(100vw - 40px);
                right: -10px;
            }
        }

        @media (max-width: 768px) {
            .mm-chat-widget {
                bottom: 20px;
                right: 10px;
            }
            
            .mm-chat-panel {
                width: calc(100vw - 0px);
                height: calc(100vh - 300px);
                bottom: 70px;
                right: -10px;
            }

            .mm-system-prompt-modal {
                padding-left: 10px;
                padding-right: 10px;
            }

            .mm-system-prompt-content {
                width: 100%;
                height: 90vh;
            }
        }
    `;

    class MMChatWidget {
        constructor(config = {}) {
            this.apiUrl = config.apiUrl || window.MM_CHAT_API_URL || window.location.origin;
            this.conversationHistory = [];
            this.isOpen = false;
            this.isLoading = false;
            this.widgetContainer = null;
            this.currentMode = 'ai';
            this.abortController = null;
            this.modeSelected = false; // Track if user has selected a mode
            
            this.init();
        }

        init() {
            this.injectStyles();
            this.createWidget();
            this.bindEvents();
            this.updateConfigDependencies();
        }

        injectStyles() {
            if (document.getElementById('mm-chat-styles')) return;
            
            const style = document.createElement('style');
            style.id = 'mm-chat-styles';
            style.textContent = CSS_STYLES;
            document.head.appendChild(style);
        }

        createWidget() {
            this.widgetContainer = document.createElement('div');
            const bubbleClass = window.MM_HIDE_CHAT_BUBBLE ? 'mm-chat-bubble hidden' : 'mm-chat-bubble';
            this.widgetContainer.innerHTML = `
                <div class="mm-chat-widget" id="mmChatWidget">
                    <div class="${bubbleClass}" id="mmChatBubble"></div>
                    
                    <div class="mm-welcome-popup" id="mmWelcomePopup">
                        <div class="mm-welcome-content">
                            <h3>Hi, 歡迎使用 MM Madam 智能服務，</h3>
                            <p>Madam 可以協助你使用 財經M平方 平台之服務<br>了解總經知識、查找圖表與報告，甚至提供客服支援。</p>
                            <div class="mm-welcome-question">今天要站內查詢，還是智能問答呢？</div>
                            <div class="mm-welcome-buttons">
                                <button class="mm-welcome-btn" id="mmWelcomeSearch">站內查詢</button>
                                <button class="mm-welcome-btn" id="mmWelcomeChat">智能問答</button>
                            </div>
                        </div>
                    </div>
                    
                    <div class="mm-chat-panel" id="mmChatPanel">
                        <div class="mm-chat-header">
                            <div>
                                <h3>MM Madam</h3>
                            </div>
                            <div>
                                <button class="mm-mode-switch-btn" id="mmModeSwitchBtn">AI</button>
                                ${window.MM_DISABLE_SYSTEM_PROMPT_TOGGLE ? '' : '<button class="mm-system-prompt-toggle" id="mmSystemPromptToggle">📝</button>'}
                                ${window.MM_DISABLE_CONFIG_TOGGLE ? '' : '<button class="mm-config-toggle" id="mmConfigToggle">⚙️</button>'}
                            </div>
                        </div>
                        
                        <div class="mm-config-panel" id="mmConfigPanel">
                            <button class="mm-config-back" id="mmConfigBack">← Back to Chat</button>
                            <div class="mm-config-item">
                                <label>
                                    <input type="checkbox" id="isPaidUser" checked>
                                    💎 付費用戶
                                </label>
                            </div>
                            <div class="mm-config-item">
                                <label>
                                    <input type="checkbox" id="hasChart" checked>
                                    📊 MM圖表
                                </label>
                            </div>
                            <div class="mm-config-item">
                                <label>
                                    <input type="checkbox" id="hasQuickie" checked>
                                    💡 MM短評
                                </label>
                            </div>
                            <div class="mm-config-item">
                                <label>
                                    <input type="checkbox" id="hasBlog" checked>
                                    📝 MM部落格
                                </label>
                            </div>
                            <div class="mm-config-item">
                                <label>
                                    <input type="checkbox" id="hasEdm" checked>
                                    📮 MM獨家報告
                                </label>
                            </div>
                            <div class="mm-config-item">
                                <label>
                                    <input type="checkbox" id="hasPodcast" checked>
                                    🎙️ MM Podcast
                                </label>
                            </div>
                            <div class="mm-config-item">
                                <label>
                                    <input type="checkbox" id="hasGoogleSearch" checked>
                                    🔍 Google搜尋
                                </label>
                            </div>
                            <div class="mm-config-item">
                                <label>
                                    <input type="checkbox" id="hasHelpCenter" checked>
                                    ❓ MM幫助中心
                                </label>
                            </div>
                            <div class="mm-config-item">
                                <label>
                                    💭 記得前幾輪對話:
                                    <input type="number" id="conversationRounds" value="2" min="1" max="10" step="1" style="width: 60px; margin-left: 10px; padding: 2px 6px; border: 1px solid #ddd; border-radius: 4px;">
                                </label>
                            </div>
                            <div class="mm-config-item">
                                <label>
                                    🎯 最多相關資料筆數:
                                    <input type="number" id="nMostRelevant" value="5" min="1" max="20" step="1" style="width: 60px; margin-left: 10px; padding: 2px 6px; border: 1px solid #ddd; border-radius: 4px;">
                                </label>
                            </div>
                            <div class="mm-config-item">
                                <label>
                                    🧠 Thinking Budget:
                                    <input type="number" id="thinkingBudget" value="500" min="1000" max="20000" step="1000" style="width: 80px; margin-left: 10px; padding: 2px 6px; border: 1px solid #ddd; border-radius: 4px;">
                                    of Quality Model:
                                    <select id="qualityModel" style="width: 120px; margin-left: 10px; padding: 2px 6px; border: 1px solid #ddd; border-radius: 4px;">
                                        <option value="gemini-3-flash-preview">gemini-3-flash-preview</option>
                                        <option value="gemini-2.5-pro">gemini-2.5-pro</option>
                                        <option value="gemini-3-pro-preview">gemini-3-pro-preview</option>
                                    </select>
                                </label>
                            </div>
                        </div>
                        
                        <div class="mm-chat-messages" id="mmChatMessages">
                        </div>
                        
                        <div class="mm-chat-input-area">
                            <div class="mm-chat-input-container">
                                <div class="mm-input-wrapper">
                                    <textarea 
                                        class="mm-chat-input" 
                                        id="mmChatInput" 
                                        placeholder="Ask Madam..."
                                        rows="1"
                                    ></textarea>
                                </div>
                                <button class="mm-chat-send" id="mmChatSend">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                                        <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
                                    </svg>
                                </button>
                                <button class="mm-chat-stop" id="mmChatStop">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                                        <path d="M6 6h12v12H6z"/>
                                    </svg>
                                </button>
                            </div>
                        </div>
                    </div>
                    
                    <div class="mm-system-prompt-modal" id="mmSystemPromptModal">
                        <div class="mm-system-prompt-content">
                            <div class="mm-system-prompt-header">
                                <h3>📝 System Prompt</h3>
                                <button class="mm-system-prompt-close" id="mmSystemPromptClose">×</button>
                            </div>
                            <div class="mm-system-prompt-body">
                                <div class="mm-system-prompt-text" id="mmSystemPromptText">
                                    Loading system prompt...
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            
            document.body.appendChild(this.widgetContainer);
            this.initializeElements();
        }

        initializeElements() {
            this.bubble = document.getElementById('mmChatBubble');
            this.welcomePopup = document.getElementById('mmWelcomePopup');
            this.welcomeSearchBtn = document.getElementById('mmWelcomeSearch');
            this.welcomeChatBtn = document.getElementById('mmWelcomeChat');
            this.panel = document.getElementById('mmChatPanel');
            this.titleElement = document.querySelector('.mm-chat-header h3');
            this.modeSwitchBtn = document.getElementById('mmModeSwitchBtn');
            this.messages = document.getElementById('mmChatMessages');
            this.input = document.getElementById('mmChatInput');
            this.sendBtn = document.getElementById('mmChatSend');
            this.stopBtn = document.getElementById('mmChatStop');
            this.configToggle = document.getElementById('mmConfigToggle');
            this.configPanel = document.getElementById('mmConfigPanel');
            this.configBack = document.getElementById('mmConfigBack');
            this.systemPromptToggle = document.getElementById('mmSystemPromptToggle');
            this.systemPromptModal = document.getElementById('mmSystemPromptModal');
            this.systemPromptClose = document.getElementById('mmSystemPromptClose');
            this.systemPromptText = document.getElementById('mmSystemPromptText');
            
            this.configElements = {
                isPaidUser: document.getElementById('isPaidUser'),
                hasChart: document.getElementById('hasChart'),
                hasQuickie: document.getElementById('hasQuickie'),
                hasBlog: document.getElementById('hasBlog'),
                hasEdm: document.getElementById('hasEdm'),
                hasPodcast: document.getElementById('hasPodcast'),
                hasHelpCenter: document.getElementById('hasHelpCenter'),
                hasGoogleSearch: document.getElementById('hasGoogleSearch'),
                conversationRounds: document.getElementById('conversationRounds'),
                nMostRelevant: document.getElementById('nMostRelevant'),
                thinkingBudget: document.getElementById('thinkingBudget'),
                qualityModel: document.getElementById('qualityModel')
            };
            
            console.log('Config elements initialized:', this.configElements);
        }

        bindEvents() {
            this.bubble.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleWelcomePopup();
            });
            this.welcomeSearchBtn.addEventListener('click', () => this.selectSearchMode());
            this.welcomeChatBtn.addEventListener('click', () => this.selectChatMode());
            this.modeSwitchBtn.addEventListener('click', () => this.switchMode());
            
            // Close welcome popup when clicking outside (including the bubble)
            document.addEventListener('click', (e) => {
                if (this.welcomePopup && this.welcomePopup.classList.contains('open')) {
                    // Check if click is outside the welcome popup
                    if (!this.welcomePopup.contains(e.target)) {
                        this.welcomePopup.classList.remove('open');
                    }
                }
            });
            this.sendBtn.addEventListener('click', () => this.sendMessage());
            this.stopBtn.addEventListener('click', () => this.stopRequest());
            if (this.configToggle) {
                this.configToggle.addEventListener('click', () => this.toggleConfig());
            }
            if (this.configBack) {
                this.configBack.addEventListener('click', () => this.toggleConfig());
            }
            if (this.systemPromptToggle) {
                this.systemPromptToggle.addEventListener('click', () => this.toggleSystemPrompt());
            }
            if (this.systemPromptClose) {
                this.systemPromptClose.addEventListener('click', () => this.closeSystemPrompt());
            }
            if (this.systemPromptModal) {
                this.systemPromptModal.addEventListener('click', (e) => {
                    if (e.target === this.systemPromptModal) {
                        this.closeSystemPrompt();
                    }
                });
            }
            
            this.input.addEventListener('keydown', () => {
                // Enter key now only creates new lines, doesn't send message
                // Users must click the send button to send messages
            });

            this.input.addEventListener('input', () => {
                this.autoResizeTextarea();
                this.updateSendButtonState();
            });

            this.configElements.isPaidUser.addEventListener('change', () => {
                this.updateConfigDependencies();
            });

            this.autoResizeTextarea();
            this.updateSendButtonState();
        }

        updateConfigDependencies() {
            const isPaid = this.configElements.isPaidUser.checked;

            if (!isPaid) {
                // Store current state before disabling
                if (!this.savedFeatureStates) {
                    this.savedFeatureStates = {};
                    ['hasChart', 'hasQuickie', 'hasBlog', 'hasEdm', 'hasPodcast', 'hasGoogleSearch'].forEach(key => {
                        this.savedFeatureStates[key] = this.configElements[key].checked;
                    });
                }
            }

            ['hasChart', 'hasQuickie', 'hasBlog', 'hasEdm', 'hasPodcast', 'hasGoogleSearch'].forEach(key => {
                this.configElements[key].disabled = !isPaid;
                if (!isPaid) {
                    this.configElements[key].checked = false;
                } else if (this.savedFeatureStates && this.savedFeatureStates[key] !== undefined) {
                    // Restore previous state when re-enabling
                    this.configElements[key].checked = this.savedFeatureStates[key];
                }
            });

            // Clear saved states after restoring
            if (isPaid && this.savedFeatureStates) {
                this.savedFeatureStates = null;
            }
        }

        setMode(mode) {
            this.currentMode = mode;
            
            // Clear all messages when switching between modes
            this.conversationHistory = [];
            this.clearAllMessages();
            
            // Update placeholder based on mode
            if (this.currentMode === 'ai') {
                this.input.placeholder = 'Ask Madam...';
            } else {
                this.input.placeholder = 'Search...';
            }
            
            // Update title based on mode
            this.updateTitle();
        }

        updateTitle() {
            if (this.titleElement) {
                if (this.currentMode === 'search') {
                    this.titleElement.textContent = 'MM Madam - 站內查詢';
                } else {
                    this.titleElement.textContent = 'MM Madam - 智能問答';
                }
            }
            
            // Update switch button text
            if (this.modeSwitchBtn) {
                if (this.currentMode === 'search') {
                    this.modeSwitchBtn.textContent = '換至 智能問答';
                } else {
                    this.modeSwitchBtn.textContent = '換至 站內查詢';
                }
            }
        }

        switchMode() {
            // Switch between AI and Search modes
            const newMode = this.currentMode === 'ai' ? 'search' : 'ai';
            this.setMode(newMode);
        }

        autoResizeTextarea() {
            this.input.style.height = 'auto';
            this.input.style.height = Math.min(this.input.scrollHeight, 100) + 'px';
        }

        updateSendButtonState() {
            const hasText = this.input.value.trim().length > 0;
            if (hasText) {
                this.sendBtn.disabled = false;
                this.sendBtn.classList.remove('disabled');
            } else {
                this.sendBtn.disabled = true;
                this.sendBtn.classList.add('disabled');
            }
        }

        showWelcomePopup() {
            // Close chat panel if open
            this.panel.classList.remove('open');
            this.welcomePopup.classList.add('open');
        }

        toggleWelcomePopup() {
            // If chat panel is open, toggle it instead of showing welcome popup
            if (this.panel.classList.contains('open')) {
                this.toggleChat();
                return;
            }
            
            // If user has already selected a mode, just toggle chat directly
            if (this.modeSelected) {
                this.toggleChat();
                return;
            }
            
            // Otherwise show/hide welcome popup
            if (this.welcomePopup.classList.contains('open')) {
                this.welcomePopup.classList.remove('open');
            } else {
                this.welcomePopup.classList.add('open');
            }
        }

        selectSearchMode() {
            this.currentMode = 'search';
            this.modeSelected = true;
            this.welcomePopup.classList.remove('open');
            this.setMode('search');
            this.toggleChat();
        }

        selectChatMode() {
            this.currentMode = 'ai';
            this.modeSelected = true;
            this.welcomePopup.classList.remove('open');
            this.setMode('ai');
            this.toggleChat();
        }

        toggleChat() {
            this.isOpen = !this.isOpen;
            this.panel.classList.toggle('open', this.isOpen);
            if (this.isOpen) {
                this.input.focus();
            }
        }

        closeChat() {
            this.isOpen = false;
            this.panel.classList.remove('open');
            this.welcomePopup.classList.remove('open');
            this.configPanel.classList.remove('open');
            this.systemPromptModal.classList.remove('open');
        }

        toggleConfig() {
            this.configPanel.classList.toggle('open');
            
            // Hide/show chat messages and input area when config is toggled
            const isConfigOpen = this.configPanel.classList.contains('open');
            if (isConfigOpen) {
                this.messages.style.display = 'none';
                document.querySelector('.mm-chat-input-area').style.display = 'none';
            } else {
                this.messages.style.display = 'flex';
                document.querySelector('.mm-chat-input-area').style.display = 'block';
            }
        }

        async toggleSystemPrompt() {
            const isOpen = this.systemPromptModal.classList.contains('open');
            if (isOpen) {
                this.closeSystemPrompt();
            } else {
                await this.openSystemPrompt();
            }
        }

        async openSystemPrompt() {
            this.systemPromptModal.classList.add('open');
            await this.loadSystemPrompt();
        }

        closeSystemPrompt() {
            this.systemPromptModal.classList.remove('open');
        }

        async loadSystemPrompt() {
            try {
                this.systemPromptText.textContent = 'Loading system prompt...';
                
                const response = await fetch(`${this.apiUrl}/system-prompt`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        message: this.input.value.trim() || 'Sample message',
                        config: this.getConfig()
                    })
                });

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const data = await response.json();
                this.systemPromptText.textContent = data.system_prompt;
                
            } catch (error) {
                console.error('System prompt error:', error);
                this.systemPromptText.textContent = 'Error loading system prompt. Please try again.';
            }
        }

        getConfig() {
            console.log('thinkingBudget element:', this.configElements.thinkingBudget);
            console.log('thinkingBudget value:', this.configElements.thinkingBudget?.value);
            console.log('thinkingBudget parsed:', this.configElements.thinkingBudget?.value !== '' ? parseInt(this.configElements.thinkingBudget?.value) : 500);
            
            return {
                is_paid_user: this.configElements.isPaidUser.checked,
                has_chart: this.configElements.hasChart.checked,
                has_quickie: this.configElements.hasQuickie.checked,
                has_blog: this.configElements.hasBlog.checked,
                has_edm: this.configElements.hasEdm.checked,
                has_podcast: this.configElements.hasPodcast.checked,
                has_help_center: this.configElements.hasHelpCenter.checked,
                has_google_search: this.configElements.hasGoogleSearch.checked,
                conversation_rounds: parseInt(this.configElements.conversationRounds.value) || 1,
                N_most_relevant: parseInt(this.configElements.nMostRelevant.value) || 5,
                thinking_budget: this.configElements.thinkingBudget.value !== '' ? parseInt(this.configElements.thinkingBudget.value) : 500,
                quality_model: this.configElements.qualityModel.value || 'gemini-3-flash-preview'
            };
        }

        getGA4SubLevel() {
            try {
                // Try to access ga4_custom.user_properties.sub_level directly
                if (typeof window.ga4_custom !== 'undefined' && 
                    window.ga4_custom.user_properties && 
                    window.ga4_custom.user_properties.sub_level) {
                    console.log('Found GA4 sub_level:', window.ga4_custom.user_properties.sub_level);
                    return window.ga4_custom.user_properties.sub_level;
                }
                
                // Alternative: check for dataLayer
                if (typeof dataLayer !== 'undefined' && Array.isArray(dataLayer)) {
                    for (const item of dataLayer.reverse()) {
                        if (item.user_properties && item.user_properties.sub_level) {
                            console.log('Found sub_level in dataLayer:', item.user_properties.sub_level);
                            return item.user_properties.sub_level;
                        }
                        if (item.ga4_custom && item.ga4_custom.user_properties && item.ga4_custom.user_properties.sub_level) {
                            console.log('Found ga4_custom sub_level in dataLayer:', item.ga4_custom.user_properties.sub_level);
                            return item.ga4_custom.user_properties.sub_level;
                        }
                    }
                }
                
                console.log('GA4 sub_level not found');
                return null;
            } catch (error) {
                console.log('Could not retrieve GA4 sub_level:', error);
                return null;
            }
        }

        getUserId() {
            return 1001000;
        }

        addMessage(content, role = 'user', tokenData = null, markdown = null) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `mm-message ${role}`;
            messageDiv.innerHTML = content;

            // Add copy button for assistant messages
            if (role === 'assistant') {
                // Store markdown as data attribute if provided
                if (markdown) {
                    messageDiv.setAttribute('data-markdown', markdown);
                }

                // Create copy button
                const copyButton = document.createElement('button');
                copyButton.className = 'mm-copy-button';
                copyButton.innerHTML = `
                    <svg viewBox="0 0 24 24" class="copy-icon">
                        <path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
                    </svg>
                    <span class="copy-text">Copy</span>
                    <svg viewBox="0 0 24 24" class="check-icon" style="display: none;">
                        <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                    </svg>
                `;
                copyButton.addEventListener('click', () => this.copyMarkdown(copyButton, messageDiv));
                messageDiv.appendChild(copyButton);
            }

            // Add footnote for assistant messages if token data is provided
            if (role === 'assistant' && tokenData) {
                const footnoteDiv = document.createElement('div');
                footnoteDiv.className = 'mm-message-footnote';
                footnoteDiv.innerHTML = `
                    <div class="mm-token-info">
                        <span>${tokenData.token_usage.prompt_tokens.toLocaleString()} input</span>
                        <span>${tokenData.token_usage.completion_tokens.toLocaleString()} output</span>
                        ${tokenData.token_usage.thinking_tokens > 0 ? `<span>${tokenData.token_usage.thinking_tokens.toLocaleString()} thinking</span>` : ''}
                        <span>${tokenData.token_usage.total_tokens.toLocaleString()} tokens</span>
                        <span>💰 $${tokenData.cost ? tokenData.cost.toFixed(3) : '0.000'}</span>
                    </div>
                    <div class="mm-time-info">⏱️ ${tokenData.response_time ? tokenData.response_time.toFixed(2) : '0.00'}s</div>
                `;
                messageDiv.appendChild(footnoteDiv);
            }

            this.messages.appendChild(messageDiv);
            this.scrollToBottom();
        }

        async copyMarkdown(button, messageDiv) {
            const markdown = messageDiv.getAttribute('data-markdown');
            if (!markdown) {
                console.error('No markdown content found');
                return;
            }

            try {
                // Use modern Clipboard API
                await navigator.clipboard.writeText(markdown);

                // Visual feedback
                const copyIcon = button.querySelector('.copy-icon');
                const checkIcon = button.querySelector('.check-icon');
                const copyText = button.querySelector('.copy-text');

                // Show success state
                copyIcon.style.display = 'none';
                checkIcon.style.display = 'block';
                copyText.textContent = 'Copied!';
                button.classList.add('copied');

                // Reset after 2 seconds
                setTimeout(() => {
                    copyIcon.style.display = 'block';
                    checkIcon.style.display = 'none';
                    copyText.textContent = 'Copy';
                    button.classList.remove('copied');
                }, 2000);

            } catch (err) {
                console.error('Failed to copy:', err);

                // Fallback for older browsers
                const textArea = document.createElement('textarea');
                textArea.value = markdown;
                textArea.style.position = 'fixed';
                textArea.style.left = '-999999px';
                document.body.appendChild(textArea);
                textArea.select();

                try {
                    document.execCommand('copy');
                    // Show success feedback
                    const copyText = button.querySelector('.copy-text');
                    copyText.textContent = 'Copied!';
                    setTimeout(() => {
                        copyText.textContent = 'Copy';
                    }, 2000);
                } catch (err2) {
                    console.error('Fallback copy failed:', err2);
                } finally {
                    document.body.removeChild(textArea);
                }
            }
        }

        showTypingIndicator() {
            const typingDiv = document.createElement('div');
            typingDiv.className = 'mm-typing-indicator';
            typingDiv.id = 'mmTypingIndicator';
            typingDiv.innerHTML = `
                <div class="mm-typing-dots">
                    <div class="mm-typing-dot"></div>
                    <div class="mm-typing-dot"></div>
                    <div class="mm-typing-dot"></div>
                </div>
            `;
            this.messages.appendChild(typingDiv);
            this.scrollToBottom();
        }

        hideTypingIndicator() {
            const indicator = document.getElementById('mmTypingIndicator');
            if (indicator) {
                indicator.remove();
            }
        }

        scrollToBottom() {
            this.messages.scrollTop = this.messages.scrollHeight;
        }

        clearAllMessages() {
            // Clear all messages including the greeting
            this.messages.innerHTML = '';
        }

        showError(message) {
            const errorDiv = document.createElement('div');
            errorDiv.className = 'mm-error-message';
            errorDiv.textContent = message;
            this.messages.appendChild(errorDiv);
            this.scrollToBottom();
        }

        async sendMessage() {
            const message = this.input.value.trim();
            if (!message || this.isLoading) return;

            if (this.currentMode === 'search') {
                await this.sendSearchRequest(message);
            } else {
                await this.sendChatRequest(message);
            }
        }

        async sendSearchRequest(message) {
            this.addMessage(message, 'user');
            this.input.value = '';
            this.autoResizeTextarea();
            this.updateSendButtonState();

            this.isLoading = true;
            this.sendBtn.disabled = true;
            this.showStopButton();
            this.showTypingIndicator();

            this.abortController = new AbortController();

            try {
                const response = await fetch(`${this.apiUrl}/search`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        query: message
                    }),
                    signal: this.abortController.signal
                });

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const data = await response.json();
                
                this.hideTypingIndicator();
                this.addMessage(data.results, 'assistant');
                
            } catch (error) {
                if (error.name === 'AbortError') {
                    this.hideTypingIndicator();
                } else {
                    console.error('Search error:', error);
                    this.hideTypingIndicator();
                    this.showError('Sorry, I encountered an error during search. Please try again.');
                }
            } finally {
                this.isLoading = false;
                this.sendBtn.disabled = false;
                this.hideStopButton();
                this.abortController = null;
                this.input.focus();
            }
        }

        async sendChatRequest(message) {
            this.addMessage(message, 'user');
            this.input.value = '';
            this.autoResizeTextarea();
            this.updateSendButtonState();
            
            this.conversationHistory.push({ role: 'user', content: message });
            
            // Keep last 10 messages for context
            this.conversationHistory = this.conversationHistory.slice(-10);

            this.isLoading = true;
            this.sendBtn.disabled = true;
            this.showStopButton();
            this.showTypingIndicator();

            this.abortController = new AbortController();

            try {
                const configData = this.getConfig();
                console.log('Sending config:', configData);
                
                const response = await fetch(`${this.apiUrl}/chat`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        user_id: this.getUserId(),
                        message: message,
                        jwt: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJtYWNyb21pY3JvLm1lIiwiYXVkIjoibWFjcm9taWNyby5tZSIsInN1YiI6IjEwMDEwMDAiLCJpYXQiOjE3MzM3ODg4MDAsImV4cCI6MTg5MzQ1NjAwMH0.hJe-30wc3KwEJHluEVisjzOShB1Z8ZPobmW_mo1CgSE',
                        conversation_history: this.conversationHistory.slice(0, -1),
                        config: configData,
                        sub_level: this.getGA4SubLevel()
                    }),
                    signal: this.abortController.signal
                });

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const data = await response.json();

                this.hideTypingIndicator();
                this.addMessage(data.response, 'assistant', data, data.response_markdown);

                this.conversationHistory.push({ role: 'assistant', content: data.response });
                
            } catch (error) {
                if (error.name === 'AbortError') {
                    this.hideTypingIndicator();
                    // Remove the last user message from history since it was cancelled
                    this.conversationHistory.pop();
                } else {
                    console.error('Chat error:', error);
                    this.hideTypingIndicator();
                    this.showError('Sorry, I encountered an error. Please try again.');
                }
            } finally {
                this.isLoading = false;
                this.sendBtn.disabled = false;
                this.hideStopButton();
                this.abortController = null;
                this.input.focus();
            }
        }

        stopRequest() {
            if (this.abortController) {
                this.abortController.abort();
            }
        }

        showStopButton() {
            if (this.stopBtn) {
                this.stopBtn.classList.add('show');
                this.sendBtn.style.display = 'none';
            }
        }

        hideStopButton() {
            if (this.stopBtn) {
                this.stopBtn.classList.remove('show');
                this.sendBtn.style.display = 'flex';
            }
        }

        updateBubbleVisibility() {
            if (this.bubble) {
                if (window.MM_HIDE_CHAT_BUBBLE) {
                    this.bubble.classList.add('hidden');
                } else {
                    this.bubble.classList.remove('hidden');
                }
            }
        }
    }

    // Global API
    window.MMChatWidget = {
        instance: null,
        
        init: function(config = {}) {
            if (this.instance) {
                console.warn('MM Chat Widget already initialized');
                return this.instance;
            }
            
            this.instance = new MMChatWidget(config);
            return this.instance;
        },
        
        destroy: function() {
            if (this.instance && this.instance.widgetContainer) {
                this.instance.widgetContainer.remove();
                this.instance = null;
                
                const styles = document.getElementById('mm-chat-styles');
                if (styles) styles.remove();
            }
        }
    };

    // Auto-initialize if DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            window.MMChatWidget.init();
        });
    } else {
        window.MMChatWidget.init();
    }

})();