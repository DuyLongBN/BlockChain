/**
 * BlockPlate - Smart Contract License Plate Management
 * Frontend JavaScript
 */

const API = '/api';
let currentTab = 'dashboard';
let userAccount = null;
let userNetwork = null;
let isAdmin = false;
let adminToken = null;
let adminTokenExpiresAt = 0;
let renderedAdminStatus = null;

const FORM_OPTION_SETS = {
    vehicleTypes: [
        'Xe máy',
        'Ô tô',
        'Xe tải',
        'Xe khách',
        'Xe buýt',
        'Xe bán tải',
        'Xe điện',
        'Xe chuyên dùng',
        'Khác'
    ],
    colors: [
        'Trắng',
        'Đen',
        'Bạc',
        'Xám',
        'Đỏ',
        'Xanh dương',
        'Xanh lá',
        'Vàng',
        'Cam',
        'Nâu',
        'Tím',
        'Hồng',
        'Khác'
    ],
    provinces: [
        'Hà Nội',
        'Huế',
        'Hải Phòng',
        'Đà Nẵng',
        'Thành phố Hồ Chí Minh',
        'Cần Thơ',
        'Tuyên Quang',
        'Cao Bằng',
        'Lạng Sơn',
        'Quảng Ninh',
        'Điện Biên',
        'Lai Châu',
        'Sơn La',
        'Lào Cai',
        'Thái Nguyên',
        'Phú Thọ',
        'Bắc Ninh',
        'Hưng Yên',
        'Ninh Bình',
        'Thanh Hóa',
        'Nghệ An',
        'Hà Tĩnh',
        'Quảng Trị',
        'Quảng Ngãi',
        'Gia Lai',
        'Khánh Hòa',
        'Lâm Đồng',
        'Đắk Lắk',
        'Đồng Nai',
        'Tây Ninh',
        'Vĩnh Long',
        'Đồng Tháp',
        'Cà Mau',
        'An Giang'
    ]
};

function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value).replace(/[&<>"']/g, ch => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[ch]));
}

function jsStringArg(value) {
    return escapeHtml(JSON.stringify(String(value ?? '')));
}

function normalizePlateNumber(value) {
    const text = String(value || '').trim().toUpperCase();
    if (!text || text === 'UNKNOWN') return text;

    const compact = text.replace(/[^A-Z0-9]/g, '');
    if (compact.length < 7) return text;

    const bottomLen = compact.length >= 8 ? 5 : 4;
    const topLen = compact.length - bottomLen;
    if (![3, 4].includes(topLen)) return text;

    let top = compact.slice(0, topLen);
    let bottom = compact.slice(topLen);
    if (!/^\d{2}/.test(top) || !/^\d+$/.test(bottom)) return text;

    if (top.length > 3) top = `${top.slice(0, 2)}-${top.slice(2)}`;
    if (bottom.length === 5) bottom = `${bottom.slice(0, 3)}.${bottom.slice(3)}`;
    return `${top}-${bottom}`;
}

function normalizePlateInputValue(inputOrId) {
    const input = typeof inputOrId === 'string' ? document.getElementById(inputOrId) : inputOrId;
    const plate = normalizePlateNumber(input?.value || '');
    if (input && plate) input.value = plate;
    return plate;
}

function getTransactionMeta(type) {
    const txMeta = {
        register: { icon: '➕', label: 'Đăng ký' },
        update: { icon: '🛠️', label: 'Cập nhật phương tiện' },
        reactivate: { icon: '🔓', label: 'Mở khóa phương tiện' },
        transfer: { icon: '🔄', label: 'Chuyển nhượng' },
        violation: { icon: '⚠️', label: 'Vi phạm' },
        fine_paid: { icon: '✅', label: 'Nộp phạt' },
        deactivate: { icon: '🔒', label: 'Khóa phương tiện' },
        verify: { icon: '🔎', label: 'Xác thực' }
    };
    return txMeta[type] || { icon: '•', label: type || 'Khác' };
}

function shortHash(hash) {
    const text = String(hash || '');
    if (text.length <= 18) return text;
    return `${text.slice(0, 10)}...${text.slice(-8)}`;
}

function adminHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    if (adminToken) headers['X-Admin-Token'] = adminToken;
    return headers;
}

function readHeaders() {
    return adminToken ? { 'X-Admin-Token': adminToken } : {};
}

function adminPayload(payload = {}) {
    return { ...payload, admin_token: adminToken };
}

function clearAdminAuth() {
    isAdmin = false;
    adminToken = null;
    adminTokenExpiresAt = 0;
}

function initChoiceControls() {
    document.querySelectorAll('select[data-select-source]').forEach(select => {
        const source = select.dataset.selectSource;
        const options = FORM_OPTION_SETS[source] || [];
        const currentValue = select.value;
        const placeholder = select.dataset.placeholder || 'Chọn';
        select.innerHTML = `<option value="">${escapeHtml(placeholder)}</option>` + options
            .map(option => `<option value="${escapeHtml(option)}">${escapeHtml(option)}</option>`)
            .join('');
        if (currentValue && options.includes(currentValue)) {
            select.value = currentValue;
        }
    });
}

function initDatePickers() {
    const today = new Date().toISOString().slice(0, 10);
    document.querySelectorAll('input[type="date"]').forEach(input => {
        input.max = today;
        if (input.dataset.defaultToday === 'true' && !input.value) {
            input.value = today;
        }
    });
}

function initFormControls() {
    initChoiceControls();
    initDatePickers();
    initPlateFormatControls();
}

function initPlateFormatControls() {
    [
        'regPlateNumber', 'updPlateNumber', 'txPlateNumber', 'deactivatePlateNumber',
        'violPlateNumber', 'paidPlateNumber', 'stolenPlateNumber', 'qrPlateNumber',
        'qrScanPlate', 'historySearchInput', 'quickVerifyInput', 'adminDeactivatePlate', 'adminUpdPlate',
        'adminViolPlate', 'adminPaidPlate', 'adminRegPlate'
    ].forEach(id => {
        const input = document.getElementById(id);
        if (!input || input.dataset.plateNormalizeBound === 'true') return;
        input.dataset.plateNormalizeBound = 'true';
        input.addEventListener('blur', () => normalizePlateInputValue(input));
    });
}

// ============ Metamask Wallet Connection ============
async function connectMetamask() {
    const btn = document.getElementById('connectWalletBtn');
    
    // Check if Metamask is installed
    if (typeof window.ethereum === 'undefined') {
        showToast('❌ Metamask chưa được cài đặt. Vui lòng cài Metamask trước!', 'error');
        window.open('https://metamask.io/download/', '_blank');
        return;
    }

    try {
        showLoading(true, '🦊 Đang kết nối với Metamask...');
        
        // Request account access
        const accounts = await window.ethereum.request({ 
            method: 'eth_requestAccounts' 
        });
        
        userAccount = accounts[0];
        
        // Get network
        const chainId = await window.ethereum.request({ 
            method: 'eth_chainId' 
        });
        userNetwork = chainId;
        
        // Update button UI
        updateWalletButton(userAccount);
        
        // Send to backend to store
        await fetch(`${API}/wallet-connect`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                address: userAccount,
                network: chainId
            })
        });

        showLoading(false);
        showToast(`✅ Kết nối thành công! ${userAccount.substring(0, 6)}...${userAccount.substring(38)}`, 'success');
        
    } catch (error) {
        showLoading(false);
        if (error.code === -32602) {
            showToast('❌ Metamask bị từ chối kết nối', 'error');
        } else {
            showToast(`❌ Lỗi: ${error.message}`, 'error');
        }
    }
}

function updateWalletButton(account) {
    const btn = document.getElementById('connectWalletBtn');
    const icon = document.getElementById('walletIcon');
    const text = document.getElementById('walletText');
    
    if (account) {
        btn.classList.add('connected');
        icon.textContent = '✅';
        text.textContent = `${account.substring(0, 6)}...${account.substring(38)}`;
    } else {
        btn.classList.remove('connected');
        icon.textContent = '🦊';
        text.textContent = 'Kết nối ví';
    }
}

// Listen to account/network changes
if (typeof window.ethereum !== 'undefined') {
    window.ethereum.on('accountsChanged', async (accounts) => {
        if (accounts.length === 0) {
            await revokeAdminSession();
            userAccount = null;
            clearAdminAuth();
            updateWalletButton(null);
            updateAdminUI(false);
            showToast('⚠️ Ví đã được ngắt kết nối', 'warning');
        } else {
            await revokeAdminSession();
            userAccount = accounts[0];
            clearAdminAuth();
            updateWalletButton(userAccount);
            updateAdminUI(false);
            showToast(`✅ Chuyển sang tài khoản: ${accounts[0].substring(0, 6)}...`, 'success');
        }
    });

    window.ethereum.on('chainChanged', () => {
        showToast('⚠️ Mạng đã thay đổi. Trang sẽ reload...', 'warning');
        setTimeout(() => location.reload(), 1500);
    });
}

// ============ Navigation ============
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            const tab = item.dataset.tab;
            if (!tab) return;
            switchTab(tab);
            const focusTarget = item.dataset.focusTarget;
            if (focusTarget) {
                setTimeout(() => document.getElementById(focusTarget)?.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                }), 50);
            }
        });
    });
});

function switchTab(tab) {
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    const navEl = document.querySelector(`[data-tab="${tab}"]`);
    const tabEl = document.getElementById(`tab-${tab}`);
    if (navEl) navEl.classList.add('active');
    if (tabEl) tabEl.classList.add('active');
    currentTab = tab;

    const titles = {
        dashboard: '📊 Tổng Quan Hệ Thống',
        recognition: '📷 Hỗ Trợ OCR Nhập Biển Số',
        blockchain: '⛓️ Quản Lý Và Xác Thực Biển Số',
        history: '📋 Lịch Sử Giao Dịch',
        admin: '🛡️ Quản Trị Smart Contract',
        webcam: '🎥 Webcam Hỗ Trợ OCR',
        timeline: '📈 Timeline Giao Dịch',
        stolen: '🚨 Xe Mất Cắp'
    };
    document.getElementById('pageTitle').textContent = titles[tab] || '';

    if (tab === 'dashboard') refreshDashboard();
    if (tab === 'blockchain') loadAllPlates();
    if (tab === 'admin' && !isAdmin) {
        showToast('⚠️ Bạn cần kết nối ví Admin để sử dụng', 'warning');
    }
}

// ============ Toast Notifications ============
function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 3500);
}

function showLoading(show = true, text = 'Đang xử lý...') {
    const overlay = document.getElementById('loadingOverlay');
    document.getElementById('loadingText').textContent = text;
    overlay.classList.toggle('hidden', !show);
}

// ============ Blockchain Status ============
async function checkBlockchainStatus() {
    try {
        const res = await fetch(`${API}/blockchain/status`, { headers: readHeaders() });
        const data = await res.json();
        const dot = document.getElementById('bcDot');
        const text = document.getElementById('bcText');
        const badge = document.getElementById('networkBadge');

        if (data.connected) {
            dot.classList.add('connected');
            text.textContent = 'Đã kết nối';
            badge.classList.remove('disconnected');
            document.getElementById('networkName').textContent = 'Sepolia Testnet';
            if (data.block_number) {
                document.getElementById('statBlockNum').textContent = data.block_number;
            }
        } else {
            dot.classList.remove('connected');
            text.textContent = 'Mất kết nối';
            badge.classList.add('disconnected');
            document.getElementById('networkName').textContent = 'Offline';
        }
    } catch (e) {
        document.getElementById('bcDot').classList.remove('connected');
        document.getElementById('bcText').textContent = 'Lỗi kết nối';
        document.getElementById('networkBadge').classList.add('disconnected');
    }
}

// ============ Dashboard ============
async function refreshDashboard() {
    try {
        const res = await fetch(`${API}/blockchain/statistics`);
        const data = await res.json();
        document.getElementById('statRegNum').textContent = data.total_registered || 0;
        document.getElementById('statActiveNum').textContent = data.active_plates || 0;
        document.getElementById('statInactiveNum').textContent = data.inactive_plates || 0;
        document.getElementById('statRegTxNum').textContent = data.total_registered_events || 0;
        document.getElementById('statVerNum').textContent = data.total_verifications || 0;
        document.getElementById('statTransNum').textContent = data.total_transfers || 0;
    } catch (e) { console.error('Dashboard error:', e); }
    loadRecentPlates();
}

async function loadRecentPlates() {
    try {
        const res = await fetch(`${API}/blockchain/plates`, { headers: readHeaders() });
        const plates = await res.json();
        const list = document.getElementById('recentPlatesList');

        if (!plates || plates.length === 0) {
            list.innerHTML = '<div class="empty-msg">Chưa có biển số nào được đăng ký</div>';
            return;
        }

        list.innerHTML = plates.slice(-8).reverse().map(p => `
            <div class="plate-item" onclick="showPlateDetail(${jsStringArg(p.plate_number)})">
                <div>
                    <div class="plate-item-number">${escapeHtml(p.plate_number)}</div>
                    <div class="plate-item-owner">${escapeHtml(p.owner_name)}</div>
                </div>
                <span class="plate-item-badge ${p.is_active ? 'badge-active' : 'badge-inactive'}">
                    ${p.is_active ? '✓ Active' : '✗ Inactive'}
                </span>
                ${!p.is_active && isAdmin ? `<button class="btn btn-small btn-success reactivate-inline-btn" onclick="event.stopPropagation(); reactivatePlate(${jsStringArg(p.plate_number)}, this)">Mở khóa</button>` : ''}
            </div>
        `).join('');
    } catch (e) { console.error('Load plates error:', e); }
}

// ============ Quick Verify ============
async function quickVerify() {
    const plate = normalizePlateInputValue('quickVerifyInput');
    if (!plate) { showToast('Vui lòng nhập biển số', 'warning'); return; }

    const resultDiv = document.getElementById('quickVerifyResult');
    resultDiv.classList.remove('hidden', 'verified', 'not-found');

    try {
        const res = await fetch(`${API}/blockchain/verify/${encodeURIComponent(plate)}`, { headers: readHeaders() });
        const data = await res.json();

        const displayPlate = data.plate_number || plate;
        const inactive = data.is_active === false;

        if (data.is_registered) {
            resultDiv.classList.add(inactive ? 'not-found' : 'verified');
            resultDiv.innerHTML = `
                <div style="font-weight:600;color:${inactive ? 'var(--warning)' : 'var(--success)'};margin-bottom:8px">${inactive ? '⚠️ Biển số đang inactive' : '✅ Biển số hợp lệ'}</div>
                <div style="font-size:13px;color:var(--text-secondary)">
                    <div>Biển số: <strong>${escapeHtml(displayPlate)}</strong></div>
                    <div>Chủ xe: <strong>${escapeHtml(data.owner_name)}</strong></div>
                    <div>Loại xe: ${escapeHtml(data.vehicle_type || 'N/A')}</div>
                    <div>Tỉnh: ${escapeHtml(data.province || 'N/A')}</div>
                    <div>Trạng thái: <strong>${inactive ? 'Inactive' : 'Active'}</strong></div>
                    <div>Ngày ĐK: ${formatDate(data.registered_at)}</div>
                </div>
            `;
        } else {
            resultDiv.classList.add('not-found');
            resultDiv.innerHTML = `
                <div style="font-weight:600;color:var(--error)">❌ Không tìm thấy</div>
                <div style="font-size:13px;color:var(--text-secondary);margin-top:4px">
                    Biển số <strong>${escapeHtml(displayPlate)}</strong> chưa được đăng ký trên blockchain
                </div>
            `;
        }
    } catch (e) {
        resultDiv.classList.add('not-found');
        resultDiv.innerHTML = `<div style="color:var(--error)">Lỗi kết nối blockchain</div>`;
    }
}

// ============ Recognition ============
function formatVnd(value) {
    return `${Number(value || 0).toLocaleString('vi-VN')} VND`;
}

function renderViolationsList(violations = []) {
    const unpaid = violations.filter(v => !v.is_paid);
    if (!unpaid.length) return '';

    return `
        <div class="ocr-violations">
            <div class="ocr-violations-title">⚠️ ${unpaid.length} lỗi phạt chưa thanh toán</div>
            ${unpaid.map(v => `
                <div class="ocr-violation-item">
                    <div>${escapeHtml(v.description || 'Vi phạm chưa có mô tả')}</div>
                    <strong>${formatVnd(v.fine_amount)}</strong>
                </div>
            `).join('')}
        </div>
    `;
}

function renderBlockchainSummary(detection = {}) {
    const bc = detection.blockchain || {};
    const status = String(detection.verification_status || '').toUpperCase();

    if (!bc.registered) {
        return `
            <div class="ocr-blockchain-summary not-found">
                <strong>Chưa đăng ký trên blockchain</strong>
                <span>Biển OCR đề xuất chưa có trong smart contract. Hãy sửa lại biển nếu OCR đọc sai rồi xác thực lại.</span>
            </div>
        `;
    }

    const isInactive = bc.active === false || status === 'STOLEN';
    const hasUnpaidFine = Number(bc.unpaid_fines || 0) > 0;
    const summaryClass = isInactive ? 'danger' : (hasUnpaidFine ? 'warning' : 'verified');
    const summaryTitle = isInactive
        ? 'Biển đang inactive / bị báo mất'
        : (hasUnpaidFine ? 'Đã đăng ký, còn lỗi phạt' : 'Đã xác thực trên blockchain');

    return `
        <div class="ocr-blockchain-summary ${summaryClass}">
            <strong>${escapeHtml(summaryTitle)}</strong>
            <div class="ocr-bc-grid">
                <span>Chủ xe</span><b>${escapeHtml(bc.owner_name || 'N/A')}</b>
                <span>Loại xe</span><b>${escapeHtml(bc.vehicle_type || 'N/A')}</b>
                <span>Màu</span><b>${escapeHtml(bc.color || 'N/A')}</b>
                <span>Tỉnh/TP</span><b>${escapeHtml(bc.province || 'N/A')}</b>
                <span>Trạng thái</span><b>${isInactive ? 'Inactive' : 'Active'}</b>
            </div>
            ${renderViolationsList(bc.violations || [])}
        </div>
    `;
}

async function processImage(event) {
    const file = event.target.files[0];
    if (!file) return;

    showLoading(true, 'Đang OCR và kiểm tra blockchain...');
    const formData = new FormData();
    formData.append('image', file);

    try {
        const res = await fetch(`${API}/image-authenticate`, {
            method: 'POST',
            headers: readHeaders(),
            body: formData
        });
        const data = await res.json();

        if (data.success) {
            // Show result image
            const container = document.getElementById('recImageContainer');
            if (data.result_image_base64) {
                container.innerHTML = `<img src="data:image/jpeg;base64,${data.result_image_base64}" alt="Kết quả OCR">`;
            } else if (data.result_image_path) {
                const imgPath = data.result_image_path.replace(/\\/g, '/');
                const filename = imgPath.split('/').pop();
                container.innerHTML = `<img src="/results/${filename}" alt="Kết quả OCR">`;
            }

            // Show detections
            const resultsList = document.getElementById('recResultsList');
            if (data.detections && data.detections.length > 0) {
                resultsList.innerHTML = data.detections.map((d, idx) => {
                    const displayPlate = d.display_plate_number || d.plate_number || '';
                    const inputId = `recognizedPlate${idx}`;
                    const resultId = `recognizedVerifyResult${idx}`;
                    const confidence = Number(d.confidence || 0) * 100;
                    const rawConfidence = Number(d.raw_confidence || d.confidence || 0) * 100;
                    const reviewMessage = d.quality_message || 'OCR chỉ là đề xuất, cần kiểm tra trước khi xác thực blockchain';
                    const reviewBadgeClass = d.needs_review ? 'warning' : 'pending';
                    const blockchainSummary = renderBlockchainSummary(d);
                    const rawConfidenceText = rawConfidence > confidence + 1
                        ? `<div class="rec-result-note">Confidence OCR gốc: ${rawConfidence.toFixed(1)}%, đã hạ vì cần kiểm tra định dạng.</div>`
                        : '';
                    return `
                        <div class="rec-result-item">
                            <div class="rec-result-plate">${escapeHtml(displayPlate)}</div>
                            <div class="rec-result-conf">Độ tin cậy sau kiểm tra: ${confidence.toFixed(1)}%</div>
                            ${rawConfidenceText}
                            <div class="bc-verify-badge ${reviewBadgeClass}">${escapeHtml(reviewMessage)}</div>
                            <div class="ocr-confirm-row">
                                <input id="${inputId}" class="input-field rec-result-input" value="${escapeHtml(displayPlate)}">
                                <button class="btn btn-primary btn-small" onclick="verifyRecognizedPlate('${inputId}', '${resultId}')">
                                    Xác thực lại
                                </button>
                            </div>
                            <div id="${resultId}" class="verify-result inline-result">${blockchainSummary}</div>
                        </div>
                    `;
                }).join('');
            } else {
                resultsList.innerHTML = '<div class="empty-msg">Không phát hiện biển số</div>';
            }

            showToast(`Đã xử lý ${data.detection_count} biển số trong cùng một luồng`, 'success');
        } else {
            showToast(data.error || 'Lỗi xử lý ảnh', 'error');
        }
    } catch (e) {
        showToast('Lỗi kết nối server', 'error');
    }
    showLoading(false);
    event.target.value = '';
}

async function verifyRecognizedPlate(inputId, resultId) {
    const input = document.getElementById(inputId);
    const resultDiv = document.getElementById(resultId);
    if (!input || !resultDiv) return;

    const plate = normalizePlateInputValue(input);
    if (!plate) {
        showToast('Vui lòng kiểm tra và nhập biển số trước khi xác thực', 'warning');
        return;
    }

    resultDiv.classList.remove('hidden', 'verified', 'not-found');
    resultDiv.innerHTML = '<div style="color:var(--text-secondary)">Đang tra cứu smart contract...</div>';

    try {
        const [verifyRes, violationsRes] = await Promise.all([
            fetch(`${API}/blockchain/verify/${encodeURIComponent(plate)}`, { headers: readHeaders() }),
            fetch(`${API}/blockchain/violations/${encodeURIComponent(plate)}`, { headers: readHeaders() }).catch(() => null)
        ]);
        const data = await verifyRes.json();
        const violations = violationsRes && violationsRes.ok ? await violationsRes.json() : [];

        const displayPlate = data.plate_number || plate;

        if (data.is_registered) {
            resultDiv.classList.add('verified');
            const inactive = data.is_active === false;
            const unpaid = Array.isArray(violations) ? violations.filter(v => !v.is_paid) : [];
            resultDiv.innerHTML = `
                <div class="ocr-blockchain-summary ${inactive ? 'danger' : (unpaid.length ? 'warning' : 'verified')}">
                    <strong>${inactive ? 'Biển đang inactive / bị báo mất' : (unpaid.length ? 'Đã đăng ký, còn lỗi phạt' : 'Đã xác thực trên blockchain')}</strong>
                    <div class="ocr-bc-grid">
                        <span>Biển số</span><b>${escapeHtml(displayPlate)}</b>
                        <span>Chủ xe</span><b>${escapeHtml(data.owner_name || 'N/A')}</b>
                        <span>Loại xe</span><b>${escapeHtml(data.vehicle_type || 'N/A')}</b>
                        <span>Màu xe</span><b>${escapeHtml(data.color || 'N/A')}</b>
                        <span>Tỉnh/TP</span><b>${escapeHtml(data.province || 'N/A')}</b>
                        <span>Trạng thái</span><b>${inactive ? 'Inactive' : 'Active'}</b>
                    </div>
                    ${renderViolationsList(violations)}
                </div>
            `;
        } else {
            resultDiv.classList.add('not-found');
            resultDiv.innerHTML = `
                <div class="ocr-blockchain-summary not-found">
                    <strong>Chưa đăng ký trên blockchain</strong>
                    <span>Biển số <b>${escapeHtml(displayPlate)}</b> chưa có trong smart contract.</span>
                </div>
            `;
        }
    } catch (e) {
        resultDiv.classList.add('not-found');
        resultDiv.innerHTML = '<div style="color:var(--error)">Lỗi kết nối blockchain</div>';
    }
}

// ============ Blockchain Register ============
async function registerPlate(event) {
    event.preventDefault();
    if (!(await ensureAdminAuth())) return;
    const btn = document.getElementById('registerBtn');
    btn.disabled = true;

    const payload = {
        plate_number: normalizePlateInputValue('regPlateNumber'),
        owner_name: document.getElementById('regOwnerName').value.trim(),
        vehicle_type: document.getElementById('regVehicleType').value,
        color: document.getElementById('regColor').value.trim(),
        province: document.getElementById('regProvince').value.trim()
    };

    showLoading(true, 'Đang ghi lên blockchain...');
    const resultDiv = document.getElementById('registerResult');
    resultDiv.classList.remove('hidden', 'success', 'error');

    try {
        const res = await fetch(`${API}/blockchain/register`, {
            method: 'POST',
            headers: adminHeaders(),
            body: JSON.stringify(adminPayload(payload))
        });
        const data = await res.json();

        if (data.success) {
            resultDiv.classList.add('success');
            resultDiv.innerHTML = `
                <div style="font-weight:600;color:var(--success)">✅ Đăng ký thành công!</div>
                <div style="margin-top:8px;font-size:13px">
                    <div>Biển số: <strong>${escapeHtml(data.plate_number)}</strong></div>
                    <div>Block: #${data.block_number}</div>
                    <div>Gas: ${data.gas_used}</div>
                </div>
                <div class="tx-hash">TX: ${escapeHtml(data.tx_hash)}</div>
            `;
            showToast(`Đã đăng ký ${data.plate_number || ''} lên blockchain!`, 'success');
            document.getElementById('registerForm').reset();
            await Promise.allSettled([
                loadAllPlates(),
                refreshDashboard(),
                loadTimeline({ silent: true })
            ]);
        } else {
            resultDiv.classList.add('error');
            resultDiv.innerHTML = `<div style="color:var(--error)">❌ ${escapeHtml(data.error)}</div>`;
            showToast(data.error, 'error');
        }
    } catch (e) {
        resultDiv.classList.add('error');
        resultDiv.innerHTML = `<div style="color:var(--error)">❌ Lỗi kết nối</div>`;
        showToast('Lỗi kết nối blockchain', 'error');
    }
    showLoading(false);
    btn.disabled = false;
}

// ============ Transfer Ownership ============
async function transferOwnership(event) {
    event.preventDefault();
    if (!(await ensureAdminAuth())) return;
    const btn = document.getElementById('transferBtn');
    btn.disabled = true;

    const payload = {
        plate_number: normalizePlateInputValue('txPlateNumber'),
        new_owner: document.getElementById('txNewOwner').value.trim()
    };

    showLoading(true, 'Đang chuyển nhượng...');
    const resultDiv = document.getElementById('transferResult');
    resultDiv.classList.remove('hidden', 'success', 'error');

    try {
        const res = await fetch(`${API}/blockchain/transfer`, {
            method: 'POST',
            headers: adminHeaders(),
            body: JSON.stringify(adminPayload(payload))
        });
        const data = await res.json();

        if (data.success) {
            resultDiv.classList.add('success');
            resultDiv.innerHTML = `
                <div style="font-weight:600;color:var(--success)">✅ Chuyển nhượng thành công!</div>
                <div style="margin-top:8px;font-size:13px">
                    <div>${escapeHtml(data.previous_owner)} → <strong>${escapeHtml(data.new_owner)}</strong></div>
                    <div>Block: #${data.block_number}</div>
                </div>
                <div class="tx-hash">TX: ${escapeHtml(data.tx_hash)}</div>
            `;
            showToast('Chuyển nhượng thành công!', 'success');
            document.getElementById('transferForm').reset();
            await Promise.allSettled([
                loadAllPlates(),
                refreshDashboard(),
                loadTimeline({ silent: true })
            ]);
        } else {
            resultDiv.classList.add('error');
            resultDiv.innerHTML = `<div style="color:var(--error)">❌ ${escapeHtml(data.error)}</div>`;
            showToast(data.error, 'error');
        }
    } catch (e) {
        resultDiv.classList.add('error');
        resultDiv.innerHTML = `<div style="color:var(--error)">❌ Lỗi kết nối</div>`;
    }
    showLoading(false);
    btn.disabled = false;
}

async function changeVehicleInfo({
    plateNumber,
    vehicleType = '',
    color = '',
    province = '',
    form = null,
    button = null,
    resultDiv = null
}) {
    if (!(await ensureAdminAuth('cập nhật thông tin phương tiện'))) return;

    const plate = normalizePlateNumber(plateNumber);
    if (!plate) {
        showToast('Nhập biển số cần cập nhật', 'warning');
        return;
    }

    if (button) button.disabled = true;
    if (resultDiv) resultDiv.classList.remove('hidden', 'success', 'error');
    showLoading(true, 'Đang cập nhật phương tiện trên blockchain...');

    try {
        const res = await fetch(`${API}/blockchain/update`, {
            method: 'POST',
            headers: adminHeaders(),
            body: JSON.stringify(adminPayload({
                plate_number: plate,
                vehicle_type: vehicleType,
                color,
                province
            }))
        });
        const data = await res.json();

        if (data.success) {
            if (resultDiv) {
                resultDiv.classList.add('success');
                resultDiv.innerHTML = `
                    ✅ Đã cập nhật phương tiện ${escapeHtml(data.plate_number)}.
                    <div>Loại xe: ${escapeHtml(data.vehicle_type || '')}</div>
                    <div>Màu xe: ${escapeHtml(data.color || '')}</div>
                    <div>Tỉnh/TP: ${escapeHtml(data.province || '')}</div>
                    <div class="tx-hash">TX: ${escapeHtml(data.tx_hash || '')}</div>
                `;
            }
            if (form) form.reset();
            showToast('Cập nhật phương tiện thành công', 'success');
            await refreshPlateManagementViews(data.plate_number || plate);
        } else {
            if (resultDiv) {
                resultDiv.classList.add('error');
                resultDiv.innerHTML = `❌ Lỗi: ${escapeHtml(data.error || 'Không thể cập nhật phương tiện')}`;
            }
            showToast(data.error || 'Không thể cập nhật phương tiện', 'error');
        }
    } catch (e) {
        if (resultDiv) {
            resultDiv.classList.add('error');
            resultDiv.innerHTML = '❌ Lỗi kết nối server';
        }
        showToast('Lỗi kết nối server', 'error');
    }

    if (button) button.disabled = false;
    showLoading(false);
}

async function updateVehicle(event) {
    event.preventDefault();
    const form = document.getElementById('updateVehicleForm');
    return changeVehicleInfo({
        plateNumber: document.getElementById('updPlateNumber').value,
        vehicleType: document.getElementById('updVehicleType').value,
        color: document.getElementById('updColor').value,
        province: document.getElementById('updProvince').value,
        form,
        button: document.getElementById('updateVehicleBtn'),
        resultDiv: document.getElementById('updateVehicleResult')
    });
}

// ============ Load All Plates ============
async function loadAllPlates() {
    try {
        const res = await fetch(`${API}/blockchain/plates`, { headers: readHeaders() });
        const plates = await res.json();
        const tbody = document.getElementById('plateTableBody');

        if (!plates || plates.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="empty-msg">Chưa có dữ liệu</td></tr>';
            return;
        }

        tbody.innerHTML = plates.map(p => `
            <tr onclick="showPlateDetail(${jsStringArg(p.plate_number)})" style="cursor:pointer">
                <td class="plate-num">${escapeHtml(p.plate_number)}</td>
                <td>${escapeHtml(p.owner_name)}</td>
                <td>${escapeHtml(p.vehicle_type || '-')}</td>
                <td>${escapeHtml(p.province || '-')}</td>
                <td>${formatDate(p.registered_at)}</td>
                <td><span class="status-badge ${p.is_active ? 'status-active' : 'status-inactive'}">
                    ${p.is_active ? 'Active' : 'Inactive'}
                </span>${!p.is_active && isAdmin ? `<button class="btn btn-small btn-success reactivate-table-btn" onclick="event.stopPropagation(); reactivatePlate(${jsStringArg(p.plate_number)}, this)">Mở khóa</button>` : ''}</td>
            </tr>
        `).join('');
    } catch (e) { console.error('Load plates error:', e); }
}

// ============ Plate Detail ============
async function showPlateDetail(plateNumber) {
    switchTab('history');
    const detailDiv = document.getElementById('plateDetailView');
    const historyTimeline = document.getElementById('historyTimeline');
    const lookupPlate = normalizePlateNumber(plateNumber);
    detailDiv.innerHTML = '<div class="empty-msg">Đang tải chi tiết biển số...</div>';

    try {
        const res = await fetch(`${API}/blockchain/info/${encodeURIComponent(lookupPlate)}`, { headers: readHeaders() });
        const data = await res.json();

        if (data.found) {
            const canonicalPlate = data.plate_number || lookupPlate;
            const [history, violations, txData] = await Promise.all([
                fetch(`${API}/blockchain/history/${encodeURIComponent(canonicalPlate)}`, { headers: readHeaders() }).then(r => r.json()).catch(() => []),
                fetch(`${API}/blockchain/violations/${encodeURIComponent(canonicalPlate)}`, { headers: readHeaders() }).then(r => r.json()).catch(() => []),
                fetch(`${API}/timeline/plate/${encodeURIComponent(canonicalPlate)}?limit=20`, { headers: readHeaders() }).then(r => r.json()).catch(() => ({ transactions: [] }))
            ]);
            const transactions = Array.isArray(txData.transactions) ? txData.transactions : [];
            detailDiv.innerHTML = renderPlateDetailPanel(data, history, violations, transactions);
            if (historyTimeline) {
                historyTimeline.innerHTML = renderPlateHistoryTimeline(canonicalPlate, transactions);
            }
        } else {
            detailDiv.innerHTML = '<div class="empty-msg">Không tìm thấy thông tin biển số trên smart contract</div>';
            if (historyTimeline) historyTimeline.innerHTML = '<div class="empty-msg">Không có giao dịch liên quan</div>';
        }
    } catch (e) {
        detailDiv.innerHTML = '<div class="empty-msg">Lỗi kết nối</div>';
    }
}

function renderPlateDetailPanel(data, history = [], violations = [], transactions = []) {
    const active = data.is_active !== false;
    const plate = data.plate_number || '';
    const unpaidCount = violations.filter(v => !v.is_paid).length;
    const txCount = transactions.filter(tx => tx.tx_hash).length;

    return `
        <div class="plate-detail-panel">
            <div class="detail-hero ${active ? 'active' : 'inactive'}">
                <div>
                    <div class="detail-plate-number">${escapeHtml(plate)}</div>
                    <div class="detail-subtitle">Nguồn xác thực: Smart Contract Sepolia</div>
                </div>
                <span class="detail-status ${active ? 'status-active' : 'status-inactive'}">
                    ${active ? 'Active' : 'Inactive'}
                </span>
            </div>

            <div class="detail-summary-row">
                <div class="detail-summary-item">
                    <span>Vi phạm</span>
                    <strong>${violations.length}</strong>
                </div>
                <div class="detail-summary-item">
                    <span>Chưa nộp phạt</span>
                    <strong class="${unpaidCount ? 'text-warning' : ''}">${unpaidCount}</strong>
                </div>
                <div class="detail-summary-item">
                    <span>Giao dịch</span>
                    <strong>${txCount}</strong>
                </div>
            </div>

            <div class="detail-section">
                <div class="detail-section-title">Thông tin phương tiện</div>
                <div class="detail-grid detail-grid-wide">
                    ${renderDetailItem('Biển số', plate)}
                    ${renderDetailItem('Chủ xe', data.owner_name || 'N/A')}
                    ${renderDetailItem('Loại xe', data.vehicle_type || 'N/A')}
                    ${renderDetailItem('Màu xe', data.color || 'N/A')}
                    ${renderDetailItem('Tỉnh/Thành phố', data.province || 'N/A')}
                    ${renderDetailItem('Ngày đăng ký', formatDate(data.registered_at))}
                    ${renderDetailItem('Cập nhật cuối', formatDate(data.last_updated))}
                    ${renderDetailItem('Trạng thái', active ? 'Active' : 'Inactive')}
                </div>
                ${!active && isAdmin ? `<div class="detail-actions"><button class="btn btn-success" onclick="reactivatePlate(${jsStringArg(plate)}, this)">Mở khóa phương tiện</button></div>` : ''}
            </div>

            <div class="detail-section">
                <div class="detail-section-title">Lịch sử chuyển nhượng</div>
                ${renderTransferHistory(history)}
            </div>

            <div class="detail-section">
                <div class="detail-section-title">Danh sách vi phạm</div>
                ${renderViolationHistory(plate, violations)}
            </div>

            <div class="detail-section">
                <div class="detail-section-title">Giao dịch liên quan</div>
                ${renderEtherscanTransactions(transactions)}
            </div>
        </div>
    `;
}

function renderDetailItem(label, value) {
    return `
        <div class="detail-item">
            <div class="detail-item-label">${escapeHtml(label)}</div>
            <div class="detail-item-value">${escapeHtml(value || 'N/A')}</div>
        </div>
    `;
}

function renderTransferHistory(history = []) {
    if (!Array.isArray(history) || history.length === 0) {
        return '<div class="detail-empty">Chưa có giao dịch chuyển nhượng.</div>';
    }

    return `
        <div class="detail-list">
            ${history.map(h => `
                <div class="detail-list-item transfer">
                    <div class="detail-list-main">
                        <strong>${escapeHtml(h.previous_owner || 'N/A')}</strong>
                        <span class="detail-arrow">→</span>
                        <strong>${escapeHtml(h.new_owner || 'N/A')}</strong>
                    </div>
                    <div class="detail-list-meta">${formatDate(h.transferred_at)}</div>
                </div>
            `).join('')}
        </div>
    `;
}

function renderViolationHistory(plate, violations = []) {
    if (!Array.isArray(violations) || violations.length === 0) {
        return '<div class="detail-empty">Chưa có vi phạm được ghi nhận.</div>';
    }

    return `
        <div class="detail-list">
            ${violations.map((v, idx) => {
                const violationIndex = Number.isFinite(Number(v.index)) ? Number(v.index) : idx;
                const paid = v.is_paid === true;
                return `
                    <div class="detail-list-item violation ${paid ? 'paid' : 'unpaid'}">
                        <div class="detail-list-main">
                            <strong>#${violationIndex} - ${escapeHtml(v.description || 'Vi phạm')}</strong>
                            <span class="violation-paid-badge ${paid ? 'paid' : 'unpaid'}">${paid ? 'Đã nộp' : 'Chưa nộp'}</span>
                        </div>
                        <div class="detail-list-meta">
                            ${Number(v.fine_amount || 0).toLocaleString('vi-VN')} VNĐ · ${formatDate(v.timestamp)}
                        </div>
                        ${isAdmin && !paid ? `<button class="btn btn-small btn-success" onclick="markViolationPaid(${jsStringArg(plate)}, ${violationIndex}, this)">Đánh dấu đã nộp</button>` : ''}
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

function renderEtherscanTransactions(transactions = []) {
    const validTransactions = (transactions || []).filter(tx => tx.tx_hash);
    if (validTransactions.length === 0) {
        return '<div class="detail-empty">Chưa có giao dịch Etherscan liên quan.</div>';
    }

    return `
        <div class="detail-tx-list">
            ${validTransactions.map(tx => {
                const meta = getTransactionMeta(tx.type);
                const txUrl = tx.etherscan_url || `https://sepolia.etherscan.io/tx/${encodeURIComponent(tx.tx_hash || '')}`;
                const blockUrl = tx.block_url || (tx.block_number ? `https://sepolia.etherscan.io/block/${encodeURIComponent(tx.block_number)}` : '');
                return `
                    <div class="detail-tx-item">
                        <div class="detail-tx-icon">${meta.icon}</div>
                        <div class="detail-tx-body">
                            <div class="detail-tx-title">${escapeHtml(meta.label)}</div>
                            <div class="detail-tx-meta">${formatDate(tx.timestamp)} · ${Number(tx.gas_used || 0)} gas</div>
                            <div class="detail-tx-links">
                                <a href="${escapeHtml(txUrl)}" target="_blank" rel="noopener noreferrer">TX ${escapeHtml(shortHash(tx.tx_hash))}</a>
                                ${blockUrl ? `<a href="${escapeHtml(blockUrl)}" target="_blank" rel="noopener noreferrer">Block #${escapeHtml(tx.block_number)}</a>` : ''}
                            </div>
                        </div>
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

function renderPlateHistoryTimeline(plate, transactions = []) {
    const validTransactions = (transactions || []).filter(tx => tx.tx_hash);
    if (validTransactions.length === 0) {
        return `<div class="empty-msg">Chưa có giao dịch blockchain liên quan đến ${escapeHtml(plate)}</div>`;
    }

    return validTransactions.map(tx => {
        const meta = getTransactionMeta(tx.type);
        const txUrl = tx.etherscan_url || `https://sepolia.etherscan.io/tx/${encodeURIComponent(tx.tx_hash || '')}`;
        return `
            <div class="timeline-item">
                <div class="timeline-dot ${escapeHtml(tx.type || '')}"></div>
                <div class="timeline-body">
                    <div class="timeline-title">${meta.icon} ${escapeHtml(meta.label)}</div>
                    <div class="timeline-desc">${escapeHtml(tx.plate_number || plate)} · ${Number(tx.gas_used || 0)} gas</div>
                    <div class="timeline-time">${formatDate(tx.timestamp)}</div>
                    <a class="detail-inline-link" href="${escapeHtml(txUrl)}" target="_blank" rel="noopener noreferrer">Xem trên Etherscan</a>
                </div>
            </div>
        `;
    }).join('');
}

async function refreshPlateManagementViews(plate = '') {
    await Promise.allSettled([
        loadAllPlates(),
        refreshDashboard(),
        loadTimeline({ silent: true })
    ]);
    if (plate && currentTab === 'blockchain') {
        showPlateDetail(plate);
    }
}

async function changePlateActivation({
    mode,
    plateNumber,
    button = null,
    input = null,
    resultDiv = null
}) {
    const isDeactivate = mode === 'deactivate';
    const actionLabel = isDeactivate ? 'khóa phương tiện' : 'mở khóa phương tiện';
    if (!(await ensureAdminAuth(actionLabel))) return;

    const plate = normalizePlateNumber(plateNumber);
    if (!plate) {
        showToast('Nhập biển số cần xử lý', 'warning');
        return;
    }

    const confirmMessage = isDeactivate
        ? `Khóa phương tiện mang biển số ${plate} trên blockchain?`
        : `Mở khóa phương tiện mang biển số ${plate} trên blockchain?`;
    if (!confirm(confirmMessage)) return;

    if (button) button.disabled = true;
    if (resultDiv) resultDiv.classList.remove('hidden', 'success', 'error');
    showLoading(true, isDeactivate ? 'Đang khóa phương tiện...' : 'Đang mở khóa phương tiện...');

    try {
        const res = await fetch(`${API}/blockchain/${mode}`, {
            method: 'POST',
            headers: adminHeaders(),
            body: JSON.stringify(adminPayload({ plate_number: plate }))
        });
        const data = await res.json();

        if (data.success) {
            const successMessage = isDeactivate
                ? `Đã khóa phương tiện ${plate}`
                : `Đã mở khóa phương tiện ${plate}`;
            if (resultDiv) {
                resultDiv.classList.add('success');
                resultDiv.innerHTML = `✅ ${escapeHtml(successMessage)}.<div class="tx-hash">TX: ${escapeHtml(data.tx_hash || '')}</div>`;
            }
            if (input) input.value = '';
            showToast(successMessage, 'success');
            await refreshPlateManagementViews(plate);
        } else {
            if (resultDiv) {
                resultDiv.classList.add('error');
                resultDiv.innerHTML = `❌ Lỗi: ${escapeHtml(data.error || 'Không thể cập nhật trạng thái phương tiện')}`;
            }
            showToast(data.error || 'Không thể cập nhật trạng thái phương tiện', 'error');
        }
    } catch (e) {
        if (resultDiv) {
            resultDiv.classList.add('error');
            resultDiv.innerHTML = '❌ Lỗi kết nối server';
        }
        showToast('Lỗi kết nối server', 'error');
    }

    if (button) button.disabled = false;
    showLoading(false);
}

async function deactivatePlate() {
    const input = document.getElementById('deactivatePlateNumber');
    return changePlateActivation({
        mode: 'deactivate',
        plateNumber: input?.value,
        input,
        button: document.getElementById('deactivateBtn'),
        resultDiv: document.getElementById('deactivateResult')
    });
}

async function reactivateManagedPlate() {
    const input = document.getElementById('deactivatePlateNumber');
    return changePlateActivation({
        mode: 'reactivate',
        plateNumber: input?.value,
        input,
        button: document.getElementById('reactivateBtn'),
        resultDiv: document.getElementById('deactivateResult')
    });
}

async function reactivatePlate(plateNumber, button = null) {
    return changePlateActivation({
        mode: 'reactivate',
        plateNumber,
        button
    });
}

async function addViolation(event) {
    event.preventDefault();
    if (!(await ensureAdminAuth())) return;
    const btn = document.getElementById('violationBtn');
    btn.disabled = true;

    const payload = {
        plate_number: normalizePlateInputValue('violPlateNumber'),
        description: document.getElementById('violDescription').value.trim(),
        fine_amount: parseInt(document.getElementById('violFine').value) || 0
    };

    showLoading(true, 'Đang ghi nhận vi phạm...');
    const resultDiv = document.getElementById('violationResult');
    resultDiv.classList.remove('hidden', 'success', 'error');

    try {
        const res = await fetch(`${API}/blockchain/violation`, {
            method: 'POST',
            headers: adminHeaders(),
            body: JSON.stringify(adminPayload(payload))
        });
        const data = await res.json();

        if (data.success) {
            resultDiv.classList.add('success');
            resultDiv.innerHTML = `✅ Đã ghi nhận lỗi cho biển ${escapeHtml(payload.plate_number)}.`;
            document.getElementById('violationForm').reset();
            showToast('Ghi lỗi thành công', 'success');
            await Promise.allSettled([
                refreshDashboard(),
                loadTimeline({ silent: true })
            ]);
        } else {
            resultDiv.classList.add('error');
            resultDiv.innerHTML = `❌ Lỗi: ${escapeHtml(data.error)}`;
            showToast(data.error, 'error');
        }
    } catch (e) {
        resultDiv.classList.add('error');
        resultDiv.innerHTML = '❌ Lỗi kết nối server';
        showToast('Lỗi mạng', 'error');
    }
    btn.disabled = false;
    showLoading(false);
}

async function markViolationPaid(plateNumber, violationIndex, button = null, resultDiv = null) {
    if (!(await ensureAdminAuth('xử lý nộp phạt'))) return;

    const plate = normalizePlateNumber(plateNumber);
    const index = Number(violationIndex);
    if (!plate || !Number.isInteger(index) || index < 0) {
        showToast('Nhập biển số và mã lỗi hợp lệ', 'warning');
        return;
    }

    if (!confirm(`Đánh dấu lỗi #${index} của biển ${plate} là đã nộp phạt?`)) return;

    if (button) button.disabled = true;
    if (resultDiv) resultDiv.classList.remove('hidden', 'success', 'error');
    showLoading(true, 'Đang xử lý nộp phạt trên blockchain...');

    try {
        const res = await fetch(`${API}/blockchain/violation/paid`, {
            method: 'POST',
            headers: adminHeaders(),
            body: JSON.stringify(adminPayload({
                plate_number: plate,
                violation_index: index
            }))
        });
        const data = await res.json();

        if (data.success) {
            if (resultDiv) {
                resultDiv.classList.add('success');
                resultDiv.innerHTML = `✅ Đã đánh dấu lỗi #${escapeHtml(index)} của biển ${escapeHtml(plate)} là đã nộp phạt.<div class="tx-hash">TX: ${escapeHtml(data.tx_hash || '')}</div>`;
            }
            showToast('Đã cập nhật trạng thái nộp phạt', 'success');
            await Promise.allSettled([
                refreshDashboard(),
                loadTimeline({ silent: true })
            ]);
            if (currentTab === 'history') {
                showPlateDetail(plate);
            }
        } else {
            if (resultDiv) {
                resultDiv.classList.add('error');
                resultDiv.innerHTML = `❌ Lỗi: ${escapeHtml(data.error || 'Không thể xử lý nộp phạt')}`;
            }
            showToast(data.error || 'Không thể xử lý nộp phạt', 'error');
        }
    } catch (e) {
        if (resultDiv) {
            resultDiv.classList.add('error');
            resultDiv.innerHTML = '❌ Lỗi kết nối server';
        }
        showToast('Lỗi kết nối server', 'error');
    }

    if (button) button.disabled = false;
    showLoading(false);
}

async function submitMarkViolationPaid(event) {
    event.preventDefault();
    const form = document.getElementById('paidViolationForm');
    const resultDiv = document.getElementById('paidViolationResult');
    const button = document.getElementById('paidViolationBtn');
    await markViolationPaid(
        document.getElementById('paidPlateNumber').value,
        document.getElementById('paidViolationIndex').value,
        button,
        resultDiv
    );
    if (!resultDiv.classList.contains('error')) {
        form.reset();
    }
}

// ============ Search Plate History ============
async function searchPlateHistory() {
    const plate = normalizePlateInputValue('historySearchInput');
    if (!plate) { showToast('Nhập biển số cần tìm', 'warning'); return; }
    showPlateDetail(plate);
}

// ============ Utilities ============
function formatDate(isoStr) {
    if (!isoStr) return 'N/A';
    try {
        const d = new Date(isoStr);
        return d.toLocaleDateString('vi-VN') + ' ' + d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
    } catch (e) { return isoStr; }
}

// ============ WEBCAM REAL-TIME ============
let webcamStream = null;
let webcamActive = false;
let webcamEventSource = null;
let lastLiveDetectionKey = '';

async function startWebcam() {
    try {
        showLoading(true, '🎥 Khởi động webcam...');
        
        const response = await fetch(`${API}/start-webcam`, { method: 'POST' });
        const data = await response.json();
        
        if (data.status === 'started' || data.status === 'already_running') {
            webcamActive = true;
            document.getElementById('startWebcamBtn').classList.add('hidden');
            document.getElementById('stopWebcamBtn').classList.remove('hidden');
            lastLiveDetectionKey = '';

            if (webcamEventSource) {
                webcamEventSource.close();
                webcamEventSource = null;
            }
            
            // Setup EventSource for streaming
            webcamEventSource = new EventSource(`${API}/stream`);
            webcamEventSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.type === 'ping') return;

                    if (data.frame) {
                        const img = new Image();
                        img.onload = () => {
                            const canvas = document.getElementById('webcamCanvas');
                            const container = document.getElementById('webcamContainer');
                            const ctx = canvas.getContext('2d');
                            
                            // Set canvas size to match container
                            canvas.width = container.clientWidth;
                            canvas.height = container.clientHeight;
                            
                            // Fill with background color first
                            ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
                            ctx.fillRect(0, 0, canvas.width, canvas.height);
                            
                            // Calculate dimensions to maintain aspect ratio
                            const imgAspect = img.width / img.height;
                            const canvasAspect = canvas.width / canvas.height;
                            let drawWidth, drawHeight, offsetX, offsetY;
                            
                            if (imgAspect > canvasAspect) {
                                drawWidth = canvas.width;
                                drawHeight = canvas.width / imgAspect;
                                offsetX = 0;
                                offsetY = (canvas.height - drawHeight) / 2;
                            } else {
                                drawHeight = canvas.height;
                                drawWidth = canvas.height * imgAspect;
                                offsetX = (canvas.width - drawWidth) / 2;
                                offsetY = 0;
                            }
                            
                            ctx.drawImage(img, offsetX, offsetY, drawWidth, drawHeight);
                            document.getElementById('webcamCanvas').classList.remove('hidden');
                            document.querySelector('.webcam-placeholder').classList.add('hidden');
                        };
                        img.src = `data:image/jpeg;base64,${data.frame}`;
                    }
                    
                    // Update detections
                    if (Array.isArray(data.detections)) {
                        updateLiveDetections(data.detections, Boolean(data.recognition_pending));
                    }
                } catch (e) { }
            };
            
            webcamEventSource.onerror = () => {
                if (webcamActive) {
                    webcamEventSource.close();
                    webcamEventSource = null;
                    // Update UI to stopped state automatically
                    webcamActive = false;
                    document.getElementById('startWebcamBtn').classList.remove('hidden');
                    document.getElementById('stopWebcamBtn').classList.add('hidden');
                    document.getElementById('webcamCanvas').classList.add('hidden');
                    document.querySelector('.webcam-placeholder').classList.remove('hidden');
                    showToast('⚠️ Mất kết nối webcam (Server khởi động lại hoặc lỗi mạng)', 'warning');
                }
            };
            
            showToast('✅ Webcam đã khởi động', 'success');
        }
        
        showLoading(false);
    } catch (e) {
        showLoading(false);
        showToast('❌ Lỗi khởi động webcam: ' + e.message, 'error');
    }
}

async function stopWebcam() {
    try {
        showLoading(true, '⏹️ Dừng webcam...');
        
        const response = await fetch(`${API}/stop-webcam`, { method: 'POST' });
        const data = await response.json();
        
        if (data.status === 'stopped') {
            webcamActive = false;
            if (webcamEventSource) {
                webcamEventSource.close();
                webcamEventSource = null;
            }
            lastLiveDetectionKey = '';
            document.getElementById('startWebcamBtn').classList.remove('hidden');
            document.getElementById('stopWebcamBtn').classList.add('hidden');
            
            // Ẩn canvas, hiển thị placeholder
            const canvas = document.getElementById('webcamCanvas');
            canvas.classList.add('hidden');
            canvas.width = 0;
            canvas.height = 0;
            
            const container = document.getElementById('webcamContainer');
            container.style.background = 'rgba(0, 0, 0, 0.4)';
            document.querySelector('.webcam-placeholder').classList.remove('hidden');
            document.getElementById('liveDetectionsList').innerHTML = '<div class="empty-msg">Chưa phát hiện biển số nào</div>';
            document.getElementById('liveDetectionCount').textContent = '0';
            showToast('✅ Webcam đã dừng', 'success');
        }
        
        showLoading(false);
    } catch (e) {
        showLoading(false);
        showToast('❌ Lỗi dừng webcam', 'error');
    }
}

function updateLiveDetections(detections, pending = false) {
    const list = document.getElementById('liveDetectionsList');
    const key = JSON.stringify([pending, ...detections.map(det => [
        det.plate_number || '',
        Number(det.confidence || 0).toFixed(3),
        det.needs_review ? 'review' : 'ok'
    ])]);
    if (key === lastLiveDetectionKey) return;
    lastLiveDetectionKey = key;
    document.getElementById('liveDetectionCount').textContent = detections.length;

    if (!detections || detections.length === 0) {
        if (pending) {
            list.innerHTML = '<div class="empty-msg">\u0110ang nh\u1eadn d\u1ea1ng...</div>';
            return;
        }
        list.innerHTML = '<div class="empty-msg">Chưa phát hiện biển số nào</div>';
        return;
    }
    
    let html = '';
    detections.forEach(det => {
        const displayPlate = det.display_plate_number || det.plate_number || '';
        const message = det.quality_message ? `<div class="live-detection-note">${escapeHtml(det.quality_message)}</div>` : '';
        html += `
            <div class="live-detection-item">
                <span class="plate-badge">${escapeHtml(displayPlate)}</span>
                <span class="confidence-badge">${(Number(det.confidence || 0) * 100).toFixed(1)}%</span>
                ${message}
            </div>
        `;
    });
    list.innerHTML = html;
}

// ============ BLOCKCHAIN TIMELINE ============
async function loadTimeline(options = {}) {
    const silent = options?.silent === true;
    const filter = document.getElementById('timelineFilter').value;
    if (!silent) showLoading(true, '📈 Tải timeline...');
    
    try {
        const url = filter ? `${API}/timeline/all?type=${filter}` : `${API}/timeline/all`;
        const response = await fetch(url, { headers: readHeaders() });
        const data = await response.json();
        
        const timeline = document.getElementById('transactionTimeline');
        
        if (!data.transactions || data.transactions.length === 0) {
            timeline.innerHTML = '<div class="empty-msg">Không có giao dịch nào</div>';
        } else {
            let html = '<div class="transactions-list">';
            const txMeta = {
                register: { icon: '➕', label: 'Đăng ký' },
                update: { icon: '🛠️', label: 'Cập nhật phương tiện' },
                reactivate: { icon: '🔓', label: 'Mở khóa phương tiện' },
                transfer: { icon: '🔄', label: 'Chuyển nhượng' },
                violation: { icon: '⚠️', label: 'Vi phạm' },
                fine_paid: { icon: '✅', label: 'Nộp phạt' },
                deactivate: { icon: '🔒', label: 'Khóa phương tiện' }
            };
            data.transactions.forEach(tx => {
                const meta = txMeta[tx.type] || { icon: '•', label: tx.type || 'Khác' };
                const icon = meta.icon;
                const label = meta.label;
                
                html += `
                    <div class="transaction-item">
                        <div class="tx-icon">${icon}</div>
                        <div class="tx-info">
                            <div class="tx-header">
                                <span class="tx-type">${label}</span>
                                <span class="tx-plate">${escapeHtml(tx.plate_number)}</span>
                            </div>
                            <div class="tx-time">${formatDate(tx.timestamp)}</div>
                            <div class="tx-hash">
                                <a href="https://sepolia.etherscan.io/tx/${encodeURIComponent(tx.tx_hash || '')}" target="_blank" rel="noopener noreferrer" style="color: var(--primary);">
                                    🔗 Xem trên Etherscan
                                </a>
                            </div>
                        </div>
                        <div class="tx-gas">${Number(tx.gas_used || 0)} gas</div>
                    </div>
                `;
            });
            html += '</div>';
            timeline.innerHTML = html;
        }
        
        // Update stats
        const stats = await fetch(`${API}/timeline/statistics`, { headers: readHeaders() }).then(r => r.json());
        document.getElementById('totalTransactions').textContent = stats.total_transactions || 0;
        const byType = stats.by_type || {};
        document.getElementById('registerCount').textContent = byType.register || 0;
        document.getElementById('updateCount').textContent = byType.update || 0;
        document.getElementById('reactivateCount').textContent = byType.reactivate || 0;
        document.getElementById('transferCount').textContent = byType.transfer || 0;
        document.getElementById('violationCount').textContent = byType.violation || 0;
        document.getElementById('finePaidCount').textContent = byType.fine_paid || 0;
        document.getElementById('deactivateCount').textContent = byType.deactivate || 0;
        
        if (!silent) showToast(`✅ Tải timeline thành công (${data.transactions.length} giao dịch)`, 'success');
    } catch (e) {
        document.getElementById('transactionTimeline').innerHTML = '<div class="empty-msg">Lỗi tải dữ liệu</div>';
        if (!silent) showToast('❌ Lỗi tải timeline', 'error');
    }
    
    if (!silent) showLoading(false);
}

// ============ STOLEN VEHICLES ============
function clearStolenReportResult() {
    const resultDiv = document.getElementById('stolenReportResult');
    if (!resultDiv) return;
    resultDiv.classList.add('hidden');
    resultDiv.classList.remove('success', 'error');
    resultDiv.innerHTML = '';
}

async function reportStolenVehicle(event) {
    event.preventDefault();
    if (!(await ensureAdminAuth())) return;
    const btn = document.getElementById('reportStolenBtn');
    btn.disabled = true;
    
    const payload = {
        plate_number: normalizePlateInputValue('stolenPlateNumber'),
        owner_name: document.getElementById('stolenOwnerName').value.trim(),
        vehicle_type: document.getElementById('stolenVehicleType').value.trim(),
        color: document.getElementById('stolenColor').value.trim(),
        province: document.getElementById('stolenProvince').value.trim(),
        report_date: document.getElementById('stolenReportDate').value,
        description: document.getElementById('stolenDescription').value.trim()
    };
    
    showLoading(true, '📢 Báo cáo xe mất cắp...');
    const resultDiv = document.getElementById('stolenReportResult');
    resultDiv.classList.remove('hidden', 'success', 'error');
    
    try {
        const res = await fetch(`${API}/stolen/add`, {
            method: 'POST',
            headers: adminHeaders(),
            body: JSON.stringify(adminPayload(payload))
        });
        const data = await res.json();
        
        if (data.success) {
            const lock = data.blockchain_lock;
            const lockHtml = lock
                ? (lock.success
                    ? `<div style="margin-top:8px">🔒 Đã khóa phương tiện trên blockchain.<div class="tx-hash">TX: ${escapeHtml(lock.tx_hash || '')}</div></div>`
                    : `<div style="margin-top:8px;color:var(--warning)">⚠️ Báo cáo đã lưu, nhưng chưa khóa được trên blockchain: ${escapeHtml(lock.error || 'Không rõ lỗi')}</div>`)
                : '';
            resultDiv.classList.add('success');
            resultDiv.innerHTML = `✅ ${escapeHtml(data.message)}${lockHtml}`;
            document.getElementById('stolenReportForm').reset();
            initDatePickers();
            showToast('✅ Báo cáo xe mất thành công', 'success');
            await Promise.allSettled([
                loadStolenList(),
                loadAllPlates(),
                refreshDashboard(),
                loadTimeline({ silent: true })
            ]);
        } else {
            resultDiv.classList.add('error');
            resultDiv.innerHTML = `❌ Lỗi: ${escapeHtml(data.error)}`;
            showToast(data.error, 'error');
        }
    } catch (e) {
        resultDiv.classList.add('error');
        resultDiv.innerHTML = '❌ Lỗi kết nối server';
        showToast('Lỗi mạng', 'error');
    }
    
    btn.disabled = false;
    showLoading(false);
}

async function loadStolenList() {
    clearStolenReportResult();
    showLoading(true, '📋 Tải danh sách xe mất...');
    
    try {
        const response = await fetch(`${API}/stolen/list`, { headers: readHeaders() });
        const data = await response.json();
        
        const list = document.getElementById('stolenList');
        
        if (!data.vehicles || data.vehicles.length === 0) {
            list.innerHTML = '<div class="empty-msg">Chưa có xe mất cắp nào được báo cáo</div>';
        } else {
            let html = '<div class="stolen-vehicles-grid">';
            data.vehicles.forEach(vehicle => {
                html += `
                    <div class="stolen-vehicle-card">
                        <div class="stolen-plate-display">${escapeHtml(vehicle.plate_number)}</div>
                        <div class="stolen-info">
                            <div><strong>Chủ xe:</strong> ${escapeHtml(vehicle.owner_name)}</div>
                            <div><strong>Loại:</strong> ${escapeHtml(vehicle.vehicle_type || 'N/A')}</div>
                            <div><strong>Màu:</strong> ${escapeHtml(vehicle.color || 'N/A')}</div>
                            <div><strong>Tỉnh:</strong> ${escapeHtml(vehicle.province || 'N/A')}</div>
                            <div><strong>Ngày báo:</strong> ${escapeHtml(vehicle.report_date)}</div>
                        </div>
                        ${isAdmin ? `<button class="btn btn-small" onclick="markStolenRecovered(${jsStringArg(vehicle.plate_number)})">✅ Tìm thấy</button>` : ''}
                    </div>
                `;
            });
            html += '</div>';
            list.innerHTML = html;
        }
        
        // Load stats
        const stats = await fetch(`${API}/stolen/statistics`, { headers: readHeaders() }).then(r => r.json());
        document.getElementById('currentStolenCount').textContent = stats.currently_missing || 0;
        document.getElementById('recoveredCount').textContent = stats.recovered || 0;
        document.getElementById('canceledCount').textContent = stats.canceled_reports || 0;
        
        // Province list
        if (stats.by_province && Object.keys(stats.by_province).length > 0) {
            let provinceHtml = '';
            Object.entries(stats.by_province)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 5)
                .forEach(([province, count]) => {
                    provinceHtml += `<div style="padding: 8px; border-bottom: 1px solid var(--border);">
                        <strong>${escapeHtml(province)}</strong>: <span style="color: var(--error);">${Number(count || 0)}</span> xe
                    </div>`;
                });
            document.getElementById('provinceList').innerHTML = provinceHtml;
        }
        
        showToast(`✅ Tải danh sách thành công (${data.total} xe)`, 'success');
    } catch (e) {
        document.getElementById('stolenList').innerHTML = '<div class="empty-msg">Lỗi tải dữ liệu</div>';
        showToast('❌ Lỗi tải danh sách', 'error');
    }
    
    showLoading(false);
}

async function searchStolenVehicles() {
    const search = document.getElementById('stolenSearchInput').value.trim();
    if (!search) {
        loadStolenList();
        return;
    }
    
    showLoading(true, '🔍 Tìm kiếm xe mất...');
    
    try {
        const response = await fetch(`${API}/stolen/search?plate=${encodeURIComponent(search)}`, { headers: readHeaders() });
        const data = await response.json();
        
        const list = document.getElementById('stolenList');
        
        if (!data.vehicles || data.vehicles.length === 0) {
            list.innerHTML = '<div class="empty-msg">Không tìm thấy xe nào phù hợp</div>';
        } else {
            let html = '<div class="stolen-vehicles-grid">';
            data.vehicles.forEach(vehicle => {
                html += `
                    <div class="stolen-vehicle-card">
                        <div class="stolen-plate-display">${escapeHtml(vehicle.plate_number)}</div>
                        <div class="stolen-info">
                            <div><strong>Chủ xe:</strong> ${escapeHtml(vehicle.owner_name)}</div>
                            <div><strong>Loại:</strong> ${escapeHtml(vehicle.vehicle_type || 'N/A')}</div>
                            <div><strong>Màu:</strong> ${escapeHtml(vehicle.color || 'N/A')}</div>
                            <div><strong>Tỉnh:</strong> ${escapeHtml(vehicle.province || 'N/A')}</div>
                        </div>
                        ${isAdmin ? `<button class="btn btn-small" onclick="markStolenRecovered(${jsStringArg(vehicle.plate_number)})">✅ Tìm thấy</button>` : ''}
                    </div>
                `;
            });
            html += '</div>';
            list.innerHTML = html;
        }
        
        showToast(`✅ Tìm thấy ${data.total} kết quả`, 'success');
    } catch (e) {
        showToast('❌ Lỗi tìm kiếm', 'error');
    }
    
    showLoading(false);
}

async function markStolenRecovered(plateNumber) {
    if (!(await ensureAdminAuth())) return;
    if (!confirm(`Bạn có chắc đã tìm thấy xe ${plateNumber} không?`)) return;
    
    showLoading(true, '✅ Cập nhật trạng thái...');
    
    try {
        const res = await fetch(`${API}/stolen/resolve/${encodeURIComponent(plateNumber)}`, {
            method: 'POST',
            headers: adminHeaders(),
            body: JSON.stringify(adminPayload({ status: 'recovered' }))
        });
        const data = await res.json();
        
        if (data.success) {
            const unlock = data.blockchain_unlock;
            if (unlock && unlock.success) {
                showToast('✅ Đã tìm thấy xe và mở khóa phương tiện', 'success');
            } else if (unlock) {
                showToast(`✅ Đã cập nhật danh sách. Chưa mở khóa blockchain: ${unlock.error || 'Không rõ lỗi'}`, 'warning');
            } else {
                showToast('✅ Đã cập nhật - Xe tìm thấy', 'success');
            }
            await Promise.allSettled([
                loadStolenList(),
                loadAllPlates(),
                refreshDashboard(),
                loadTimeline({ silent: true })
            ]);
        } else {
            showToast('❌ Lỗi: ' + data.error, 'error');
        }
    } catch (e) {
        showToast('❌ Lỗi cập nhật', 'error');
    }
    
    showLoading(false);
}

// ============ QR CODE GENERATOR ============
async function generateQRCode() {
    if (!(await ensureAdminAuth('tạo QR xác minh'))) return;
    const plate = normalizePlateInputValue('qrPlateNumber');
    const owner = document.getElementById('qrOwnerName').value.trim();
    const type = document.getElementById('qrVehicleType').value.trim();
    const color = document.getElementById('qrColor')?.value.trim() || '';
    const province = document.getElementById('qrProvince')?.value.trim() || '';
    
    if (!plate || !owner || !type) {
        showToast('⚠️ Vui lòng nhập đủ thông tin', 'warning');
        return;
    }
    
    showLoading(true, '🔲 Tạo QR code...');
    
    try {
        const res = await fetch(`${API}/qr/generate`, {
            method: 'POST',
            headers: adminHeaders(),
            body: JSON.stringify(adminPayload({
                plate_number: plate,
                owner_name: owner,
                vehicle_type: type,
                color,
                province
            }))
        });
        const data = await res.json();
        
        if (data.success) {
            const display = document.getElementById('qrCodeDisplay');
            const img = document.getElementById('qrImage');
            img.src = data.qr_image_url;
            display.classList.remove('hidden');
            showToast('✅ Tạo QR code thành công', 'success');
        } else {
            showToast('❌ Lỗi: ' + data.error, 'error');
        }
    } catch (e) {
        showToast('❌ Lỗi tạo QR code', 'error');
    }
    
    showLoading(false);
}

async function scanQRCode() {
    const fileInput = document.getElementById('qrScanImage');
    const plate = normalizePlateInputValue('qrScanPlate');
    const resultDiv = document.getElementById('qrScanResult');
    const file = fileInput.files && fileInput.files[0];
    if (!file) {
        showToast('Vui lòng chọn ảnh QR', 'warning');
        return;
    }

    resultDiv.classList.remove('hidden', 'success', 'error');
    showLoading(true, 'Đang quét QR...');

    try {
        const formData = new FormData();
        formData.append('image', file);
        if (plate) formData.append('plate_number', plate);

        const res = await fetch(`${API}/qr/scan`, {
            method: 'POST',
            headers: readHeaders(),
            body: formData
        });
        const data = await res.json();

        if (data.success || data.verified) {
            resultDiv.classList.add('success');
            resultDiv.innerHTML = `
                <div><strong>QR hợp lệ</strong></div>
                <div>Biển số: ${escapeHtml(data.plate_number || '')}</div>
                <div>Chủ xe: ${escapeHtml(data.owner_name || '')}</div>
                <div>Loại xe: ${escapeHtml(data.vehicle_type || '')}</div>
                <div>Màu: ${escapeHtml(data.color || '')}</div>
                <div>Tỉnh/TP: ${escapeHtml(data.province || '')}</div>
            `;
            showToast('Đã xác minh QR', 'success');
        } else {
            resultDiv.classList.add('error');
            resultDiv.innerHTML = `Lỗi QR: ${escapeHtml(data.error || 'Không xác minh được')}`;
            showToast(data.error || 'Không xác minh được QR', 'error');
        }
    } catch (e) {
        resultDiv.classList.add('error');
        resultDiv.innerHTML = 'Lỗi kết nối server';
        showToast('Lỗi quét QR', 'error');
    }

    showLoading(false);
}

// ============ Init ============
document.addEventListener('DOMContentLoaded', () => {
    initFormControls();
    checkBlockchainStatus();
    refreshDashboard();
    loadTimeline();
    loadStolenList();
    setInterval(checkBlockchainStatus, 10000);
    setInterval(loadTimeline, 30000);
    setInterval(loadStolenList, 60000);

    const timelineFilter = document.getElementById('timelineFilter');
    if (timelineFilter) {
        timelineFilter.addEventListener('change', loadTimeline);
    }

    const stolenForm = document.getElementById('stolenReportForm');
    if (stolenForm) {
        stolenForm.addEventListener('input', clearStolenReportResult);
        stolenForm.addEventListener('change', clearStolenReportResult);
    }

    // Restore the wallet label without opening an Admin signature prompt.
    if (typeof window.ethereum !== 'undefined') {
        window.ethereum.request({ method: 'eth_accounts' }).then(accounts => {
            if (accounts.length > 0) {
                userAccount = accounts[0];
                updateWalletButton(userAccount);
            }
        }).catch(() => {});
    }
});

// ============ ADMIN AUTHORIZATION ============
async function adminLogin() {
    if (typeof window.ethereum === 'undefined') {
        showToast('MetaMask chưa được cài đặt', 'error');
        return;
    }

    if (!userAccount) {
        await connectMetamask();
    }
    if (!userAccount) return;

    await checkAdminRole(userAccount);
}

async function revokeAdminSession() {
    if (!adminToken) return;
    try {
        await fetch(`${API}/admin/logout`, {
            method: 'POST',
            headers: adminHeaders(),
            body: JSON.stringify(adminPayload())
        });
    } catch (e) {
        console.error('Admin logout error:', e);
    }
}

async function adminLogout() {
    await revokeAdminSession();
    clearAdminAuth();
    updateAdminUI(false);
    if (currentTab === 'admin') switchTab('dashboard');
    showToast('Đã đăng xuất Admin', 'success');
}

async function checkAdminRole(address) {
    if (!address) {
        clearAdminAuth();
        updateAdminUI(false);
        return;
    }

    try {
        if (adminToken && Date.now() < adminTokenExpiresAt) {
            const tokenRes = await fetch(`${API}/admin/check`, {
                method: 'POST',
                headers: adminHeaders(),
                body: JSON.stringify({ admin_token: adminToken })
            });
            const tokenData = await tokenRes.json();
            if (tokenData.is_admin) {
                isAdmin = true;
                updateAdminUI(true, tokenData);
                return;
            }
            clearAdminAuth();
        }

        if (typeof window.ethereum === 'undefined') {
            clearAdminAuth();
            updateAdminUI(false);
            return;
        }

        const challengeRes = await fetch(`${API}/auth/challenge`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ address })
        });
        const challenge = await challengeRes.json();
        if (!challenge.success) {
            clearAdminAuth();
            updateAdminUI(false, challenge);
            showToast(challenge.error || 'Bạn không có quyền Admin', 'warning');
            return;
        }

        const signature = await window.ethereum.request({
            method: 'personal_sign',
            params: [challenge.message, address]
        });

        const res = await fetch(`${API}/admin/check`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                address,
                nonce: challenge.nonce,
                signature
            })
        });
        const data = await res.json();

        isAdmin = data.is_admin === true;
        adminToken = data.admin_token || null;
        adminTokenExpiresAt = data.expires_at ? data.expires_at * 1000 : 0;
        updateAdminUI(isAdmin, data);

        if (isAdmin) {
            showToast('Đã xác thực Admin bằng MetaMask.', 'success');
        } else {
            showToast('Bạn không có quyền Admin', 'warning');
        }
    } catch (e) {
        console.error('Admin check error:', e);
        clearAdminAuth();
        updateAdminUI(false);
    }
}

async function validateCurrentAdminToken() {
    if (!adminToken || Date.now() >= adminTokenExpiresAt) {
        clearAdminAuth();
        updateAdminUI(false);
        return false;
    }

    try {
        const res = await fetch(`${API}/admin/check`, {
            method: 'POST',
            headers: adminHeaders(),
            body: JSON.stringify({ admin_token: adminToken })
        });
        const data = await res.json();
        if (data.is_admin === true) {
            isAdmin = true;
            updateAdminUI(true, data);
            return true;
        }
    } catch (e) {
        console.error('Admin token validation error:', e);
    }

    clearAdminAuth();
    updateAdminUI(false);
    return false;
}

async function ensureAdminAuth(actionName = 'thao tac nay') {
    if (await validateCurrentAdminToken()) {
        return true;
    }

    showToast(`Chức năng "${actionName}" yêu cầu đăng nhập Admin bằng MetaMask`, 'error');
    return false;
}

function updateAdminUI(adminStatus, data = {}) {
    const roleChanged = renderedAdminStatus !== adminStatus;
    renderedAdminStatus = adminStatus;
    const adminBadge = document.getElementById('adminBadge');
    const adminOnlyActions = document.querySelectorAll('.admin-only-action');
    const adminNavItems = document.querySelectorAll('.nav-admin-item');
    const adminLoginItem = document.getElementById('nav-admin-login');
    const adminLogoutItem = document.getElementById('nav-admin-logout');
    const userModeBanner = document.getElementById('userModeBanner');
    const adminModeBanner = document.getElementById('adminModeBanner');
    const blockchainUserBanner = document.getElementById('blockchainUserBanner');
    const blockchainAdminBanner = document.getElementById('blockchainAdminBanner');

    adminOnlyActions.forEach(action => {
        action.classList.toggle('hidden', !adminStatus);
    });
    adminNavItems.forEach(item => item.classList.toggle('hidden', !adminStatus));
    document.querySelectorAll('.nav-label-public').forEach(label => label.classList.toggle('hidden', adminStatus));
    document.querySelectorAll('.nav-label-admin').forEach(label => label.classList.toggle('hidden', !adminStatus));
    adminLoginItem?.classList.toggle('hidden', adminStatus);
    adminLogoutItem?.classList.toggle('hidden', !adminStatus);
    userModeBanner?.classList.toggle('hidden', adminStatus);
    adminModeBanner?.classList.toggle('hidden', !adminStatus);
    blockchainUserBanner?.classList.toggle('hidden', adminStatus);
    blockchainAdminBanner?.classList.toggle('hidden', !adminStatus);

    if (adminStatus) {
        // Show admin badge on topbar
        if (adminBadge) {
            adminBadge.classList.remove('hidden');
            adminBadge.classList.add('admin-badge-animate');
        }

        adminNavItems.forEach(item => item.classList.add('admin-nav-reveal'));

        // Update admin panel info
        if (data.wallet_address) {
            const addrDisplay = document.getElementById('adminAddressDisplay');
            if (addrDisplay) {
                addrDisplay.textContent = data.wallet_address;
                addrDisplay.classList.add('admin-address-verified');
            }
        }
        if (data.admin_address) {
            const contractAdmin = document.getElementById('contractAdminDisplay');
            if (contractAdmin) contractAdmin.textContent = data.admin_address;
        }
        if (data.contract_address) {
            const contractAddr = document.getElementById('contractAddressDisplay');
            if (contractAddr) contractAddr.textContent = data.contract_address;
        }
    } else {
        // Hide admin badge
        if (adminBadge) {
            adminBadge.classList.add('hidden');
            adminBadge.classList.remove('admin-badge-animate');
        }

        adminNavItems.forEach(item => item.classList.remove('admin-nav-reveal'));

        // Reset admin panel info
        const addrDisplay = document.getElementById('adminAddressDisplay');
        if (addrDisplay) {
            addrDisplay.textContent = 'Chưa kết nối';
            addrDisplay.classList.remove('admin-address-verified');
        }
        if (currentTab === 'admin') switchTab('dashboard');
    }

    if (roleChanged) {
        checkBlockchainStatus();
        loadRecentPlates();
        loadAllPlates();
        loadTimeline();
        loadStolenList();
    }
}

// ============ ADMIN PANEL ACTIONS ============
async function adminDeactivatePlate() {
    const input = document.getElementById('adminDeactivatePlate');
    return changePlateActivation({
        mode: 'deactivate',
        plateNumber: input?.value,
        input,
        button: document.getElementById('adminDeactivateBtn'),
        resultDiv: document.getElementById('adminDeactivateResult')
    });
}

async function adminReactivatePlate() {
    const input = document.getElementById('adminDeactivatePlate');
    return changePlateActivation({
        mode: 'reactivate',
        plateNumber: input?.value,
        input,
        button: document.getElementById('adminReactivateBtn'),
        resultDiv: document.getElementById('adminDeactivateResult')
    });
}

async function adminUpdateVehicle(event) {
    event.preventDefault();
    const form = document.getElementById('adminUpdateVehicleForm');
    return changeVehicleInfo({
        plateNumber: normalizePlateInputValue('adminUpdPlate'),
        vehicleType: document.getElementById('adminUpdType').value,
        color: document.getElementById('adminUpdColor').value,
        province: document.getElementById('adminUpdProvince').value,
        form,
        button: document.getElementById('adminUpdateVehicleBtn'),
        resultDiv: document.getElementById('adminUpdateVehicleResult')
    });
}

async function adminAddViolation(event) {
    event.preventDefault();
    if (!(await ensureAdminAuth())) return;

    const payload = {
        plate_number: normalizePlateInputValue('adminViolPlate'),
        description: document.getElementById('adminViolDesc').value.trim(),
        fine_amount: parseInt(document.getElementById('adminViolFine').value) || 0
    };

    showLoading(true, 'Đang ghi nhận vi phạm...');
    const resultDiv = document.getElementById('adminViolationResult');
    resultDiv.classList.remove('hidden', 'success', 'error');

    try {
        const res = await fetch(`${API}/blockchain/violation`, {
            method: 'POST',
            headers: adminHeaders(),
            body: JSON.stringify(adminPayload(payload))
        });
        const data = await res.json();

        if (data.success) {
            resultDiv.classList.add('success');
            resultDiv.innerHTML = `✅ Đã ghi nhận lỗi cho biển ${escapeHtml(payload.plate_number)}.<div class="tx-hash">TX: ${escapeHtml(data.tx_hash)}</div>`;
            document.getElementById('adminViolationForm').reset();
            showToast('✅ Ghi lỗi vi phạm thành công', 'success');
            await Promise.allSettled([
                refreshDashboard(),
                loadTimeline({ silent: true })
            ]);
        } else {
            resultDiv.classList.add('error');
            resultDiv.innerHTML = `❌ Lỗi: ${escapeHtml(data.error)}`;
            showToast(data.error, 'error');
        }
    } catch (e) {
        resultDiv.classList.add('error');
        resultDiv.innerHTML = '❌ Lỗi kết nối server';
    }
    showLoading(false);
}

async function adminMarkViolationPaid(event) {
    event.preventDefault();
    const form = document.getElementById('adminPaidViolationForm');
    const resultDiv = document.getElementById('adminPaidViolationResult');
    const button = document.getElementById('adminPaidViolationBtn');
    await markViolationPaid(
        normalizePlateInputValue('adminPaidPlate'),
        document.getElementById('adminPaidIndex').value,
        button,
        resultDiv
    );
    if (!resultDiv.classList.contains('error')) {
        form.reset();
    }
}

async function adminRegisterPlate(event) {
    event.preventDefault();
    if (!(await ensureAdminAuth())) return;

    const payload = {
        plate_number: normalizePlateInputValue('adminRegPlate'),
        owner_name: document.getElementById('adminRegOwner').value.trim(),
        vehicle_type: document.getElementById('adminRegType').value,
        color: document.getElementById('adminRegColor').value.trim(),
        province: document.getElementById('adminRegProvince').value.trim()
    };

    showLoading(true, 'Đang đăng ký lên blockchain...');
    const resultDiv = document.getElementById('adminRegisterResult');
    resultDiv.classList.remove('hidden', 'success', 'error');

    try {
        const res = await fetch(`${API}/blockchain/register`, {
            method: 'POST',
            headers: adminHeaders(),
            body: JSON.stringify(adminPayload(payload))
        });
        const data = await res.json();

        if (data.success) {
            resultDiv.classList.add('success');
            resultDiv.innerHTML = `
                <div style="font-weight:600;color:var(--success)">✅ Đăng ký thành công!</div>
                <div style="margin-top:8px;font-size:13px">
                    <div>Biển số: <strong>${escapeHtml(data.plate_number)}</strong></div>
                    <div>Block: #${data.block_number}</div>
                    <div>Gas: ${data.gas_used}</div>
                </div>
                <div class="tx-hash">TX: ${escapeHtml(data.tx_hash)}</div>
            `;
            showToast(`✅ Đã đăng ký ${data.plate_number}`, 'success');
            document.getElementById('adminRegisterForm').reset();
            await Promise.allSettled([
                loadAllPlates(),
                refreshDashboard(),
                loadTimeline({ silent: true })
            ]);
        } else {
            resultDiv.classList.add('error');
            resultDiv.innerHTML = `❌ ${escapeHtml(data.error)}`;
            showToast(data.error, 'error');
        }
    } catch (e) {
        resultDiv.classList.add('error');
        resultDiv.innerHTML = '❌ Lỗi kết nối server';
    }
    showLoading(false);
}


