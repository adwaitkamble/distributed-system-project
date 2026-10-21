import React, { useState, useEffect } from 'react';
import Navbar from './components/Navbar';
import Dashboard from './components/Dashboard';
import Voting from './components/Voting';
import Nodes from './components/Nodes';
import Election from './components/Election';
import Recovery from './components/Recovery';
import Events from './components/Events';
import { fetchNodeStatus } from './api';
import { AlertCircle, ShieldCheck } from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [nodeInfo, setNodeInfo] = useState(null);
  const [apiError, setApiError] = useState(null);

  const loadStatus = async () => {
    try {
      const data = await fetchNodeStatus();
      setNodeInfo(data);
      setApiError(null);
    } catch (err) {
      console.error('Error fetching node status:', err);
      setApiError('Unable to connect to Flask REST Bridge. Ensure the node container is running.');
    }
  };

  useEffect(() => {
    loadStatus();
    const interval = setInterval(loadStatus, 2500);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="app-container">
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        nodeInfo={nodeInfo}
        onRefresh={loadStatus}
      />

      <main className="main-content" id="main-content" tabIndex={-1}>
        {apiError && (
          <div 
            className="alert alert-warning" 
            role="alert" 
            style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}
          >
            <AlertCircle size={18} aria-hidden="true" style={{ color: 'var(--color-warning)' }} />
            <span>
              <strong>REST Bridge Disconnected:</strong> {apiError}
            </span>
          </div>
        )}

        <div key={activeTab}>
          {activeTab === 'dashboard' && (
            <Dashboard nodeInfo={nodeInfo} onNavigate={setActiveTab} />
          )}

          {activeTab === 'voting' && (
            <Voting nodeInfo={nodeInfo} onVoteSuccess={loadStatus} />
          )}

          {activeTab === 'nodes' && (
            <Nodes nodeInfo={nodeInfo} />
          )}

          {activeTab === 'election' && (
            <Election nodeInfo={nodeInfo} onElectionTriggered={loadStatus} />
          )}

          {activeTab === 'recovery' && (
            <Recovery nodeInfo={nodeInfo} onRecoveryTriggered={loadStatus} />
          )}

          {activeTab === 'events' && (
            <Events />
          )}
        </div>
      </main>

      <footer 
        role="contentinfo"
        style={{
          marginTop: 'auto',
          borderTop: '1px solid var(--color-border-subtle)',
          backgroundColor: '#FFFFFF',
          padding: '1.25rem 2rem',
          fontSize: '0.8125rem',
          color: 'var(--color-text-secondary)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '1rem'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <ShieldCheck size={16} color="var(--color-teal-accent)" aria-hidden="true" />
          <span>Fault-Tolerant Distributed Consensus • B.Tech Capstone Project</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem', flexWrap: 'wrap' }}>
          <span>Protocol: <strong style={{ color: 'var(--color-navy-primary)' }}>Bully / Ring Election</strong></span>
          <span>Storage: <strong style={{ color: 'var(--color-navy-primary)' }}>Replicated MySQL WAL</strong></span>
          <span>Transport: <strong style={{ color: 'var(--color-navy-primary)' }}>gRPC & HTTP REST</strong></span>
        </div>
      </footer>
    </div>
  );
}
