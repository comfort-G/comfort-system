const resetPasswordForm = document.getElementById('reset-password-form');
const resetMessage = document.getElementById('reset-message');
const resetUrl = new URL(window.location.href);
const resetToken = resetUrl.searchParams.get('token') || '';

if (resetToken) {
    window.history.replaceState({}, document.title, `${resetUrl.pathname}${resetUrl.hash}`);
} else if (resetMessage && resetPasswordForm) {
    resetMessage.textContent = 'This password reset link is invalid or has expired. Request a new one.';
    resetPasswordForm.hidden = true;
}

resetPasswordForm?.addEventListener('submit', async event => {
    event.preventDefault();
    const passwordField = document.getElementById('new-password');
    const confirmField = document.getElementById('confirm-password');
    const submitButton = resetPasswordForm.querySelector('button[type="submit"]');
    if (!passwordField || !confirmField || !resetMessage || !submitButton) return;

    if (passwordField.value !== confirmField.value) {
        resetMessage.textContent = 'The passwords do not match.';
        return;
    }

    resetMessage.textContent = '';
    submitButton.disabled = true;
    try {
        const response = await fetch('/api/auth/reset-password-submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: resetToken,
                new_password: passwordField.value
            })
        });
        const result = await response.json();

        if (response.ok && result.status === 'success') {
            resetMessage.textContent = 'Your password has been reset. You can now sign in.';
            resetPasswordForm.hidden = true;
        } else {
            resetMessage.textContent = result.detail ||
                'Could not reset your password. Request a new reset link and try again.';
        }
    } catch (error) {
        resetMessage.textContent = 'Could not reach the server. Check your connection and try again.';
        console.error('Password reset submission failed:', error);
    } finally {
        submitButton.disabled = false;
    }
});
