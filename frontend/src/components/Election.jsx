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
  RefreshCw,
  GitBranch
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
        fetchEvents({ source: 'election', limit: 15 }),
      ]);
      if (sRes?.success) setStatus(sRes);
      if (eRes?.success) setEvents(eRes.events || []);
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
    <div className="election-page route-fade-in">
      <div className="page-header">
        <div>
          <h2 className="page-title">Leader Election & Consensus</h2>
          <p className="page-description">
            Autonomous failover coordination via deterministic leader election ({status?.algorithm?.toUpperCase() || 'BULLY'}). Guarantees coordinator uniqueness across dynamic peer crashes.
          </p>
        </div>
        <button 
          type="button"
          className="btn btn-secondary" 
          onClick={loadElectionData}
          style={{ padding: '0.4rem 0.85rem', fontSize: '0.8125rem' }}
        >
          <RefreshCw size={14} aria-hidden="true" />
          <span>Refresh Status</span>
        </button>
      </div>

      {/* Top Stat Overview */}
      <div className="grid-4" style={{ marginBottom: '1.75rem' }}>
        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Election Protocol</span>
            <GitBranch size={18} className="stat-icon" aria-hidden="true" />
          </div>
          <div className="stat-value">
            {status?.algorithm?.toUpperCase() || 'BULLY'}
          </div>
          <div className="stat-meta">
            <span>{isBully ? 'Highest active ID wins • O(N²)' : 'Logical Token Ring • O(N)'}</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Election Term</span>
            <Clock size={18} className="stat-icon" aria-hidden="true" />
          </div>
          <div className="stat-value">
            #{status?.election_term ?? 0}
          </div>
          <div className="stat-meta">
            <span>Monotonic generation counter</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Active Coordinator</span>
            <Crown size={18} className="stat-icon" style={{ color: 'var(--color-indigo-light)' }} aria-hidden="true" />
          </div>
          <div className="stat-value">
            Node {status?.current_coordinator ?? '?'}
          </div>
          <div className="stat-meta">
            <span>{status?.is_coordinator ? 'This node holds Leader lease' : 'Remote peer holds lease'}</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Convergence State</span>
            <Radio size={18} className="stat-icon" aria-hidden="true" />
          </div>
          <div className="stat-value" style={{ fontSize: '1.25rem' }}>
            {status?.election_in_progress ? 'IN PROGRESS' : 'STABLE'}
          </div>
          <div className="stat-meta">
            <span>Initiator: Node {status?.initiator_id ?? 'None'}</span>
          </div>
        </div>
      </div>

      <div className="grid-2">
        {/* Election Trigger Action Card */}
        <section className="card" aria-labelledby="trigger-election-title">
          <div className="card-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Zap size={18} color="var(--color-amber)" aria-hidden="true" />
              <h3 id="trigger-election-title" style={{ fontSize: '1.0625rem', fontWeight: 700, margin: 0, color: '#FFFFFF' }}>
                Trigger Leader Election
              </h3>
            </span>
            <span className={`badge ${status?.is_coordinator ? 'badge-coordinator' : 'badge-follower'}`}>
              Host: Node {nodeInfo?.node_id} ({nodeInfo?.role})
            </span>
          </div>

          <p className="card-subtitle">
            Broadcasts an election message to higher-ID peers. If no higher peer replies, this node promotes itself to <code>COORDINATOR</code> and performs log synchronization.
          </p>

          <div 
            style={{ 
              marginBottom: '1.25rem', 
              padding: '0.85rem', 
              backgroundColor: 'rgba(255, 255, 255, 0.03)', 
              borderRadius: 'var(--radius-sm)', 
              border: '1px solid var(--color-border-glass)' 
            }}
          >
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', fontSize: '0.84rem', color: 'var(--color-text-primary)', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={blocking}
                onChange={(e) => setBlocking(e.target.checked)}
                style={{ accentColor: 'var(--color-indigo)' }}
              />
              <span style={{ fontWeight: 600 }}>Synchronous Resolution (Blocking RPC)</span>
            </label>
            <p style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', marginTop: '0.25rem', marginLeft: '1.5rem' }}>
              When enabled, the REST request will wait until the cluster finalizes election before returning.
            </p>
          </div>

          <button
            type="button"
            className="btn btn-primary"
            onClick={handleStartElection}
            disabled={triggering || status?.election_in_progress}
            style={{ width: '100%', padding: '0.75rem' }}
          >
            {triggering ? (
              <>
                <RefreshCw size={16} className="spin-icon" aria-hidden="true" />
                <span>Negotiating Consensus with Peers...</span>
              </>
            ) : (
              <>
                <Zap size={16} aria-hidden="true" />
                <span>Initiate Election on Node {nodeInfo?.node_id}</span>
              </>
            )}
          </button>

          <div aria-live="polite">
            {triggerResult && (
              <div
                className={`alert ${triggerResult.success ? 'alert-success' : 'alert-error'}`}
                style={{ marginTop: '1.25rem' }}
                role="alert"
              >
                {triggerResult.success ? (
                  <CheckCircle2 size={18} style={{ flexShrink: 0, marginTop: '2px', color: 'var(--color-cyan)' }} aria-hidden="true" />
                ) : (
                  <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: '2px', color: 'var(--color-crimson)' }} aria-hidden="true" />
                )}
                <div style={{ flex: 1 }}>
                  <strong>{triggerResult.success ? 'Election Finalized' : 'Election Trigger Failed'}</strong>
                  <p style={{ marginTop: '0.2rem', fontSize: '0.84rem', color: 'var(--color-text-secondary)' }}>
                    {triggerResult.message || `Consensus finalized: Node ${triggerResult.coordinator_id} is elected Coordinator for Term #${triggerResult.term ?? status?.election_term}.`}
                  </p>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* Message Overhead & Metrics Card */}
        <section className="card" aria-labelledby="metrics-title">
          <div className="card-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <BarChart3 size={18} color="var(--color-indigo)" aria-hidden="true" />
              <h3 id="metrics-title" style={{ fontSize: '1.0625rem', fontWeight: 700, margin: 0, color: '#FFFFFF' }}>
                Algorithmic Message Complexity
              </h3>
            </span>
            <span className="badge badge-neutral">Term Telemetry</span>
          </div>

          <p className="card-subtitle">
            Logical message overhead across Bully/Ring phases during coordinator election.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', fontSize: '0.84rem' }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                <span style={{ color: 'var(--color-text-secondary)', fontWeight: 600 }}>Total Logical Messages:</span>
                <strong style={{ color: '#FFFFFF', fontSize: '1rem', fontFamily: 'var(--font-mono)' }}>{totalMsgs}</strong>
              </div>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${Math.min(100, (totalMsgs / 20) * 100)}%` }} />
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                <span style={{ color: 'var(--color-text-muted)' }}>Election Broadcasts:</span>
                <span style={{ fontFamily: 'var(--font-mono)' }}>{electionSent}</span>
              </div>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${totalMsgs ? (electionSent / totalMsgs) * 100 : 0}%`, background: 'var(--color-indigo)' }} />
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                <span style={{ color: 'var(--color-text-muted)' }}>OK / Suppression Replies:</span>
                <span style={{ fontFamily: 'var(--font-mono)' }}>{okSent}</span>
              </div>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${totalMsgs ? (okSent / totalMsgs) * 100 : 0}%`, background: 'var(--color-amber)' }} />
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                <span style={{ color: 'var(--color-text-muted)' }}>Coordinator Victory Messages:</span>
                <span style={{ fontFamily: 'var(--font-mono)' }}>{coordSent}</span>
              </div>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${totalMsgs ? (coordSent / totalMsgs) * 100 : 0}%`, background: 'var(--color-cyan)' }} />
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: '0.75rem', borderTop: '1px solid var(--color-border-glass)', fontSize: '0.8125rem' }}>
              <span style={{ color: 'var(--color-text-muted)' }}>Election Duration:</span>
              <strong style={{ color: '#FFFFFF', fontFamily: 'var(--font-mono)' }}>
                {metrics.duration_ms !== undefined ? `${metrics.duration_ms} ms` : 'Instantaneous / Fast'}
              </strong>
            </div>
          </div>
        </section>
      </div>

      {/* Recent Election Audit Log */}
      <section className="card" style={{ marginTop: '2rem' }} aria-labelledby="election-log-title">
        <div className="card-title">
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Clock size={18} color="var(--color-cyan)" aria-hidden="true" />
            <h3 id="election-log-title" style={{ fontSize: '1.0625rem', fontWeight: 700, margin: 0, color: '#FFFFFF' }}>
              Recent Election Audit Log
            </h3>
          </span>
          <span className="badge badge-neutral">Immutable Stream</span>
        </div>

        <div className="table-responsive">
          <table className="data-table" aria-label="Election Events History">
            <thead>
              <tr>
                <th scope="col">Event Type</th>
                <th scope="col">Term</th>
                <th scope="col">Initiator</th>
                <th scope="col">Origin Node</th>
                <th scope="col">Lamport TS</th>
                <th scope="col">Payload Details</th>
              </tr>
            </thead>
            <tbody>
              {events.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', color: 'var(--color-text-muted)', padding: '2rem' }}>
                    No election events logged yet. Trigger an election above to view live audit records.
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
                    <td style={{ fontFamily: 'var(--font-mono)' }}>#{ev.election_term}</td>
                    <td>Node {ev.initiator_id}</td>
                    <td>Node {ev.node_id}</td>
                    <td><code style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-cyan)' }}>#{ev.lamport_ts}</code></td>
                    <td>
                      <code style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', fontFamily: 'var(--font-mono)' }}>
                        {typeof ev.details === 'object' ? JSON.stringify(ev.details) : String(ev.details || '-')}
                      </code>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
