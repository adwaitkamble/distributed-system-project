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
  Radio,
  Zap
} from 'lucide-react';
import { fetchTally, fetchNodes } from '../api';

export default function Dashboard({ nodeInfo, onNavigate }) {
  const [tallyData, setTallyData] = useState({ tally: {}, total_votes: 0 });
  const [clusterNodes, setClusterNodes] = useState([]);
  const [loading, setLoading] = useState(true);

  const loadData = async () => {
    try {
      const [tRes, nRes] = await Promise.all([fetchTally(), fetchNodes()]);
      if (tRes.success) setTallyData(tRes);
      if (nRes.success) setClusterNodes(nRes.nodes || []);
    } catch (err) {
      console.error('Failed to load dashboard data:', err);
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

  // Calculate highest voted candidate for the winner highlight
  let leadingCandidate = null;
  let maxVotes = -1;
  candidates.forEach(c => {
    const v = tally[c] || 0;
    if (v > maxVotes && v > 0) {
      maxVotes = v;
      leadingCandidate = c;
    }
  });

  const isCoord = nodeInfo?.is_coordinator;
  const activeNodesCount = clusterNodes.filter(n => n.is_active).length;
  const totalNodesCount = clusterNodes.length || 1;

  // Candidate avatar colors
  const candidateColors = {
    Alice: { bg: 'linear-gradient(135deg, #6366f1, #8b5cf6)', bar: 'linear-gradient(90deg, #6366f1, #a855f7)' },
    Bob: { bg: 'linear-gradient(135deg, #06b6d4, #3b82f6)', bar: 'linear-gradient(90deg, #06b6d4, #3b82f6)' },
    Charlie: { bg: 'linear-gradient(135deg, #10b981, #059669)', bar: 'linear-gradient(90deg, #10b981, #34d399)' },
  };

  return (
    <div className="dashboard-page">
      {/* Hero Cluster Status Banner */}
      <div 
        style={{
          background: isCoord 
            ? 'linear-gradient(135deg, rgba(16, 185, 129, 0.12), rgba(6, 182, 212, 0.08))' 
            : 'linear-gradient(135deg, rgba(99, 102, 241, 0.12), rgba(59, 130, 246, 0.08))',
          border: isCoord ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(99, 102, 241, 0.3)',
          borderRadius: 'var(--radius-lg)',
          padding: '1.5rem 1.75rem',
          marginBottom: '2rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '1.25rem',
          boxShadow: 'var(--shadow-sm)'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div 
            style={{
              width: '48px',
              height: '48px',
              borderRadius: 'var(--radius-md)',
              background: isCoord ? 'rgba(16, 185, 129, 0.2)' : 'rgba(99, 102, 241, 0.2)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: isCoord ? 'var(--accent-emerald-light)' : 'var(--accent-indigo-light)',
            }}
          >
            {isCoord ? <Crown size={26} /> : <Server size={26} />}
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 800, margin: 0 }}>
                {isCoord ? `Node ${nodeInfo?.node_id} is Active Cluster Leader` : `Node ${nodeInfo?.node_id} is Follower Replica`}
              </h2>
              <span className={`badge ${isCoord ? 'badge-coordinator' : 'badge-follower'}`}>
                {isCoord ? 'COORDINATOR' : 'FOLLOWER'}
              </span>
            </div>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: '0.25rem' }}>
              {isCoord 
                ? 'Accepting vote writes and orchestrating gRPC consensus replication to active replicas.' 
                : `Synchronized with Leader (Node ${nodeInfo?.coordinator_id ?? '?'}). Follower nodes maintain read-only database replicas.`}
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          {isCoord ? (
            <button className="btn btn-primary" onClick={() => onNavigate('voting')}>
              <Vote size={16} />
              <span>Cast Ballot Now</span>
              <ArrowRight size={14} />
            </button>
          ) : (
            <a 
              href={`http://localhost:${5000 + (nodeInfo?.coordinator_id || 3)}`}
              className="btn btn-primary"
            >
              <span>Switch to Leader (Node {nodeInfo?.coordinator_id})</span>
              <ExternalLink size={14} />
            </a>
          )}
        </div>
      </div>

      {/* Top Stat Widgets */}
      <div className="grid-4">
        {/* Connected Node */}
        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Connected Node</span>
            <Server size={18} className="stat-icon" />
          </div>
          <span className="stat-value" style={{ color: isCoord ? 'var(--accent-emerald-light)' : 'var(--accent-indigo-light)' }}>
            Node {nodeInfo?.node_id ?? '?'}
          </span>
          <span className="stat-meta">
            <Radio size={12} style={{ color: isCoord ? 'var(--accent-emerald)' : 'var(--accent-indigo)' }} />
            {isCoord ? 'Cluster Leader' : `Leader is Node ${nodeInfo?.coordinator_id ?? '?'}`}
          </span>
        </div>

        {/* Cluster Coordinator */}
        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Cluster Leader</span>
            <Crown size={18} className="stat-icon" />
          </div>
          <span className="stat-value" style={{ color: 'var(--accent-emerald-light)' }}>
            Node {nodeInfo?.coordinator_id ?? 'None'}
          </span>
          <span className="stat-meta">
            <Zap size={12} style={{ color: 'var(--accent-amber)' }} />
            Term #{nodeInfo?.election_term ?? 0} ({nodeInfo?.election_algorithm?.toUpperCase()})
          </span>
        </div>

        {/* Committed Votes */}
        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Committed Ballots</span>
            <CheckCircle2 size={18} className="stat-icon" />
          </div>
          <span className="stat-value" style={{ color: 'var(--accent-cyan-light)' }}>
            {totalCommitted}
          </span>
          <span className="stat-meta">
            <ShieldCheck size={12} style={{ color: 'var(--accent-cyan)' }} />
            Authoritative DB verified
          </span>
        </div>

        {/* Cluster Consensus Status */}
        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Cluster Mesh</span>
            <Activity size={18} className="stat-icon" />
          </div>
          <span className="stat-value" style={{ color: 'var(--accent-emerald-light)' }}>
            {activeNodesCount}/{totalNodesCount} Active
          </span>
          <span className="stat-meta">
            <Layers size={12} style={{ color: 'var(--accent-indigo)' }} />
            Policy: {nodeInfo?.replication_policy?.toUpperCase()}
          </span>
        </div>
      </div>

      {/* Main Grid: Live Leaderboard + Topology */}
      <div className="grid-2">
        {/* Authoritative Ballot Leaderboard */}
        <div className="card">
          <div className="card-title">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Trophy size={18} style={{ color: 'var(--accent-amber)' }} />
              <span>Authoritative Live Tally</span>
            </div>
            <span className="badge badge-active">{totalCommitted} Total Confirmed</span>
          </div>

          <p className="card-subtitle">
            Real-time verified votes committed across dedicated MySQL databases.
          </p>

          <div style={{ marginTop: '1.25rem' }}>
            {candidates.map((cand) => {
              const count = tally[cand] || 0;
              const pct = totalCommitted > 0 ? Math.round((count / totalCommitted) * 100) : 0;
              const isLeader = cand === leadingCandidate && count > 0;
              const colorInfo = candidateColors[cand] || { bg: 'linear-gradient(135deg, #6366f1, #8b5cf6)', bar: 'linear-gradient(90deg, #6366f1, #a855f7)' };

              return (
                <div key={cand} className="leaderboard-item">
                  <div className="leaderboard-meta">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                      <div 
                        style={{
                          width: '28px',
                          height: '28px',
                          borderRadius: '6px',
                          background: colorInfo.bg,
                          color: '#fff',
                          fontWeight: 800,
                          fontSize: '0.8rem',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center'
                        }}
                      >
                        {cand.charAt(0)}
                      </div>
                      <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>{cand}</span>
                      {isLeader && (
                        <span className="badge" style={{ background: 'rgba(245, 158, 11, 0.15)', color: 'var(--accent-amber-light)', fontSize: '0.65rem', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
                          ★ Leader
                        </span>
                      )}
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                      <span style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--text-primary)' }}>{count}</span>
                      <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>({pct}%)</span>
                    </div>
                  </div>

                  <div className="progress-track">
                    <div 
                      className="progress-fill" 
                      style={{ 
                        width: `${pct}%`,
                        background: colorInfo.bar
                      }}
                    ></div>
                  </div>
                </div>
              );
            })}
          </div>

          <div style={{ marginTop: '1.75rem', display: 'flex', gap: '0.75rem', borderTop: '1px solid var(--border-subtle)', paddingTop: '1.25rem' }}>
            <button className="btn btn-primary" onClick={() => onNavigate('voting')}>
              <Vote size={15} />
              <span>Cast Ballot</span>
            </button>
            <button className="btn btn-secondary" onClick={loadData}>
              <span>Refresh Tally</span>
            </button>
          </div>
        </div>

        {/* Cluster Nodes Quick Overview */}
        <div className="card">
          <div className="card-title">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Server size={18} style={{ color: 'var(--accent-indigo)' }} />
              <span>Cluster Node Mesh</span>
            </div>
            <button
              className="btn btn-secondary"
              style={{ padding: '0.35rem 0.75rem', fontSize: '0.75rem' }}
              onClick={() => onNavigate('nodes')}
            >
              <span>View Full Mesh</span>
              <ArrowRight size={12} />
            </button>
          </div>

          <p className="card-subtitle">
            Physical MySQL and gRPC peer consensus heartbeats.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
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
                    padding: '0.85rem 1.15rem',
                    borderRadius: 'var(--radius-md)',
                    background: n.is_self 
                      ? 'rgba(99, 102, 241, 0.08)' 
                      : (isNodeLeader ? 'rgba(16, 185, 129, 0.06)' : 'rgba(255, 255, 255, 0.02)'),
                    border: n.is_self 
                      ? '1px solid rgba(99, 102, 241, 0.35)' 
                      : (isNodeLeader ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid var(--border-subtle)'),
                    transition: 'var(--transition)'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
                    <div 
                      style={{
                        width: '32px',
                        height: '32px',
                        borderRadius: 'var(--radius-sm)',
                        background: isNodeLeader ? 'rgba(16, 185, 129, 0.2)' : 'rgba(255, 255, 255, 0.05)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: isNodeLeader ? 'var(--accent-emerald-light)' : 'var(--text-secondary)'
                      }}
                    >
                      {isNodeLeader ? <Crown size={16} /> : <Server size={16} />}
                    </div>

                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>Node {n.node_id}</span>
                        {n.is_self && (
                          <span className="badge badge-active" style={{ fontSize: '0.62rem' }}>Current Host</span>
                        )}
                      </div>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        Port {port} • {n.address || 'gRPC:50051'}
                      </span>
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
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
                        style={{ padding: '0.3rem 0.5rem', fontSize: '0.75rem' }}
                        title={`Open Node ${n.node_id} web UI`}
                      >
                        <ExternalLink size={12} />
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          <div style={{ marginTop: '1.25rem', paddingTop: '1rem', borderTop: '1px solid var(--border-subtle)', fontSize: '0.8rem', color: 'var(--text-muted)', display: 'flex', justifyContent: 'space-between' }}>
            <span>Election Algorithm: <strong style={{ color: 'var(--text-secondary)', textTransform: 'uppercase' }}>{nodeInfo?.election_algorithm || 'Bully'}</strong></span>
            <span>MySQL Host: <strong style={{ color: 'var(--text-secondary)' }}>{nodeInfo?.db_host || 'isolated container'}</strong></span>
          </div>
        </div>
      </div>
    </div>
  );
}
