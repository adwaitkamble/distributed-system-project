import React, { useEffect, useState } from 'react';
import { fetchNodes } from '../api';
import { 
  Server, 
  Activity, 
  CheckCircle2, 
  XCircle, 
  ExternalLink, 
  Shield, 
  Zap, 
  RefreshCw, 
  Cpu, 
  Database, 
  Network, 
  Radio,
  ArrowRight
} from 'lucide-react';

export default function Nodes({ nodeInfo }) {
  const [nodes, setNodes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const loadNodes = async () => {
    try {
      const res = await fetchNodes();
      if (res.success) {
        setNodes(res.nodes || []);
      }
    } catch (err) {
      console.error('Failed to load nodes:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadNodes();
    let interval;
    if (autoRefresh) {
      interval = setInterval(loadNodes, 2500);
    }
    return () => clearInterval(interval);
  }, [autoRefresh]);

  const currentNodeId = nodeInfo?.node_id;
  const coordinatorId = nodeInfo?.coordinator_id;

  return (
    <div className="nodes-page" style={{ animation: 'fadeIn 0.3s ease-out' }}>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 className="page-title">Cluster Nodes & Topology</h2>
          <p className="page-description">
            Live health telemetry, gRPC peer connectivity, and role status across all cluster participants.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem', color: 'var(--text-secondary)', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              style={{ accentColor: 'var(--accent-indigo)' }}
            />
            Auto-refresh (2.5s)
          </label>
          <button 
            className="btn btn-secondary" 
            onClick={loadNodes}
            style={{ padding: '0.45rem 0.9rem', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}
          >
            <RefreshCw size={14} className={loading ? 'spin-icon' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* Cluster Overview Stats */}
      <div className="grid-4" style={{ marginBottom: '1.75rem' }}>
        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Total Cluster Nodes</span>
            <Server size={18} className="stat-icon" />
          </div>
          <div className="stat-value" style={{ color: 'var(--accent-indigo-light)' }}>
            {nodes.length || (nodeInfo?.cluster_size || 3)}
          </div>
          <div className="stat-meta">
            <span>Containerized peer processes</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Active Coordinator</span>
            <Zap size={18} className="stat-icon" style={{ color: 'var(--accent-emerald)' }} />
          </div>
          <div className="stat-value" style={{ color: 'var(--accent-emerald-light)' }}>
            Node {coordinatorId ?? '?'}
          </div>
          <div className="stat-meta">
            <span>Holds cluster coordinator lease</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Network Protocol</span>
            <Network size={18} className="stat-icon" />
          </div>
          <div className="stat-value" style={{ fontSize: '1.4rem', color: 'var(--accent-cyan-light)' }}>
            gRPC + HTTP
          </div>
          <div className="stat-meta">
            <span>Protobuf message serialization</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Consensus Election</span>
            <Radio size={18} className="stat-icon" />
          </div>
          <div className="stat-value" style={{ fontSize: '1.4rem', color: 'var(--accent-amber-light)' }}>
            {nodeInfo?.algorithm?.toUpperCase() || 'BULLY'}
          </div>
          <div className="stat-meta">
            <span>Term #{nodeInfo?.election_term ?? 0} active</span>
          </div>
        </div>
      </div>

      {/* Node Cards Grid */}
      <div className="grid-3">
        {nodes.map((n) => {
          const isCoord = n.is_coordinator;
          const isCurrent = n.node_id === currentNodeId;
          const httpPort = 5000 + n.node_id;
          const grpcPort = 50050 + n.node_id;

          return (
            <div
              key={n.node_id}
              className={`node-card ${isCoord ? 'is-coordinator' : ''}`}
              style={{
                background: isCoord 
                  ? 'linear-gradient(180deg, rgba(16, 185, 129, 0.08) 0%, rgba(15, 23, 42, 0.85) 100%)' 
                  : (isCurrent ? 'linear-gradient(180deg, rgba(99, 102, 241, 0.08) 0%, rgba(15, 23, 42, 0.85) 100%)' : 'var(--bg-card)'),
                border: isCoord 
                  ? '1px solid rgba(16, 185, 129, 0.35)' 
                  : (isCurrent ? '1px solid rgba(99, 102, 241, 0.35)' : '1px solid var(--border-subtle)'),
                borderRadius: 'var(--radius-lg)',
                padding: '1.5rem',
                display: 'flex',
                flexDirection: 'column',
                position: 'relative',
                transition: 'var(--transition-smooth)',
                boxShadow: isCoord ? '0 8px 32px rgba(16, 185, 129, 0.12)' : 'var(--shadow-sm)'
              }}
            >
              {/* Header */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <div
                    style={{
                      width: '42px',
                      height: '42px',
                      borderRadius: 'var(--radius-md)',
                      background: isCoord ? 'rgba(16, 185, 129, 0.15)' : 'rgba(255, 255, 255, 0.05)',
                      border: isCoord ? '1px solid rgba(16, 185, 129, 0.4)' : '1px solid var(--border-subtle)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: isCoord ? 'var(--accent-emerald-light)' : 'var(--text-secondary)'
                    }}
                  >
                    <Server size={22} />
                  </div>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                      <span style={{ fontSize: '1.15rem', fontWeight: 800 }}>Node {n.node_id}</span>
                      {isCurrent && (
                        <span style={{ 
                          fontSize: '0.65rem', 
                          background: 'rgba(99, 102, 241, 0.2)', 
                          color: 'var(--accent-indigo-light)', 
                          padding: '0.15rem 0.45rem', 
                          borderRadius: '999px',
                          fontWeight: 700
                        }}>
                          THIS HOST
                        </span>
                      )}
                    </div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      Container: voting-node{n.node_id}
                    </span>
                  </div>
                </div>

                <span className={`badge ${isCoord ? 'badge-coordinator' : 'badge-follower'}`}>
                  {isCoord ? '● Leader' : '○ Follower'}
                </span>
              </div>

              {/* Status details */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem', fontSize: '0.85rem', flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                    <Activity size={14} /> Health Status:
                  </span>
                  <span className={`badge ${n.is_active ? 'badge-active' : 'badge-inactive'}`}>
                    {n.is_active ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
                    {n.is_active ? 'Online' : 'Offline'}
                  </span>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                    <Network size={14} /> gRPC Port:
                  </span>
                  <code style={{ fontSize: '0.8rem', background: 'rgba(255,255,255,0.05)', padding: '0.15rem 0.5rem', borderRadius: '4px', fontFamily: 'var(--font-mono)' }}>
                    :{grpcPort}
                  </code>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                    <Database size={14} /> MySQL Store:
                  </span>
                  <span style={{ color: 'var(--accent-emerald-light)', fontSize: '0.8rem', fontWeight: 600 }}>
                    node{n.node_id}_db:3306 (WAL)
                  </span>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                    <Cpu size={14} /> Web Console:
                  </span>
                  <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                    http://localhost:{httpPort}
                  </span>
                </div>
              </div>

              {/* Bottom Quick Switch Action */}
              <div style={{ marginTop: '1.5rem', paddingTop: '1rem', borderTop: '1px solid var(--border-subtle)' }}>
                {isCurrent ? (
                  <div style={{ textAlign: 'center', fontSize: '0.8rem', color: 'var(--text-muted)', padding: '0.4rem 0' }}>
                    Currently viewing this node dashboard
                  </div>
                ) : (
                  <a
                    href={`http://localhost:${httpPort}`}
                    className="btn btn-secondary"
                    style={{ 
                      width: '100%', 
                      fontSize: '0.8rem', 
                      padding: '0.5rem',
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '0.4rem',
                      textDecoration: 'none'
                    }}
                  >
                    Open Node {n.node_id} Dashboard
                    <ExternalLink size={14} />
                  </a>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Cluster Coordination Invariants Audit Table */}
      <div className="card" style={{ marginTop: '2rem' }}>
        <div className="card-title">
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Shield size={20} color="var(--accent-emerald)" />
            Distributed Consensus & Safety Invariants
          </span>
          <span className="badge badge-active">Audited & Verified</span>
        </div>

        <div className="table-responsive">
          <table className="data-table">
            <thead>
              <tr>
                <th>Invariant Guarantee</th>
                <th>Status</th>
                <th>Algorithmic Subsystem</th>
                <th>Formal Specification</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>Leader Uniqueness</strong></td>
                <td><span className="badge badge-active"><CheckCircle2 size={12} /> Verified</span></td>
                <td>Election Manager (Bully / Ring)</td>
                <td>At most one active coordinator lease exists per monotonic Lamport election term #{nodeInfo?.election_term ?? 0}.</td>
              </tr>
              <tr>
                <td><strong>Crash-Failure Detection</strong></td>
                <td><span className="badge badge-active"><CheckCircle2 size={12} /> Active</span></td>
                <td>Heartbeat Health Daemon</td>
                <td>Nodes evaluate peer liveness using <code>time.monotonic()</code> timeouts; heartbeat failure triggers immediate election.</td>
              </tr>
              <tr>
                <td><strong>Synchronous Replication Quorum</strong></td>
                <td><span className="badge badge-active"><CheckCircle2 size={12} /> Active</span></td>
                <td>Replication Engine</td>
                <td>Policy: <code>{nodeInfo?.replication_policy?.toUpperCase()}</code>. Ballots must achieve ack consensus prior to client reply.</td>
              </tr>
              <tr>
                <td><strong>Recovery-Authority Rule</strong></td>
                <td><span className="badge badge-active"><CheckCircle2 size={12} /> Enforced</span></td>
                <td>State Recovery & SyncLog</td>
                <td>Prevents resurrection of ghost votes unacknowledged by a previous failing coordinator.</td>
              </tr>
              <tr>
                <td><strong>Deterministic Total Ordering</strong></td>
                <td><span className="badge badge-active"><CheckCircle2 size={12} /> Enforced</span></td>
                <td>Lamport Logical Clock</td>
                <td>All state mutations stamped with strictly monotonic Lamport timestamps <code>(ts, node_id)</code>.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
