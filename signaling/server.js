const WebSocket = require('ws');
const wss = new WebSocket.Server({ host: '0.0.0.0', port: 8080 });

let sender = null;
const viewers = new Set();

console.log('✅ Signaling server at ws://0.0.0.0:8080');

function broadcastToViewers(msg) {
  for (const v of viewers) if (v.readyState === WebSocket.OPEN) v.send(msg);
}

wss.on('connection', (ws) => {
  let role = 'unknown';
  console.log('⚡ Client connected');

  ws.on('message', (raw) => {
    let data;
    try { data = JSON.parse(raw); } catch { return; }

    // Explicit role set by client (recommended)
    if (data.type === 'role') {
      role = data.role; // 'sender' or 'viewer'
      if (role === 'sender') {
        sender = ws;
        console.log('📤 Sender connected');
        broadcastToViewers(JSON.stringify({ type: 'sender-connected' }));
      } else if (role === 'viewer') {
        viewers.add(ws);
        console.log(`📺 Viewer connected (total: ${viewers.size})`);
        if (sender) ws.send(JSON.stringify({ type: 'sender-connected' }));
        else ws.send(JSON.stringify({ type: 'sender-disconnected' }));
      }
      return;
    }

    // Relay signaling between sender and viewers
    if (data.type === 'offer' && role === 'viewer' && sender?.readyState === WebSocket.OPEN) {
      sender.send(raw);
    } else if (data.type === 'answer' && role === 'sender') {
      for (const v of viewers) if (v.readyState === WebSocket.OPEN) v.send(raw);
    } else if (data.type === 'ice-candidate') {
      if (role === 'viewer' && sender?.readyState === WebSocket.OPEN) sender.send(raw);
      if (role === 'sender') for (const v of viewers) if (v.readyState === WebSocket.OPEN) v.send(raw);
    }
  });

  ws.on('close', () => {
    if (ws === sender) {
      console.log('❌ Sender disconnected');
      sender = null;
      broadcastToViewers(JSON.stringify({ type: 'sender-disconnected' }));
    }
    if (viewers.delete(ws)) {
      console.log(`👋 Viewer disconnected (total: ${viewers.size})`);
    }
  });
});