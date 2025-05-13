// static/js/scripts.js
document.addEventListener('htmx:afterSwap', function() {
    const chatWindow = document.getElementById('chat-window');
    if (chatWindow) {
        chatWindow.scrollTop = chatWindow.scrollHeight;
    }
});

window.onload = function() {
    if (typeof htmx === 'undefined') {
        console.error('htmx failed to load. Check CDN or network.');
    } else {
        console.log('htmx is loaded');
    }
};