/**
 * API client communicating exclusively with Flask REST bridge.
 * React NEVER communicates directly with gRPC, SQLite, or MySQL.
 */

const API_BASE = '/api';

export async function fetchHealth() {
  const res = await fetch(`${API_BASE}/health`);
  return res.json();
}

export async function fetchNodeStatus() {
  const res = await fetch(`${API_BASE}/node`);
  return res.json();
}

export async function fetchNodes() {
  const res = await fetch(`${API_BASE}/nodes`);
  return res.json();
}

export async function fetchNode(nodeId) {
  const res = await fetch(`${API_BASE}/nodes/${nodeId}`);
  return res.json();
}

export async function submitVote(clientId, choice) {
  const res = await fetch(`${API_BASE}/votes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id: clientId, choice }),
  });
  const data = await res.json();
  return { status: res.status, ...data };
}

export async function fetchTally() {
  const res = await fetch(`${API_BASE}/votes/tally`);
  return res.json();
}

export async function fetchVote(voteId) {
  const res = await fetch(`${API_BASE}/votes/${encodeURIComponent(voteId)}`);
  return res.json();
}

export async function fetchElectionStatus() {
  const res = await fetch(`${API_BASE}/election/status`);
  return res.json();
}

export async function startElection(blocking = false) {
  const res = await fetch(`${API_BASE}/election/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ blocking }),
  });
  return res.json();
}

export async function fetchRecoveryStatus() {
  const res = await fetch(`${API_BASE}/recovery/status`);
  return res.json();
}

export async function startRecovery(params = {}) {
  const res = await fetch(`${API_BASE}/recovery/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  return res.json();
}

export async function fetchEvents(params = {}) {
  const query = new URLSearchParams(params).toString();
  const res = await fetch(`${API_BASE}/events${query ? `?${query}` : ''}`);
  return res.json();
}
