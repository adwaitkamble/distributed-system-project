import React, { useEffect, useState } from 'react';
import { fetchRecoveryStatus, startRecovery } from '../api';
import { 
  ShieldCheck, 
  Database, 
  RotateCcw, 
  AlertTriangle, 
  CheckCircle2, 
  Activity, 
  Layers, 
  FileText, 
  RefreshCw,
  GitMerge
} from 'lucide-react';

export default function Recovery({ nodeInfo, onRecoveryTriggered }) {
  const [recoveryData, setRecoveryData] = useState(null);
  const [recovering, setRecovering] = useState(false);
  const [triggerResult, setTriggerResult] = useState(null);

  const loadRecovery = async () => {
    try {
      const res = await fetchRecoveryStatus();
      if (res?.success) setRecoveryData(res);
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
    <div className="recovery-page route-fade-in">
      <div className="page-header">
        <div>
          <h2 className="page-title">State Recovery & SyncLog Invariants</h2>
          <p className="page-description">
            Enforces the Recovery-Authority Rule, eliminates ghost votes from crashed coordinators, and synchronizes missing ballots via gRPC SyncLog before serving client writes.
          </p>
        </div>
        <button 
          type="button"
          className="btn btn-secondary" 
          onClick={loadRecovery}
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
            <span className="stat-label">Operational State</span>
            <Activity size={18} className="stat-icon" aria-hidden="true" />
          </div>
          <div className="stat-value" style={{ textTransform: 'uppercase' }}>
            {role}
          </div>
          <div className="stat-meta">
            <span>{isRecovering ? 'Non-voting (syncing logs)' : 'Serving & Operational'}</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Replication Policy</span>
            <Layers size={18} className="stat-icon" aria-hidden="true" />
          </div>
          <div className="stat-value">
            {recoveryData?.replication_policy?.toUpperCase() || 'ALL'}
          </div>
          <div className="stat-meta">
            <span>Quorum threshold gating</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Ghost Votes Demoted</span>
            <AlertTriangle size={18} className="stat-icon" style={{ color: 'var(--color-warning)' }} aria-hidden="true" />
          </div>
          <div className="stat-value">
            {lastRec?.rejected_partial_finalizations_count ?? 0}
          </div>
          <div className="stat-meta">
            <span>Phantom finalizations suppressed</span>
          </div>
        </div>

        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Committed Replayed</span>
            <Database size={18} className="stat-icon" style={{ color: 'var(--color-success)' }} aria-hidden="true" />
          </div>
          <div className="stat-value">
            {lastRec?.committed_votes_count ?? 0}
          </div>
          <div className="stat-meta">
            <span>Max Lamport: #{lastRec?.max_lamport_ts ?? 0}</span>
          </div>
        </div>
      </div>

      <div className="grid-2">
        {/* Recovery Action Card */}
        <section className="card" aria-labelledby="sync-card-title">
          <div className="card-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <RotateCcw size={18} color="var(--color-navy-primary)" aria-hidden="true" />
              <h3 id="sync-card-title" style={{ fontSize: '1.0625rem', fontWeight: 700, margin: 0 }}>
                Trigger State Recovery
              </h3>
            </span>
            <span className={`badge ${lastRec?.success ? 'badge-active' : 'badge-neutral'}`}>
              Last Run: {lastRec?.success ? 'Succeeded' : 'None / Pending'}
            </span>
          </div>

          <p className="card-subtitle">
            Synchronizes missing transaction logs from live peers, reconciles divergent records, and executes the Recovery-Authority Rule to prevent resurrection of unacknowledged ballots.
          </p>

          <div
            style={{
              padding: '0.85rem 1rem',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'var(--color-surface-subtle)',
              border: '1px solid var(--color-border-subtle)',
              marginBottom: '1.25rem',
              fontSize: '0.8125rem',
              lineHeight: 1.5
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--color-navy-primary)', fontWeight: 600, marginBottom: '0.25rem' }}>
              <ShieldCheck size={16} color="var(--color-teal-accent)" aria-hidden="true" />
              Safety Guarantee
            </div>
            A recovering node remains strictly non-voting until peer log merging and database replay complete successfully.
          </div>

          <button
            type="button"
            className="btn btn-primary"
            onClick={handleStartRecovery}
            disabled={recovering}
            style={{ width: '100%', padding: '0.75rem' }}
          >
            {recovering ? (
              <>
                <RefreshCw size={16} className="spin-icon" aria-hidden="true" />
                <span>Synchronizing Logs Across Peers...</span>
              </>
            ) : (
              <>
                <GitMerge size={16} aria-hidden="true" />
                <span>Run State Recovery & SyncLog</span>
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
                  <CheckCircle2 size={18} style={{ flexShrink: 0, marginTop: '2px' }} aria-hidden="true" />
                ) : (
                  <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: '2px' }} aria-hidden="true" />
                )}
                <div style={{ flex: 1 }}>
                  <strong>{triggerResult.success ? 'State Recovery Completed' : 'Recovery Rejected'}</strong>
                  <p style={{ marginTop: '0.2rem', fontSize: '0.84rem' }}>
                    {triggerResult.success
                      ? `Promoted to ${triggerResult.role?.toUpperCase()}. Synced ${triggerResult.votes_synced_count ?? 0} missing records in ${triggerResult.duration_ms ?? 0} ms.`
                      : triggerResult.error || 'Failed to satisfy recovery consensus policy.'}
                  </p>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* SyncLog Telemetry Card */}
        <section className="card" aria-labelledby="telemetry-card-title">
          <div className="card-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <FileText size={18} color="var(--color-navy-primary)" aria-hidden="true" />
              <h3 id="telemetry-card-title" style={{ fontSize: '1.0625rem', fontWeight: 700, margin: 0 }}>
                SyncLog Execution Telemetry
              </h3>
            </span>
            <span className="badge badge-neutral">Durable Replay</span>
          </div>

          {lastRec ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', fontSize: '0.84rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--color-border-subtle)' }}>
                <span style={{ color: 'var(--color-text-muted)' }}>Status / Outcome:</span>
                <span className={`badge ${lastRec.success ? 'badge-active' : 'badge-inactive'}`}>
                  {lastRec.success ? 'Verified Success' : 'Failed / Incomplete'}
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--color-border-subtle)' }}>
                <span style={{ color: 'var(--color-text-muted)' }}>Accepted Remote Records:</span>
                <strong style={{ color: 'var(--color-navy-primary)' }}>{lastRec.accepted_votes_count ?? 0}</strong>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--color-border-subtle)' }}>
                <span style={{ color: 'var(--color-text-muted)' }}>Rejected Partial Finalizations:</span>
                <strong style={{ color: 'var(--color-warning-text)' }}>{lastRec.rejected_partial_finalizations_count ?? 0}</strong>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--color-border-subtle)' }}>
                <span style={{ color: 'var(--color-text-muted)' }}>Client-ID Conflicts:</span>
                <span>{lastRec.client_id_conflicts_count ?? 0}</span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '0.5rem', borderBottom: '1px solid var(--color-border-subtle)' }}>
                <span style={{ color: 'var(--color-text-muted)' }}>Peers Polled:</span>
                <span>
                  {lastRec.peers_contacted?.length ? `Nodes: [${lastRec.peers_contacted.join(', ')}]` : 'None / Local only'}
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--color-text-muted)' }}>Execution Duration:</span>
                <span style={{ color: 'var(--color-navy-primary)', fontWeight: 600 }}>{lastRec.duration_ms ?? 0} ms</span>
              </div>

              {lastRec.error && (
                <div className="alert alert-error" style={{ marginTop: '0.75rem' }} role="alert">
                  <span>{lastRec.error}</span>
                </div>
              )}
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '2rem 1rem', color: 'var(--color-text-muted)' }}>
              <RotateCcw size={28} style={{ margin: '0 auto 0.5rem', opacity: 0.4 }} aria-hidden="true" />
              <p style={{ fontSize: '0.875rem' }}>No recovery executed yet on this node instance.</p>
              <p style={{ fontSize: '0.78rem', marginTop: '0.2rem' }}>Trigger recovery using the button on the left to synchronize missing state.</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
