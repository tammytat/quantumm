document.addEventListener('DOMContentLoaded', function() {
    
    function initBuilder() {
        const rows = document.querySelectorAll('.dynamic-lessonblock_set');
        
        rows.forEach(row => {
            const typeSelect = row.querySelector('select[name$="-block_type"]');
            if (!typeSelect) return; 

            const fieldsToToggle = row.querySelectorAll('.field-env_key, .field-content, .field-image, .field-hint, .field-expected_output');
            
            const toggleFields = () => {
                const isSelected = typeSelect.value !== "";
                fieldsToToggle.forEach(f => {
                    f.style.display = isSelected ? '' : 'none';
                });
            };

            typeSelect.removeEventListener('change', toggleFields);
            typeSelect.addEventListener('change', toggleFields);

            toggleFields();
        });
    }

    initBuilder();

    document.addEventListener('click', function(e) {
        if (e.target && (e.target.closest('.add-row') || e.target.classList.contains('add-row'))) {
            setTimeout(initBuilder, 300);
        }
    });
});