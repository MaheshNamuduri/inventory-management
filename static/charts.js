function drawCharts(stockData, topSold) {
    console.log("Stock Data:", stockData);
    console.log("Top Sold:", topSold);

    const stockCtx = document.getElementById('stockChart').getContext('2d');
    new Chart(stockCtx, {
        type: 'bar',  // Explicitly bar
        data: {
            labels: stockData.map(item => item[0] || 'Unknown'),
            datasets: [{
                label: 'Remaining Stock',
                data: stockData.map(item => item[1] || 0),
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                borderColor: 'rgba(75, 192, 192, 1)',
                borderWidth: 1
            }]
        },
        options: { scales: { y: { beginAtZero: true } } }
    });

    const topSoldCtx = document.getElementById('topSoldChart').getContext('2d');
    new Chart(topSoldCtx, {
        type: 'pie',  // Explicitly pie
        data: {
            labels: topSold.map(item => item[0] || 'Unknown'),
            datasets: [{
                label: 'Units Sold',
                data: topSold.map(item => item[1] || 0),
                backgroundColor: ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF']
            }]
        }
    });
}