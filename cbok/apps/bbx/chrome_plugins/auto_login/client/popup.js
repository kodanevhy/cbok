window.onload = function () {
    displayPasswords();
}

async function readPassword(address, all_known=false) {
    try {
        const response = await fetch('http://127.0.0.1:80/bbx/chrome_passphrase/');
        const data = await response.json();

        console.log(data)
        if (data.code == 200) {
            if (all_known) {
                return data.result
            } else {
                const match = data.result.find((entry) => entry.ip === address);
                return match ? match.password : null;
            }
        }
      } catch (error) {
        console.error('Error fetching passwords:', error);
        return null;
      }
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
                for (const item of password) {
                    let knownPasswordDiv = document.createElement("div");
                    knownPasswordDiv.className = "known-password";
                    knownPasswordDiv.innerText = `${item.ip}\t${item.password}`;
                    knownPasswordDiv.style.fontSize = "12px";
                    if (domain === item.ip) {
                        knownPasswordDiv.style.fontWeight = "bold";
                        document.getElementById("currentTabPassword").value = item.password;
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
