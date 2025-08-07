const express = require('express');
const { spawn } = require('child_process');
const app = express();

let signalingServer = null;
let streamerProcess = null;

// Start signaling server automatically when controller starts
function startSignalingServer() {
  if (signalingServer) return;
  
  console.log('🚦 Starting signaling server...');
  signalingServer = spawn('node', ['signaling/server.js'], { stdio: 'inherit' });
  
  signalingServer.on('exit', (code) => {
    console.log(`❌ Signaling server exited with code ${code}`);
    signalingServer = null;
  });
  
  signalingServer.on('error', (err) => {
    console.error('❌ Signaling server error:', err);
    signalingServer = null;
  });
}

function stopSignalingServer() {
  if (signalingServer) {
    console.log('🛑 Stopping signaling server...');
    signalingServer.kill('SIGINT');
    signalingServer = null;
  }
}

app.post('/start', (req, res) => {
  if (streamerProcess) return res.json({ ok: true, status: 'already-running' });
  
  console.log('📹 Starting Python streamer...');
  streamerProcess = spawn('python3', ['src/webrtc_streamer.py'], { stdio: 'inherit' });
  
  streamerProcess.on('exit', (code) => {
    console.log(`Python streamer exited with code ${code}`);
    streamerProcess = null;
  });
  
  streamerProcess.on('error', (err) => {
    console.error('❌ Streamer error:', err);
    streamerProcess = null;
  });
  
  res.json({ ok: true, status: 'started' });
});

app.post('/stop', (req, res) => {
  if (!streamerProcess) return res.json({ ok: true, status: 'not-running' });
  
  console.log('🛑 Stopping Python streamer...');
  streamerProcess.kill('SIGINT');
  streamerProcess = null;
  
  res.json({ ok: true, status: 'stopping' });
});

app.get('/status', (req, res) => {
  res.json({ 
    signaling: !!signalingServer,
    streamer: !!streamerProcess 
  });
});

// Graceful shutdown
process.on('SIGINT', () => {
  console.log('\n🛑 Shutting down controller...');
  if (streamerProcess) streamerProcess.kill('SIGINT');
  stopSignalingServer();
  process.exit(0);
});

process.on('SIGTERM', () => {
  console.log('\n🛑 Shutting down controller...');
  if (streamerProcess) streamerProcess.kill('SIGINT');
  stopSignalingServer();
  process.exit(0);
});

// Start signaling server when controller starts
startSignalingServer();

// Give signaling server time to start, then start the HTTP server
setTimeout(() => {
  app.listen(8090, () => {
    console.log('▶️ Controller on http://0.0.0.0:8090');
    console.log('🚦 Signaling server: ws://0.0.0.0:8080');
    console.log('📹 Use POST /start to begin streaming');
  });
}, 1000);