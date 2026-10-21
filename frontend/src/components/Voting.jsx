import React, { useState } from 'react';
import { submitVote, fetchVote } from '../api';
import { 
  Vote, 
  CheckCircle2, 
  AlertTriangle, 
  Copy, 
  Check, 
  Search, 
  ShieldCheck, 
  ArrowRight,
  ExternalLink,
  Database,
  RefreshCw
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
      platform: 'Decentralized Architecture & Scalability',
      description: 'Distributed consensus optimization and high-availability clustering.',
      avatar: 'A'
    },
    {
      name: 'Bob',
      platform: 'Fault-Tolerant Consensus & Safety',
      description: 'Formal verification of safety invariants and Byzantine fault resilience.',
      avatar: 'B'
    },
    {
      name: 'Charlie',
      platform: 'Zero-Downtime State Recovery',
      description: 'Durable WAL replication, fast replay, and high write throughput.',
      avatar: 'C'
    }
  ];

  const handleSubmit = async (e) => {
    e.preventDefault();
    const cleanClient = clientId.trim();
    if (!cleanClient) {
      setFeedback({ success: false, message: 'Please enter a valid Voter ID.' });
      return;
    }
    if (!choice) {
      setFeedback({ success: false, message: 'Please select a candidate before submitting your ballot.' });
      return;
    }

    setSubmitting(true);
    setFeedback(null);

    try {
      const res = await submitVote(cleanClient, choice);
      if (res.success) {
        setFeedback({
          success: true,
          voteId: res.vote_id,
          message: 'Ballot successfully committed across quorum peers and logged to MySQL WAL.',
          lamportTs: res.lamport_ts,
          choice: res.choice,
          nodeId: res.node_id,
        });

        setClientId('');
        setChoice('');
        if (onVoteSuccess) onVoteSuccess();
      } else {
        setFeedback({
          success: false,
          error: res.error,
          message: res.message || 'Vote rejected: write permissions are restricted to the active coordinator.',
          coordinatorId: res.coordinator_id,
        });
      }
    } catch (err) {
      setFeedback({
        success: false,
        error: 'network_error',
        message: `Failed to contact Flask REST bridge: ${err.message}`,
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleCopyReceipt = (text) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedReceipt(true);
    setTimeout(() => setCopiedReceipt(false), 2000);
  };

  const handleLookup = async (e) => {
    e.preventDefault();
    const cleanId = lookupId.trim();
    if (!cleanId) return;

    setLookingUp(true);
    setLookupResult(null);
    setLookupError('');

    try {
      const res = await fetchVote(cleanId);
      if (res.success && res.vote) {
        setLookupResult(res.vote);
      } else {
        setLookupError(res.message || `No ballot record found with identifier "${cleanId}".`);
      }
    } catch (err) {
      setLookupError(`Lookup query failed: ${err.message}`);
    } finally {
      setLookingUp(false);
    }
  };

  const isCoordinator = Boolean(nodeInfo?.is_coordinator);
  const coordinatorId = nodeInfo?.coordinator_id ?? 1;

  return (
    <div className="voting-page route-fade-in">
      <div className="page-header">
        <div>
          <h2 className="page-title">Ballot Casting & Verification</h2>
          <p className="page-description">
            Cast cryptographically ordered ballots with Lamport timestamp guarantees. Each ballot is committed across synchronous database replicas before acknowledgment.
          </p>
        </div>
      </div>

      <div className="grid-2">
        {/* Vote Submission Card */}
        <section className="card" aria-labelledby="ballot-submission-title">
          <div className="card-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Vote size={18} color="var(--color-navy-primary)" aria-hidden="true" />
              <h3 id="ballot-submission-title" style={{ fontSize: '1.0625rem', fontWeight: 700, margin: 0 }}>
                Cast Your Ballot
              </h3>
            </span>
            {isCoordinator ? (
              <span className="badge badge-coordinator">
                <CheckCircle2 size={12} aria-hidden="true" />
                Coordinator Node {nodeInfo?.node_id} (Accepting Writes)
              </span>
            ) : (
              <span className="badge badge-follower">
                <AlertTriangle size={12} aria-hidden="true" />
                Follower Node {nodeInfo?.node_id ?? '?'} (Read-Only)
              </span>
            )}
          </div>

          {/* Follower Write Guard Notice */}
          {!isCoordinator && (
            <div className="alert alert-warning" role="region" aria-label="Follower Node Notice">
              <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: '2px' }} aria-hidden="true" />
              <div style={{ flex: 1 }}>
                <strong style={{ color: 'var(--color-warning-text)' }}>Connected to Follower Node {nodeInfo?.node_id ?? '?'}</strong>
                <p style={{ marginTop: '0.25rem', fontSize: '0.84rem' }}>
                  In this distributed architecture, write operations are handled exclusively by the active Coordinator (<strong>Node {coordinatorId}</strong>) to guarantee linearizable consistency and avoid split-brain writes.
                </p>
                <div style={{ marginTop: '0.75rem' }}>
                  <a
                    href={`http://localhost:${5000 + coordinatorId}`}
                    className="btn btn-navy"
                    style={{ fontSize: '0.8125rem', padding: '0.4rem 0.85rem' }}
                  >
                    <span>Switch to Coordinator (Node {coordinatorId})</span>
                    <ExternalLink size={14} aria-hidden="true" />
                  </a>
                </div>
              </div>
            </div>
          )}

          {/* Submission Feedback Alert (Accessible Live Region) */}
          <div aria-live="polite">
            {feedback && (
              <div 
                className={`alert ${feedback.success ? 'alert-success' : 'alert-error'}`}
                role="alert"
              >
                {feedback.success ? (
                  <CheckCircle2 size={18} style={{ flexShrink: 0, marginTop: '2px' }} aria-hidden="true" />
                ) : (
                  <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: '2px' }} aria-hidden="true" />
                )}
                <div style={{ flex: 1 }}>
                  <strong>{feedback.success ? 'Ballot Committed Successfully!' : 'Submission Rejected'}</strong>
                  <p style={{ marginTop: '0.2rem', fontSize: '0.84rem' }}>{feedback.message}</p>
                  
                  {feedback.voteId && (
                    <div className="receipt-card">
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-teal-hover)' }}>
                        <span>DURABLE RECEIPT IDENTIFIER</span>
                        <span>Lamport TS: #{feedback.lamportTs}</span>
                      </div>
                      <div className="receipt-code-box">
                        <span>{feedback.voteId}</span>
                        <button
                          type="button"
                          onClick={() => handleCopyReceipt(feedback.voteId)}
                          className="btn btn-secondary"
                          style={{ padding: '0.25rem 0.6rem', fontSize: '0.75rem', height: '28px' }}
                          title="Copy receipt to clipboard"
                        >
                          {copiedReceipt ? <Check size={13} color="var(--color-success)" aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
                          <span>{copiedReceipt ? 'Copied' : 'Copy'}</span>
                        </button>
                      </div>
                    </div>
                  )}

                  {feedback.coordinatorId && (
                    <div style={{ marginTop: '0.75rem' }}>
                      <a
                        href={`http://localhost:${5000 + feedback.coordinatorId}`}
                        className="btn btn-primary"
                        style={{ fontSize: '0.8125rem', padding: '0.4rem 0.85rem' }}
                      >
                        <span>Redirect to Coordinator (Node {feedback.coordinatorId})</span>
                        <ArrowRight size={14} aria-hidden="true" />
                      </a>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label" htmlFor="voter-id-input">
                Voter / Client Identifier <span style={{ color: 'var(--color-danger)' }}>*</span>
              </label>
              <input
                id="voter-id-input"
                type="text"
                className="form-input"
                placeholder="e.g. voter_001, student_42"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                disabled={submitting}
                required
                aria-describedby="voter-id-help"
              />
              <span id="voter-id-help" className="form-helper">
                Each voter ID may only cast one ballot per election. Duplicate submissions will be rejected with HTTP 409.
              </span>
            </div>

            <fieldset className="form-group" style={{ border: 'none', padding: 0 }}>
              <legend className="form-label">
                Select Candidate <span style={{ color: 'var(--color-danger)' }}>*</span>
              </legend>
              <div className="candidate-selection-list" role="radiogroup" aria-label="Candidate Options">
                {candidates.map((cand) => {
                  const isSelected = choice === cand.name;
                  const radioId = `candidate-${cand.name.toLowerCase()}`;
                  return (
                    <label
                      key={cand.name}
                      htmlFor={radioId}
                      className={`candidate-card-option ${isSelected ? 'is-selected' : ''}`}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem', flex: 1 }}>
                        <div className="candidate-avatar-badge" aria-hidden="true">
                          {cand.avatar}
                        </div>
                        <div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <strong style={{ fontSize: '0.95rem', color: 'var(--color-navy-primary)' }}>
                              {cand.name}
                            </strong>
                            <span className="badge badge-neutral" style={{ fontSize: '0.65rem' }}>
                              {cand.platform}
                            </span>
                          </div>
                          <p style={{ fontSize: '0.78rem', color: 'var(--color-text-secondary)', marginTop: '0.15rem' }}>
                            {cand.description}
                          </p>
                        </div>
                      </div>

                      <input
                        type="radio"
                        id={radioId}
                        name="candidate-choice"
                        value={cand.name}
                        checked={isSelected}
                        onChange={() => setChoice(cand.name)}
                        disabled={submitting}
                        style={{ marginLeft: '1rem' }}
                      />
                    </label>
                  );
                })}
              </div>
            </fieldset>

            <button
              type="submit"
              className="btn btn-primary"
              style={{ width: '100%', padding: '0.75rem', fontSize: '0.9375rem' }}
              disabled={submitting || !clientId.trim() || !choice}
            >
              {submitting ? (
                <>
                  <RefreshCw size={16} className="spin-icon" aria-hidden="true" />
                  <span>Replicating Ballot Across Quorum...</span>
                </>
              ) : (
                <>
                  <Vote size={16} aria-hidden="true" />
                  <span>Submit Verified Ballot</span>
                </>
              )}
            </button>
          </form>
        </section>

        {/* Digital Ballot Receipt Verification Card */}
        <section className="card" aria-labelledby="receipt-lookup-title">
          <div className="card-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <ShieldCheck size={18} color="var(--color-teal-accent)" aria-hidden="true" />
              <h3 id="receipt-lookup-title" style={{ fontSize: '1.0625rem', fontWeight: 700, margin: 0 }}>
                Verify Ballot Receipt
              </h3>
            </span>
            <span className="badge badge-neutral">
              <Database size={12} aria-hidden="true" />
              Audit Verification
            </span>
          </div>

          <p className="card-subtitle">
            Query the authoritative database to verify ballot immutability and confirm the <code>COMMITTED</code> state. Format: <code>client_id:origin_node:lamport_ts</code>.
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
                  placeholder="e.g. voter_001:1:1"
                  value={lookupId}
                  onChange={(e) => setLookupId(e.target.value)}
                  disabled={lookingUp}
                />
                <button
                  type="submit"
                  className="btn btn-secondary"
                  disabled={lookingUp || !lookupId.trim()}
                  style={{ flexShrink: 0 }}
                >
                  {lookingUp ? (
                    <RefreshCw size={14} className="spin-icon" aria-hidden="true" />
                  ) : (
                    <Search size={14} aria-hidden="true" />
                  )}
                  <span>Verify</span>
                </button>
              </div>
            </div>
          </form>

          {lookupError && (
            <div className="alert alert-error" role="alert">
              <AlertTriangle size={16} style={{ flexShrink: 0 }} aria-hidden="true" />
              <span>{lookupError}</span>
            </div>
          )}

          {lookupResult && (
            <div 
              style={{
                padding: '1.25rem',
                borderRadius: 'var(--radius-md)',
                backgroundColor: 'var(--color-surface-subtle)',
                border: '1px solid var(--color-border-subtle)',
                marginBottom: '1rem'
              }}
              role="region"
              aria-label="Ballot Audit Details"
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.85rem', paddingBottom: '0.65rem', borderBottom: '1px solid var(--color-border-subtle)' }}>
                <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--color-navy-primary)', textTransform: 'uppercase' }}>
                  Ballot Audit Record
                </span>
                <span className={`badge ${lookupResult.status === 'COMMITTED' ? 'badge-coordinator' : 'badge-warning'}`}>
                  ● {lookupResult.status}
                </span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem', fontSize: '0.84rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--color-text-muted)' }}>Voter Identification:</span>
                  <strong style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-navy-primary)' }}>
                    {lookupResult.client_id}
                  </strong>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--color-text-muted)' }}>Selected Candidate:</span>
                  <strong style={{ color: 'var(--color-teal-accent)' }}>
                    {lookupResult.choice}
                  </strong>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--color-text-muted)' }}>Origin Coordinator:</span>
                  <span>Node {lookupResult.origin_node_id}</span>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--color-text-muted)' }}>Lamport Timestamp:</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                    #{lookupResult.lamport_ts}
                  </span>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--color-text-muted)' }}>Local Timestamp:</span>
                  <span style={{ color: 'var(--color-text-secondary)', fontSize: '0.8rem' }}>
                    {lookupResult.received_at_ms ? new Date(lookupResult.received_at_ms).toLocaleTimeString() : 'Persisted'}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Invariant Note */}
          <div style={{ padding: '0.85rem', backgroundColor: 'var(--color-surface-subtle)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--color-border-subtle)', fontSize: '0.78rem', color: 'var(--color-text-secondary)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontWeight: 600, color: 'var(--color-navy-primary)', marginBottom: '0.2rem' }}>
              <ShieldCheck size={14} color="var(--color-teal-accent)" aria-hidden="true" />
              Consensus Invariant
            </div>
            All ballots must be replicated and committed to MySQL with monotonic Lamport ordering before the voter receipt is generated.
          </div>
        </section>
      </div>
    </div>
  );
}
