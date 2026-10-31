import React, { useEffect, useState, useRef } from 'react';
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
  RefreshCw,
  Box
} from 'lucide-react';
import gsap from 'gsap';
import { useGSAP } from '@gsap/react';
import { fetchTally, fetchNodes } from '../api';
import Cluster3DTopology from './Cluster3DTopology';

// Smooth GSAP Numeric Counter for metric widgets & tally headers
function GsapCounter({ value = 0, duration = 1.0, prefix = '', suffix = '' }) {
  const numRef = useRef(null);
  const stateRef = useRef({ val: 0 });

  useGSAP(() => {
    gsap.to(stateRef.current, {
      val: Number(value) || 0,
      duration: duration,
      ease: 'power2.out',
      onUpdate: () => {
        if (numRef.current) {
          numRef.current.textContent = `${prefix}${Math.round(stateRef.current.val).toLocaleString()}${suffix}`;
        }
      }
    });
  }, [value]);

  return <span ref={numRef} className="tally-num">{prefix}{value || 0}{suffix}</span>;
}

// Kinetic Candidate Tally Row: Smoothly interpolates vote counts and progress bar width on 2.5s poll resolutions
function CandidateTallyRow({ cand, count = 0, total = 0, isLeader }) {
  const rowRef = useRef(null);
  const barRef = useRef(null);
  const countRef = useRef(null);
  const pctRef = useRef(null);
  const animState = useRef({ count: 0, pct: 0 });

  const targetPct = total > 0 ? Math.round((count / total) * 100) : 0;

  useGSAP(() => {
    // 1. Smoothly interpolate numeric count & percentage
    gsap.to(animState.current, {
      count: count,
      pct: targetPct,
      duration: 1.2,
      ease: 'power2.out',
      onUpdate: () => {
        if (countRef.current) {
          const c = Math.round(animState.current.count);
          countRef.current.textContent = `${c} ${c === 1 ? 'vote' : 'votes'}`;
        }
        if (pctRef.current) {
          pctRef.current.textContent = `(${Math.round(animState.current.pct)}%)`;
        }
      }
    });

    // 2. Hardware-accelerated smooth progress meter animation
    if (barRef.current) {
      gsap.to(barRef.current, {
        width: `${targetPct}%`,
        duration: 1.2,
        ease: 'power2.out',
        force3D: true
      });
    }
  }, { dependencies: [count, targetPct], scope: rowRef });

  return (
    <div ref={rowRef} className="tally-item">
      <div className="tally-meta">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
          <div className="candidate-avatar-badge" aria-hidden="true">
            {cand.charAt(0)}
          </div>
          <div>
            <span style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>{cand}</span>
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
          <span 
            ref={countRef}
            className="tally-num"
            style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--color-text-primary)' }}
          >
            {count} {count === 1 ? 'vote' : 'votes'}
          </span>
          <span 
            ref={pctRef}
            className="tally-num"
            style={{ color: 'var(--color-text-muted)', fontSize: '0.84rem' }}
          >
            ({targetPct}%)
          </span>
        </div>
      </div>

      <div 
        className="progress-track" 
        role="progressbar" 
        aria-valuenow={targetPct} 
        aria-valuemin={0} 
        aria-valuemax={100}
        aria-label={`${cand} votes: ${count} (${targetPct}%)`}
      >
        <div 
          ref={barRef}
          className="progress-fill gpu-accel" 
          style={{ width: `${targetPct}%` }} 
        />
      </div>
    </div>
  );
}

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

  // 2.5s Native Fetch Polling Interval with Leak-Free Cleanup
  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 2500);
    return () => clearInterval(interval);
  }, []);

  const totalCommitted = tallyData.total_votes || 0;
  const tally = tallyData.tally || {};
  const candidates = nodeInfo?.candidates || ['Alice', 'Bob', 'Charlie'];

  // Calculate authoritative leading candidate
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
  const coordId = nodeInfo?.coordinator_id ?? 1;

  return (
    <div className="dashboard-page route-fade-in">
      {/* Cluster Node Role Banner */}
      <div 
        className="card"
        style={{
          borderLeft: isCoord ? '4px solid var(--color-indigo)' : '4px solid var(--color-cyan)',
          marginBottom: '1.75rem',
          padding: '1.25rem 1.5rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '1.25rem',
          background: isCoord 
            ? 'linear-gradient(90deg, rgba(99, 102, 241, 0.15) 0%, rgba(18, 24, 38, 0.8) 100%)' 
            : 'linear-gradient(90deg, rgba(6, 182, 212, 0.12) 0%, rgba(18, 24, 38, 0.8) 100%)'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div 
            style={{
              width: '46px',
              height: '46px',
              borderRadius: 'var(--radius-md)',
              background: isCoord ? 'var(--color-indigo)' : 'var(--color-cyan)',
              boxShadow: isCoord ? '0 0 20px var(--color-indigo-glow)' : '0 0 20px var(--color-cyan-glow)',
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
              <h2 style={{ fontSize: '1.2rem', fontWeight: 800, margin: 0, color: '#FFFFFF' }}>
                {isCoord ? `Node ${nodeInfo?.node_id} is Active Cluster Coordinator` : `Node ${nodeInfo?.node_id} is Follower Replica`}
              </h2>
              <span className={`badge ${isCoord ? 'badge-coordinator' : 'badge-follower'}`}>
                {isCoord ? '★ ACTIVE LEADER' : 'REPLICA FOLLOWER'}
              </span>
            </div>
            <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.875rem', marginTop: '0.25rem' }}>
              {isCoord 
                ? 'Accepting vote writes and orchestrating 2-Phase Commit (2PC) replication to cluster peers.' 
                : `Connected to Leader (Node ${coordId}). Replicas maintain read-only synchronized copies of the ballot ledger.`}
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
              <span>Cast Ballot</span>
              <ArrowRight size={14} aria-hidden="true" />
            </button>
          ) : (
            <a 
              href={`http://localhost:${5000 + coordId}`}
              className="btn btn-primary"
            >
              <span>Switch to Leader (Node {coordId})</span>
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

      {/* Cluster Metrics (4 columns Bento Top Row) */}
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
              className={`status-dot ${isCoord ? 'status-dot-active' : 'status-dot-indigo'}`} 
              aria-hidden="true" 
            />
            {isCoord ? 'Cluster Coordinator' : `Coordinator is Node ${coordId}`}
          </span>
        </div>

        {/* Coordinator Lease */}
        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Coordinator Lease</span>
            <Crown size={18} className="stat-icon" aria-hidden="true" />
          </div>
          <span className="stat-value">
            Node {nodeInfo?.coordinator_id ?? 'None'}
          </span>
          <span className="stat-meta">
            <Zap size={13} style={{ color: 'var(--color-amber)' }} aria-hidden="true" />
            Term #{nodeInfo?.election_term ?? 0} • {nodeInfo?.election_algorithm?.toUpperCase() || 'BULLY'}
          </span>
        </div>

        {/* Committed Ballots (with smooth GSAP counter) */}
        <div className="stat-widget">
          <div className="stat-header">
            <span className="stat-label">Committed Ballots</span>
            <CheckCircle2 size={18} className="stat-icon" aria-hidden="true" />
          </div>
          <span className="stat-value">
            {loading ? '...' : <GsapCounter value={totalCommitted} />}
          </span>
          <span className="stat-meta">
            <ShieldCheck size={13} style={{ color: 'var(--color-cyan)' }} aria-hidden="true" />
            2PC Consensus Verified
          </span>
        </div>

        {/* Active Mesh Quorum */}
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

      {/* Main Bento Grid: 3D Topology Stage (7 cols) + 2PC Results Tally (5 cols) */}
      <div className="bento-grid">
        {/* Bento Box 1: Interactive R3F 3D Consensus Topology Stage */}
        <section className="card bento-col-7" aria-labelledby="topology-stage-title" style={{ display: 'flex', flexDirection: 'column' }}>
          <div className="card-title">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem' }}>
              <Box size={18} style={{ color: 'var(--color-cyan)' }} aria-hidden="true" />
              <h3 id="topology-stage-title" style={{ fontSize: '1.0625rem', fontWeight: 700, margin: 0 }}>
                3D Consensus Topology Mesh
              </h3>
            </div>
            <span className="badge badge-active">
              <span className="status-dot status-dot-active" aria-hidden="true" />
              Live R3F Engine
            </span>
          </div>

          <p className="card-subtitle">
            Interactive WebGL mesh rendering active Coordinator and Follower nodes. Camera automatically refocuses on election failover.
          </p>

          {/* R3F 3D Topology Component */}
          <div className="bento-stage-3d" style={{ flex: 1, minHeight: '360px' }}>
            <Cluster3DTopology 
              nodes={clusterNodes} 
              coordinatorId={nodeInfo?.coordinator_id || 1} 
              onSelectNode={(node) => console.log('Selected node:', node)}
            />
          </div>

          <div style={{ marginTop: '1rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>
            <span>gRPC Replication Beams: <strong style={{ color: 'var(--color-cyan)' }}>Active</strong></span>
            <span>Failover Camera Interpolation: <strong style={{ color: 'var(--color-indigo-light)' }}>GSAP Power2.inOut</strong></span>
          </div>
        </section>

        {/* Bento Box 2: Authoritative 2PC Live Results Tally with GSAP Interpolation */}
        <section className="card bento-col-5" aria-labelledby="tally-section-title" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
          <div>
            <div className="card-title">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Trophy size={18} style={{ color: 'var(--color-amber)' }} aria-hidden="true" />
                <h3 id="tally-section-title" style={{ fontSize: '1.0625rem', fontWeight: 700, margin: 0 }}>
                  2PC Committed Results
                </h3>
              </div>
              <span className="badge badge-coordinator">
                <GsapCounter value={totalCommitted} suffix={totalCommitted === 1 ? ' Vote' : ' Votes'} />
              </span>
            </div>

            <p className="card-subtitle">
              Smooth kinetic interpolation binds 2.5s polling resolutions into seamless GSAP transitions.
            </p>

            {/* Results Table & Progress Bars with Kinetic GSAP Tweens */}
            <div style={{ marginTop: '1.25rem' }}>
              {candidates.map((cand) => {
                const count = tally[cand] || 0;
                const isLeader = cand === leadingCandidate && count > 0;

                return (
                  <CandidateTallyRow
                    key={cand}
                    cand={cand}
                    count={count}
                    total={totalCommitted}
                    isLeader={isLeader}
                  />
                );
              })}
            </div>

            {totalCommitted === 0 && !loading && (
              <div 
                style={{ 
                  padding: '1.5rem', 
                  textAlign: 'center', 
                  backgroundColor: 'rgba(255, 255, 255, 0.02)', 
                  borderRadius: 'var(--radius-md)', 
                  border: '1px dashed var(--color-border-glass)',
                  marginTop: '1.25rem',
                  color: 'var(--color-text-muted)',
                  fontSize: '0.875rem'
                }}
              >
                No ballots committed yet for this election. Cast a ballot to initiate consensus.
              </div>
            )}
          </div>

          <div style={{ marginTop: '1.5rem', display: 'flex', gap: '0.75rem', borderTop: '1px solid var(--color-border-glass)', paddingTop: '1.25rem', flexWrap: 'wrap' }}>
            <button 
              type="button"
              className="btn btn-primary" 
              onClick={() => onNavigate('voting')}
              style={{ flex: 1 }}
            >
              <Vote size={15} aria-hidden="true" />
              <span>Cast Ballot</span>
            </button>
            <button 
              type="button"
              className="btn btn-secondary" 
              onClick={loadData}
              title="Manual telemetry refresh"
            >
              <RefreshCw size={14} aria-hidden="true" />
              <span>Refresh</span>
            </button>
          </div>
        </section>

        {/* Bento Box 3: Synchronized Node Mesh Quick Overview (12 cols) */}
        <section className="card bento-col-12" aria-labelledby="mesh-section-title">
          <div className="card-title">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Server size={18} style={{ color: 'var(--color-indigo)' }} aria-hidden="true" />
              <h3 id="mesh-section-title" style={{ fontSize: '1.0625rem', fontWeight: 700, margin: 0 }}>
                Cluster Peers & Endpoints
              </h3>
            </div>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ padding: '0.35rem 0.75rem', fontSize: '0.8rem' }}
              onClick={() => onNavigate('nodes')}
            >
              <span>Detailed Telemetry & Invariants</span>
              <ArrowRight size={12} aria-hidden="true" />
            </button>
          </div>

          <p className="card-subtitle">
            Distributed nodes synchronized via gRPC consensus channels and local MySQL durable write-ahead logs.
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.85rem' }}>
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
                    padding: '0.85rem 1rem',
                    borderRadius: 'var(--radius-md)',
                    background: n.is_self ? 'rgba(99, 102, 241, 0.12)' : 'rgba(255, 255, 255, 0.03)',
                    border: n.is_self ? '1px solid var(--color-indigo-glow)' : '1px solid var(--color-border-glass)',
                    transition: 'all var(--transition-fast)'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <div 
                      style={{
                        width: '34px',
                        height: '34px',
                        borderRadius: 'var(--radius-sm)',
                        background: isNodeLeader ? 'var(--color-indigo)' : 'rgba(255, 255, 255, 0.08)',
                        color: '#FFFFFF',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        flexShrink: 0
                      }}
                      aria-hidden="true"
                    >
                      {isNodeLeader ? <Crown size={18} /> : <Server size={18} />}
                    </div>

                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                        <strong style={{ fontSize: '0.9rem', color: '#FFFFFF' }}>
                          Node {n.node_id}
                        </strong>
                        {n.is_self && (
                          <span className="badge badge-active" style={{ fontSize: '0.625rem', padding: '0.1rem 0.4rem' }}>
                            Connected Host
                          </span>
                        )}
                      </div>
                      <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>
                        Port {port} • gRPC:5005{n.node_id}
                      </span>
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                    <span className={`badge ${isNodeLeader ? 'badge-coordinator' : 'badge-follower'}`}>
                      {isNodeLeader ? 'LEADER' : 'FOLLOWER'}
                    </span>
                    {!n.is_self && (
                      <a
                        href={`http://localhost:${port}`}
                        target="_blank"
                        rel="noreferrer"
                        className="btn btn-secondary"
                        style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
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
        </section>
      </div>
    </div>
  );
}
