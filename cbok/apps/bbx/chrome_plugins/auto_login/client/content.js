chrome.runtime.onMessage.addListener(async function (request, sender, sendResponse) {
    if (request.action === "tabLogin") {
        const username = document.getElementById("id_username");
        const password = document.getElementById("id_password");
        if (!username || !password) {
            console.error("Unsupported page.");
            return;
        }
        const identity = request.identity;
        try {
            await sendLoginRecord(identity);
        } catch (error) {
            console.error('Error sending login record:', error);
        }

        const loginButton = locateLoginButton();
        if (!loginButton) {
            console.error("Cannot locate login button.");
            return;
        }
        username.value = identity.Username;
        password.value = identity.Password;
        loginButton.click();
    }
});


function locateLoginButton() {
    const buttons = document.getElementsByTagName("button");
    for (let i = 0; i < buttons.length; i++) {
        if (buttons[i].innerText === "登录") {
            return buttons[i];
        }
    }
    return null;
}

async function getAddressFromFile() {
    const response = await fetch(chrome.runtime.getURL('address')); 
    const text = await response.text();
    return text.trim();
}

async function sendLoginRecord(identity) {
    const ipAddress = await getAddressFromFile();
    const requestData = {
        address: identity.Address,
        password: identity.Password
    };

    const url = `http://${ipAddress}:30080/bbx/chrome_login_record_create/`;

    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestData),
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        console.log(data);
    } catch (error) {
        console.error('Error:', error);
        throw error;
    }
}
