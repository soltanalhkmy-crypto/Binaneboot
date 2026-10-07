let chartInstance = null;

async function fetchWithAuth(url, options = {}) {
    const token = localStorage.getItem('token');
    if (!token) {
        window.location.href = '/';
        return;
    }

    if (!options.headers) {
        options.headers = {};
    }
    options.headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(url, options);
    if (response.status === 401) {
        logout();
    }
    return response;
}

function logout() {
    localStorage.removeItem('token');
    window.location.href = '/';
}

async function loadSettings() {
    const res = await fetchWithAuth('/api/settings');
    const data = await res.json();

    document.getElementById('target_funding_rate').value = data.target_funding_rate;
    document.getElementById('trade_amount').value = data.trade_amount;
    document.getElementById('entry_time_minutes').value = data.entry_time_minutes;
    document.getElementById('exit_safe_seconds').value = data.exit_safe_seconds;

    updateBotStatusUI(data.bot_active);
}

function updateBotStatusUI(isActive) {
    const badge = document.getElementById('botStatusBadge');
    const btn = document.getElementById('toggleBotBtn');

    if (isActive) {
        badge.textContent = 'يعمل';
        badge.className = 'px-3 py-1 inline-flex text-sm leading-5 font-semibold rounded-full bg-green-100 text-green-800';
        btn.textContent = 'إيقاف البوت';
        btn.className = 'w-full bg-red-500 hover:bg-red-600 text-white font-bold py-2 px-4 rounded';
    } else {
        badge.textContent = 'متوقف';
        badge.className = 'px-3 py-1 inline-flex text-sm leading-5 font-semibold rounded-full bg-red-100 text-red-800';
        btn.textContent = 'تشغيل البوت';
        btn.className = 'w-full bg-green-500 hover:bg-green-600 text-white font-bold py-2 px-4 rounded';
    }
}

async function toggleBot() {
    const res = await fetchWithAuth('/api/toggle_bot', { method: 'POST' });
    const data = await res.json();
    updateBotStatusUI(data.bot_active);
}

document.getElementById('settingsForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    const payload = {
        target_funding_rate: parseFloat(document.getElementById('target_funding_rate').value),
        trade_amount: parseFloat(document.getElementById('trade_amount').value),
        entry_time_minutes: parseInt(document.getElementById('entry_time_minutes').value),
        exit_safe_seconds: parseInt(document.getElementById('exit_safe_seconds').value),
        bot_active: document.getElementById('botStatusBadge').textContent === 'يعمل' // keep current status
    };

    await fetchWithAuth('/api/settings', {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
    });

    alert('تم حفظ الإعدادات بنجاح');
});

async function loadTrades() {
    const filter = document.getElementById('timeFilter').value;
    const res = await fetchWithAuth('/api/trades');
    let trades = await res.json();

    // Simple client-side filtering
    const now = new Date();
    if (filter === 'today') {
        trades = trades.filter(t => new Date(t.entry_time).toDateString() === now.toDateString());
    } else if (filter === 'week') {
        const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
        trades = trades.filter(t => new Date(t.entry_time) >= weekAgo);
    } else if (filter === 'month') {
        const monthAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
        trades = trades.filter(t => new Date(t.entry_time) >= monthAgo);
    }

    const tbody = document.getElementById('tradesTableBody');
    tbody.innerHTML = '';

    let cumulativeProfit = 0;
    const chartLabels = [];
    const chartData = [];

    // trades are descending, reverse for chart to be chronological
    const chartTrades = [...trades].reverse();

    chartTrades.forEach(trade => {
        if (trade.profit_usdt != null) {
            cumulativeProfit += trade.profit_usdt;
            chartLabels.push(new Date(trade.entry_time).toLocaleString('ar-EG', {month: 'short', day: 'numeric', hour: '2-digit', minute:'2-digit'}));
            chartData.push(cumulativeProfit);
        }
    });

    trades.forEach(trade => {
        const tr = document.createElement('tr');

        const entryTime = new Date(trade.entry_time).toLocaleString('ar-EG');
        const profitColor = trade.profit_usdt > 0 ? 'text-green-600' : (trade.profit_usdt < 0 ? 'text-red-600' : '');

        tr.innerHTML = `
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${trade.symbol}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${entryTime}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                ${trade.spot_entry_price ? trade.spot_entry_price.toFixed(4) : '-'} /
                ${trade.futures_entry_price ? trade.futures_entry_price.toFixed(4) : '-'}
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                ${trade.spot_exit_price ? trade.spot_exit_price.toFixed(4) : '-'} /
                ${trade.futures_exit_price ? trade.futures_exit_price.toFixed(4) : '-'}
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${trade.amount}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm font-bold ${profitColor}">
                ${trade.profit_usdt != null ? trade.profit_usdt.toFixed(4) : '-'}
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full
                    ${trade.status === 'closed' ? 'bg-green-100 text-green-800' :
                      (trade.status === 'open' ? 'bg-yellow-100 text-yellow-800' : 'bg-red-100 text-red-800')}">
                    ${trade.status === 'closed' ? 'مغلقة' : (trade.status === 'open' ? 'مفتوحة' : 'فشلت')}
                </span>
            </td>
        `;
        tbody.appendChild(tr);
    });

    updateChart(chartLabels, chartData);
}

function updateChart(labels, data) {
    const ctx = document.getElementById('profitChart').getContext('2d');

    if (chartInstance) {
        chartInstance.destroy();
    }

    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'إجمالي الأرباح التراكمية (USDT)',
                data: data,
                borderColor: 'rgb(79, 70, 229)',
                backgroundColor: 'rgba(79, 70, 229, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });
}

// Initial load
document.getElementById('credentialsForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    const payload = {
        new_username: document.getElementById('new_username').value,
        new_password: document.getElementById('new_password').value
    };

    const res = await fetchWithAuth('/api/credentials', {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
    });

    if (res.ok) {
        alert('تم تحديث بيانات الدخول بنجاح! الرجاء تسجيل الدخول مجدداً.');
        logout();
    } else {
        alert('حدث خطأ أثناء التحديث.');
    }
});

// Initial load
document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    loadTrades();

    // Refresh trades every minute
    setInterval(loadTrades, 60000);
});
