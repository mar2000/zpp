// Obsługa AJAXowego dodawania punktów
document.addEventListener('DOMContentLoaded', function() {
    const background = document.getElementById('route-background');
    const svg = document.querySelector('.route-svg');
    const pointForm = document.getElementById('point-form');
    
    if (pointForm) {
        pointForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const formData = new FormData(pointForm);
            const x = formData.get('x');
            const y = formData.get('y');
            
            try {
                const response = await fetch(pointForm.action, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': formData.get('csrfmiddlewaretoken'),
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: formData
                });
                
                const data = await response.json();
                
                if (data.success) {
                    // Dodaj nowy punkt do SVG
                    const pointsCount = document.querySelectorAll('.point-group').length;
                    const newPoint = document.createElementNS('http://www.w3.org/2000/svg', 'g');
                    newPoint.setAttribute('class', 'point-group');
                    newPoint.setAttribute('transform', `translate(${x},${y})`);
                    newPoint.innerHTML = `
                        <circle r="6" fill="red" class="route-point"/>
                        <text x="0" y="-10" text-anchor="middle" fill="black" font-size="12" font-weight="bold" class="point-label">
                            ${pointsCount + 1}
                        </text>
                    `;
                    svg.appendChild(newPoint);
                    
                    // Zaktualizuj ścieżkę
                    updatePath();
                    
                    // Wyczyść formularz
                    pointForm.reset();
                }
            } catch (error) {
                console.error('Error:', error);
            }
        });
    }
    
    function updatePath() {
        const points = Array.from(document.querySelectorAll('.point-group'));
        const path = document.querySelector('.route-path');
        let pathData = '';
        
        points.forEach((point, index) => {
            const transform = point.getAttribute('transform');
            const [x, y] = transform.match(/\d+/g);
            pathData += `${index === 0 ? 'M' : 'L'}${x},${y} `;
        });
        
        path.setAttribute('d', pathData);
    }
});
