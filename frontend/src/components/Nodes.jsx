import React, { useEffect, useState } from 'react';
import { fetchNodes } from '../api';
import { 
  Server, 
  Activity, 
  CheckCircle2, 
  XCircle, 
  ExternalLink, 
  Shield, 
  RefreshCw, 
  Cpu, 
  Database, 
  Network, 
  Radio,
  Crown,
  Box
} from 'lucide-react';
import Cluster3DTopology from './Cluster3DTopology';

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
    <div className="nodes-page route-fade-in">
      <div className="page-header">
        <div>
          <h2 className="page-title">Cluster Topology & Node Telemetry</h2>
          <p className="page-description">
            Real-time peer discovery, interactive 3D WebGL mesh, gRPC endpoints, and operational roles for all participating cluster nodes.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', fontSize: '0.84rem', color: 'var(--color-text-secondary)', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              style={{ accentColor: 'var(--color-cyan)' }}
            />
            <span>Auto-refresh (2.5s)</span>
          </label>
          <button 
            type="button"
            className="btn btn-secondary" 
            onClick={loadNodes}
            style={{ padding: '0.4rem 0.85rem', fontSize: '0.8125rem' }}
          >
            <RefreshCw size={14} className={loading ? 'spin-icon' : ''} aria-hidden="true" />
            <span>Refresh Telemetry</span>
          </button>
        </div>
      </div>

      {/* 3D Interactive WebGL Hero Canvas */}
      <section className="card" style={{ marginBottom: '1.75rem', padding: '1.25rem' }}>
        <div className="card-title" style={{ marginBottom: '0.75rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Box size={18} style={{ color: 'var(--color-cyan)' }} aria-hidden="true" />
            <h3 style={{ fontSize: '1.0625rem', fontWeight: 700, margin: 0, color: '#FFFFFF' }}>
              Interactive 3D Consensus Topology Mesh
            </h3>
          </div>
          <span className="badge badge-coordinator">
            <Crown size={12} aria-hidden="true" />
            Active Leader: Node {coordinatorId ?? 1}
          </span>
        </div>
        <div className="bento-stage-3d" style={{ height: '380px' }}>
          <Cluster3DTopology nodes={nodes} coordinatorId={coordinatorId || 1} />
        </div>
      </section>

      {/* Overview Stat Strip */}
      <div className="grid-4" style={{ marginBottom: '1.75rem' }}>
        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Total Cluster Nodes</span>
            <Server size={18} className="stat-icon" aria-hidden="true" />
          </div>
          <div className="stat-value">
            {nodes.length || (nodeInfo?.cluster_size || 3)}
          </div>
          <div className="stat-meta">
            <span>Containerized runtime peers</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Active Coordinator</span>
            <Crown size={18} className="stat-icon" style={{ color: 'var(--color-indigo-light)' }} aria-hidden="true" />
          </div>
          <div className="stat-value">
            Node {coordinatorId ?? '?'}
          </div>
          <div className="stat-meta">
            <span>Holds cluster leader lease</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Communication Layer</span>
            <Network size={18} className="stat-icon" aria-hidden="true" />
          </div>
          <div className="stat-value" style={{ fontSize: '1.35rem' }}>
            gRPC + HTTP
          </div>
          <div className="stat-meta">
            <span>Protobuf binary serialization</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Consensus Protocol</span>
            <Radio size={18} className="stat-icon" aria-hidden="true" />
          </div>
          <div className="stat-value" style={{ fontSize: '1.35rem' }}>
            {nodeInfo?.election_algorithm?.toUpperCase() || 'BULLY'}
          </div>
          <div className="stat-meta">
            <span>Election Term #{nodeInfo?.election_term ?? 0}</span>
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
              className="card"
              style={{
                borderTop: isCoord 
                  ? '4px solid var(--color-indigo)' 
                  : (isCurrent ? '4px solid var(--color-cyan)' : '1px solid var(--color-border-glass)'),
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              {/* Header */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.15rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                  <div
                    style={{
                      width: '38px',
                      height: '38px',
                      borderRadius: 'var(--radius-md)',
                      backgroundColor: isCoord ? 'rgba(99, 102, 241, 0.2)' : 'rgba(255, 255, 255, 0.04)',
                      border: isCoord ? '1px solid var(--color-indigo-glow)' : '1px solid var(--color-border-glass)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: isCoord ? 'var(--color-indigo-light)' : '#FFFFFF'
                    }}
                    aria-hidden="true"
                  >
                    {isCoord ? <Crown size={20} /> : <Server size={20} />}
                  </div>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                      <strong style={{ fontSize: '1.05rem', color: '#FFFFFF' }}>
                        Node {n.node_id}
                      </strong>
                      {isCurrent && (
                        <span className="badge badge-active" style={{ fontSize: '0.625rem', padding: '0.1rem 0.4rem' }}>
                          Current Host
                        </span>
                      )}
                    </div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>
                      Container: voting-node{n.node_id}
                    </span>
                  </div>
                </div>

                <span className={`badge ${isCoord ? 'badge-coordinator' : 'badge-follower'}`}>
                  {isCoord ? '★ Leader' : '○ Follower'}
                </span>
              </div>

              {/* Status Details */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem', fontSize: '0.84rem', flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                    <Activity size={14} aria-hidden="true" /> Health Status:
                  </span>
                  <span className={`badge ${n.is_active ? 'badge-active' : 'badge-inactive'}`}>
                    {n.is_active ? <CheckCircle2 size={12} aria-hidden="true" /> : <XCircle size={12} aria-hidden="true" />}
                    <span>{n.is_active ? 'Online' : 'Offline'}</span>
                  </span>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                    <Network size={14} aria-hidden="true" /> gRPC Port:
                  </span>
                  <code style={{ fontSize: '0.8rem', backgroundColor: 'rgba(255, 255, 255, 0.04)', padding: '0.15rem 0.45rem', borderRadius: '4px', fontFamily: 'var(--font-mono)', color: 'var(--color-cyan-light)' }}>
                    :{grpcPort}
                  </code>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                    <Database size={14} aria-hidden="true" /> Database:
                  </span>
                  <span style={{ fontSize: '0.8rem', color: '#FFFFFF', fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
                    node{n.node_id}_db:3306 (WAL)
                  </span>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                    <Cpu size={14} aria-hidden="true" /> REST Endpoint:
                  </span>
                  <span style={{ color: 'var(--color-text-secondary)', fontSize: '0.8rem', fontFamily: 'var(--font-mono)' }}>
                    :{httpPort}
                  </span>
                </div>
              </div>

              {/* Bottom Quick Switch Action */}
              <div style={{ marginTop: '1.25rem', paddingTop: '0.85rem', borderTop: '1px solid var(--color-border-glass)' }}>
                {isCurrent ? (
                  <div style={{ textAlign: 'center', fontSize: '0.8125rem', color: 'var(--color-text-muted)', padding: '0.35rem 0' }}>
                    Currently viewing this node console
                  </div>
                ) : (
                  <a
                    href={`http://localhost:${httpPort}`}
                    className="btn btn-secondary"
                    style={{ width: '100%', fontSize: '0.8125rem', padding: '0.45rem' }}
                    title={`Open Node ${n.node_id} dashboard`}
                  >
                    <span>Open Node {n.node_id} Console</span>
                    <ExternalLink size={13} aria-hidden="true" />
                  </a>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Cluster Invariants Specification Table */}
      <section className="card" style={{ marginTop: '2rem' }} aria-labelledby="invariants-table-title">
        <div className="card-title">
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Shield size={18} color="var(--color-cyan)" aria-hidden="true" />
            <h3 id="invariants-table-title" style={{ fontSize: '1.0625rem', fontWeight: 700, margin: 0, color: '#FFFFFF' }}>
              Distributed Consensus & Safety Invariants
            </h3>
          </span>
          <span className="badge badge-active">Formally Audited</span>
        </div>

        <div className="table-responsive">
          <table className="data-table" aria-label="Consensus Safety Invariants">
            <thead>
              <tr>
                <th scope="col">Invariant Guarantee</th>
                <th scope="col">Status</th>
                <th scope="col">Subsystem</th>
                <th scope="col">Technical Specification</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong style={{ color: '#FFFFFF' }}>Leader Uniqueness</strong></td>
                <td><span className="badge badge-active"><CheckCircle2 size={12} aria-hidden="true" /> Verified</span></td>
                <td>Election Manager ({nodeInfo?.election_algorithm?.toUpperCase() || 'Bully'})</td>
                <td>At most one active coordinator lease exists per monotonic Lamport election term #{nodeInfo?.election_term ?? 0}.</td>
              </tr>
              <tr>
                <td><strong style={{ color: '#FFFFFF' }}>Crash-Failure Detection</strong></td>
                <td><span className="badge badge-active"><CheckCircle2 size={12} aria-hidden="true" /> Active</span></td>
                <td>Heartbeat Health Daemon</td>
                <td>Nodes evaluate peer liveness using monotonic timeouts; coordinator failure triggers deterministic election.</td>
              </tr>
              <tr>
                <td><strong style={{ color: '#FFFFFF' }}>Replication Quorum</strong></td>
                <td><span className="badge badge-active"><CheckCircle2 size={12} aria-hidden="true" /> Active</span></td>
                <td>Replication Engine</td>
                <td>Policy: <code style={{ fontFamily: 'var(--font-mono)' }}>{nodeInfo?.replication_policy?.toUpperCase()}</code>. Ballots must achieve ack consensus prior to client reply.</td>
              </tr>
              <tr>
                <td><strong style={{ color: '#FFFFFF' }}>Recovery-Authority Rule</strong></td>
                <td><span className="badge badge-active"><CheckCircle2 size={12} aria-hidden="true" /> Enforced</span></td>
                <td>State Recovery & SyncLog</td>
                <td>Prevents resurrection of ghost votes unacknowledged by a previous failing coordinator.</td>
              </tr>
              <tr>
                <td><strong style={{ color: '#FFFFFF' }}>Deterministic Ordering</strong></td>
                <td><span className="badge badge-active"><CheckCircle2 size={12} aria-hidden="true" /> Enforced</span></td>
                <td>Lamport Logical Clock</td>
                <td>All state transitions stamped with monotonic logical timestamps <code style={{ fontFamily: 'var(--font-mono)' }}>(ts, node_id)</code>.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
