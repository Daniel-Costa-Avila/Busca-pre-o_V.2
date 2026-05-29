(function () {
    "use strict";

    const bootstrap = window.PRICE_MONITOR_BOOTSTRAP || {};
    const tokenFromQuery = new URLSearchParams(window.location.search).get("api_token") || "";
    const apiToken = tokenFromQuery || bootstrap.apiToken || "";
    const apiBase = (bootstrap.apiBase || window.APP_CONFIG && window.APP_CONFIG.apiBase || "").replace(/\/$/, "");

    const state = {
        currentJobId: localStorage.getItem("pm_current_job_id") || "",
        followMode: false,
        followTimer: null,
        eventSource: null,
        eventsConnected: false,
        eventsJobId: "",
    };
    const adminState = {
        sessionToken: localStorage.getItem("pm_admin_session_token") || "",
        actor: null,
    };

    const timeline = document.getElementById("timeline");
    const chipApi = document.getElementById("chip-api");
    const chipJob = document.getElementById("chip-job");
    const chipTime = document.getElementById("chip-time");

    const kpiQueued = document.getElementById("kpi-queued");
    const kpiRunning = document.getElementById("kpi-running");
    const kpiDone = document.getElementById("kpi-done");
    const kpiFailed = document.getElementById("kpi-failed");

    const runForm = document.getElementById("run-form");
    const fileInput = document.getElementById("file-input");
    const fileInputStatus = document.getElementById("file-input-status");
    const useDefaultInput = document.getElementById("use-default-input");
    const emailRecipients = document.getElementById("email-recipients");
    const outputMode = document.getElementById("output-mode");
    const emailAttachmentFile = document.getElementById("email-attachment-file");
    const whatsappRecipients = document.getElementById("whatsapp-recipients");
    const driveFolderId = document.getElementById("drive-folder-id");
    const driveCredentialsFile = document.getElementById("drive-credentials-file");
    const autoEmailManual = document.getElementById("auto-email-manual");
    const autoEmailDaily = document.getElementById("auto-email-daily");
    const autoWhatsAppManual = document.getElementById("auto-whatsapp-manual");
    const autoWhatsAppDaily = document.getElementById("auto-whatsapp-daily");
    const autoDriveManual = document.getElementById("auto-drive-manual");
    const autoDriveDaily = document.getElementById("auto-drive-daily");
    const btnSaveEmailSettings = document.getElementById("btn-save-email-settings");
    const btnSaveWhatsAppSettings = document.getElementById("btn-save-whatsapp-settings");
    const btnSaveDriveSettings = document.getElementById("btn-save-drive-settings");
    const runFeedback = document.getElementById("run-feedback");
    const downloadManualLatest = document.getElementById("btn-download-manual-latest");

    const currentJob = document.getElementById("current-job");
    const currentStatus = document.getElementById("current-status");
    const currentError = document.getElementById("current-error");
    const currentCreated = document.getElementById("current-created");
    const currentFinished = document.getElementById("current-finished");
    const currentEmailStatus = document.getElementById("current-email-status");
    const currentWhatsAppStatus = document.getElementById("current-whatsapp-status");
    const currentDriveStatus = document.getElementById("current-drive-status");
    const downloadCurrent = document.getElementById("btn-download-current");
    const openDriveCurrent = document.getElementById("btn-open-drive-current");
    const downloadDaily = document.getElementById("btn-download-daily");

    const dailyEnabled = document.getElementById("daily-enabled");
    const dailyTime = document.getElementById("daily-time");
    const dailyRunCount = document.getElementById("daily-run-count");
    const dailyNext = document.getElementById("daily-next");
    const dailyNextSlot = document.getElementById("daily-next-slot");
    const dailyJob = document.getElementById("daily-job");
    const dailyExtraSummary = document.getElementById("daily-extra-summary");
    const dailySlots = document.getElementById("daily-slots");
    const dailyNewTime = document.getElementById("daily-new-time");
    const btnDailyAddTime = document.getElementById("btn-daily-add-time");

    const btnRefreshAll = document.getElementById("btn-refresh-all");
    const btnRefreshStatus = document.getElementById("btn-refresh-status");
    const btnStopRun = document.getElementById("btn-stop-run");
    const btnSendEmailCurrent = document.getElementById("btn-send-email-current");
    const btnSendEmailLatest = document.getElementById("btn-send-email-latest");
    const btnSendWhatsAppCurrent = document.getElementById("btn-send-whatsapp-current");
    const btnSendWhatsAppLatest = document.getElementById("btn-send-whatsapp-latest");
    const btnSendDriveCurrent = document.getElementById("btn-send-drive-current");
    const btnSendDriveLatest = document.getElementById("btn-send-drive-latest");
    const btnClearJob = document.getElementById("btn-clear-job");
    const btnFollow = document.getElementById("btn-follow");
    const downloadLatestFound = document.getElementById("btn-download-latest-found");
    const btnCheckFunctions = document.getElementById("btn-check-functions");

    const themeSelect = document.getElementById("theme-select");
    const densitySelect = document.getElementById("density-select");
    const contrastRange = document.getElementById("contrast-range");
    const featureMenuButtons = Array.from(document.querySelectorAll(".feature-menu-btn[data-feature-target]"));
    const featurePanes = Array.from(document.querySelectorAll(".feature-pane"));
    const activePath = document.getElementById("active-path");
    const marketplaceTabButtons = Array.from(document.querySelectorAll(".tab-btn[data-tab-target]"));
    const marketplaceTabPanes = Array.from(document.querySelectorAll(".tab-pane"));

    const magaluApiKey = document.getElementById("magalu-api-key");
    const magaluApiKeyId = document.getElementById("magalu-api-key-id");
    const magaluApiKeySecret = document.getElementById("magalu-api-key-secret");
    const magaluAccessToken = document.getElementById("magalu-access-token");
    const magaluRefreshToken = document.getElementById("magalu-refresh-token");
    const magaluApiBase = document.getElementById("magalu-api-base");
    const magaluTokenUrl = document.getElementById("magalu-token-url");
    const magaluPricesPath = document.getElementById("magalu-prices-path");
    const magaluSellerId = document.getElementById("magalu-seller-id");
    const magaluRedirectUri = document.getElementById("magalu-redirect-uri");
    const magaluGeneratedReturnUrl = document.getElementById("magalu-generated-return-url");
    const magaluAuthScope = document.getElementById("magalu-auth-scope");
    const magaluAuthUrl = document.getElementById("magalu-auth-url");
    const btnSaveMagaluCredentials = document.getElementById("btn-save-magalu-credentials");

    const magaluFlagApiKey = document.getElementById("magalu-flag-api-key");
    const magaluFlagApiKeyId = document.getElementById("magalu-flag-api-key-id");
    const magaluFlagApiKeySecret = document.getElementById("magalu-flag-api-key-secret");
    const magaluFlagAccessToken = document.getElementById("magalu-flag-access-token");
    const magaluFlagRefreshToken = document.getElementById("magalu-flag-refresh-token");

    const adminSessionStatus = document.getElementById("admin-session-status");
    const adminCurrentUser = document.getElementById("admin-current-user");
    const adminCurrentRole = document.getElementById("admin-current-role");
    const adminLoginUsername = document.getElementById("admin-login-username");
    const adminLoginPassword = document.getElementById("admin-login-password");
    const btnAdminLogin = document.getElementById("btn-admin-login");
    const btnAdminLogout = document.getElementById("btn-admin-logout");
    const btnAdminRefreshUsers = document.getElementById("btn-admin-refresh-users");
    const adminNewUsername = document.getElementById("admin-new-username");
    const adminNewFullName = document.getElementById("admin-new-full-name");
    const adminNewPassword = document.getElementById("admin-new-password");
    const adminNewRole = document.getElementById("admin-new-role");
    const adminNewActive = document.getElementById("admin-new-active");
    const btnAdminCreateUser = document.getElementById("btn-admin-create-user");
    const adminUsersBody = document.getElementById("admin-users-body");
    const adminFeedback = document.getElementById("admin-feedback");

    function logEvent(message, kind) {
        const li = document.createElement("li");
        const now = new Date().toLocaleTimeString("pt-BR");
        const label = document.createElement("strong");
        label.textContent = message;
        const stamp = document.createElement("span");
        stamp.textContent = now;
        li.appendChild(label);
        li.appendChild(stamp);
        if (kind === "error") {
            li.style.borderColor = "rgba(239, 68, 68, 0.35)";
            li.style.background = "rgba(254, 242, 242, 0.85)";
        }
        if (kind === "success") {
            li.style.borderColor = "rgba(16, 185, 129, 0.35)";
            li.style.background = "rgba(236, 253, 245, 0.85)";
        }
        timeline.prepend(li);
        while (timeline.children.length > 18) {
            timeline.removeChild(timeline.lastChild);
        }
    }

    function setFeedback(text, kind) {
        runFeedback.textContent = text || "";
        runFeedback.style.color = kind === "error" ? "#dc2626" : kind === "success" ? "#0f9f6e" : "#637082";
    }

    function updateFileInputStatus() {
        if (!fileInputStatus) return;
        if (useDefaultInput && useDefaultInput.checked) {
            fileInputStatus.textContent = "Base padrao selecionada. O arquivo e opcional.";
            return;
        }
        if (fileInput && fileInput.files && fileInput.files.length > 0) {
            fileInputStatus.textContent = `Arquivo selecionado: ${fileInput.files[0].name}`;
            return;
        }
        fileInputStatus.textContent = "Nenhum arquivo selecionado.";
    }

    function fmtTs(value) {
        if (!value) return "-";
        const number = Number(value);
        if (Number.isNaN(number)) return "-";
        return new Date(number * 1000).toLocaleString("pt-BR");
    }

    function updateClock() {
        chipTime.textContent = new Date().toLocaleTimeString("pt-BR");
    }

    function applyTokenHeaders(headers) {
        if (apiToken) {
            headers.Authorization = `Bearer ${apiToken}`;
        }
        return headers;
    }

    function apiUrl(path) {
        if (!apiBase) return path;
        if (path.startsWith("http://") || path.startsWith("https://")) return path;
        if (!path.startsWith("/")) return `${apiBase}/${path}`;
        return `${apiBase}${path}`;
    }

    async function apiRequest(path, options) {
        const cfg = options || {};
        const headers = applyTokenHeaders(cfg.headers || {});
        const response = await fetch(apiUrl(path), { ...cfg, headers });
        return response;
    }

    async function extractApiError(response) {
        try {
            const data = await response.json();
            if (data && typeof data === "object") {
                if (data.detail) return String(data.detail);
                if (data.error) return String(data.error);
                if (data.message) return String(data.message);
            }
        } catch (jsonErr) {
            // fallback para texto puro
        }
        try {
            const txt = await response.text();
            if (txt && txt.trim()) return txt.trim();
        } catch (textErr) {
            // ignora
        }
        return `HTTP ${response.status}`;
    }

    function applyAdminSessionHeaders(headers) {
        if (adminState.sessionToken) {
            headers["x-user-session"] = adminState.sessionToken;
        }
        return headers;
    }

    async function adminApiRequest(path, options) {
        const cfg = options || {};
        const mergedHeaders = applyAdminSessionHeaders(cfg.headers || {});
        return apiRequest(path, { ...cfg, headers: mergedHeaders });
    }

    function setAdminFeedback(text, kind) {
        if (!adminFeedback) return;
        adminFeedback.textContent = text || "";
        adminFeedback.style.color =
            kind === "error" ? "#dc2626" : kind === "success" ? "#0f9f6e" : "#637082";
    }

    function escapeHtml(value) {
        return String(value || "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll("\"", "&quot;")
            .replaceAll("'", "&#39;");
    }

    function syncAdminSessionUi() {
        const isConnected = Boolean(adminState.sessionToken);
        const actor = adminState.actor || {};
        if (adminSessionStatus) adminSessionStatus.textContent = isConnected ? "Conectado" : "Desconectado";
        if (adminCurrentUser) adminCurrentUser.textContent = actor.username || "-";
        if (adminCurrentRole) adminCurrentRole.textContent = actor.role || "-";
        if (btnAdminLogout) btnAdminLogout.disabled = !isConnected;
    }

    function renderAdminUsers(users) {
        if (!adminUsersBody) return;
        const list = Array.isArray(users) ? users : [];
        if (list.length === 0) {
            adminUsersBody.innerHTML = `
                <tr>
                    <td colspan="7">Nenhum usuario cadastrado.</td>
                </tr>
            `;
            return;
        }

        adminUsersBody.innerHTML = list
            .map(function (user) {
                const username = String(user.username || "");
                const fullName = String(user.full_name || "");
                const role = String(user.role || "operator");
                const isActive = Boolean(user.is_active);
                const createdAt = String(user.created_at || "-");
                const updatedAt = String(user.updated_at || "-");
                const statusLabel = isActive ? "Ativo" : "Inativo";
                const toggleActiveLabel = isActive ? "Desativar" : "Ativar";
                const toggleRoleLabel = role === "admin" ? "Tornar Operator" : "Tornar Admin";
                return `
                    <tr>
                        <td>${escapeHtml(username)}</td>
                        <td>${escapeHtml(fullName || "-")}</td>
                        <td>${escapeHtml(role)}</td>
                        <td>${escapeHtml(statusLabel)}</td>
                        <td>${escapeHtml(createdAt)}</td>
                        <td>${escapeHtml(updatedAt)}</td>
                        <td>
                            <div class="mini-actions">
                                <button class="mini-btn" data-admin-action="toggle-active" data-username="${escapeHtml(username)}" data-active="${isActive ? "1" : "0"}">${escapeHtml(toggleActiveLabel)}</button>
                                <button class="mini-btn" data-admin-action="toggle-role" data-username="${escapeHtml(username)}" data-role="${escapeHtml(role)}">${escapeHtml(toggleRoleLabel)}</button>
                                <button class="mini-btn" data-admin-action="reset-password" data-username="${escapeHtml(username)}">Nova Senha</button>
                                <button class="mini-btn danger" data-admin-action="delete" data-username="${escapeHtml(username)}">Excluir</button>
                            </div>
                        </td>
                    </tr>
                `;
            })
            .join("");
    }

    async function refreshAdminUsers(silent) {
        syncAdminSessionUi();
        if (!adminState.sessionToken) {
            if (!silent) {
                setAdminFeedback("Conecte uma sessao admin para listar usuarios.", "info");
            }
            renderAdminUsers([]);
            return;
        }
        try {
            const response = await adminApiRequest("/api/admin/users", { method: "GET" });
            if (response.status === 401 || response.status === 403) {
                adminState.sessionToken = "";
                adminState.actor = null;
                localStorage.removeItem("pm_admin_session_token");
                syncAdminSessionUi();
            }
            if (!response.ok) {
                const detail = await extractApiError(response);
                throw new Error(detail);
            }
            const data = await response.json();
            adminState.actor = data.actor || adminState.actor;
            syncAdminSessionUi();
            renderAdminUsers(data.users || []);
            if (!silent) {
                setAdminFeedback(`Usuarios carregados: ${Number(data.count || 0)}.`, "success");
            }
        } catch (error) {
            renderAdminUsers([]);
            setAdminFeedback(`Falha ao carregar usuarios: ${error.message}`, "error");
            logEvent(`Falha ao carregar usuarios: ${error.message}`, "error");
        }
    }

    async function adminAuthenticate() {
        try {
            const payload = {
                username: (adminLoginUsername && adminLoginUsername.value ? adminLoginUsername.value : "admin").trim(),
                password: adminLoginPassword && adminLoginPassword.value ? adminLoginPassword.value : "admin123",
            };
            const response = await apiRequest("/api/admin/users/authenticate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!response.ok) {
                const detail = await extractApiError(response);
                throw new Error(detail);
            }
            const data = await response.json();
            adminState.sessionToken = String(data.session_token || "");
            adminState.actor = data.user || null;
            localStorage.setItem("pm_admin_session_token", adminState.sessionToken);
            syncAdminSessionUi();
            await refreshAdminUsers(true);
            setAdminFeedback(`Sessao admin iniciada para ${adminState.actor && adminState.actor.username ? adminState.actor.username : "-"}.`, "success");
            logEvent("Sessao admin iniciada.", "success");
        } catch (error) {
            setAdminFeedback(`Falha ao autenticar admin: ${error.message}`, "error");
            logEvent(`Falha ao autenticar admin: ${error.message}`, "error");
        }
    }

    async function adminLogout() {
        try {
            await adminApiRequest("/api/admin/users/logout", { method: "POST" });
        } catch (error) {
            logEvent(`Falha ao encerrar sessao admin: ${error.message}`, "error");
        }
        adminState.sessionToken = "";
        adminState.actor = null;
        localStorage.removeItem("pm_admin_session_token");
        syncAdminSessionUi();
        renderAdminUsers([]);
        setAdminFeedback("Sessao admin encerrada.", "info");
    }

    async function adminCreateUser() {
        const username = adminNewUsername ? adminNewUsername.value.trim() : "";
        const fullName = adminNewFullName ? adminNewFullName.value.trim() : "";
        const password = adminNewPassword ? adminNewPassword.value : "";
        const role = adminNewRole ? adminNewRole.value : "operator";
        const isActive = adminNewActive ? Boolean(adminNewActive.checked) : true;

        if (!username || !password) {
            setAdminFeedback("Informe usuario e senha para criar um novo cadastro.", "error");
            return;
        }

        try {
            const response = await adminApiRequest("/api/admin/users", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    username: username,
                    password: password,
                    full_name: fullName || null,
                    role: role,
                    is_active: isActive,
                }),
            });
            if (!response.ok) {
                const detail = await extractApiError(response);
                throw new Error(detail);
            }

            if (adminNewUsername) adminNewUsername.value = "";
            if (adminNewFullName) adminNewFullName.value = "";
            if (adminNewPassword) adminNewPassword.value = "";
            if (adminNewRole) adminNewRole.value = "operator";
            if (adminNewActive) adminNewActive.checked = true;

            await refreshAdminUsers(true);
            setAdminFeedback(`Usuario ${username} criado com sucesso.`, "success");
            logEvent(`Usuario ${username} criado.`, "success");
        } catch (error) {
            setAdminFeedback(`Falha ao criar usuario: ${error.message}`, "error");
            logEvent(`Falha ao criar usuario: ${error.message}`, "error");
        }
    }

    async function adminUpdateUser(username, payload) {
        const response = await adminApiRequest(`/api/admin/users/${encodeURIComponent(username)}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const detail = await extractApiError(response);
            throw new Error(detail);
        }
        return response.json();
    }

    async function adminDeleteUser(username) {
        const response = await adminApiRequest(`/api/admin/users/${encodeURIComponent(username)}`, {
            method: "DELETE",
        });
        if (!response.ok) {
            const detail = await extractApiError(response);
            throw new Error(detail);
        }
        return response.json();
    }

    async function handleAdminTableClick(event) {
        const target = event.target;
        if (!target || !target.dataset) return;
        const action = String(target.dataset.adminAction || "");
        const username = String(target.dataset.username || "");
        if (!action || !username) return;

        try {
            if (action === "toggle-active") {
                const isActive = String(target.dataset.active || "") === "1";
                await adminUpdateUser(username, { is_active: !isActive });
                await refreshAdminUsers(true);
                setAdminFeedback(`Usuario ${username} atualizado.`, "success");
                return;
            }

            if (action === "toggle-role") {
                const role = String(target.dataset.role || "operator").toLowerCase();
                const nextRole = role === "admin" ? "operator" : "admin";
                await adminUpdateUser(username, { role: nextRole });
                await refreshAdminUsers(true);
                setAdminFeedback(`Perfil de ${username} alterado para ${nextRole}.`, "success");
                return;
            }

            if (action === "reset-password") {
                const newPassword = window.prompt(`Nova senha para ${username}:`, "");
                if (!newPassword || !newPassword.trim()) return;
                await adminUpdateUser(username, { new_password: newPassword.trim() });
                setAdminFeedback(`Senha de ${username} atualizada.`, "success");
                logEvent(`Senha de ${username} atualizada por admin.`);
                return;
            }

            if (action === "delete") {
                const confirmed = window.confirm(`Excluir usuario ${username}?`);
                if (!confirmed) return;
                await adminDeleteUser(username);
                await refreshAdminUsers(true);
                setAdminFeedback(`Usuario ${username} excluido.`, "success");
                logEvent(`Usuario ${username} excluido.`, "success");
            }
        } catch (error) {
            setAdminFeedback(`Falha na operacao (${action}): ${error.message}`, "error");
            logEvent(`Falha na operacao de usuario (${action}): ${error.message}`, "error");
        }
    }

    function setCredentialChip(chipElement, label, configured) {
        if (!chipElement) return;
        chipElement.textContent = `${label}: ${configured ? "configurado" : "pendente"}`;
        chipElement.className = configured ? "chip chip-ok" : "chip chip-pending";
    }

    function setSecretFieldPlaceholder(inputElement, configured) {
        if (!inputElement) return;
        inputElement.placeholder = configured
            ? "Ja configurado (preencha para atualizar)"
            : "Nao configurado";
    }

    function activateMarketplaceTab(targetId) {
        if (!targetId) return;

        marketplaceTabButtons.forEach(function (button) {
            const isActive = button.dataset.tabTarget === targetId;
            button.classList.toggle("is-active", isActive);
            button.setAttribute("aria-selected", isActive ? "true" : "false");
        });

        marketplaceTabPanes.forEach(function (pane) {
            const isActive = pane.id === targetId;
            pane.classList.toggle("is-active", isActive);
            pane.classList.toggle("hidden", !isActive);
        });
    }

    function bindMarketplaceTabs() {
        marketplaceTabButtons.forEach(function (button) {
            button.setAttribute("role", "tab");
            button.addEventListener("click", function () {
                activateMarketplaceTab(button.dataset.tabTarget);
            });
        });

        if (marketplaceTabButtons.length > 0) {
            activateMarketplaceTab(marketplaceTabButtons[0].dataset.tabTarget);
        }
    }

    function activateFeaturePane(targetId) {
        if (!targetId) return;

        let activeLabel = "Visao Geral";
        featureMenuButtons.forEach(function (button) {
            const isActive = button.dataset.featureTarget === targetId;
            button.classList.toggle("is-active", isActive);
            if (isActive) {
                activeLabel = String(button.dataset.featureLabel || button.textContent || activeLabel).trim();
            }
        });

        featurePanes.forEach(function (pane) {
            const isActive = pane.id === targetId;
            pane.classList.toggle("is-active", isActive);
            pane.classList.toggle("hidden", !isActive);
        });

        if (activePath) {
            activePath.textContent = `Painel / ${activeLabel}`;
        }
        localStorage.setItem("pm_feature_tab", targetId);
    }

    function bindFeatureMenu() {
        featureMenuButtons.forEach(function (button) {
            button.addEventListener("click", function () {
                activateFeaturePane(button.dataset.featureTarget);
            });
        });

        if (featureMenuButtons.length === 0) return;

        const stored = localStorage.getItem("pm_feature_tab") || "";
        const hasStored = featurePanes.some(function (pane) {
            return pane.id === stored;
        });
        const fallback = featureMenuButtons[0].dataset.featureTarget;
        activateFeaturePane(hasStored ? stored : fallback);
    }

    function buildNonEmptyPayload(candidates) {
        const payload = {};
        Object.entries(candidates).forEach(function (entry) {
            const key = entry[0];
            const rawValue = entry[1];
            if (!rawValue) return;
            const value = String(rawValue).trim();
            if (!value) return;
            payload[key] = value;
        });
        return payload;
    }

    async function refreshMarketplaceCredentials() {
        try {
            const response = await apiRequest("/api/marketplace/credentials", { method: "GET" });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            const magalu = data.magalu || {};

            setCredentialChip(magaluFlagApiKey, "API Key", Boolean(magalu.has_api_key));
            setCredentialChip(magaluFlagApiKeyId, "Key ID", Boolean(magalu.has_api_key_id));
            setCredentialChip(magaluFlagApiKeySecret, "Key Secret", Boolean(magalu.has_api_key_secret));
            setCredentialChip(magaluFlagAccessToken, "Access Token", Boolean(magalu.has_access_token));
            setCredentialChip(magaluFlagRefreshToken, "Refresh Token", Boolean(magalu.has_refresh_token));

            setSecretFieldPlaceholder(magaluApiKey, Boolean(magalu.has_api_key));
            setSecretFieldPlaceholder(magaluApiKeyId, Boolean(magalu.has_api_key_id));
            setSecretFieldPlaceholder(magaluApiKeySecret, Boolean(magalu.has_api_key_secret));
            setSecretFieldPlaceholder(magaluAccessToken, Boolean(magalu.has_access_token));
            setSecretFieldPlaceholder(magaluRefreshToken, Boolean(magalu.has_refresh_token));

            if (magaluApiBase) magaluApiBase.value = String(magalu.api_base || "");
            if (magaluTokenUrl) magaluTokenUrl.value = String(magalu.token_url || "");
            if (magaluPricesPath) magaluPricesPath.value = String(magalu.prices_path || "");
            if (magaluSellerId) magaluSellerId.value = String(magalu.seller_id || "");
            if (magaluRedirectUri) magaluRedirectUri.value = String(magalu.redirect_uri || "");
            if (magaluGeneratedReturnUrl) magaluGeneratedReturnUrl.value = String(magalu.return_url || "");
            if (magaluAuthScope) magaluAuthScope.value = String(magalu.auth_scope || "");
            if (magaluAuthUrl) {
                const authUrl = String(magalu.authorization_url || "");
                if (authUrl) {
                    magaluAuthUrl.href = authUrl;
                    magaluAuthUrl.classList.remove("hidden");
                } else {
                    magaluAuthUrl.href = "#";
                    magaluAuthUrl.classList.add("hidden");
                }
            }
        } catch (error) {
            logEvent(`Falha ao carregar credenciais de API: ${error.message}`, "error");
        }
    }

    async function saveMagaluCredentials() {
        const payload = buildNonEmptyPayload({
            api_key: magaluApiKey && magaluApiKey.value,
            api_key_id: magaluApiKeyId && magaluApiKeyId.value,
            api_key_secret: magaluApiKeySecret && magaluApiKeySecret.value,
            access_token: magaluAccessToken && magaluAccessToken.value,
            refresh_token: magaluRefreshToken && magaluRefreshToken.value,
            api_base: magaluApiBase && magaluApiBase.value,
            token_url: magaluTokenUrl && magaluTokenUrl.value,
            prices_path: magaluPricesPath && magaluPricesPath.value,
            seller_id: magaluSellerId && magaluSellerId.value,
            redirect_uri: magaluRedirectUri && magaluRedirectUri.value,
            auth_scope: magaluAuthScope && magaluAuthScope.value,
        });
        if (Object.keys(payload).length === 0) {
            logEvent("Nenhum campo da Magalu preenchido para salvar.");
            return;
        }

        try {
            const response = await apiRequest("/api/marketplace/credentials/magalu", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!response.ok) {
                const detail = await extractApiError(response);
                throw new Error(detail);
            }

            if (magaluApiKey) magaluApiKey.value = "";
            if (magaluApiKeyId) magaluApiKeyId.value = "";
            if (magaluApiKeySecret) magaluApiKeySecret.value = "";
            if (magaluAccessToken) magaluAccessToken.value = "";
            if (magaluRefreshToken) magaluRefreshToken.value = "";

            await refreshMarketplaceCredentials();
            logEvent("Credenciais da Magalu salvas.", "success");
        } catch (error) {
            logEvent(`Falha ao salvar credenciais da Magalu: ${error.message}`, "error");
        }
    }

    function updateJobUI(statusData) {
        if (!state.currentJobId) {
            currentJob.textContent = "-";
            currentStatus.textContent = "-";
            currentError.textContent = "-";
            currentCreated.textContent = "-";
            currentFinished.textContent = "-";
            currentEmailStatus.textContent = "-";
            currentWhatsAppStatus.textContent = "-";
            currentDriveStatus.textContent = "-";
            chipJob.textContent = "Job: -";
            downloadCurrent.classList.add("hidden");
            if (openDriveCurrent) {
                openDriveCurrent.classList.add("hidden");
                openDriveCurrent.href = "#";
            }
            return;
        }

        currentJob.textContent = state.currentJobId;
        chipJob.textContent = `Job: ${state.currentJobId}`;
        if (!statusData) return;

        currentStatus.textContent = statusData.status || "-";
        currentError.textContent = statusData.error || "-";
        currentCreated.textContent = fmtTs(statusData.created_at);
        currentFinished.textContent = fmtTs(statusData.finished_at);
        const emailBase = statusData.email_status || "-";
        const emailErr = statusData.email_error ? ` (${statusData.email_error})` : "";
        currentEmailStatus.textContent = `${emailBase}${emailErr}`;
        const whatsappBase = statusData.whatsapp_status || "-";
        const whatsappErr = statusData.whatsapp_error ? ` (${statusData.whatsapp_error})` : "";
        currentWhatsAppStatus.textContent = `${whatsappBase}${whatsappErr}`;
        const driveBase = statusData.drive_status || "-";
        const driveErr = statusData.drive_error ? ` (${statusData.drive_error})` : "";
        currentDriveStatus.textContent = `${driveBase}${driveErr}`;

        if (statusData.output_available) {
            downloadCurrent.href = withToken(`/download/${state.currentJobId}`);
            downloadCurrent.classList.remove("hidden");
        } else {
            downloadCurrent.classList.add("hidden");
        }

        if (openDriveCurrent) {
            if (statusData.drive_file_url) {
                openDriveCurrent.href = statusData.drive_file_url;
                openDriveCurrent.classList.remove("hidden");
            } else {
                openDriveCurrent.classList.add("hidden");
                openDriveCurrent.href = "#";
            }
        }
    }

    function withToken(url) {
        if (!apiToken) return url;
        const joiner = url.includes("?") ? "&" : "?";
        return `${apiUrl(url)}${joiner}api_token=${encodeURIComponent(apiToken)}`;
    }

    function closeRealtimeEvents() {
        if (state.eventSource) {
            state.eventSource.close();
            state.eventSource = null;
        }
        if (state.eventsConnected) {
            state.eventsConnected = false;
            chipApi.textContent = "API: online (polling)";
            chipApi.className = "chip chip-pending";
        }
    }

    function updateManualLatestFromPayload(latest) {
        if (latest && latest.job_id && latest.output_available) {
            downloadManualLatest.href = withToken(`/download/${latest.job_id}`);
            downloadManualLatest.classList.remove("hidden");
        } else {
            downloadManualLatest.classList.add("hidden");
        }
    }

    function updateLatestOutputFromPayload(latest) {
        if (!downloadLatestFound) return;
        if (latest && latest.job_id && latest.output_available) {
            downloadLatestFound.href = withToken(`/download/${latest.job_id}`);
            downloadLatestFound.classList.remove("hidden");
            return;
        }
        downloadLatestFound.href = "#";
        downloadLatestFound.classList.add("hidden");
    }

    function applyRealtimeSnapshot(payload) {
        if (!payload || typeof payload !== "object") return;

        updateKpis(payload.counts || null);
        updateManualLatestFromPayload(payload.latest_manual_job || null);

        if (
            state.currentJobId &&
            payload.current_job &&
            payload.current_job.job_id === state.currentJobId
        ) {
            updateJobUI(payload.current_job);
        }
    }

    function buildEventsUrl() {
        const query = state.currentJobId ? `?job_id=${encodeURIComponent(state.currentJobId)}` : "";
        return withToken(`/api/events${query}`);
    }

    function syncRealtimeSubscription() {
        if (typeof EventSource === "undefined") {
            return;
        }

        const wantedJobId = state.currentJobId || "";
        if (state.eventSource && state.eventsJobId === wantedJobId) {
            return;
        }

        closeRealtimeEvents();
        state.eventsJobId = wantedJobId;

        const source = new EventSource(buildEventsUrl());
        state.eventSource = source;

        source.addEventListener("open", function () {
            if (!state.eventsConnected) {
                logEvent("Canal de atualizacao em tempo real conectado.", "success");
            }
            state.eventsConnected = true;
            chipApi.textContent = "API: online (tempo real)";
            chipApi.className = "chip chip-ok";
        });

        source.addEventListener("snapshot", function (event) {
            try {
                const payload = JSON.parse(event.data || "{}");
                applyRealtimeSnapshot(payload);
            } catch (error) {
                // Mantem o stream ativo mesmo se houver payload invalido.
            }
        });

        source.addEventListener("error", function () {
            if (state.eventsConnected) {
                logEvent("Canal em tempo real desconectado. Reconeccao automatica em andamento.", "error");
            }
            state.eventsConnected = false;
            chipApi.textContent = "API: online (reconectando)";
            chipApi.className = "chip chip-pending";
        });
    }

    async function refreshHealth() {
        try {
            const response = await fetch("/api/health", { method: "GET" });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            chipApi.textContent = "API: online";
            chipApi.className = "chip chip-ok";
            return true;
        } catch (error) {
            chipApi.textContent = "API: offline";
            chipApi.className = "chip chip-bad";
            logEvent(`Falha na API: ${error.message}`, "error");
            return false;
        }
    }

    async function refreshDaily() {
        try {
            const response = await apiRequest("/api/daily/latest", { method: "GET" });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            applyDailySchedule(data);
        } catch (error) {
            dailyEnabled.textContent = "indisponivel";
            if (dailySlots) {
                dailySlots.innerHTML = "";
            }
            logEvent(`Agenda diaria indisponivel: ${error.message}`, "error");
        }
    }

    async function addDailyTime() {
        if (!dailyNewTime) return;
        let value = String(dailyNewTime.value || "").trim();
        if (!value) {
            logEvent("Informe um horario no formato HH:MM.", "error");
            return;
        }
        if (/^\d{3,4}$/.test(value)) {
            value = value.padStart(4, "0");
            value = `${value.slice(0, 2)}:${value.slice(2)}`;
        }
        if (/^\d{1,2}:\d{2}:\d{2}$/.test(value)) {
            value = value.slice(0, 5);
        }
        if (!/^\d{1,2}:\d{2}$/.test(value)) {
            logEvent("Horario invalido. Use o formato HH:MM (ex.: 09:30).", "error");
            return;
        }
        try {
            const response = await apiRequest("/api/daily/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ run_time: value, enabled: true }),
            });
            if (!response.ok) {
                const detail = await extractApiError(response);
                throw new Error(detail);
            }
            dailyNewTime.value = "";
            logEvent(`Horario ${value} adicionado.`, "success");
            await refreshDaily();
        } catch (error) {
            logEvent(`Falha ao adicionar horario: ${error.message}`, "error");
        }
    }

    function applyDailySchedule(data) {
        dailyEnabled.textContent = data.enabled ? "ATIVA" : "INATIVA";
        if (dailyRunCount) {
            const activeCount = Number(data.active_slot_count || 0);
            dailyRunCount.textContent = activeCount === 1 ? "1 horario ativo" : `${activeCount} horarios ativos`;
        }
        if (Array.isArray(data.run_times) && data.run_times.length > 0) {
            dailyTime.textContent = `Ativos: ${data.run_times.join(", ")}`;
        } else {
            dailyTime.textContent = "Ativos: -";
        }
        dailyNext.textContent = data.next_run_at ? fmtTs(data.next_run_at) : "-";
        if (dailyNextSlot) {
            dailyNextSlot.textContent = data.next_run_time ? `Proximo horario: ${data.next_run_time}` : "Sem proxima execucao";
        }
        if (dailyExtraSummary) {
            const extraTotal = Number(data.extra_total_count || 0);
            const extraEnabled = Number(data.extra_enabled_count || 0);
            dailyExtraSummary.textContent =
                extraTotal > 0 ? `${extraEnabled}/${extraTotal} extras ativos` : "Sem horarios extras";
        }

        const latest = data.latest_daily_job;
        if (latest && latest.job_id) {
            dailyJob.textContent = `${latest.job_id} (${latest.status})`;
            if (latest.output_available) {
                downloadDaily.href = withToken("/download/daily/fixed");
                downloadDaily.classList.remove("hidden");
            } else {
                downloadDaily.classList.add("hidden");
            }
        } else {
            dailyJob.textContent = "Nenhum job";
            downloadDaily.classList.add("hidden");
        }
        renderDailySlots(Array.isArray(data.slots) ? data.slots : [], Boolean(data.enabled));
    }

    function renderDailySlots(slots, automationEnabled) {
        if (!dailySlots) return;
        if (!Array.isArray(slots) || slots.length === 0) {
            dailySlots.innerHTML = "";
            return;
        }
        dailySlots.innerHTML = slots
            .map(function (slot) {
                const time = String(slot.time || "");
                const enabled = Boolean(slot.enabled);
                const fixed = Boolean(slot.fixed);
                const isNext = Boolean(slot.is_next);
                const title = String(slot.title || (fixed ? "Rotina fixa" : "Horario adicional"));
                const description = String(slot.description || "");
                const badges = [];
                if (fixed) {
                    badges.push('<span class="daily-slot-badge is-fixed">Fixo</span>');
                }
                if (isNext && automationEnabled) {
                    badges.push('<span class="daily-slot-badge is-next">Proximo</span>');
                }
                return `
                    <article class="daily-slot${enabled ? " is-enabled" : ""}${fixed ? " is-fixed" : ""}${isNext && automationEnabled ? " is-next" : ""}">
                        <div class="daily-slot-main">
                            <div class="daily-slot-topline">
                                <strong class="daily-slot-time">${escapeHtml(time)}</strong>
                                ${badges.join("")}
                            </div>
                            <span class="daily-slot-title">${escapeHtml(title)}</span>
                            <span class="daily-slot-description">${escapeHtml(description)}</span>
                        </div>
                        <button
                            type="button"
                            class="schedule-switch${fixed ? " is-fixed" : ""}"
                            data-run-time="${escapeHtml(time)}"
                            aria-label="${escapeHtml(fixed ? `Horario fixo ${time}` : `Alternar horario ${time}`)}"
                            aria-pressed="${enabled ? "true" : "false"}"
                            ${fixed ? "disabled" : ""}
                        ></button>
                    </article>
                `;
            })
            .join("");
    }

    async function toggleDailySlot(runTime, enabled, triggerButton) {
        if (!runTime) return;
        if (triggerButton) {
            triggerButton.disabled = true;
        }
        try {
            const response = await apiRequest("/api/daily/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ run_time: runTime, enabled }),
            });
            if (!response.ok) {
                throw new Error(await extractApiError(response));
            }
            const data = await response.json();
            applyDailySchedule(data);
            logEvent(enabled ? `Horario ${runTime} ativado.` : `Horario ${runTime} desativado.`, "success");
        } catch (error) {
            if (triggerButton) {
                triggerButton.disabled = false;
            }
            logEvent(`Falha ao atualizar horario ${runTime}: ${error.message}`, "error");
        }
    }

    function handleDailySlotsClick(event) {
        const button = event.target.closest(".schedule-switch[data-run-time]");
        if (!button || button.disabled) return;
        const runTime = String(button.dataset.runTime || "");
        const nextEnabled = button.getAttribute("aria-pressed") !== "true";
        toggleDailySlot(runTime, nextEnabled, button);
    }

    async function refreshManualLatest() {
        try {
            const response = await apiRequest("/api/manual/latest", { method: "GET" });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            updateManualLatestFromPayload(data.latest_manual_job || null);
        } catch (error) {
            downloadManualLatest.classList.add("hidden");
            logEvent(`Ultimo manual indisponivel: ${error.message}`, "error");
        }
    }

    async function refreshLatestOutput() {
        try {
            const response = await apiRequest("/api/output/latest", { method: "GET" });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            updateLatestOutputFromPayload(data.latest_output_job || null);
        } catch (error) {
            updateLatestOutputFromPayload(null);
            logEvent(`Ultima planilha indisponivel: ${error.message}`, "error");
        }
    }

    async function recoverCurrentJobFromLatestManual() {
        const response = await apiRequest("/api/manual/latest", { method: "GET" });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        const latest = data.latest_manual_job;
        if (!latest || !latest.job_id) {
            state.currentJobId = "";
            localStorage.removeItem("pm_current_job_id");
            updateJobUI(null);
            syncRealtimeSubscription();
            return;
        }
        state.currentJobId = latest.job_id;
        localStorage.setItem("pm_current_job_id", latest.job_id);
        updateJobUI(latest);
        syncRealtimeSubscription();
    }

    async function refreshStatus() {
        updateJobUI(null);
        if (!state.currentJobId) return;
        try {
            const response = await apiRequest(`/api/status/${state.currentJobId}`, { method: "GET" });
            if (response.status === 404) {
                await recoverCurrentJobFromLatestManual();
                return;
            }
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            updateJobUI(data);

            if (data.status === "DONE") {
                logEvent(`Job ${state.currentJobId} concluido.`, "success");
            }
            if (data.status === "FAILED") {
                const detail = data.error ? ` (${data.error})` : "";
                logEvent(`Job ${state.currentJobId} falhou${detail}.`, "error");
            }
            if (data.status === "STOPPED") {
                const detail = data.error ? ` (${data.error})` : "";
                logEvent(`Job ${state.currentJobId} interrompido${detail}.`, "error");
            }
        } catch (error) {
            logEvent(`Erro ao consultar status: ${error.message}`, "error");
        }
    }

    function updateKpis(counts) {
        if (!counts) return;
        if (kpiQueued) kpiQueued.textContent = counts.QUEUED ?? kpiQueued.textContent;
        if (kpiRunning) kpiRunning.textContent = counts.RUNNING ?? kpiRunning.textContent;
        if (kpiDone) kpiDone.textContent = counts.DONE ?? kpiDone.textContent;
        if (kpiFailed) kpiFailed.textContent = counts.FAILED ?? kpiFailed.textContent;
    }

    async function refreshOverview() {
        try {
            const response = await apiRequest("/api/overview", { method: "GET" });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            updateKpis(data.counts || null);
        } catch (error) {
            logEvent(`Falha ao atualizar KPIs: ${error.message}`, "error");
        }
    }

    async function refreshEmailSettings() {
        try {
            const response = await apiRequest("/api/email/settings", { method: "GET" });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (typeof data.recipients_csv === "string") {
                emailRecipients.value = data.recipients_csv;
            }
            autoEmailManual.checked = Boolean(data.auto_send_manual);
            autoEmailDaily.checked = Boolean(data.auto_send_daily);
        } catch (error) {
            logEvent(`Falha ao carregar configuracao de e-mail: ${error.message}`, "error");
        }
    }

    async function refreshWhatsAppSettings() {
        try {
            const response = await apiRequest("/api/whatsapp/settings", { method: "GET" });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (typeof data.recipients_csv === "string") {
                whatsappRecipients.value = data.recipients_csv;
            }
            autoWhatsAppManual.checked = Boolean(data.auto_send_manual);
            autoWhatsAppDaily.checked = Boolean(data.auto_send_daily);
        } catch (error) {
            logEvent(`Falha ao carregar configuracao de WhatsApp: ${error.message}`, "error");
        }
    }

    async function refreshDriveSettings() {
        try {
            const response = await apiRequest("/api/drive/settings", { method: "GET" });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (typeof data.folder_id === "string" && driveFolderId) {
                driveFolderId.value = data.folder_id;
            }
            if (typeof data.credentials_file === "string" && driveCredentialsFile) {
                driveCredentialsFile.value = data.credentials_file;
            }
            if (autoDriveManual) {
                autoDriveManual.checked = Boolean(data.auto_send_manual);
            }
            if (autoDriveDaily) {
                autoDriveDaily.checked = Boolean(data.auto_send_daily);
            }
        } catch (error) {
            logEvent(`Falha ao carregar configuracao de Google Drive: ${error.message}`, "error");
        }
    }

    async function saveEmailSettings() {
        const payload = {
            recipients: emailRecipients.value.trim(),
            auto_send_manual: autoEmailManual.checked,
            auto_send_daily: autoEmailDaily.checked,
        };
        try {
            const response = await apiRequest("/api/email/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            emailRecipients.value = data.recipients_csv || "";
            autoEmailManual.checked = Boolean(data.auto_send_manual);
            autoEmailDaily.checked = Boolean(data.auto_send_daily);
            logEvent("Configuracao de e-mail salva.", "success");
        } catch (error) {
            logEvent(`Falha ao salvar configuracao de e-mail: ${error.message}`, "error");
        }
    }

    async function saveWhatsAppSettings() {
        const payload = {
            recipients: whatsappRecipients.value.trim(),
            auto_send_manual: autoWhatsAppManual.checked,
            auto_send_daily: autoWhatsAppDaily.checked,
        };
        try {
            const response = await apiRequest("/api/whatsapp/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            whatsappRecipients.value = data.recipients_csv || "";
            autoWhatsAppManual.checked = Boolean(data.auto_send_manual);
            autoWhatsAppDaily.checked = Boolean(data.auto_send_daily);
            logEvent("Configuracao de WhatsApp salva.", "success");
        } catch (error) {
            logEvent(`Falha ao salvar configuracao de WhatsApp: ${error.message}`, "error");
        }
    }

    async function saveDriveSettings() {
        const payload = {
            credentials_file: driveCredentialsFile ? driveCredentialsFile.value.trim() : "",
            folder_id: driveFolderId ? driveFolderId.value.trim() : "",
            auto_send_manual: autoDriveManual ? autoDriveManual.checked : false,
            auto_send_daily: autoDriveDaily ? autoDriveDaily.checked : false,
        };
        try {
            const response = await apiRequest("/api/drive/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (driveCredentialsFile) driveCredentialsFile.value = data.credentials_file || "";
            if (driveFolderId) driveFolderId.value = data.folder_id || "";
            if (autoDriveManual) autoDriveManual.checked = Boolean(data.auto_send_manual);
            if (autoDriveDaily) autoDriveDaily.checked = Boolean(data.auto_send_daily);
            const accountLabel = data.service_account_email ? ` (${data.service_account_email})` : "";
            logEvent(`Configuracao de Google Drive salva${accountLabel}.`, "success");
        } catch (error) {
            logEvent(`Falha ao salvar configuracao de Google Drive: ${error.message}`, "error");
        }
    }

    async function startRun(event) {
        event.preventDefault();
        const file = fileInput.files[0];
        if (!file && !useDefaultInput.checked) {
            setFeedback("Selecione um arquivo ou habilite o uso do input padrao.", "error");
            return;
        }

        setFeedback("Iniciando processamento...", "info");
        const formData = new FormData();
        if (file) {
            formData.append("file", file, file.name);
        }
        formData.append("email_recipients", emailRecipients.value.trim());
        formData.append("output_mode", outputMode ? outputMode.value : "completa");
        if (emailAttachmentFile && emailAttachmentFile.files.length > 0) {
            const extraFile = emailAttachmentFile.files[0];
            formData.append("email_attachment_file", extraFile, extraFile.name);
        }
        formData.append("whatsapp_recipients", whatsappRecipients.value.trim());
        formData.append("auto_email", autoEmailManual.checked ? "1" : "0");
        formData.append("auto_email_daily", autoEmailDaily.checked ? "1" : "0");
        formData.append("auto_whatsapp", autoWhatsAppManual.checked ? "1" : "0");
        formData.append("auto_whatsapp_daily", autoWhatsAppDaily.checked ? "1" : "0");
        formData.append("drive_folder_id", driveFolderId ? driveFolderId.value.trim() : "");
        formData.append("drive_credentials_file", driveCredentialsFile ? driveCredentialsFile.value.trim() : "");
        formData.append("auto_drive", autoDriveManual && autoDriveManual.checked ? "1" : "0");
        formData.append("auto_drive_daily", autoDriveDaily && autoDriveDaily.checked ? "1" : "0");

        try {
            const response = await apiRequest("/api/run", {
                method: "POST",
                body: formData,
            });
            if (!response.ok) {
                const detail = await extractApiError(response);
                throw new Error(detail || `HTTP ${response.status}`);
            }
            const data = await response.json();
            state.currentJobId = data.job_id || "";
            localStorage.setItem("pm_current_job_id", state.currentJobId);
            updateJobUI(null);
            syncRealtimeSubscription();
            activateFeaturePane("feature-pane-status");
            setFeedback(`Job iniciado: ${state.currentJobId}`, "success");
            const autoEmailLabel = data.auto_email_enabled ? "com envio automatico" : "sem envio automatico";
            const autoWhatsAppLabel = data.auto_whatsapp_enabled ? "WhatsApp automatico ativo" : "WhatsApp automatico inativo";
            const autoDriveLabel = data.auto_drive_enabled ? "Drive automatico ativo" : "Drive automatico inativo";
            logEvent(`Job ${state.currentJobId} iniciado (${autoEmailLabel}; ${autoWhatsAppLabel}; ${autoDriveLabel}).`, "success");
            await refreshStatus();
        } catch (error) {
            setFeedback(`Falha ao iniciar job: ${error.message}`, "error");
            logEvent(`Falha ao iniciar job: ${error.message}`, "error");
        }
    }

    function clearJob() {
        state.currentJobId = "";
        localStorage.removeItem("pm_current_job_id");
        updateJobUI(null);
        syncRealtimeSubscription();
        setFeedback("Job atual limpo.", "info");
        logEvent("Job atual removido do painel.");
    }

    async function sendLatestByEmail(recipientsCsv) {
        const query = recipientsCsv ? `?to=${encodeURIComponent(recipientsCsv)}` : "";
        const response = await apiRequest(`/api/email/send/latest${query}`, {
            method: "POST",
        });
        if (!response.ok) {
            const detail = await extractApiError(response);
            throw new Error(detail);
        }

        const data = await response.json();
        const latestJobId = data.job_id || "";
        if (latestJobId) {
            state.currentJobId = latestJobId;
            localStorage.setItem("pm_current_job_id", latestJobId);
            syncRealtimeSubscription();
            await refreshStatus();
        }
        logEvent(`E-mail enviado para o ultimo resultado disponivel (${latestJobId || "-"})`, "success");
    }

    async function stopRunningJob() {
        try {
            const response = await apiRequest("/api/jobs/stop", { method: "POST" });
            if (!response.ok) {
                const detail = await extractApiError(response);
                throw new Error(detail);
            }
            const data = await response.json();
            if (data.status === "idle") {
                logEvent("Nenhum job em execucao para parar.");
            } else {
                if (data.job_id) {
                    state.currentJobId = data.job_id;
                    localStorage.setItem("pm_current_job_id", state.currentJobId);
                    syncRealtimeSubscription();
                }
                logEvent(`Solicitacao de parada enviada para job ${data.job_id}.`, "success");
            }
            await refreshOverview();
            await refreshStatus();
        } catch (error) {
            logEvent(`Falha ao parar job: ${error.message || "erro desconhecido"}`, "error");
        }
    }

    async function sendCurrentByEmail() {
        const recipients = emailRecipients.value.trim();

        try {
            if (!state.currentJobId) {
                await sendLatestByEmail(recipients);
                return;
            }

            const query = recipients ? `?to=${encodeURIComponent(recipients)}` : "";
            const response = await apiRequest(`/api/email/${state.currentJobId}/send${query}`, { method: "POST" });
            if (response.ok) {
                logEvent(`E-mail enviado para job ${state.currentJobId}.`, "success");
                await refreshStatus();
                return;
            }

            const detail = await extractApiError(response);
            if (String(detail).toLowerCase().includes("somente jobs concluidos")) {
                logEvent("Job atual nao concluido. Enviando ultimo disponivel...", "success");
                await sendLatestByEmail(recipients);
                return;
            }

            throw new Error(detail);
        } catch (error) {
            logEvent(`Falha no envio por e-mail: ${error.message || "erro desconhecido"}`, "error");
        }
    }

    async function sendLatestByEmailNow() {
        const recipients = emailRecipients.value.trim();
        try {
            await sendLatestByEmail(recipients);
        } catch (error) {
            logEvent(`Falha no envio por e-mail: ${error.message || "erro desconhecido"}`, "error");
        }
    }

    async function sendLatestByWhatsApp(recipientsCsv) {
        const query = recipientsCsv ? `?to=${encodeURIComponent(recipientsCsv)}` : "";
        const response = await apiRequest(`/api/whatsapp/send/latest${query}`, {
            method: "POST",
        });
        if (!response.ok) {
            const detail = await extractApiError(response);
            throw new Error(detail);
        }

        const data = await response.json();
        const latestJobId = data.job_id || "";
        if (latestJobId) {
            state.currentJobId = latestJobId;
            localStorage.setItem("pm_current_job_id", latestJobId);
            syncRealtimeSubscription();
            await refreshStatus();
        }
        logEvent(`WhatsApp enviado para o ultimo resultado disponivel (${latestJobId || "-"})`, "success");
    }

    async function sendCurrentByWhatsApp() {
        const recipients = whatsappRecipients.value.trim();

        try {
            if (!state.currentJobId) {
                await sendLatestByWhatsApp(recipients);
                return;
            }

            const query = recipients ? `?to=${encodeURIComponent(recipients)}` : "";
            const response = await apiRequest(`/api/whatsapp/${state.currentJobId}/send${query}`, { method: "POST" });
            if (response.ok) {
                logEvent(`WhatsApp enviado para job ${state.currentJobId}.`, "success");
                await refreshStatus();
                return;
            }

            const detail = await extractApiError(response);
            if (String(detail).toLowerCase().includes("somente jobs concluidos")) {
                logEvent("Job atual nao concluido. Enviando ultimo disponivel por WhatsApp...", "success");
                await sendLatestByWhatsApp(recipients);
                return;
            }

            throw new Error(detail);
        } catch (error) {
            logEvent(`Falha no envio por WhatsApp: ${error.message || "erro desconhecido"}`, "error");
        }
    }

    async function sendLatestByWhatsAppNow() {
        const recipients = whatsappRecipients.value.trim();
        try {
            await sendLatestByWhatsApp(recipients);
        } catch (error) {
            logEvent(`Falha no envio por WhatsApp: ${error.message || "erro desconhecido"}`, "error");
        }
    }

    async function sendLatestToDrive(folderId, credentialsFile) {
        let query = "";
        const params = new URLSearchParams();
        if (folderId) params.set("folder_id", folderId);
        if (credentialsFile) params.set("credentials_file", credentialsFile);
        const serialized = params.toString();
        if (serialized) query = `?${serialized}`;

        const response = await apiRequest(`/api/drive/upload/latest${query}`, {
            method: "POST",
        });
        if (!response.ok) {
            const detail = await extractApiError(response);
            throw new Error(detail);
        }

        const data = await response.json();
        const latestJobId = data.job_id || "";
        if (latestJobId) {
            state.currentJobId = latestJobId;
            localStorage.setItem("pm_current_job_id", latestJobId);
            syncRealtimeSubscription();
            await refreshStatus();
        }
        logEvent(`Upload para Google Drive concluido (${latestJobId || "-"})`, "success");
    }

    async function sendCurrentToDrive() {
        const folderId = driveFolderId ? driveFolderId.value.trim() : "";
        const credentialsFile = driveCredentialsFile ? driveCredentialsFile.value.trim() : "";

        try {
            if (!state.currentJobId) {
                await sendLatestToDrive(folderId, credentialsFile);
                return;
            }

            const params = new URLSearchParams();
            if (folderId) params.set("folder_id", folderId);
            if (credentialsFile) params.set("credentials_file", credentialsFile);
            const query = params.toString() ? `?${params.toString()}` : "";

            const response = await apiRequest(`/api/drive/${state.currentJobId}/upload${query}`, { method: "POST" });
            if (response.ok) {
                logEvent(`Resultado salvo no Google Drive para job ${state.currentJobId}.`, "success");
                await refreshStatus();
                return;
            }

            const detail = await extractApiError(response);
            if (String(detail).toLowerCase().includes("somente jobs concluidos")) {
                logEvent("Job atual nao concluido. Enviando ultimo disponivel para o Google Drive...", "success");
                await sendLatestToDrive(folderId, credentialsFile);
                return;
            }

            throw new Error(detail);
        } catch (error) {
            logEvent(`Falha no upload para Google Drive: ${error.message || "erro desconhecido"}`, "error");
        }
    }

    async function sendLatestToDriveNow() {
        const folderId = driveFolderId ? driveFolderId.value.trim() : "";
        const credentialsFile = driveCredentialsFile ? driveCredentialsFile.value.trim() : "";
        try {
            await sendLatestToDrive(folderId, credentialsFile);
        } catch (error) {
            logEvent(`Falha no upload para Google Drive: ${error.message || "erro desconhecido"}`, "error");
        }
    }

    function toggleFollowMode() {
        state.followMode = !state.followMode;
        btnFollow.textContent = state.followMode ? "Parar Seguimento" : "Seguir Job";
        if (state.followMode) {
            state.followTimer = setInterval(refreshStatus, 5000);
            logEvent("Seguimento automatico ativado.");
        } else if (state.followTimer) {
            clearInterval(state.followTimer);
            state.followTimer = null;
            logEvent("Seguimento automatico pausado.");
        }
    }

    function applyVisualPrefs() {
        const savedTheme = localStorage.getItem("pm_theme") || "apple";
        const savedDensity = localStorage.getItem("pm_density") || "comfortable";
        const savedScale = localStorage.getItem("pm_scale") || "1";

        themeSelect.value = savedTheme;
        densitySelect.value = savedDensity;
        contrastRange.value = savedScale;

        document.body.classList.remove("theme-apple", "theme-graphite", "theme-ocean");
        document.body.classList.add(`theme-${savedTheme}`);
        document.body.classList.remove("density-compact", "density-comfortable", "density-spacious");
        document.body.classList.add(`density-${savedDensity}`);
        document.documentElement.style.setProperty("--scale", savedScale);
    }

    function bindVisualPrefs() {
        themeSelect.addEventListener("change", function () {
            localStorage.setItem("pm_theme", themeSelect.value);
            applyVisualPrefs();
        });
        densitySelect.addEventListener("change", function () {
            localStorage.setItem("pm_density", densitySelect.value);
            applyVisualPrefs();
        });
        contrastRange.addEventListener("input", function () {
            localStorage.setItem("pm_scale", contrastRange.value);
            applyVisualPrefs();
        });
    }

    async function runFunctionsCheck() {
        if (btnCheckFunctions) {
            btnCheckFunctions.disabled = true;
        }
        try {
            const response = await apiRequest("/api/functions/check", { method: "GET" });
            if (!response.ok) {
                const detail = await extractApiError(response);
                throw new Error(detail);
            }
            const data = await response.json();
            const summary = data.summary || {};
            const status = String(data.status || "ok").toLowerCase();
            const okCount = Number(summary.ok || 0);
            const warnCount = Number(summary.warn || 0);
            const errorCount = Number(summary.error || 0);

            const kind = status === "error" ? "error" : status === "ok" ? "success" : undefined;
            logEvent(
                `Verificacao concluida (${status.toUpperCase()}): ok=${okCount}, alerta=${warnCount}, erro=${errorCount}.`,
                kind
            );

            if (Array.isArray(data.checks)) {
                const issues = data.checks.filter(function (check) {
                    return check && String(check.status || "").toLowerCase() !== "ok";
                });
                issues.slice(0, 4).forEach(function (check) {
                    const checkStatus = String(check.status || "").toUpperCase();
                    const checkName = String(check.name || "check");
                    const checkDetail = String(check.detail || "");
                    const checkKind = checkStatus === "ERROR" ? "error" : undefined;
                    logEvent(`${checkStatus} ${checkName}: ${checkDetail}`, checkKind);
                });
            }

            await refreshAll();
        } catch (error) {
            logEvent(`Falha na verificacao de funcoes: ${error.message}`, "error");
        } finally {
            if (btnCheckFunctions) {
                btnCheckFunctions.disabled = false;
            }
        }
    }

    async function refreshAll() {
        await refreshHealth();
        await refreshOverview();
        await refreshEmailSettings();
        await refreshWhatsAppSettings();
        await refreshDriveSettings();
        await refreshMarketplaceCredentials();
        await refreshAdminUsers(true);
        await refreshDaily();
        await refreshLatestOutput();
        await refreshManualLatest();
        await refreshStatus();
    }

    function bindEvents() {
        runForm.addEventListener("submit", startRun);
        if (fileInput) {
            fileInput.addEventListener("change", updateFileInputStatus);
        }
        if (useDefaultInput) {
            useDefaultInput.addEventListener("change", updateFileInputStatus);
        }
        btnRefreshAll.addEventListener("click", refreshAll);
        btnRefreshStatus.addEventListener("click", refreshStatus);
        btnStopRun.addEventListener("click", stopRunningJob);
        btnSaveEmailSettings.addEventListener("click", saveEmailSettings);
        btnSaveWhatsAppSettings.addEventListener("click", saveWhatsAppSettings);
        if (btnSaveDriveSettings) {
            btnSaveDriveSettings.addEventListener("click", saveDriveSettings);
        }
        btnSendEmailCurrent.addEventListener("click", sendCurrentByEmail);
        if (btnSendEmailLatest) {
            btnSendEmailLatest.addEventListener("click", sendLatestByEmailNow);
        }
        if (btnSendWhatsAppCurrent) {
            btnSendWhatsAppCurrent.addEventListener("click", sendCurrentByWhatsApp);
        }
        if (btnSendWhatsAppLatest) {
            btnSendWhatsAppLatest.addEventListener("click", sendLatestByWhatsAppNow);
        }
        if (btnSendDriveCurrent) {
            btnSendDriveCurrent.addEventListener("click", sendCurrentToDrive);
        }
        if (btnSendDriveLatest) {
            btnSendDriveLatest.addEventListener("click", sendLatestToDriveNow);
        }
        if (dailySlots) {
            dailySlots.addEventListener("click", handleDailySlotsClick);
        }
        if (btnDailyAddTime) {
            btnDailyAddTime.addEventListener("click", addDailyTime);
        }
        btnClearJob.addEventListener("click", clearJob);
        btnFollow.addEventListener("click", toggleFollowMode);
        if (btnCheckFunctions) {
            btnCheckFunctions.addEventListener("click", runFunctionsCheck);
        }
        if (btnSaveMagaluCredentials) {
            btnSaveMagaluCredentials.addEventListener("click", saveMagaluCredentials);
        }
        if (btnAdminLogin) {
            btnAdminLogin.addEventListener("click", adminAuthenticate);
        }
        if (btnAdminLogout) {
            btnAdminLogout.addEventListener("click", adminLogout);
        }
        if (btnAdminRefreshUsers) {
            btnAdminRefreshUsers.addEventListener("click", function () {
                refreshAdminUsers(false);
            });
        }
        if (btnAdminCreateUser) {
            btnAdminCreateUser.addEventListener("click", adminCreateUser);
        }
        if (adminUsersBody) {
            adminUsersBody.addEventListener("click", handleAdminTableClick);
        }
    }

    function init() {
        updateKpis(bootstrap.initialCounts);
        applyVisualPrefs();
        bindVisualPrefs();
        bindFeatureMenu();
        bindMarketplaceTabs();
        syncAdminSessionUi();
        bindEvents();
        updateFileInputStatus();
        window.addEventListener("beforeunload", closeRealtimeEvents);
        updateClock();
        setInterval(updateClock, 1000);
        refreshAll();
        syncRealtimeSubscription();
        setInterval(refreshDaily, 60000);
        setInterval(refreshLatestOutput, 60000);
        setInterval(refreshManualLatest, 60000);
        setInterval(refreshOverview, 15000);
        logEvent("Painel inicializado com sucesso.");
    }

    init();
})();
