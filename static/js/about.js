document.querySelectorAll('.team-editor-form').forEach(form => {
    form.addEventListener('submit', async event => {
        event.preventDefault();
        const officeKey = form.dataset.officeKey;
        const teamPath = form.dataset.teamPath || 'executive-team';
        const button = form.querySelector('button[type="submit"]');
        const message = form.querySelector('.team-editor-message');
        const name = form.elements.namedItem('name').value.trim();
        const image = form.elements.namedItem('image').files[0];
        const formData = new FormData();
        formData.append('name', name);
        if (image) formData.append('image', image);

        button.disabled = true;
        message.textContent = 'Saving profile...';
        message.classList.remove('is-error');

        try {
            const response = await fetch(
                `/api/about/${teamPath}/${encodeURIComponent(officeKey)}`,
                {
                    method: 'PUT',
                    credentials: 'include',
                    body: formData
                }
            );
            const result = await readApiJson(response, 'Could not save the officer profile. Please try again.');
            if (!response.ok) {
                throw new Error(result.detail || `Could not save profile (${response.status}).`);
            }
            message.textContent = result.warning || result.message;
            window.location.reload();
        } catch (error) {
            message.textContent = error.message;
            message.classList.add('is-error');
            console.error('Unable to update executive profile:', error);
        } finally {
            button.disabled = false;
        }
    });
});
