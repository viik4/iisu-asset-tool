// ==UserScript==
// @name         iiSU Asset Database Organizer
// @namespace    https://github.com/viik4/iisu-asset-tool
// @version      1.0.0
// @description  Helper script to organize themed assets in Google Drive for iiSU Asset Tool database
// @author       iiSU Asset Tool
// @match        https://drive.google.com/*
// @grant        GM_addStyle
// @grant        GM_setValue
// @grant        GM_getValue
// ==/UserScript==

(function() {
    'use strict';

    // ==================== Configuration ====================

    const PLATFORMS = [
        'ANDROID', 'ARCADE', 'DREAMCAST', 'GAMECUBE', 'GAME_BOY', 'GAME_BOY_ADVANCE',
        'GAME_BOY_COLOR', 'GAME_GEAR', 'GENESIS', 'MASTER_SYSTEM', 'N64', 'NES',
        'NINTENDO_3DS', 'NINTENDO_DS', 'PC', 'PS1', 'PS2', 'PS3', 'PS4', 'PS5',
        'PSP', 'PS_VITA', 'SATURN', 'SEGA_32X', 'SEGA_CD', 'SNES', 'STEAM',
        'SWITCH', 'WII', 'WII_U', 'XBOX', 'XBOX_360', 'android_apps'
    ];

    const ASSET_FILES = ['icon.png', 'icon.jpg', 'hero_1.png', 'hero_1.jpg',
                         'hero_2.png', 'hero_2.jpg', 'title.png', 'title.jpg',
                         'slide_1.png', 'slide_2.png', 'slide_3.png', 'soundbyte.mp3'];

    // ==================== Styles ====================

    GM_addStyle(`
        #iisu-organizer-panel {
            position: fixed;
            top: 80px;
            right: 20px;
            width: 350px;
            max-height: calc(100vh - 100px);
            background: linear-gradient(135deg, #1A1E22 0%, #252A30 100%);
            border: 2px solid #00D4FF;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0, 212, 255, 0.2);
            z-index: 10000;
            font-family: 'Segoe UI', Arial, sans-serif;
            color: #FFFFFF;
            overflow: hidden;
        }

        #iisu-organizer-header {
            background: linear-gradient(90deg, #00D4FF 0%, #9575CD 50%, #FF00FF 100%);
            padding: 12px 16px;
            cursor: move;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        #iisu-organizer-header h3 {
            margin: 0;
            font-size: 14px;
            font-weight: bold;
            color: #000;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        #iisu-organizer-close {
            background: none;
            border: none;
            color: #000;
            font-size: 20px;
            cursor: pointer;
            padding: 0 4px;
        }

        #iisu-organizer-content {
            padding: 16px;
            max-height: 500px;
            overflow-y: auto;
        }

        .iisu-section {
            margin-bottom: 16px;
        }

        .iisu-section-title {
            font-size: 12px;
            color: #00D4FF;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
            padding-bottom: 4px;
            border-bottom: 1px solid #3A4048;
        }

        .iisu-input-group {
            margin-bottom: 12px;
        }

        .iisu-label {
            display: block;
            font-size: 11px;
            color: #808080;
            margin-bottom: 4px;
        }

        .iisu-input {
            width: 100%;
            padding: 8px 12px;
            background: #1A1E22;
            border: 1px solid #3A4048;
            border-radius: 6px;
            color: #FFFFFF;
            font-size: 13px;
            box-sizing: border-box;
        }

        .iisu-input:focus {
            outline: none;
            border-color: #00D4FF;
        }

        .iisu-select {
            width: 100%;
            padding: 8px 12px;
            background: #1A1E22;
            border: 1px solid #3A4048;
            border-radius: 6px;
            color: #FFFFFF;
            font-size: 13px;
            cursor: pointer;
        }

        .iisu-btn {
            padding: 10px 16px;
            border: none;
            border-radius: 6px;
            font-size: 12px;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            cursor: pointer;
            transition: all 0.2s;
            margin-right: 8px;
            margin-bottom: 8px;
        }

        .iisu-btn-primary {
            background: linear-gradient(135deg, #9575CD 0%, #FF00FF 100%);
            color: #FFF;
        }

        .iisu-btn-primary:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(149, 117, 205, 0.4);
        }

        .iisu-btn-secondary {
            background: linear-gradient(135deg, #00D4FF 0%, #007C92 100%);
            color: #FFF;
        }

        .iisu-btn-secondary:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(0, 212, 255, 0.4);
        }

        .iisu-btn-danger {
            background: transparent;
            border: 1px solid #E53935;
            color: #E53935;
        }

        .iisu-btn-danger:hover {
            background: #E53935;
            color: #FFF;
        }

        .iisu-status {
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 12px;
            margin-top: 8px;
        }

        .iisu-status-success {
            background: rgba(76, 175, 80, 0.2);
            border: 1px solid #4CAF50;
            color: #4CAF50;
        }

        .iisu-status-error {
            background: rgba(229, 57, 53, 0.2);
            border: 1px solid #E53935;
            color: #E53935;
        }

        .iisu-status-info {
            background: rgba(0, 212, 255, 0.2);
            border: 1px solid #00D4FF;
            color: #00D4FF;
        }

        .iisu-preview {
            background: #1A1E22;
            border: 1px solid #3A4048;
            border-radius: 6px;
            padding: 12px;
            font-family: monospace;
            font-size: 11px;
            color: #B0B0B0;
            max-height: 150px;
            overflow-y: auto;
            white-space: pre-wrap;
        }

        .iisu-checkbox {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
        }

        .iisu-checkbox input {
            width: 16px;
            height: 16px;
            accent-color: #00D4FF;
        }

        .iisu-toggle-btn {
            position: fixed;
            bottom: 20px;
            right: 20px;
            width: 56px;
            height: 56px;
            border-radius: 50%;
            background: linear-gradient(135deg, #00D4FF 0%, #FF00FF 100%);
            border: none;
            cursor: pointer;
            box-shadow: 0 4px 16px rgba(0, 212, 255, 0.4);
            z-index: 9999;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            color: #000;
            transition: transform 0.2s;
        }

        .iisu-toggle-btn:hover {
            transform: scale(1.1);
        }

        .iisu-help {
            font-size: 11px;
            color: #808080;
            margin-top: 4px;
        }

        .iisu-divider {
            height: 1px;
            background: linear-gradient(90deg, transparent 0%, #3A4048 50%, transparent 100%);
            margin: 16px 0;
        }
    `);

    // ==================== State ====================

    let panelVisible = false;
    let selectedFiles = [];
    let currentPath = '';

    // ==================== UI Creation ====================

    function createToggleButton() {
        const btn = document.createElement('button');
        btn.className = 'iisu-toggle-btn';
        btn.innerHTML = '🎮';
        btn.title = 'iiSU Asset Organizer';
        btn.onclick = togglePanel;
        document.body.appendChild(btn);
    }

    function createPanel() {
        const panel = document.createElement('div');
        panel.id = 'iisu-organizer-panel';
        panel.style.display = 'none';

        panel.innerHTML = `
            <div id="iisu-organizer-header">
                <h3>iiSU Asset Organizer</h3>
                <button id="iisu-organizer-close">&times;</button>
            </div>
            <div id="iisu-organizer-content">
                <div class="iisu-section">
                    <div class="iisu-section-title">Quick Actions</div>
                    <button class="iisu-btn iisu-btn-secondary" onclick="iisuOrganizer.createStructure()">
                        Create Folder Structure
                    </button>
                    <button class="iisu-btn iisu-btn-secondary" onclick="iisuOrganizer.getSelectedFiles()">
                        Get Selected Files
                    </button>
                </div>

                <div class="iisu-divider"></div>

                <div class="iisu-section">
                    <div class="iisu-section-title">Organize Assets</div>

                    <div class="iisu-input-group">
                        <label class="iisu-label">Platform</label>
                        <select id="iisu-platform" class="iisu-select">
                            ${PLATFORMS.map(p => `<option value="${p}">${p}</option>`).join('')}
                        </select>
                    </div>

                    <div class="iisu-input-group">
                        <label class="iisu-label">Game/App Name</label>
                        <input type="text" id="iisu-game-name" class="iisu-input" placeholder="e.g., Chrono Trigger">
                        <div class="iisu-help">Use the exact name you want displayed</div>
                    </div>

                    <div class="iisu-input-group">
                        <label class="iisu-label">Variant Number</label>
                        <input type="number" id="iisu-variant" class="iisu-input" value="1" min="1" max="99">
                        <div class="iisu-help">Leave as 1 for first/only version, increment for alternatives</div>
                    </div>

                    <div class="iisu-checkbox">
                        <input type="checkbox" id="iisu-skip-suffix" checked>
                        <label for="iisu-skip-suffix">Skip _1 suffix for first variant</label>
                    </div>
                </div>

                <div class="iisu-section">
                    <div class="iisu-section-title">Preview</div>
                    <div id="iisu-preview" class="iisu-preview">
                        Select options above to see folder structure...
                    </div>
                </div>

                <div class="iisu-section">
                    <button class="iisu-btn iisu-btn-primary" onclick="iisuOrganizer.createGameFolder()">
                        Create Game Folder
                    </button>
                    <button class="iisu-btn iisu-btn-primary" onclick="iisuOrganizer.moveSelectedToGame()">
                        Move Selected Files
                    </button>
                </div>

                <div id="iisu-status"></div>

                <div class="iisu-divider"></div>

                <div class="iisu-section">
                    <div class="iisu-section-title">Bulk Operations</div>
                    <button class="iisu-btn iisu-btn-secondary" onclick="iisuOrganizer.renameAssets()">
                        Rename to iiSU Format
                    </button>
                    <div class="iisu-help">Renames selected files to icon.png, hero_1.png, etc.</div>
                </div>

                <div class="iisu-section">
                    <div class="iisu-section-title">Selected Files</div>
                    <div id="iisu-selected-files" class="iisu-preview">
                        No files selected. Select files in Drive and click "Get Selected Files"
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(panel);

        // Close button
        document.getElementById('iisu-organizer-close').onclick = togglePanel;

        // Update preview on input change
        document.getElementById('iisu-platform').onchange = updatePreview;
        document.getElementById('iisu-game-name').oninput = updatePreview;
        document.getElementById('iisu-variant').oninput = updatePreview;
        document.getElementById('iisu-skip-suffix').onchange = updatePreview;

        // Make draggable
        makeDraggable(panel);
    }

    function togglePanel() {
        const panel = document.getElementById('iisu-organizer-panel');
        panelVisible = !panelVisible;
        panel.style.display = panelVisible ? 'block' : 'none';
    }

    function makeDraggable(element) {
        const header = element.querySelector('#iisu-organizer-header');
        let offsetX, offsetY, isDragging = false;

        header.onmousedown = (e) => {
            isDragging = true;
            offsetX = e.clientX - element.offsetLeft;
            offsetY = e.clientY - element.offsetTop;
        };

        document.onmousemove = (e) => {
            if (isDragging) {
                element.style.left = (e.clientX - offsetX) + 'px';
                element.style.top = (e.clientY - offsetY) + 'px';
                element.style.right = 'auto';
            }
        };

        document.onmouseup = () => {
            isDragging = false;
        };
    }

    // ==================== Helper Functions ====================

    function getFolderName() {
        const platform = document.getElementById('iisu-platform').value;
        const gameName = document.getElementById('iisu-game-name').value.trim();
        const variant = parseInt(document.getElementById('iisu-variant').value) || 1;
        const skipSuffix = document.getElementById('iisu-skip-suffix').checked;

        if (!gameName) return null;

        let folderName = gameName;
        if (variant > 1 || !skipSuffix) {
            folderName = `${gameName}_${variant}`;
        }

        return { platform, gameName, variant, folderName };
    }

    function updatePreview() {
        const preview = document.getElementById('iisu-preview');
        const info = getFolderName();

        if (!info) {
            preview.textContent = 'Enter a game name to see preview...';
            return;
        }

        preview.textContent = `📁 ${info.platform}/
  📁 ${info.folderName}/
    📄 icon.png
    📄 hero_1.png (optional)
    📄 title.png (optional)
    📄 slide_1.png (optional)`;
    }

    function showStatus(message, type = 'info') {
        const status = document.getElementById('iisu-status');
        status.className = `iisu-status iisu-status-${type}`;
        status.textContent = message;
        status.style.display = 'block';

        if (type === 'success') {
            setTimeout(() => {
                status.style.display = 'none';
            }, 3000);
        }
    }

    // ==================== Google Drive API Helpers ====================

    // Note: These functions work with Google Drive's web interface
    // They use DOM manipulation since we don't have direct API access

    function getSelectedFilesFromUI() {
        // Try to get selected items from Google Drive UI
        const selected = document.querySelectorAll('[data-id][aria-selected="true"]');
        const files = [];

        selected.forEach(el => {
            const id = el.getAttribute('data-id');
            const nameEl = el.querySelector('[data-tooltip]') || el.querySelector('.KL4NAf');
            const name = nameEl ? nameEl.textContent : 'Unknown';
            files.push({ id, name });
        });

        return files;
    }

    function getCurrentFolderFromUI() {
        // Try to get current folder path from breadcrumbs
        const breadcrumbs = document.querySelectorAll('[data-foldername]');
        const path = [];
        breadcrumbs.forEach(b => {
            const name = b.getAttribute('data-foldername') || b.textContent;
            if (name) path.push(name);
        });
        return path.join('/');
    }

    // ==================== Main Functions ====================

    window.iisuOrganizer = {
        createStructure: function() {
            const instructions = `
To create the folder structure:

1. Navigate to your iiSU Asset Database root folder
2. Create platform folders:
   ${PLATFORMS.slice(0, 10).join(', ')}...

3. Inside each platform folder, create game folders:
   - "Game Name" (first/only variant)
   - "Game Name_2" (second variant)
   - "Game Name_3" (third variant)

4. Inside each game folder, add assets:
   - icon.png (required)
   - hero_1.png (optional)
   - title.png (optional)
   - slide_1.png, slide_2.png... (optional)

The organizer will help you rename and move files!
            `;
            alert(instructions);
        },

        getSelectedFiles: function() {
            selectedFiles = getSelectedFilesFromUI();
            const display = document.getElementById('iisu-selected-files');

            if (selectedFiles.length === 0) {
                display.textContent = 'No files selected.\n\nSelect files in Drive by clicking on them (hold Ctrl/Cmd for multiple)';
                showStatus('No files selected', 'error');
            } else {
                display.textContent = selectedFiles.map(f => `📄 ${f.name}`).join('\n');
                showStatus(`Found ${selectedFiles.length} selected file(s)`, 'success');
            }
        },

        createGameFolder: function() {
            const info = getFolderName();
            if (!info) {
                showStatus('Please enter a game name', 'error');
                return;
            }

            const instructions = `
To create the game folder:

1. Navigate to: ${info.platform}/
2. Create new folder named: ${info.folderName}
3. Move your asset files into this folder
4. Rename files to iiSU format:
   - icon.png (main icon)
   - hero_1.png (banner/hero image)
   - title.png (logo)
   - slide_1.png (screenshots)

Path: ${info.platform}/${info.folderName}/
            `;

            // Copy folder name to clipboard
            navigator.clipboard.writeText(info.folderName).then(() => {
                showStatus(`Folder name "${info.folderName}" copied to clipboard!`, 'success');
                alert(instructions);
            }).catch(() => {
                alert(instructions);
            });
        },

        moveSelectedToGame: function() {
            const info = getFolderName();
            if (!info) {
                showStatus('Please enter a game name', 'error');
                return;
            }

            if (selectedFiles.length === 0) {
                showStatus('No files selected. Click "Get Selected Files" first', 'error');
                return;
            }

            const instructions = `
To move ${selectedFiles.length} file(s) to ${info.folderName}:

1. Make sure the folder exists: ${info.platform}/${info.folderName}/
2. Right-click selected files → "Move to"
3. Navigate to ${info.platform}/${info.folderName}/
4. Click "Move"

After moving, rename files to:
${selectedFiles.map((f, i) => {
    const ext = f.name.split('.').pop();
    if (i === 0) return `  ${f.name} → icon.${ext}`;
    if (i === 1) return `  ${f.name} → hero_1.${ext}`;
    if (i === 2) return `  ${f.name} → title.${ext}`;
    return `  ${f.name} → slide_${i-2}.${ext}`;
}).join('\n')}
            `;

            alert(instructions);
        },

        renameAssets: function() {
            if (selectedFiles.length === 0) {
                showStatus('No files selected. Click "Get Selected Files" first', 'error');
                return;
            }

            const renameMap = [];
            selectedFiles.forEach((f, i) => {
                const ext = f.name.split('.').pop().toLowerCase();
                const imgExt = ['png', 'jpg', 'jpeg'].includes(ext) ? ext : 'png';

                let newName;
                if (i === 0) newName = `icon.${imgExt}`;
                else if (i === 1) newName = `hero_1.${imgExt}`;
                else if (i === 2) newName = `title.${imgExt}`;
                else newName = `slide_${i - 2}.${imgExt}`;

                renameMap.push({ old: f.name, new: newName });
            });

            const instructions = `
Rename files to iiSU format:

${renameMap.map(r => `${r.old} → ${r.new}`).join('\n')}

To rename in Google Drive:
1. Right-click each file
2. Select "Rename"
3. Enter the new name

Or use keyboard shortcut: Select file and press 'n' to rename
            `;

            // Copy rename commands
            const copyText = renameMap.map(r => r.new).join('\n');
            navigator.clipboard.writeText(copyText).then(() => {
                showStatus('New filenames copied to clipboard!', 'success');
            });

            alert(instructions);
        }
    };

    // ==================== Initialization ====================

    function init() {
        // Wait for Drive to load
        setTimeout(() => {
            createToggleButton();
            createPanel();
            console.log('iiSU Asset Organizer loaded!');
        }, 2000);
    }

    // Run on page load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
