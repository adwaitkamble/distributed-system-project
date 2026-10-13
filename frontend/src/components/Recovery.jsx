import React, { useEffect, useState } from 'react';
import { fetchRecoveryStatus, startRecovery } from '../api';
import { 
  ShieldCheck, 
  Database, 
  RotateCcw, 
  AlertTriangle, 
  CheckCircle2, 
  Sparkles, 
  Activity, 
  Cpu, 
  Layers, 
  FileText, 
  RefreshCw,
  GitMerge,
  ArrowRight
} from 'lucide-react';

export default function Recovery({ nodeInfo, onRecoveryTriggered }) {
  const [recoveryData, setRecoveryData] = useState(null);
  const [recovering, setRecovering] = useState(false);
  const [triggerResult, setTriggerResult] = useState(null);

  const loadRecovery = async () => {
    try {
      const res = await fetchRecoveryStatus();
      if (res.success) setRecoveryData(res);
    } catch (err) {
      console.error('Failed to load recovery status:', err);
    }
  };

  useEffect(() => {
    loadRecovery();
    const interval = setInterval(loadRecovery, 3000);
    return () => clearInterval(interval);
  }, []);

  const handleStartRecovery = async () => {
    setRecovering(true);
    setTriggerResult(null);

    try {
      const res = await startRecovery();
      setTriggerResult(res);
      await loadRecovery();
      if (onRecoveryTriggered) onRecoveryTriggered();
    } catch (err) {
      setTriggerResult({ success: false, error: err.message });
    } finally {
      setRecovering(false);
    }
  };

  const lastRec = recoveryData?.last_recovery;
  const isRecovering = recoveryData?.is_recovering;
  const role = recoveryData?.role || nodeInfo?.role || 'unknown';

  return (
    <div className="recovery-page" style={{ animation: 'fadeIn 0.3s ease-out' }}>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 className="page-title">State Recovery & SyncLog Invariants</h2>
          <p className="page-description">
            Enforces Phase 4 Recovery-Authority Rule, ghost-vote elimination, and policy-gated coordinator promotion.
          </p>
        </div>
        <button 
          className="btn btn-secondary" 
          onClick={loadRecovery}
          style={{ padding: '0.45rem 0.9rem', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}
        >
          <RefreshCw size={14} />
          Refresh
        </button>
      </div>

      {/* Top Stat Overview */}
      <div className="grid-4" style={{ marginBottom: '1.75rem' }}>
        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Node Role State</span>
            <Activity size={18} className="stat-icon" />
          </div>
          <div className="stat-value" style={{ textTransform: 'uppercase', color: isRecovering ? 'var(--accent-amber)' : 'var(--accent-indigo-light)' }}>
            {role}
          </div>
          <div className="stat-meta">
            <span>{isRecovering ? 'Non-voting (syncing logs)' : 'Operational & Serving'}</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Replication Policy</span>
            <Layers size={18} className="stat-icon" />
          </div>
          <div className="stat-value" style={{ color: 'var(--accent-cyan-light)' }}>
            {recoveryData?.replication_policy?.toUpperCase() || 'ALL'}
          </div>
          <div className="stat-meta">
            <span>Snapshot policy gating</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Ghost Votes Demoted</span>
            <AlertTriangle size={18} className="stat-icon" style={{ color: 'var(--accent-amber)' }} />
          </div>
          <div className="stat-value" style={{ color: 'var(--accent-amber-light)' }}>
            {lastRec?.rejected_partial_finalizations_count ?? 0}
          </div>
          <div className="stat-meta">
            <span>Phantom finalizations blocked</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Committed Replayed</span>
            <Database size={18} className="stat-icon" style={{ color: 'var(--accent-emerald)' }} />
          </div>
          <div className="stat-value" style={{ color: 'var(--accent-emerald-light)' }}>
            {lastRec?.committed_votes_count ?? 0}
          </div>
          <div className="stat-meta">
            <span>Max Lamport: #{lastRec?.max_lamport_ts ?? 0}</span>
          </div>
        </div>
      </div>

      <div className="grid-2">
        {/* Recovery Action Card */}
        <div className="card">
          <div className="card-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <RotateCcw size={20} color="var(--accent-indigo-light)" />
              Execute State Synchronization
            </span>
            <span className={`badge ${lastRec?.success ? 'badge-active' : 'badge-inactive'}`}>
              Last: {lastRec?.success ? 'Succeeded' : 'Pending / None'}
            </span>
          </div>

          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '1.25rem' }}>
            Polls surviving peers via gRPC <code>SyncLog</code>, merges missing votes deterministically, enforces the 
            <strong> Recovery-Authority Rule</strong> to prevent ghost-vote resurrection, and repairs lagging peers.
          </p>

          <div
            style={{
              padding: '1rem',
              borderRadius: 'var(--radius-md)',
              background: 'rgba(99, 102, 241, 0.05)',
              border: '1px solid rgba(99, 102, 241, 0.2)',
              marginBottom: '1.25rem',
              fontSize: '0.825rem',
              color: 'var(--text-secondary)',
              lineHeight: 1.55
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--accent-indigo-light)', fontWeight: 700, marginBottom: '0.35rem' }}>
              <ShieldCheck size={16} />
              Phase 4 Safety Invariant
            </div>
            A recovering coordinator remains strictly non-voting until all snapshot peers or quorum succeed and repair fan-out completes without exception.
          </div>

          <button
            className="btn btn-primary"
            onClick={handleStartRecovery}
            disabled={recovering}
            style={{ width: '100%', padding: '0.85rem' }}
          >
            {recovering ? (
              <>
                <Sparkles size={16} className="spin-icon" />
                Synchronizing Logs Across Peers...
              </>
            ) : (
              <>
                <GitMerge size={16} />
                Run Recovery & Synchronization →
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
                <strong>{triggerResult.success ? 'State Recovery Completed' : 'Recovery Policy Denied'}</strong>
                <p style={{ marginTop: '0.25rem', fontSize: '0.85rem' }}>
                  {triggerResult.success
                    ? `Role promoted to ${triggerResult.role?.toUpperCase()}. Synced ${triggerResult.votes_synced_count ?? 0} missing records in ${triggerResult.duration_ms ?? 0} ms.`
                    : triggerResult.error || 'Failed to satisfy recovery consensus policy.'}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Detailed Metrics Breakdown */}
        <div className="card">
          <div className="card-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <FileText size={20} color="var(--accent-cyan-light)" />
              SyncLog Execution Telemetry
            </span>
            <span className="badge badge-follower">Durable DB WAL</span>
          </div>

          {lastRec ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem', fontSize: '0.875rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
                <span style={{ color: 'var(--text-muted)' }}>Status / Outcome:</span>
                <span className={`badge ${lastRec.success ? 'badge-active' : 'badge-inactive'}`}>
                  {lastRec.success ? 'Verified Success' : 'Policy Blocked'}
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
                <span style={{ color: 'var(--text-muted)' }}>Accepted Remote Records:</span>
                <strong style={{ color: 'var(--accent-indigo-light)' }}>{lastRec.accepted_votes_count ?? 0}</strong>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
                <span style={{ color: 'var(--text-muted)' }}>Rejected Partial Finalizations:</span>
                <strong style={{ color: 'var(--accent-amber-light)' }}>{lastRec.rejected_partial_finalizations_count ?? 0}</strong>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
                <span style={{ color: 'var(--text-muted)' }}>Client-ID Conflicts:</span>
                <span>{lastRec.client_id_conflicts_count ?? 0}</span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
                <span style={{ color: 'var(--text-muted)' }}>Peers Contacted:</span>
                <span>
                  {lastRec.peers_contacted?.length ? `Nodes: [${lastRec.peers_contacted.join(', ')}]` : 'None / Local only'}
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>Execution Latency:</span>
                <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{lastRec.duration_ms ?? 0} ms</span>
              </div>

              {lastRec.error && (
                <div className="alert alert-error" style={{ marginTop: '0.75rem' }}>
                  <span>{lastRec.error}</span>
                </div>
              )}
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '2.5rem 1rem', color: 'var(--text-muted)' }}>
              <RotateCcw size={32} style={{ margin: '0 auto 0.75rem', opacity: 0.4 }} />
              <p style={{ fontSize: '0.9rem' }}>No previous recovery execution recorded on this runtime instance.</p>
              <p style={{ fontSize: '0.8rem', marginTop: '0.25rem' }}>Trigger recovery using the button on the left to initialize.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
