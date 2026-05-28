// Code.gs

const CONFIG = {
  ALLOWED_DOMAIN: "suaempresa.com.br",
  ALLOWED_EMAILS: [
    "usuario1@suaempresa.com.br",
    "usuario2@suaempresa.com.br"
  ]
};

function doGet() {
  const user = Session.getActiveUser().getEmail();
  if (!isUserAllowed(user)) {
    return HtmlService.createHtmlOutput("Acesso negado.");
  }
  const template = HtmlService.createTemplateFromFile("index");
  template.userEmail = user;
  return template.evaluate().setTitle("Portal Interno");
}

function isUserAllowed(email) {
  if (!email) return false;
  const domain = email.split("@")[1] || "";
  if (domain.toLowerCase() === CONFIG.ALLOWED_DOMAIN.toLowerCase()) {
    return true;
  }
  return CONFIG.ALLOWED_EMAILS.map(e => e.toLowerCase()).includes(email.toLowerCase());
}

function getConfig_() {
  const props = PropertiesService.getScriptProperties();
  return {
    baseUrl: props.getProperty("BASE_URL") || "",
    apiToken: props.getProperty("API_TOKEN") || ""
  };
}

function callServerGet(query) {
  const user = Session.getActiveUser().getEmail();
  if (!isUserAllowed(user)) {
    throw new Error("Acesso negado.");
  }

  const cfg = getConfig_();
  if (!cfg.baseUrl) {
    throw new Error("Configuracao ausente: BASE_URL.");
  }

  const url = `${cfg.baseUrl}/api/health?query=${encodeURIComponent(query || "")}`;
  const options = {
    method: "get",
    headers: buildAuthHeaders_(cfg.apiToken),
    muteHttpExceptions: true
  };

  const response = UrlFetchApp.fetch(url, options);
  const status = response.getResponseCode();
  const body = response.getContentText();

  if (status >= 400) {
    throw new Error(`HTTP ${status}: ${body}`);
  }

  return body;
}

function uploadAndRun(base64Data, filename) {
  const user = Session.getActiveUser().getEmail();
  if (!isUserAllowed(user)) {
    throw new Error("Acesso negado.");
  }

  const cfg = getConfig_();
  if (!cfg.baseUrl) {
    throw new Error("Configuracao ausente: BASE_URL.");
  }

  if (!base64Data || !filename) {
    throw new Error("Arquivo invalido.");
  }

  const bytes = Utilities.base64Decode(base64Data);
  const boundary = "----AppsScriptBoundary" + new Date().getTime();
  const meta =
    "--" + boundary + "\r\n" +
    "Content-Disposition: form-data; name=\"file\"; filename=\"" + filename + "\"\r\n" +
    "Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n";
  const tail = "\r\n--" + boundary + "--\r\n";

  const payload = Utilities.newBlob(meta).getBytes()
    .concat(bytes)
    .concat(Utilities.newBlob(tail).getBytes());

  const response = UrlFetchApp.fetch(cfg.baseUrl + "/api/run", {
    method: "post",
    contentType: "multipart/form-data; boundary=" + boundary,
    payload: payload,
    headers: buildAuthHeaders_(cfg.apiToken),
    muteHttpExceptions: true
  });

  const status = response.getResponseCode();
  const body = response.getContentText();
  if (status >= 400) {
    throw new Error(`HTTP ${status}: ${body}`);
  }

  return body;
}

function buildAuthHeaders_(token) {
  const headers = { "Accept": "application/json" };
  if (token) {
    headers["Authorization"] = "Bearer " + token;
  }
  return headers;
}
