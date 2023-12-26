chrome.runtime.onMessage.addListener(function (request, sender, sendResponse) {
    if (request.action === "tabLogin") {
        const username = document.getElementById("id_username");
        const password = document.getElementById("id_password");
        if (!username || !password) {
            console.error("Unsupported page.");
            return;
        }
        const loginButton = locateLoginButton();
        if (!loginButton) {
            console.error("Cannot locate login button.");
            return;
        }
        const identity = request.identity;
        username.value = identity.correctedUsername;
        password.value = identity.correctedPassword;
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
