import React, { useState } from 'react';
import { submitVote, fetchVote } from '../api';
import confetti from 'canvas-confetti';
import { 
  Vote, 
  CheckCircle2, 
  AlertTriangle, 
  Copy, 
  Check, 
  Search, 
  ShieldCheck, 
  Sparkles, 
  Clock, 
  ArrowRight,
  ExternalLink,
  Award,
  Hash,
  Database
} from 'lucide-react';

export default function Voting({ nodeInfo, onVoteSuccess }) {
  const [clientId, setClientId] = useState('');
  const [choice, setChoice] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState(null);
  const [copiedReceipt, setCopiedReceipt] = useState(false);

  // Receipt lookup state
  const [lookupId, setLookupId] = useState('');
  const [lookupResult, setLookupResult] = useState(null);
  const [lookupError, setLookupError] = useState('');
  const [lookingUp, setLookingUp] = useState(false);

  const candidates = [
    {
      name: 'Alice',
      role: 'Platform Engineering & Scalability',
      color: '#6366f1',
      gradient: 'linear-gradient(135deg, #6366f1, #4338ca)',
      avatar: 'A',
      tag: 'Decentralized Architecture'
    },
    {
      name: 'Bob',
      role: 'Security & Cryptographic Invariants',
      color: '#06b6d4',
      gradient: 'linear-gradient(135deg, #06b6d4, #0e7490)',
      avatar: 'B',
      tag: 'Fault-Tolerant Consensus'
    },
    {
      name: 'Charlie',
      role: 'High-Throughput Replicated Logs',
      color: '#10b981',
      gradient: 'linear-gradient(135deg, #10b981, #047857)',
      avatar: 'C',
      tag: 'Zero-Downtime Recovery'
    }
  ];

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!clientId.trim()) {
      setFeedback({ success: false, message: 'Please enter a valid Voter ID' });
      return;
    }
    if (!choice) {
      setFeedback({ success: false, message: 'Please select a candidate before casting your ballot' });
      return;
    }

    setSubmitting(true);
    setFeedback(null);

    try {
      const res = await submitVote(clientId.trim(), choice);
      if (res.success) {
        setFeedback({
          success: true,
          voteId: res.vote_id,
          message: `Ballot successfully committed across quorum peers!`,
          lamportTs: res.lamport_ts,
          choice: res.choice,
          nodeId: res.node_id,
        });

        // Trigger celebratory confetti animation
        try {
          confetti({
            particleCount: 90,
            spread: 70,
            origin: { y: 0.65 },
            colors: ['#6366f1', '#06b6d4', '#10b981', '#f59e0b', '#ec4899']
          });
        } catch (_) {}

        setClientId('');
        setChoice('');
        if (onVoteSuccess) onVoteSuccess();
      } else {
        setFeedback({
          success: false,
          error: res.error,
          message: res.message || 'Vote rejected: write permissions restricted to active coordinator',
          coordinatorId: res.coordinator_id,
        });
      }
    } catch (err) {
      setFeedback({
        success: false,
        error: 'network_error',
        message: `Failed to contact REST bridge: ${err.message}`,
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleCopyReceipt = (text) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedReceipt(true);
    setTimeout(() => setCopiedReceipt(false), 2200);
  };

  const handleLookup = async (e) => {
    e.preventDefault();
    if (!lookupId.trim()) return;

    setLookingUp(true);
    setLookupResult(null);
    setLookupError('');

    try {
      const res = await fetchVote(lookupId.trim());
      if (res.success) {
        setLookupResult(res.vote);
      } else {
        setLookupError(res.message || 'Vote record not found in cluster database');
      }
    } catch (err) {
      setLookupError(`Lookup query failed: ${err.message}`);
    } finally {
      setLookingUp(false);
    }
  };

  const isCoordinator = !!nodeInfo?.is_coordinator;
  const coordinatorId = nodeInfo?.coordinator_id ?? 3;

  return (
    <div className="voting-page" style={{ animation: 'fadeIn 0.3s ease-out' }}>
      <div className="page-header">
        <h2 className="page-title">Cast Your Ballot</h2>
        <p className="page-description">
          Cryptographically signed client votes replicated with strict Lamport ordering and two-phase finalization.
        </p>
      </div>

      <div className="grid-2">
        {/* Vote Submission Card */}
        <div className="card">
          <div className="card-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <Vote size={20} color="var(--accent-indigo-light)" />
              Ballot Submission Terminal
            </span>
            {isCoordinator ? (
              <span className="badge badge-coordinator">
                <CheckCircle2 size={12} />
                Node {nodeInfo?.node_id} (Leader)
              </span>
            ) : (
              <span className="badge badge-follower">
                <AlertTriangle size={12} />
                Node {nodeInfo?.node_id ?? '?'} (Follower)
              </span>
            )}
          </div>

          {/* Follower Guard Notice */}
          {!isCoordinator && (
            <div 
              className="alert" 
              style={{ 
                background: 'rgba(59, 130, 246, 0.08)', 
                border: '1px solid rgba(59, 130, 246, 0.25)', 
                marginBottom: '1.5rem',
                borderRadius: 'var(--radius-md)'
              }}
            >
              <AlertTriangle size={20} color="#60a5fa" style={{ flexShrink: 0, marginTop: '2px' }} />
              <div style={{ flex: 1 }}>
                <strong style={{ color: '#93c5fd' }}>Connected to Follower Node {nodeInfo?.node_id ?? '?'}</strong>
                <p style={{ marginTop: '0.35rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                  In this consensus cluster, write votes are accepted exclusively by the active Coordinator (<strong>Node {coordinatorId}</strong>) to prevent split-brain discrepancies.
                </p>
                <div style={{ marginTop: '0.75rem' }}>
                  <a
                    href={`http://localhost:${5000 + coordinatorId}`}
                    className="btn btn-primary"
                    style={{ 
                      display: 'inline-flex', 
                      alignItems: 'center', 
                      gap: '0.4rem', 
                      padding: '0.45rem 0.95rem', 
                      fontSize: '0.825rem',
                      textDecoration: 'none'
                    }}
                  >
                    Switch to Coordinator (Node {coordinatorId})
                    <ExternalLink size={14} />
                  </a>
                </div>
              </div>
            </div>
          )}

          {/* Submission Feedback Alert */}
          {feedback && (
            <div className={`alert ${feedback.success ? 'alert-success' : 'alert-error'}`}>
              {feedback.success ? (
                <CheckCircle2 size={20} style={{ flexShrink: 0, marginTop: '2px' }} />
              ) : (
                <AlertTriangle size={20} style={{ flexShrink: 0, marginTop: '2px' }} />
              )}
              <div style={{ flex: 1 }}>
                <strong>{feedback.success ? 'Ballot Accepted & Quorum Committed!' : 'Submission Rejected'}</strong>
                <p style={{ marginTop: '0.25rem', fontSize: '0.875rem' }}>{feedback.message}</p>
                
                {feedback.voteId && (
                  <div className="receipt-card" style={{ marginTop: '0.85rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.4rem' }}>
                      <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--accent-emerald-light)' }}>
                        Durable Vote Receipt
                      </span>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        Lamport TS: #{feedback.lamportTs}
                      </span>
                    </div>
                    <div className="receipt-code">
                      <span>{feedback.voteId}</span>
                      <button
                        type="button"
                        onClick={() => handleCopyReceipt(feedback.voteId)}
                        className="btn btn-secondary"
                        style={{ padding: '0.25rem 0.6rem', fontSize: '0.75rem', height: '28px' }}
                      >
                        {copiedReceipt ? <Check size={14} color="var(--accent-emerald)" /> : <Copy size={14} />}
                        {copiedReceipt ? 'Copied' : 'Copy'}
                      </button>
                    </div>
                  </div>
                )}

                {feedback.coordinatorId && (
                  <div style={{ marginTop: '0.75rem' }}>
                    <a
                      href={`http://localhost:${5000 + feedback.coordinatorId}`}
                      className="btn btn-primary"
                      style={{ fontSize: '0.8rem', padding: '0.4rem 0.85rem', display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}
                    >
                      Redirect to Node {feedback.coordinatorId}
                      <ArrowRight size={14} />
                    </a>
                  </div>
                )}
              </div>
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label" htmlFor="voter-id-input">
                Voter Identification
              </label>
              <input
                id="voter-id-input"
                type="text"
                className="form-input"
                placeholder="e.g. voter_alice_01, student_982..."
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                disabled={submitting}
              />
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.35rem', display: 'block' }}>
                Must be unique per voter. Alphanumeric and underscores supported.
              </span>
            </div>

            <div className="form-group">
              <label className="form-label">Select Candidate</label>
              <div className="candidate-grid">
                {candidates.map((cand) => {
                  const isSelected = choice === cand.name;
                  return (
                    <div
                      key={cand.name}
                      className={`candidate-card ${isSelected ? 'is-selected' : ''}`}
                      onClick={() => setChoice(cand.name)}
                    >
                      <div className="candidate-avatar" style={{ background: cand.gradient }}>
                        {cand.avatar}
                      </div>
                      <div className="candidate-info">
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          <span className="candidate-name">{cand.name}</span>
                          <span style={{ 
                            fontSize: '0.7rem', 
                            background: 'rgba(255,255,255,0.06)', 
                            padding: '0.15rem 0.5rem', 
                            borderRadius: '999px',
                            color: cand.color,
                            fontWeight: 600
                          }}>
                            {cand.tag}
                          </span>
                        </div>
                        <div className="candidate-desc">{cand.role}</div>
                      </div>
                      <div style={{ marginLeft: '1rem' }}>
                        <div style={{
                          width: '20px',
                          height: '20px',
                          borderRadius: '50%',
                          border: isSelected ? `5px solid ${cand.color}` : '2px solid var(--border-medium)',
                          background: isSelected ? '#fff' : 'transparent',
                          transition: 'var(--transition)'
                        }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <button
              type="submit"
              className="btn btn-primary"
              style={{ width: '100%', padding: '0.85rem' }}
              disabled={submitting || !clientId.trim() || !choice}
            >
              {submitting ? (
                <>
                  <Sparkles size={16} className="spin-icon" />
                  Broadcasting Vote to Coordinator...
                </>
              ) : (
                <>
                  <Vote size={16} />
                  Cast Ballot Now →
                </>
              )}
            </button>
          </form>
        </div>

        {/* Digital Receipt Verification Card */}
        <div className="card">
          <div className="card-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <ShieldCheck size={20} color="var(--accent-cyan-light)" />
              Verify Ballot Receipt
            </span>
            <span className="badge badge-follower">
              <Database size={12} />
              Cryptographic Audit
            </span>
          </div>

          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '1.25rem' }}>
            Check your receipt identifier (format: <code>client_id:origin_node:lamport_ts</code>) against the local node database to prove immutability and verify its <code>COMMITTED</code> state.
          </p>

          <form onSubmit={handleLookup} style={{ marginBottom: '1.25rem' }}>
            <div className="form-group">
              <label className="form-label" htmlFor="receipt-lookup-input">
                Receipt Identifier
              </label>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <input
                  id="receipt-lookup-input"
                  type="text"
                  className="form-input"
                  placeholder="e.g. voter_101:3:14"
                  value={lookupId}
                  onChange={(e) => setLookupId(e.target.value)}
                />
                <button
                  type="submit"
                  className="btn btn-secondary"
                  disabled={lookingUp || !lookupId.trim()}
                  style={{ flexShrink: 0 }}
                >
                  {lookingUp ? <Search size={16} className="spin-icon" /> : <Search size={16} />}
                  Verify
                </button>
              </div>
            </div>
          </form>

          {lookupError && (
            <div className="alert alert-error">
              <AlertTriangle size={18} style={{ flexShrink: 0 }} />
              <span>{lookupError}</span>
            </div>
          )}

          {lookupResult && (
            <div
              style={{
                padding: '1.25rem',
                borderRadius: 'var(--radius-md)',
                background: 'rgba(10, 14, 23, 0.8)',
                border: '1px solid var(--border-medium)',
                boxShadow: 'var(--shadow-sm)'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem', paddingBottom: '0.75rem', borderBottom: '1px solid var(--border-subtle)' }}>
                <span style={{ fontSize: '0.8rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                  Audit Record Found
                </span>
                <span className={`badge ${lookupResult.status === 'COMMITTED' ? 'badge-active' : 'badge-recovering'}`}>
                  ● {lookupResult.status}
                </span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', fontSize: '0.85rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    <Hash size={14} /> Voter ID:
                  </span>
                  <strong style={{ fontFamily: 'var(--font-mono)' }}>{lookupResult.client_id}</strong>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    <Award size={14} /> Selected Candidate:
                  </span>
                  <strong style={{ color: 'var(--accent-indigo-light)' }}>{lookupResult.choice}</strong>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    <Database size={14} /> Originating Node:
                  </span>
                  <span>Node {lookupResult.origin_node_id}</span>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    <Clock size={14} /> Lamport Sequence:
                  </span>
                  <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-emerald-light)' }}>
                    #{lookupResult.lamport_ts}
                  </span>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Local Commit Time:</span>
                  <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    {lookupResult.created_at ? new Date(lookupResult.created_at).toLocaleTimeString() : 'Verified'}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Architecture info footer */}
          <div style={{ marginTop: '1.5rem', padding: '1rem', background: 'rgba(255,255,255,0.02)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
              <ShieldCheck size={14} color="var(--accent-emerald)" />
              Zero Ghost-Vote Guarantee
            </div>
            All ballots pass through deterministic 2-phase commit and are persisted with WAL logging before acknowledgment.
          </div>
        </div>
      </div>
    </div>
  );
}
