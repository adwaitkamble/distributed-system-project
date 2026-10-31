import React, { useState } from 'react';
import { 
  ShieldCheck, 
  LayoutDashboard, 
  Vote, 
  Server, 
  Crown, 
  RotateCcw, 
  ScrollText, 
  RefreshCw,
  Radio
} from 'lucide-react';

export default function Navbar({ activeTab, setActiveTab, nodeInfo, onRefresh }) {
  const [isRefreshing, setIsRefreshing] = useState(false);
  const isCoord = Boolean(nodeInfo?.is_coordinator);
  const role = isCoord ? 'COORDINATOR' : 'FOLLOWER';
  const coordId = nodeInfo?.coordinator_id ?? 'None';
  const currentNodeId = nodeInfo?.node_id ?? 1;

  const handleRefreshClick = async () => {
    setIsRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setTimeout(() => setIsRefreshing(false), 400);
    }
  };

  // Determine active cluster nodes to offer 1-click browser navigation
  const clusterNodeIds = [1, 2, 3];
  if (nodeInfo?.active_peers && Array.isArray(nodeInfo.active_peers)) {
    nodeInfo.active_peers.forEach((p) => {
      if (!clusterNodeIds.includes(p)) clusterNodeIds.push(p);
    });
  }
  clusterNodeIds.sort((a, b) => a - b);

  return (
    <header role="banner">
      {/* Cluster Quick Switch Bar */}
      <div className="cluster-switch-bar">
        <div className="cluster-switch-group">
          <span className="cluster-switch-label">
            <Radio size={14} aria-hidden="true" style={{ color: 'var(--color-cyan)' }} />
            <span>Cluster Mesh:</span>
          </span>
          <div className="cluster-switch-list" role="navigation" aria-label="Direct Node Switches">
            {clusterNodeIds.map((nid) => {
              const port = 5000 + nid;
              const isCurrent = nid === currentNodeId;
              const isLeader = nid === coordId;
              return (
                <a
                  key={nid}
                  href={`http://localhost:${port}`}
                  className={`cluster-switch-btn ${isCurrent ? 'is-current' : ''} ${isLeader && !isCurrent ? 'is-coordinator' : ''}`}
                  title={isCurrent ? `Currently connected to Node ${nid}` : `Open Node ${nid} console on port ${port}`}
                  aria-current={isCurrent ? 'page' : undefined}
                >
                  <span>Node {nid}</span>
                  {isLeader && <span style={{ fontSize: '0.65rem', fontWeight: 700 }}>[Leader]</span>}
                  {isCurrent && <span style={{ fontSize: '0.65rem' }}>(Host)</span>}
                </a>
              );
            })}
          </div>
        </div>

        <div className="cluster-meta-strip">
          <span>Replication: <strong style={{ color: '#FFFFFF' }}>{nodeInfo?.replication_policy?.toUpperCase() || 'ALL'}</strong></span>
          <span aria-hidden="true">•</span>
          <span>Consensus: <strong style={{ color: '#FFFFFF' }}>{nodeInfo?.election_algorithm?.toUpperCase() || 'BULLY'}</strong></span>
          <span aria-hidden="true">•</span>
          <span>Term: <strong style={{ color: '#FFFFFF' }}>#{nodeInfo?.election_term ?? 0}</strong></span>
        </div>
      </div>

      {/* Main Navbar */}
      <nav className="navbar" aria-label="Main Navigation">
        <button 
          type="button"
          className="brand" 
          onClick={() => setActiveTab('dashboard')}
          aria-label="Distributed Voting Console - Return to Dashboard"
        >
          <div className="brand-icon-wrapper" aria-hidden="true">
            <ShieldCheck size={22} />
          </div>
          <div>
            <h1 className="brand-title">Distributed Voting System</h1>
            <div className="brand-subtitle">Fault-Tolerant Consensus Console</div>
          </div>
        </button>

        <div className="nav-links" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'dashboard'}
            className={`nav-tab ${activeTab === 'dashboard' ? 'active' : ''}`}
            onClick={() => setActiveTab('dashboard')}
          >
            <LayoutDashboard size={15} aria-hidden="true" />
            <span>Dashboard</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'voting'}
            className={`nav-tab ${activeTab === 'voting' ? 'active' : ''}`}
            onClick={() => setActiveTab('voting')}
          >
            <Vote size={15} aria-hidden="true" />
            <span>Voting</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'nodes'}
            className={`nav-tab ${activeTab === 'nodes' ? 'active' : ''}`}
            onClick={() => setActiveTab('nodes')}
          >
            <Server size={15} aria-hidden="true" />
            <span>Nodes</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'election'}
            className={`nav-tab ${activeTab === 'election' ? 'active' : ''}`}
            onClick={() => setActiveTab('election')}
          >
            <Crown size={15} aria-hidden="true" />
            <span>Election</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'recovery'}
            className={`nav-tab ${activeTab === 'recovery' ? 'active' : ''}`}
            onClick={() => setActiveTab('recovery')}
          >
            <RotateCcw size={15} aria-hidden="true" />
            <span>Recovery</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'events'}
            className={`nav-tab ${activeTab === 'events' ? 'active' : ''}`}
            onClick={() => setActiveTab('events')}
          >
            <ScrollText size={15} aria-hidden="true" />
            <span>Audit Log</span>
          </button>
        </div>

        <div className="navbar-actions">
          <div className="host-badge-chip">
            <span
              className={`status-dot ${isCoord ? 'status-dot-active' : 'status-dot-indigo'}`}
              aria-hidden="true"
            />
            <span>Node {currentNodeId}</span>
            <span className={`badge ${isCoord ? 'badge-coordinator' : 'badge-follower'}`}>
              {role}
            </span>
          </div>

          <button
            type="button"
            className="btn btn-secondary"
            onClick={handleRefreshClick}
            disabled={isRefreshing}
            aria-label="Refresh cluster state"
            title="Refresh cluster telemetry"
            style={{ padding: '0.4rem 0.75rem', fontSize: '0.8125rem' }}
          >
            <RefreshCw size={14} className={isRefreshing ? 'spin-icon' : ''} aria-hidden="true" />
            <span>Refresh</span>
          </button>
        </div>
      </nav>
    </header>
  );
}
