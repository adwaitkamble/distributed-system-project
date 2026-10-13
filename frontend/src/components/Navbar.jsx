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
  ExternalLink,
  Radio
} from 'lucide-react';

export default function Navbar({ activeTab, setActiveTab, nodeInfo, onRefresh }) {
  const [isRefreshing, setIsRefreshing] = useState(false);
  const isCoord = nodeInfo?.is_coordinator;
  const role = isCoord ? 'COORDINATOR' : 'FOLLOWER';
  const coordId = nodeInfo?.coordinator_id ?? 'None';
  const currentNodeId = nodeInfo?.node_id ?? 1;

  const handleRefreshClick = async () => {
    setIsRefreshing(true);
    await onRefresh();
    setTimeout(() => setIsRefreshing(false), 500);
  };

  // Determine active cluster nodes to offer 1-click browser navigation
  const clusterNodeIds = [1, 2, 3];
  if (nodeInfo?.active_peers) {
    nodeInfo.active_peers.forEach(p => {
      if (!clusterNodeIds.includes(p)) clusterNodeIds.push(p);
    });
  }
  clusterNodeIds.sort((a, b) => a - b);

  return (
    <>
      {/* Cluster Quick Switch Bar */}
      <div className="cluster-switch-bar">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
          <Radio size={14} style={{ color: 'var(--accent-emerald-light)' }} />
          <span>Distributed Cluster Nodes:</span>
          <div className="cluster-switch-list">
            {clusterNodeIds.map(nid => {
              const port = 5000 + nid;
              const isCurrent = nid === currentNodeId;
              const isLeader = nid === coordId;
              return (
                <a
                  key={nid}
                  href={`http://localhost:${port}`}
                  className={`cluster-switch-btn ${isCurrent ? 'is-current' : ''} ${isLeader ? 'is-coordinator' : ''}`}
                  title={isCurrent ? `You are currently browsing Node ${nid}` : `Open Node ${nid} (port ${port})`}
                >
                  Node {nid}
                  {isLeader && <span style={{ fontSize: '0.65rem', fontWeight: 800 }}>★ LEADER</span>}
                  {isCurrent && <span style={{ fontSize: '0.65rem' }}>(Current)</span>}
                </a>
              );
            })}
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', fontSize: '0.75rem' }}>
          <span>Replication Policy: <strong style={{ color: 'var(--accent-cyan-light)', textTransform: 'uppercase' }}>{nodeInfo?.replication_policy || 'ALL'}</strong></span>
          <span>•</span>
          <span>Consensus: <strong style={{ color: 'var(--accent-indigo-light)', textTransform: 'uppercase' }}>{nodeInfo?.election_algorithm || 'BULLY'}</strong></span>
        </div>
      </div>

      {/* Main Navbar */}
      <header className="navbar">
        <div className="brand" onClick={() => setActiveTab('dashboard')}>
          <div className="brand-icon-wrapper">
            <ShieldCheck className="brand-icon" size={24} />
          </div>
          <div>
            <h1 className="brand-title">Fault-Tolerant Voting</h1>
            <div className="brand-subtitle">Distributed Consensus Cluster</div>
          </div>
        </div>

        <nav className="nav-links">
          <button
            className={`nav-tab ${activeTab === 'dashboard' ? 'active' : ''}`}
            onClick={() => setActiveTab('dashboard')}
          >
            <LayoutDashboard size={16} />
            Dashboard
          </button>
          <button
            className={`nav-tab ${activeTab === 'voting' ? 'active' : ''}`}
            onClick={() => setActiveTab('voting')}
          >
            <Vote size={16} />
            Voting
          </button>
          <button
            className={`nav-tab ${activeTab === 'nodes' ? 'active' : ''}`}
            onClick={() => setActiveTab('nodes')}
          >
            <Server size={16} />
            Nodes
          </button>
          <button
            className={`nav-tab ${activeTab === 'election' ? 'active' : ''}`}
            onClick={() => setActiveTab('election')}
          >
            <Crown size={16} />
            Election
          </button>
          <button
            className={`nav-tab ${activeTab === 'recovery' ? 'active' : ''}`}
            onClick={() => setActiveTab('recovery')}
          >
            <RotateCcw size={16} />
            Recovery
          </button>
          <button
            className={`nav-tab ${activeTab === 'events' ? 'active' : ''}`}
            onClick={() => setActiveTab('events')}
          >
            <ScrollText size={16} />
            Events
          </button>
        </nav>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          {/* Active Node Badge */}
          <div
            className="cluster-badge"
            style={{
              background: isCoord ? 'rgba(16, 185, 129, 0.15)' : 'rgba(99, 102, 241, 0.15)',
              borderColor: isCoord ? 'rgba(16, 185, 129, 0.4)' : 'rgba(99, 102, 241, 0.4)',
              color: isCoord ? 'var(--accent-emerald-light)' : 'var(--accent-indigo-light)',
            }}
          >
            <span
              className="pulse-dot"
              style={{
                backgroundColor: isCoord ? 'var(--accent-emerald)' : 'var(--accent-indigo)',
              }}
            ></span>
            <span>Host: Node {currentNodeId}</span>
            <span className={`badge ${isCoord ? 'badge-coordinator' : 'badge-follower'}`}>
              {role}
            </span>
          </div>

          <button
            className="btn btn-secondary"
            onClick={handleRefreshClick}
            disabled={isRefreshing}
            title="Refresh cluster state"
            style={{ padding: '0.45rem 0.85rem', fontSize: '0.8rem' }}
          >
            <RefreshCw size={14} className={isRefreshing ? 'spin-icon' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </header>
    </>
  );
}
