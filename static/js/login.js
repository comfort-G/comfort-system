const loginForm = document.getElementById('login-form');
const forgotPasswordToggle = document.getElementById('forgot-password-toggle');
const forgotPasswordPanel = document.getElementById('forgot-password-panel');
const forgotPasswordForm = document.getElementById('forgot-password-form');

forgotPasswordToggle?.addEventListener('click', () => {
    if (!forgotPasswordPanel) return;
    const isExpanded = forgotPasswordToggle.getAttribute('aria-expanded') === 'true';
    forgotPasswordToggle.setAttribute('aria-expanded', String(!isExpanded));
    forgotPasswordPanel.hidden = isExpanded;

    const loginIdentifier = document.getElementById('identifier');
    const recoveryIdentifier = document.getElementById('recovery-identifier');
    if (!isExpanded && loginIdentifier && recoveryIdentifier && !recoveryIdentifier.value) {
        recoveryIdentifier.value = loginIdentifier.value;
    }
});

forgotPasswordForm?.addEventListener('submit', async event => {
    event.preventDefault();
    const identifierField = document.getElementById('recovery-identifier');
    const message = document.getElementById('recovery-message');
    const submitButton = forgotPasswordForm.querySelector('button[type="submit"]');
    if (!identifierField || !message || !submitButton) return;

    message.textContent = '';
    submitButton.disabled = true;
    try {
        const response = await fetch('/api/auth/forgot-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ member_id: identifierField.value.trim() })
        });

        message.textContent =
            'Please check your registered email address for the password reset link.';
        if (!response.ok) {
            console.error('Password reset request failed with HTTP status:', response.status);
        }
    } catch (error) {
        message.textContent = 'Could not submit the request. Check your connection and try again.';
        console.error('Password reset request failed:', error);
    } finally {
        submitButton.disabled = false;
    }
});

loginForm?.addEventListener('submit', async event => {
    event.preventDefault();
    const identifierField = document.getElementById('identifier');
    const passwordField = document.getElementById('password');
    const errorBox = document.getElementById('error-message');
    const submitButton = loginForm.querySelector('button[type="submit"]');
    if (!identifierField || !passwordField || !errorBox || !submitButton) return;

    errorBox.textContent = '';
    submitButton.disabled = true;
    try {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
                identifier: identifierField.value.trim(),
                password: passwordField.value
            })
        });

        const responseText = await response.text();
        let result = {};
        if (responseText) {
            try {
                result = JSON.parse(responseText);
            } catch {
                const isHtml = responseText.trimStart().startsWith('<');
                result = {
                    detail: isHtml ? '' : responseText.slice(0, 300)
                };
            }
        }

        if (response.ok && result.status === 'success') {
            window.location.href = result.user?.must_change_password
                ? '/api/profile/settings'
                : '/api/home/view';
        } else {
            const detail = Array.isArray(result.detail)
                ? result.detail.map(error => error.msg).join(' ')
                : result.detail;
            errorBox.textContent = detail || `Sign-in failed (HTTP ${response.status}).`;
        }
    } catch (error) {
        const reason = error instanceof Error ? error.message : String(error);
        errorBox.textContent = `Could not reach the login server: ${reason}. Check your connection and try again.`;
        console.error('Login request failed:', error);
    } finally {
        submitButton.disabled = false;
    }
});
