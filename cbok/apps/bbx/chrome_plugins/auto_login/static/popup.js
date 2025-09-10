window.onload = function () {
    displayPasswords();
}

function readPassword(address, all_known=false) {
    return new Promise((resolve, reject) => {
        fetch('passphrase')
            .then(response => response.text())
            .then(data => {
                const lines = data.split('\n');
                if (all_known) {
                    resolve(lines);
                    return;
                }
                for (const line of lines) {
                    const parts = line.split(',');
                    if (parts[0].trim() === address) {
                        let password = parts[2].trim();
                        resolve(password);
                        return;
                    }
                }
                resolve(null);
            })
            .catch(error => reject(error));
    });
}

function displayPasswords() {
    chrome.tabs.query({active: true, currentWindow: true}, function (tabs) {
        const currentTab = tabs[0];
        const currentUrl = currentTab.url;
        const domain = extractDomain(currentUrl);
        document.getElementById('stageDomain').innerText = domain
        // Fill in current tab password and display all known passwords
        readPassword(domain, true).then(password => {
            if (password) {
                let parent = document.getElementById("knownPasswords");
                for (const line of password) {
                    if (!line) {
                        continue;
                    }
                    const parts = line.split(',');
                    let knownPasswordDiv = document.createElement("div");
                    knownPasswordDiv.className = "known-password";
                    knownPasswordDiv.innerText = `${parts[0]}\t${parts[2]}`;
                    knownPasswordDiv.style.fontSize = "12px";
                    if (domain === parts[0]) {
                        knownPasswordDiv.style.fontWeight = "bold";
                        document.getElementById("currentTabPassword").value = parts[2];
                    }
                    parent.appendChild(knownPasswordDiv);
                }
            }
        });

    });
}

function i_meta() {
    return {
        "Address": document.getElementById("stageDomain").innerText,
        "Username": "admin@example.org",
        "Password": document.getElementById("currentTabPassword").value,
    };
}

const tabLogin = document.getElementById('tabLogin')
tabLogin.onclick = async function () {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true})
    const identity = i_meta()
    await chrome.tabs.sendMessage(tab.id, {action: "tabLogin", identity: identity})
}

const showPasswordCheckbox = document.getElementById('showPasswordCheckbox');
showPasswordCheckbox.onclick = function () {
    let passwordField = document.getElementById("currentTabPassword");
    let checkbox = document.getElementById("showPasswordCheckbox");

    if (checkbox.checked) {
        passwordField.type = "text";
    } else {
        passwordField.type = "password";
    }
    // Ensure consistent styling after checkbox state change
    passwordField.style.width = passwordField.offsetWidth + "px";
};

const toggleKnownPasswords = document.getElementById('toggleKnownPasswords');
const knownPasswords = document.getElementById('knownPasswords');
toggleKnownPasswords.addEventListener('click', function() {

    // Toggle the display of the known passwords section
    knownPasswords.style.display = knownPasswords.style.display === 'none' ? 'block' : 'none';
});

function extractDomain(currentUrl) {
    let domain;
    const match = currentUrl.match(/:\/\/(www[0-9]?\.)?(.[^/:]+)/i);
    if (match != null && match.length > 2 && typeof match[2] === 'string' && match[2].length > 0) {
        domain = match[2];
    }
    return domain;
}
