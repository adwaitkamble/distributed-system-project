import React, { useEffect, useState } from 'react';
import { 
  Server, 
  Crown, 
  Vote, 
  CheckCircle2, 
  Activity, 
  ShieldCheck, 
  ArrowRight, 
  Trophy, 
  ExternalLink,
  Layers,
  Zap,
  AlertCircle,
  RefreshCw
} from 'lucide-react';
import { fetchTally, fetchNodes } from '../api';

export default function Dashboard({ nodeInfo, onNavigate }) {
  const [tallyData, setTallyData] = useState({ tally: {}, total_votes: 0 });
  const [clusterNodes, setClusterNodes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadData = async () => {
    try {
      setError(null);
      const [tRes, nRes] = await Promise.all([fetchTally(), fetchNodes()]);
      if (tRes?.success) setTallyData(tRes);
      if (nRes?.success) setClusterNodes(nRes.nodes || []);
    } catch (err) {
      console.error('Failed to load dashboard data:', err);
      setError('Unable to retrieve latest telemetry from local Flask bridge.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 2500);
    return () => clearInterval(interval);
  }, []);

  const totalCommitted = tallyData.total_votes || 0;
  const tally = tallyData.tally || {};
  const candidates = nodeInfo?.candidates || ['Alice', 'Bob', 'Charlie'];

  // Calculate highest voted candidate for authoritative leader highlight
  let leadingCandidate = null;
  let maxVotes = -1;
  candidates.forEach((c) => {
    const v = tally[c] || 0;
    if (v > maxVotes && v > 0) {
      maxVotes = v;
      leadingCandidate = c;
    }
  });

  const isCoord = Boolean(nodeInfo?.is_coordinator);
  const activeNodes = clusterNodes.filter((n) => n.is_active);
  const activeNodesCount = activeNodes.length;
  const totalNodesCount = clusterNodes.length || 1;
  const coordId = nodeInfo?.coordinator_id ?? 'Unknown';

  return (
    <div className="dashboard-page route-fade-in">
      {/* Cluster Node Role Banner */}
      <div 
        className="card"
        style={{
          borderLeft: isCoord ? '4px solid var(--color-success)' : '4px solid var(--color-info)',
          marginBottom: '1.75rem',
          padding: '1.25rem 1.5rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '1.25rem',
          background: isCoord ? 'var(--color-success-bg)' : 'var(--color-surface)'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div 
            style={{
              width: '44px',
              height: '44px',
              borderRadius: 'var(--radius-md)',
              background: isCoord ? 'var(--color-success)' : 'var(--color-info)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#FFFFFF',
              flexShrink: 0
            }}
          >
            {isCoord ? <Crown size={24} aria-hidden="true" /> : <Server size={24} aria-hidden="true" />}
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', flexWrap: 'wrap' }}>
              <h2 style={{ fontSize: '1.15rem', fontWeight: 700, margin: 0, color: 'var(--color-navy-primary)' }}>
                {isCoord ? `Node ${nodeInfo?.node_id} is Active Cluster Coordinator` : `Node ${nodeInfo?.node_id} is Follower Replica`}
              </h2>
              <span className={`badge ${isCoord ? 'badge-coordinator' : 'badge-follower'}`}>
                {isCoord ? 'LEADER' : 'FOLLOWER'}
              </span>
            </div>
            <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.875rem', marginTop: '0.2rem' }}>
              {isCoord 
                ? 'Accepting vote writes and orchestrating two-phase consensus replication to cluster followers.' 
                : `Connected to Leader (Node ${coordId}). Follower replicas maintain read-only synchronized copies of the ballot log.`}
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          {isCoord ? (
            <button 
              type="button"
              className="btn btn-primary" 
              onClick={() => onNavigate('voting')}
            >
              <Vote size={15} aria-hidden="true" />
              <span>Submit Ballot</span>
              <ArrowRight size={14} aria-hidden="true" />
            </button>
          ) : (
            <a 
              href={`http://localhost:${5000 + (nodeInfo?.coordinator_id || 1)}`}
              className="btn btn-navy"
            >
              <span>Connect to Coordinator (Node {coordId})</span>
              <ExternalLink size={14} aria-hidden="true" />
            </a>
          )}
        </div>
      </div>

      {error && (
        <div className="alert alert-warning" role="alert">
          <AlertCircle size={18} aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}

      {/* Primary Cluster Metrics (4 columns) */}
      <div className="grid-4">
        {/* Connected Node */}
        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Connected Node</span>
            <Server size={18} className="stat-icon" aria-hidden="true" />
          </div>
          <span className="stat-value">
            Node {nodeInfo?.node_id ?? '?'}
          </span>
          <span className="stat-meta">
            <span 
              className={`status-dot ${isCoord ? 'status-dot-active' : 'status-dot-info'}`} 
              aria-hidden="true" 
            />
            {isCoord ? 'Cluster Coordinator' : `Coordinator is Node ${coordId}`}
          </span>
        </div>

        {/* Active Coordinator */}
        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Coordinator Lease</span>
            <Crown size={18} className="stat-icon" aria-hidden="true" />
          </div>
          <span className="stat-value">
            Node {nodeInfo?.coordinator_id ?? 'None'}
          </span>
          <span className="stat-meta">
            <Zap size={13} style={{ color: 'var(--color-warning)' }} aria-hidden="true" />
            Term #{nodeInfo?.election_term ?? 0} • {nodeInfo?.election_algorithm?.toUpperCase() || 'BULLY'}
          </span>
        </div>

        {/* Committed Ballots */}
        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Committed Ballots</span>
            <CheckCircle2 size={18} className="stat-icon" aria-hidden="true" />
          </div>
          <span className="stat-value">
            {loading ? '...' : totalCommitted}
          </span>
          <span className="stat-meta">
            <ShieldCheck size={13} style={{ color: 'var(--color-teal-accent)' }} aria-hidden="true" />
            Authoritative DB verified
          </span>
        </div>

        {/* Cluster Peer Topology */}
        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Active Mesh Quorum</span>
            <Activity size={18} className="stat-icon" aria-hidden="true" />
          </div>
          <span className="stat-value">
            {loading ? '...' : `${activeNodesCount}/${totalNodesCount} Healthy`}
          </span>
          <span className="stat-meta">
            <Layers size={13} style={{ color: 'var(--color-text-secondary)' }} aria-hidden="true" />
            Replication Policy: {nodeInfo?.replication_policy?.toUpperCase() || 'ALL'}
          </span>
        </div>
      </div>

      {/* Main Grid: Authoritative Results Tally + Node Mesh */}
      <div className="grid-2">
        {/* Authoritative Live Results Tally */}
        <section className="card" aria-labelledby="tally-section-title">
          <div className="card-title">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Trophy size={18} style={{ color: 'var(--color-warning)' }} aria-hidden="true" />
              <h3 id="tally-section-title" style={{ fontSize: '1.0625rem', fontWeight: 700, margin: 0 }}>
                Committed Ballot Results
              </h3>
            </div>
            <span className="badge badge-active">
              {totalCommitted} {totalCommitted === 1 ? 'Vote Committed' : 'Votes Committed'}
            </span>
          </div>

          <p className="card-subtitle">
            Authoritative results verified across distributed database replicas. Only 2-phase committed ballots contribute to the tally.
          </p>

          {/* Results Table & Progress Bars */}
          <div style={{ marginTop: '1rem' }}>
            {candidates.map((cand) => {
              const count = tally[cand] || 0;
              const pct = totalCommitted > 0 ? Math.round((count / totalCommitted) * 100) : 0;
              const isLeader = cand === leadingCandidate && count > 0;

              return (
                <div key={cand} className="tally-item">
                  <div className="tally-meta">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                      <div className="candidate-avatar-badge" aria-hidden="true">
                        {cand.charAt(0)}
                      </div>
                      <div>
                        <span style={{ fontWeight: 600, color: 'var(--color-navy-primary)' }}>{cand}</span>
                        {isLeader && (
                          <span 
                            className="badge badge-warning" 
                            style={{ marginLeft: '0.5rem', fontSize: '0.68rem', padding: '0.1rem 0.4rem' }}
                          >
                            ★ Leader
                          </span>
                        )}
                      </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--color-text-primary)' }}>
                        {count} {count === 1 ? 'vote' : 'votes'}
                      </span>
                      <span style={{ color: 'var(--color-text-muted)', fontSize: '0.84rem' }}>
                        ({pct}%)
                      </span>
                    </div>
                  </div>

                  <div 
                    className="progress-track" 
                    role="progressbar" 
                    aria-valuenow={pct} 
                    aria-valuemin={0} 
                    aria-valuemax={100}
                    aria-label={`${cand} votes: ${count} (${pct}%)`}
                  >
                    <div 
                      className="progress-fill" 
                      style={{ width: `${pct}%` }} 
                    />
                  </div>
                </div>
              );
            })}
          </div>

          {totalCommitted === 0 && !loading && (
            <div 
              style={{ 
                padding: '1.25rem', 
                textAlign: 'center', 
                backgroundColor: 'var(--color-surface-subtle)', 
                borderRadius: 'var(--radius-md)', 
                border: '1px dashed var(--color-border-medium)',
                marginTop: '1rem',
                color: 'var(--color-text-muted)',
                fontSize: '0.875rem'
              }}
            >
              No ballots committed yet for this election. Cast a ballot to begin tallying.
            </div>
          )}

          <div style={{ marginTop: '1.5rem', display: 'flex', gap: '0.75rem', borderTop: '1px solid var(--color-border-subtle)', paddingTop: '1.25rem', flexWrap: 'wrap' }}>
            <button 
              type="button"
              className="btn btn-primary" 
              onClick={() => onNavigate('voting')}
            >
              <Vote size={15} aria-hidden="true" />
              <span>Cast Ballot</span>
            </button>
            <button 
              type="button"
              className="btn btn-secondary" 
              onClick={loadData}
            >
              <RefreshCw size={14} aria-hidden="true" />
              <span>Refresh Tally</span>
            </button>
          </div>
        </section>

        {/* Cluster Nodes Overview */}
        <section className="card" aria-labelledby="mesh-section-title">
          <div className="card-title">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Server size={18} style={{ color: 'var(--color-navy-primary)' }} aria-hidden="true" />
              <h3 id="mesh-section-title" style={{ fontSize: '1.0625rem', fontWeight: 700, margin: 0 }}>
                Cluster Nodes Overview
              </h3>
            </div>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ padding: '0.3rem 0.65rem', fontSize: '0.75rem' }}
              onClick={() => onNavigate('nodes')}
            >
              <span>View Full Topology</span>
              <ArrowRight size={12} aria-hidden="true" />
            </button>
          </div>

          <p className="card-subtitle">
            Synchronized cluster nodes connected via gRPC consensus channels and local MySQL databases.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {clusterNodes.map((n) => {
              const isNodeLeader = n.is_coordinator;
              const port = 5000 + n.node_id;

              return (
                <div
                  key={n.node_id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '0.75rem 1rem',
                    borderRadius: 'var(--radius-md)',
                    background: n.is_self ? 'var(--color-teal-light)' : 'var(--color-surface-subtle)',
                    border: n.is_self ? '1px solid var(--color-teal-border)' : '1px solid var(--color-border-subtle)',
                    transition: 'background var(--transition-fast)'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <div 
                      style={{
                        width: '32px',
                        height: '32px',
                        borderRadius: 'var(--radius-sm)',
                        background: isNodeLeader ? 'var(--color-success-bg)' : '#E2E8F0',
                        color: isNodeLeader ? 'var(--color-success-text)' : 'var(--color-navy-primary)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        flexShrink: 0
                      }}
                      aria-hidden="true"
                    >
                      {isNodeLeader ? <Crown size={16} /> : <Server size={16} />}
                    </div>

                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                        <strong style={{ fontSize: '0.9rem', color: 'var(--color-navy-primary)' }}>
                          Node {n.node_id}
                        </strong>
                        {n.is_self && (
                          <span className="badge badge-active" style={{ fontSize: '0.625rem', padding: '0.1rem 0.4rem' }}>
                            Connected Host
                          </span>
                        )}
                      </div>
                      <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                        Port {port} • {n.address || 'gRPC:50051'}
                      </span>
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span className={`badge ${isNodeLeader ? 'badge-coordinator' : 'badge-follower'}`}>
                      {isNodeLeader ? 'LEADER' : 'FOLLOWER'}
                    </span>
                    <span className={`badge ${n.is_active ? 'badge-active' : 'badge-inactive'}`}>
                      {n.is_active ? 'Healthy' : 'Down'}
                    </span>
                    {!n.is_self && (
                      <a
                        href={`http://localhost:${port}`}
                        target="_blank"
                        rel="noreferrer"
                        className="btn btn-secondary"
                        style={{ padding: '0.25rem 0.45rem', fontSize: '0.75rem' }}
                        title={`Open Node ${n.node_id} web console in new tab`}
                        aria-label={`Open Node ${n.node_id} in new window`}
                      >
                        <ExternalLink size={13} aria-hidden="true" />
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          <div style={{ marginTop: '1.25rem', paddingTop: '1rem', borderTop: '1px solid var(--color-border-subtle)', fontSize: '0.8rem', color: 'var(--color-text-muted)', display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
            <span>Protocol: <strong style={{ color: 'var(--color-text-secondary)' }}>{nodeInfo?.election_algorithm?.toUpperCase() || 'BULLY'} Consensus</strong></span>
            <span>Database: <strong style={{ color: 'var(--color-text-secondary)' }}>MySQL WAL Replica</strong></span>
          </div>
        </section>
      </div>
    </div>
  );
}
