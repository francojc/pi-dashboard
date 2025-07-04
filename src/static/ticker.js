/**
 * News Ticker JavaScript
 * Handles play/pause functionality and performance optimizations
 */

document.addEventListener('DOMContentLoaded', function() {
    const ticker = document.getElementById('newsTicker');
    const playPauseBtn = document.getElementById('tickerPlayPause');
    
    if (!ticker || !playPauseBtn) return;
    
    let isPaused = false;
    
    // Play/Pause functionality
    function toggleTicker() {
        isPaused = !isPaused;
        
        if (isPaused) {
            ticker.classList.add('paused');
            playPauseBtn.textContent = '▶️';
            playPauseBtn.setAttribute('aria-label', 'Play ticker');
        } else {
            ticker.classList.remove('paused');
            playPauseBtn.textContent = '⏸️';
            playPauseBtn.setAttribute('aria-label', 'Pause ticker');
        }
    }
    
    // Event listeners
    playPauseBtn.addEventListener('click', toggleTicker);
    
    // Pause on hover for better readability
    ticker.addEventListener('mouseenter', function() {
        if (!isPaused) {
            ticker.classList.add('paused');
        }
    });
    
    ticker.addEventListener('mouseleave', function() {
        if (!isPaused) {
            ticker.classList.remove('paused');
        }
    });
    
    // Keyboard accessibility
    playPauseBtn.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            toggleTicker();
        }
    });
    
    // Performance optimization: reduce animations when tab is not visible
    document.addEventListener('visibilitychange', function() {
        if (document.hidden) {
            ticker.style.animationPlayState = 'paused';
        } else if (!isPaused) {
            ticker.style.animationPlayState = 'running';
        }
    });
    
    // Duplicate content for seamless looping if content is short
    function duplicateContentIfNeeded() {
        const tickerWidth = ticker.scrollWidth;
        const containerWidth = ticker.parentElement.clientWidth;
        
        // If content is shorter than container, duplicate it
        if (tickerWidth < containerWidth * 2) {
            const originalContent = ticker.innerHTML;
            ticker.innerHTML = originalContent + '<span class="ticker-separator">•</span>' + originalContent;
        }
    }
    
    // Initialize duplication check
    setTimeout(duplicateContentIfNeeded, 100);
    
    // Re-check on window resize
    window.addEventListener('resize', duplicateContentIfNeeded);
});