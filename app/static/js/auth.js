document.getElementById('loginForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData();
    formData.append('username', document.getElementById('username').value);
    formData.append('password', document.getElementById('password').value);

    try {
        const response = await fetch('/api/token', {
            method: 'POST',
            body: formData
        });

        if (response.ok) {
            const data = await response.json();
            localStorage.setItem('token', data.access_token);
            window.location.href = '/dashboard';
        } else {
            document.getElementById('error-msg').classList.remove('hidden');
        }
    } catch (error) {
        console.error('Error:', error);
        document.getElementById('error-msg').classList.remove('hidden');
    }
});
