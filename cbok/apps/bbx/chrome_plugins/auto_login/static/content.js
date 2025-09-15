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

async function sendLoginRecord(identity) {
    const requestData = {
        address: identity.Address,
        password: identity.Password
    };

    try {
        const response = await fetch('http://127.0.0.1:8000/bbx/chrome_login_record_create/', {
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
