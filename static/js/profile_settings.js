function setProfileMessage(id, text, isError = false) {
    const message = document.getElementById(id);
    if (!message) return;
    message.textContent = text;
    message.classList.toggle('is-error', isError);
}

async function submitProfileForm(form, endpoint, messageId, payloadBuilder, successMessage) {
    const button = form.querySelector('button[type="submit"]');
    if (!(button instanceof HTMLButtonElement)) return;
    button.disabled = true;
    setProfileMessage(messageId, '');

    try {
        const response = await fetch(endpoint, {
            method: 'PUT',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payloadBuilder(new FormData(form)))
        });
        const result = await readApiJson(response, 'Could not save profile settings. Please try again.');
        if (!response.ok) {
            throw new Error(result.detail || `Update failed (HTTP ${response.status}).`);
        }
        setProfileMessage(messageId, result.message || successMessage);
        return true;
    } catch (error) {
        setProfileMessage(
            messageId,
            error instanceof Error ? error.message : 'The update could not be completed.',
            true
        );
        console.error(`Profile update failed for ${endpoint}:`, error);
        return false;
    } finally {
        button.disabled = false;
    }
}

document.getElementById('member-profile-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!(form instanceof HTMLFormElement)) return;
    await submitProfileForm(
        form,
        '/api/profile/me',
        'profile-details-message',
        data => ({
            phone: String(data.get('phone') || '').trim(),
            email: String(data.get('email') || '').trim() || null,
            address: String(data.get('address') || '').trim() || null,
            occupation: String(data.get('occupation') || '').trim() || null,
            date_of_birth: String(data.get('date_of_birth') || '') || null,
            next_of_kin_name: String(data.get('next_of_kin_name') || '').trim() || null,
            next_of_kin_relationship: String(data.get('next_of_kin_relationship') || '').trim() || null,
            next_of_kin_phone: String(data.get('next_of_kin_phone') || '').trim() || null
        }),
        'Profile details saved.'
    );
});

function calculateAge(value) {
    if (!value) return 'Not provided';
    const birthDate = new Date(`${value}T00:00:00`);
    if (Number.isNaN(birthDate.getTime()) || birthDate > new Date()) return 'Not provided';
    const today = new Date();
    return today.getFullYear() - birthDate.getFullYear()
        - (today.getMonth() < birthDate.getMonth()
            || (today.getMonth() === birthDate.getMonth() && today.getDate() < birthDate.getDate())
            ? 1
            : 0);
}

document.getElementById('profile-date-of-birth')?.addEventListener('input', event => {
    const input = event.currentTarget;
    if (!(input instanceof HTMLInputElement)) return;
    const age = document.getElementById('profile-age');
    if (age) age.textContent = String(calculateAge(input.value));
});

document.getElementById('profile-photo-file')?.addEventListener('change', event => {
    const input = event.currentTarget;
    if (!(input instanceof HTMLInputElement)) return;
    const file = input.files?.[0];
    if (!file) return;
    const preview = document.getElementById('profile-photo-preview');
    const placeholder = document.getElementById('profile-photo-placeholder');
    if (!(preview instanceof HTMLImageElement)) return;
    if (preview.dataset.previewUrl) URL.revokeObjectURL(preview.dataset.previewUrl);
    preview.dataset.previewUrl = URL.createObjectURL(file);
    preview.src = preview.dataset.previewUrl;
    preview.hidden = false;
    if (placeholder) placeholder.hidden = true;
});

document.getElementById('member-photo-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!(form instanceof HTMLFormElement)) return;
    const button = form.querySelector('button[type="submit"]');
    if (!(button instanceof HTMLButtonElement)) return;
    button.disabled = true;
    setProfileMessage('profile-photo-message', '');

    try {
        const response = await fetch('/api/profile/photo', {
            method: 'PUT',
            credentials: 'include',
            body: new FormData(form)
        });
        const result = await readApiJson(response, 'Could not upload the profile photo. Please try again.');
        if (!response.ok) {
            throw new Error(result.detail || `Photo upload failed (HTTP ${response.status}).`);
        }
        const preview = document.getElementById('profile-photo-preview');
        const avatar = document.getElementById('profile-avatar-image');
        const initials = document.getElementById('profile-avatar-initials');
        if (preview instanceof HTMLImageElement) {
            preview.src = result.avatar_url;
            preview.hidden = false;
        }
        if (avatar instanceof HTMLImageElement) {
            avatar.src = result.avatar_url;
            avatar.hidden = false;
            if (initials) initials.hidden = true;
        }
        const placeholder = document.getElementById('profile-photo-placeholder');
        if (placeholder) placeholder.hidden = true;
        setProfileMessage('profile-photo-message', result.warning || result.message);
        form.reset();
    } catch (error) {
        setProfileMessage(
            'profile-photo-message',
            error instanceof Error ? error.message : 'The photo upload could not be completed.',
            true
        );
        console.error('Profile photo upload failed:', error);
    } finally {
        button.disabled = false;
    }
});

document.getElementById('member-password-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!(form instanceof HTMLFormElement)) return;
    const data = new FormData(form);
    const newPassword = String(data.get('new_password') || '');
    const confirmation = String(data.get('confirm_password') || '');
    if (newPassword !== confirmation) {
        setProfileMessage('profile-password-message', 'New password and confirmation do not match.', true);
        return;
    }
    if (new TextEncoder().encode(newPassword).length > 72) {
        setProfileMessage('profile-password-message', 'Password must be no more than 72 UTF-8 bytes.', true);
        return;
    }

    const saved = await submitProfileForm(
        form,
        '/api/profile/password',
        'profile-password-message',
        fields => ({
            current_password: String(fields.get('current_password') || ''),
            new_password: newPassword
        }),
        'Password changed successfully.'
    );
    if (saved) {
        form.reset();
        if (document.querySelector('.profile-settings-page')?.dataset.mustChangePassword === 'true') {
            window.location.href = '/api/home/view';
        }
    }
});
