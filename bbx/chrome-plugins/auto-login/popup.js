window.onload = function () {
    displayCorrectedPassword();
}

function displayCorrectedPassword() {
    chrome.tabs.query({active: true, currentWindow: true}, function (tabs) {
        const currentTab = tabs[0];
        const currentUrl = currentTab.url;
        const domain = extractDomain(currentUrl);
        let cachedPassword = localStorage.getItem(domain);
        if (cachedPassword) {
            document.getElementById("correctedPassword").value = cachedPassword;
        }
    });
}

const tabLogin = document.getElementById('tabLogin');
tabLogin.onclick = async function () {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    const identity = getCurrentIdentity();
    await chrome.tabs.sendMessage(tab.id, {action: "tabLogin", identity: identity});
}

const showPasswordCheckbox = document.getElementById('showPasswordCheckbox');
showPasswordCheckbox.onclick = function () {
    let passwordField = document.getElementById("correctedPassword");
    let checkbox = document.getElementById("showPasswordCheckbox");

    if (checkbox.checked) {
        passwordField.type = "text";
    } else {
        passwordField.type = "password";
    }
    // Ensure consistent styling after checkbox state change
    passwordField.style.width = passwordField.offsetWidth + "px";
}

function extractDomain(currentUrl) {
    let domain;
    const match = currentUrl.match(/:\/\/(www[0-9]?\.)?(.[^/:]+)/i);
    if (match != null && match.length > 2 && typeof match[2] === 'string' && match[2].length > 0) {
        domain = match[2];
    }
    return domain
}

function getCorrectedPassword() {
    return document.getElementById("correctedPassword").value;
}

function getCurrentIdentity() {
    chrome.tabs.query({active: true, currentWindow: true}, function (tabs) {
        const currentTab = tabs[0];
        const currentUrl = currentTab.url;
        let domain = extractDomain(currentUrl);
        localStorage.setItem(domain, getCorrectedPassword());
    });
    return {"correctedUsername": "admin@example.org", "correctedPassword": getCorrectedPassword()};
}
