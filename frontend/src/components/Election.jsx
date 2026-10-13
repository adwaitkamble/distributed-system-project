import React, { useEffect, useState } from 'react';
import { fetchElectionStatus, startElection, fetchEvents } from '../api';
import { 
  Zap, 
  Crown, 
  Radio, 
  Clock, 
  BarChart3, 
  CheckCircle2, 
  AlertTriangle, 
  Sparkles, 
  RefreshCw,
  GitBranch,
  ShieldCheck,
  ArrowRight,
  TrendingUp,
  Cpu
} from 'lucide-react';

export default function Election({ nodeInfo, onElectionTriggered }) {
  const [status, setStatus] = useState(null);
  const [events, setEvents] = useState([]);
  const [triggering, setTriggering] = useState(false);
  const [blocking, setBlocking] = useState(false);
  const [triggerResult, setTriggerResult] = useState(null);

  const loadElectionData = async () => {
    try {
      const [sRes, eRes] = await Promise.all([
        fetchElectionStatus(),
        fetchEvents({ source: 'election', limit: 10 }),
      ]);
      if (sRes.success) setStatus(sRes);
      if (eRes.success) setEvents(eRes.events || []);
    } catch (err) {
      console.error('Failed to load election data:', err);
    }
  };

  useEffect(() => {
    loadElectionData();
    const interval = setInterval(loadElectionData, 3000);
    return () => clearInterval(interval);
  }, []);

  const handleStartElection = async () => {
    setTriggering(true);
    setTriggerResult(null);

    try {
      const res = await startElection(blocking);
      setTriggerResult(res);
      await loadElectionData();
      if (onElectionTriggered) onElectionTriggered();
    } catch (err) {
      setTriggerResult({ success: false, message: `Failed to trigger election: ${err.message}` });
    } finally {
      setTriggering(false);
    }
  };

  const metrics = status?.last_election_metrics || {};
  const msgCounts = status?.message_counts || {};
  const isBully = (status?.algorithm || 'bully').toLowerCase() === 'bully';
  const totalMsgs = metrics.total_logical_sent ?? msgCounts.total_logical_sent ?? 0;
  const electionSent = metrics.election_sent ?? msgCounts.election_sent ?? 0;
  const okSent = metrics.ok_sent ?? msgCounts.ok_sent ?? 0;
  const coordSent = metrics.coordinator_sent ?? msgCounts.coordinator_sent ?? 0;

  return (
    <div className="election-page" style={{ animation: 'fadeIn 0.3s ease-out' }}>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 className="page-title">Leader Election & Consensus</h2>
          <p className="page-description">
            Dynamic failure recovery through deterministic leader election protocols ({status?.algorithm?.toUpperCase() || 'BULLY'}).
          </p>
        </div>
        <button 
          className="btn btn-secondary" 
          onClick={loadElectionData}
          style={{ padding: '0.45rem 0.9rem', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}
        >
          <RefreshCw size={14} />
          Refresh Status
        </button>
      </div>

      {/* Top Overview Cards */}
      <div className="grid-4" style={{ marginBottom: '1.75rem' }}>
        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Consensus Protocol</span>
            <GitBranch size={18} className="stat-icon" />
          </div>
          <div className="stat-value" style={{ color: 'var(--accent-indigo-light)' }}>
            {status?.algorithm?.toUpperCase() || 'BULLY'}
          </div>
          <div className="stat-meta">
            <span>{isBully ? 'Highest active ID wins O(N²)' : 'Logical Token Ring O(N)'}</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Election Term</span>
            <Clock size={18} className="stat-icon" />
          </div>
          <div className="stat-value" style={{ color: 'var(--accent-cyan-light)' }}>
            #{status?.election_term ?? 0}
          </div>
          <div className="stat-meta">
            <span>Monotonic Lamport generation</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Active Leader</span>
            <Crown size={18} className="stat-icon" style={{ color: 'var(--accent-emerald)' }} />
          </div>
          <div className="stat-value" style={{ color: 'var(--accent-emerald-light)' }}>
            Node {status?.current_coordinator ?? '?'}
          </div>
          <div className="stat-meta">
            <span>{status?.is_coordinator ? 'This node is Leader' : 'Remote peer holds lease'}</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Convergence State</span>
            <Radio size={18} className="stat-icon" />
          </div>
          <div className="stat-value" style={{ fontSize: '1.4rem', color: status?.election_in_progress ? 'var(--accent-amber)' : 'var(--accent-emerald)' }}>
            {status?.election_in_progress ? 'ELECTION IN PROGRESS' : 'SETTLED & HEALTHY'}
          </div>
          <div className="stat-meta">
            <span>Initiator: Node {status?.initiator_id ?? 'None'}</span>
          </div>
        </div>
      </div>

      <div className="grid-2">
        {/* Election Trigger Action Card */}
        <div className="card">
          <div className="card-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <Zap size={20} color="var(--accent-amber)" />
              Trigger Leader Election
            </span>
            <span className={`badge ${status?.is_coordinator ? 'badge-coordinator' : 'badge-follower'}`}>
              Host: Node {nodeInfo?.node_id} ({nodeInfo?.role})
            </span>
          </div>

          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '1.25rem' }}>
            Broadcasts an election challenge message across all peers. Any responding node with a higher ID will suppress this caller; if no higher node replies, this node promotes itself to <code>COORDINATOR</code> and performs State Recovery.
          </p>

          <div style={{ marginBottom: '1.25rem', padding: '0.85rem', background: 'rgba(255,255,255,0.02)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', fontSize: '0.85rem', color: 'var(--text-primary)', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={blocking}
                onChange={(e) => setBlocking(e.target.checked)}
                style={{ accentColor: 'var(--accent-indigo)' }}
              />
              <span>Wait synchronously for election resolution (blocking RPC call)</span>
            </label>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.35rem', marginLeft: '1.6rem' }}>
              When enabled, the HTTP bridge waits until peers finish exchange before returning the new coordinator.
            </p>
          </div>

          <button
            className="btn btn-primary"
            onClick={handleStartElection}
            disabled={triggering || status?.election_in_progress}
            style={{ width: '100%', padding: '0.85rem' }}
          >
            {triggering ? (
              <>
                <Sparkles size={16} className="spin-icon" />
                Negotiating Consensus with Peers...
              </>
            ) : (
              <>
                <Zap size={16} />
                Initiate Election on Node {nodeInfo?.node_id} →
              </>
            )}
          </button>

          {triggerResult && (
            <div
              className={`alert ${triggerResult.success ? 'alert-success' : 'alert-error'}`}
              style={{ marginTop: '1.25rem' }}
            >
              {triggerResult.success ? (
                <CheckCircle2 size={20} style={{ flexShrink: 0, marginTop: '2px' }} />
              ) : (
                <AlertTriangle size={20} style={{ flexShrink: 0, marginTop: '2px' }} />
              )}
              <div style={{ flex: 1 }}>
                <strong>{triggerResult.success ? 'Election Resolved Successfully' : 'Election Trigger Failed'}</strong>
                <p style={{ marginTop: '0.25rem', fontSize: '0.85rem' }}>
                  {triggerResult.message || `Consensus finalized: Node ${triggerResult.coordinator_id} elected Coordinator for Term #${triggerResult.term ?? status?.election_term}.`}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Message Overhead & Metrics Breakdown */}
        <div className="card">
          <div className="card-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <BarChart3 size={20} color="var(--accent-indigo-light)" />
              Algorithmic Overhead & Message Complexity
            </span>
            <span className="badge badge-active">Per-Term Scope</span>
          </div>

          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '1.25rem' }}>
            Tracks all distributed messaging primitives exchanged to verify protocol efficiency.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', fontSize: '0.875rem' }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                <span style={{ color: 'var(--text-muted)' }}>Total Logical Messages:</span>
                <strong style={{ color: 'var(--accent-indigo-light)', fontSize: '1.1rem' }}>{totalMsgs}</strong>
              </div>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${Math.min(100, (totalMsgs / 20) * 100)}%`, background: 'var(--accent-indigo)' }} />
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                <span style={{ color: 'var(--text-muted)' }}>Election Broadcasts:</span>
                <span>{electionSent}</span>
              </div>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${totalMsgs ? (electionSent / totalMsgs) * 100 : 0}%`, background: 'var(--accent-cyan)' }} />
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                <span style={{ color: 'var(--text-muted)' }}>OK / Suppression Replies:</span>
                <span>{okSent}</span>
              </div>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${totalMsgs ? (okSent / totalMsgs) * 100 : 0}%`, background: 'var(--accent-amber)' }} />
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                <span style={{ color: 'var(--text-muted)' }}>Coordinator Victory Announcements:</span>
                <span>{coordSent}</span>
              </div>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${totalMsgs ? (coordSent / totalMsgs) * 100 : 0}%`, background: 'var(--accent-emerald)' }} />
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: '0.75rem', borderTop: '1px solid var(--border-subtle)', fontSize: '0.8rem' }}>
              <span style={{ color: 'var(--text-muted)' }}>Election Execution Duration:</span>
              <strong style={{ color: 'var(--text-primary)' }}>
                {metrics.duration_ms !== undefined ? `${metrics.duration_ms} ms` : 'Instantaneous / Fast'}
              </strong>
            </div>
          </div>
        </div>
      </div>

      {/* Recent Election Audit Log */}
      <div className="card" style={{ marginTop: '2rem' }}>
        <div className="card-title">
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Clock size={20} color="var(--accent-cyan-light)" />
            Election Events & State Transitions (Audit Trail)
          </span>
          <span className="badge badge-follower">Immutable Log</span>
        </div>

        <div className="table-responsive">
          <table className="data-table">
            <thead>
              <tr>
                <th>Event Type</th>
                <th>Term</th>
                <th>Initiator</th>
                <th>Origin Node</th>
                <th>Lamport TS</th>
                <th>Event Payload Details</th>
              </tr>
            </thead>
            <tbody>
              {events.length === 0 ? (
                <tr>
                  <td colSpan="6" style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2rem' }}>
                    No election events logged yet. Trigger an election above to view live events.
                  </td>
                </tr>
              ) : (
                events.map((ev) => (
                  <tr key={ev.id}>
                    <td>
                      <span className="badge badge-coordinator">
                        {ev.event_type}
                      </span>
                    </td>
                    <td>#{ev.election_term}</td>
                    <td>Node {ev.initiator_id}</td>
                    <td>Node {ev.node_id}</td>
                    <td><code style={{ color: 'var(--accent-emerald-light)' }}>#{ev.lamport_ts}</code></td>
                    <td>
                      <code style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                        {typeof ev.details === 'object' ? JSON.stringify(ev.details) : String(ev.details || '-')}
                      </code>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
